import io
import json
import re

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_db
from app.graph_builder import summarise_for_questions
from app.graph_service import _read_graph, rebuild_graph as rebuild_room_graph
from app.llm import chat_json
from app.models import Question, Resume, Room, Transcript
from app.rooms import get_room
from app.schemas import (
    GraphOut,
    NextQuestionRequest,
    QuestionGenerateRequest,
    QuestionOut,
    ResumeOut,
)

router = APIRouter(prefix="/api/rooms", tags=["copilot"])


async def _get_room_or_404(db: AsyncSession, code: str) -> Room:
    room = await get_room(db, code)
    if not room:
        raise HTTPException(404, "room not found")
    return room


def _extract_text(filename: str, content: bytes) -> str:
    name = (filename or "").lower()
    if name.endswith(".pdf"):
        try:
            from pdfminer.high_level import extract_text as pdf_extract

            text = pdf_extract(io.BytesIO(content)) or ""
            return re.sub(r"[ \t]+", " ", text)
        except Exception as e:
            print(f"[resume] pdf extraction failed: {e}")
            return ""
    if name.endswith(".docx"):
        try:
            import docx  # type: ignore

            document = docx.Document(io.BytesIO(content))
            return "\n".join(p.text for p in document.paragraphs)
        except Exception:
            return ""
    try:
        return content.decode("utf-8", errors="ignore")
    except Exception:
        return ""


# ---------- Resume ----------
@router.post("/{code}/resume", response_model=ResumeOut)
async def upload_resume(code: str, file: UploadFile = File(...), db: AsyncSession = Depends(get_db)):
    room = await _get_room_or_404(db, code)
    content = await file.read()
    text = _extract_text(file.filename or "resume.txt", content)
    if not text.strip():
        raise HTTPException(400, "could not extract text from file (try PDF, DOCX, TXT or MD)")

    r = Resume(room_id=room.id, filename=file.filename or "resume", text=text)
    db.add(r)
    await db.commit()
    await db.refresh(r)

    # The first graph is resume-only, so build it immediately (fast, no LLM).
    graph_built = False
    try:
        graph = await rebuild_room_graph(db, room, use_llm=False, force=True)
        graph_built = bool(graph["nodes"])
        print(f"[resume] room {code}: graph seeded with {len(graph['nodes'])} nodes")
    except Exception as e:  # noqa: BLE001
        print(f"[resume] initial graph build failed: {e}")

    return ResumeOut(
        id=r.id,
        filename=r.filename,
        text_preview=text[:500],
        parsed_at=r.parsed_at,
        graph_built=graph_built,
        skills=summarise_for_questions(text)["skills"][:15],
    )


@router.get("/{code}/resume", response_model=ResumeOut)
async def get_resume(code: str, db: AsyncSession = Depends(get_db)):
    room = await _get_room_or_404(db, code)
    r = await db.scalar(
        select(Resume).where(Resume.room_id == room.id).order_by(Resume.parsed_at.desc())
    )
    if not r:
        raise HTTPException(404, "no resume uploaded")
    summary = summarise_for_questions(r.text)
    return ResumeOut(
        id=r.id,
        filename=r.filename,
        text_preview=r.text[:500],
        parsed_at=r.parsed_at,
        graph_built=True,
        skills=summary["skills"][:15],
    )


# ---------- Questions ----------
def _qkey(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", text.lower()).strip()


_GENERIC_QUESTIONS = [
    "Walk me through the most technically challenging project on your resume. What trade-offs did you make?",
    "Tell me about a production incident you owned. How did you find the root cause and what changed afterwards?",
    "How do you decide between adding a new service and extending an existing one?",
    "Describe a time you disagreed with a teammate on a technical decision. How did you resolve it?",
]


def _deterministic_questions(summary: dict, count: int) -> list[str]:
    skills = [s for s in summary.get("skills", []) if s]
    projects = [p for p in summary.get("projects", []) if p]
    companies = [c for c in summary.get("companies", []) if c]
    out: list[str] = []

    def add(q: str) -> None:
        q = _valid_question(q)
        if q and _qkey(q) not in {_qkey(x) for x in out}:
            out.append(q)

    for i in range(0, min(len(skills), count * 2), 2):
        pair = skills[i : i + 2]
        if len(pair) == 2:
            add(
                f"Your resume lists {pair[0]} and {pair[1]}. Describe a system where you used both, "
                f"including the data flow, failure modes, and how you tested it?"
            )
        else:
            add(
                f"You listed {pair[0]} on your resume. What is the most advanced thing you have built with it, "
                f"and what did you have to learn along the way?"
            )
    for project in projects[:2]:
        add(
            f"You mention the project \"{project}\". What was the hardest technical decision in it, "
            f"and what would you change if you rebuilt it today?"
        )
    for company in companies[:2]:
        add(
            f"At {company}, what did you own end to end, and how did you measure whether it was successful?"
        )
    for generic in _GENERIC_QUESTIONS:
        add(generic)
    return out[:count]


def _valid_question(text: object) -> str | None:
    if not isinstance(text, str):
        return None
    q = re.sub(r"\s+", " ", text).strip().strip('"')
    if len(q) < 12 or len(q) > 400:
        return None
    starters = {
        "how", "what", "why", "when", "where", "which", "who", "walk", "describe", "tell",
        "explain", "can", "could", "would", "should", "do", "did", "does", "have", "has",
        "is", "are", "give", "share", "talk", "take",
    }
    first = q.split()[0].lower() if q.split() else ""
    if not q.endswith("?") and first not in starters:
        return None
    if not q.endswith("?"):
        q = q.rstrip(".") + "?"
    if q.count("?") > 2:
        return None
    return q


@router.post("/{code}/questions/generate", response_model=list[QuestionOut])
async def generate_questions(code: str, body: QuestionGenerateRequest, db: AsyncSession = Depends(get_db)):
    room = await _get_room_or_404(db, code)
    resume = await db.scalar(
        select(Resume).where(Resume.room_id == room.id).order_by(Resume.parsed_at.desc())
    )
    if not resume:
        raise HTTPException(400, "upload a resume first")

    count = max(1, min(int(body.count or 5), 12))
    job = (body.job_title or "software engineer").strip()
    summary = summarise_for_questions(resume.text)
    existing = (
        await db.scalars(select(Question).where(Question.room_id == room.id).order_by(Question.created_at))
    ).all()
    existing_texts = [q.text for q in existing]

    prompt = f"""You are an expert technical interviewer preparing for a live interview.

TARGET ROLE: {job}
CANDIDATE PROFILE (extracted from resume): {json.dumps(summary)}

RESUME (excerpt):
{resume.text[:6000]}

ALREADY ASKED (do not repeat or paraphrase):
{json.dumps(existing_texts[-20:]) if existing_texts else "[]"}

Write {count} interview questions that are specific to THIS candidate.
Rules:
- Ground every question in something concrete from the resume (a skill, project, company, or claim).
- Mix depth (how/why/trade-offs) with verification (what exactly did you do).
- One question per item, under 55 words, ending with "?".
- No generic "tell me about yourself" filler. No numbering, no preamble.
- Do not invent experience the resume does not contain.

Return ONLY JSON: {{"questions": ["...", "..."]}}"""

    llm_questions: list[str] = []
    try:
        data = await chat_json(
            prompt,
            system="You are a meticulous technical interviewer. Output only valid JSON.",
            max_tokens=1000,
            temperature=0.4,
        )
        raw = data.get("questions", []) if isinstance(data, dict) else data
        if isinstance(raw, list):
            for item in raw:
                q = _valid_question(item)
                if q:
                    llm_questions.append(q)
    except Exception as e:  # noqa: BLE001
        print(f"[questions] LLM generation failed, using deterministic fallback: {e}")

    chosen: list[str] = []
    seen = {_qkey(t) for t in existing_texts}
    for q in llm_questions + _deterministic_questions(summary, count + 3):
        key = _qkey(q)
        if key in seen:
            continue
        seen.add(key)
        chosen.append(q)
        if len(chosen) >= count:
            break

    out: list[QuestionOut] = []
    for qtext in chosen:
        qrow = Question(room_id=room.id, text=qtext, source="resume")
        db.add(qrow)
        await db.commit()
        await db.refresh(qrow)
        out.append(QuestionOut(id=qrow.id, text=qrow.text, source=qrow.source, parent_id=qrow.parent_id, created_at=qrow.created_at))

    if out:
        try:
            from app.signaling import manager

            await manager.broadcast(code, {"type": "questions", "questions": [q.model_dump() for q in out]})
        except Exception:
            pass
    return out


@router.get("/{code}/questions", response_model=list[QuestionOut])
async def list_questions(code: str, db: AsyncSession = Depends(get_db)):
    room = await _get_room_or_404(db, code)
    rows = (
        await db.scalars(select(Question).where(Question.room_id == room.id).order_by(Question.created_at))
    ).all()
    return [QuestionOut(id=r.id, text=r.text, source=r.source, parent_id=r.parent_id, created_at=r.created_at) for r in rows]


@router.post("/{code}/questions/next", response_model=QuestionOut)
async def next_question(code: str, body: NextQuestionRequest, db: AsyncSession = Depends(get_db)):
    room = await _get_room_or_404(db, code)
    resume = await db.scalar(
        select(Resume).where(Resume.room_id == room.id).order_by(Resume.parsed_at.desc())
    )
    transcripts = (
        await db.scalars(
            select(Transcript).where(Transcript.room_id == room.id).order_by(Transcript.created_at)
        )
    ).all()
    questions = (
        await db.scalars(select(Question).where(Question.room_id == room.id).order_by(Question.created_at))
    ).all()

    interviewer_names = {"interviewer", "host", (room.host_name or "").lower()}
    candidate_lines = [
        t.text
        for t in transcripts
        if (t.speaker or "").strip().lower() not in interviewer_names and t.text.strip()
    ]
    answer = (body.previous_answer or "").strip() or (candidate_lines[-1] if candidate_lines else "")
    last_q = questions[-1] if questions else None
    recent = "\n".join(
        f"{'Q' if (t.speaker or '').lower() in interviewer_names else 'A'}: {t.text}"
        for t in transcripts[-8:]
    )
    asked_recently = "\n".join(f"- {q.text}" for q in questions[-3:])
    summary = summarise_for_questions(resume.text) if resume else {"skills": [], "projects": []}

    prompt = f"""You are an adaptive interviewer. Ask ONE follow-up question based on what the candidate just said.

CANDIDATE PROFILE: {json.dumps(summary)}
RESUME (excerpt): {(resume.text[:2500] if resume else "(no resume)")}

CANDIDATE ANSWER: {answer or "(no answer yet)"}

RECENT EXCHANGE:
{recent or "(none)"}

QUESTIONS YOU ALREADY ASKED (do NOT reuse their topics or reword them):
{asked_recently or "(none yet)"}

Rules:
- Probe a gap, an unstated detail, a trade-off, or a possible inconsistency in the answer.
- Use the candidate's own words/technology names.
- If the answer is vague, ask for a specific example with numbers, tools, or outcomes.
- One NEW question only, under 45 words, ending with "?".
- It must cover a DIFFERENT angle than every question above (change the feature, skill, or concern entirely).
- Do not repeat or paraphrase any earlier question.

Return ONLY JSON: {{"question": "..."}}"""

    qtext = ""
    try:
        data = await chat_json(
            prompt,
            system="You are a sharp technical interviewer. Output only valid JSON.",
            max_tokens=400,
            temperature=0.5,
        )
        if isinstance(data, dict):
            qtext = _valid_question(data.get("question", "")) or ""
    except Exception as e:  # noqa: BLE001
        print(f"[questions] adaptive generation failed, using fallback: {e}")

    def _too_similar(new_q: str, recent_questions: list) -> bool:
        """Reject wardrobe repeats: >60% informative-word overlap with anything asked recently."""
        stop = {"what", "how", "the", "you", "your", "a", "an", "of", "in", "for", "and", "did",
                "do", "to", "with", "can", "could", "tell", "me", "about", "it", "is", "was",
                "describe", "explain", "walk", "through"}
        def words(q: str):
            return {w for w in re.findall(r"[a-z0-9]+", q.lower()) if w not in stop and len(w) > 2}
        nw = words(new_q)
        if not nw:
            return False
        for q in recent_questions:
            ow = words(q.text)
            if ow and len(nw & ow) / len(nw | ow) > 0.6:
                return True
        return False

    if qtext and _too_similar(qtext, questions[-3:]):
        print("[questions] adaptive question too similar to a previous one; using fallback")
        qtext = ""

    if not qtext:
        skills = []
        try:
            from app.graph_builder import match_skills

            skills = match_skills(answer)[:2]
        except Exception:
            skills = []
        if skills:
            qtext = (
                f"You mentioned {skills[0]}. Can you walk me through a specific problem you solved with it — "
                f"what broke, how you diagnosed it, and what the measurable outcome was?"
            )
        elif summary.get("projects"):
            qtext = f"You mentioned {summary['projects'][0]}. What was your individual contribution versus the team's?"
        else:
            qtext = "Can you give a concrete example of the hardest bug you have debugged recently, and how you found the root cause?"

    qrow = Question(
        room_id=room.id,
        text=qtext,
        source="adaptive",
        parent_id=last_q.id if last_q else None,
    )
    db.add(qrow)
    await db.commit()
    await db.refresh(qrow)
    out = QuestionOut(id=qrow.id, text=qrow.text, source=qrow.source, parent_id=qrow.parent_id, created_at=qrow.created_at)
    try:
        from app.signaling import manager

        await manager.broadcast(code, {"type": "question", "question": out.model_dump()})
    except Exception:
        pass
    return out


# ---------- Knowledge graph ----------
@router.get("/{code}/graph", response_model=GraphOut)
async def get_graph(code: str, db: AsyncSession = Depends(get_db)):
    room = await _get_room_or_404(db, code)
    data = await _read_graph(db, room)
    return GraphOut(nodes=data["nodes"], edges=data["edges"])


@router.post("/{code}/graph/rebuild", response_model=GraphOut)
async def rebuild_graph(
    code: str,
    source: str = Query("all", pattern="^(all|resume|transcript)$"),
    force: bool = Query(True),
    db: AsyncSession = Depends(get_db),
):
    room = await _get_room_or_404(db, code)
    try:
        data = await rebuild_room_graph(db, room, use_llm=(source != "resume"), force=force)
    except Exception as e:  # noqa: BLE001
        raise HTTPException(500, f"graph rebuild failed: {e}")
    return GraphOut(nodes=data["nodes"], edges=data["edges"])
