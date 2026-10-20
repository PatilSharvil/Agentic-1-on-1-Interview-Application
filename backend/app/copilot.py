import io
import json

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_db
from app.models import GraphEdge, GraphNode, Question, Resume, Room
from app.openrouter import chat, chat_json
from app.rooms import get_room
from app.schemas import GraphOut, GraphNodeOut, GraphEdgeOut, QuestionGenerateRequest, QuestionOut, NextQuestionRequest, ResumeOut

router = APIRouter(prefix="/api/rooms", tags=["copilot"])


async def _get_room_or_404(db: AsyncSession, code: str) -> Room:
    room = await get_room(db, code)
    if not room:
        raise HTTPException(404, "room not found")
    return room


def _extract_text(filename: str, content: bytes) -> str:
    if filename.lower().endswith(".pdf"):
        try:
            from pdfminer.high_level import extract_text as pdf_extract

            return pdf_extract(io.BytesIO(content)) or ""
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
        raise HTTPException(400, "could not extract text from file")
    from app.models import Resume as ResumeModel

    r = ResumeModel(room_id=room.id, filename=file.filename or "resume", text=text)
    db.add(r)
    await db.commit()
    await db.refresh(r)
    return ResumeOut(id=r.id, filename=r.filename, text_preview=text[:500], parsed_at=r.parsed_at)


@router.get("/{code}/resume", response_model=ResumeOut)
async def get_resume(code: str, db: AsyncSession = Depends(get_db)):
    room = await _get_room_or_404(db, code)
    from app.models import Resume as ResumeModel

    r = await db.scalar(select(ResumeModel).where(ResumeModel.room_id == room.id).order_by(ResumeModel.parsed_at.desc()))
    if not r:
        raise HTTPException(404, "no resume uploaded")
    return ResumeOut(id=r.id, filename=r.filename, text_preview=r.text[:500], parsed_at=r.parsed_at)


# ---------- Questions ----------
@router.post("/{code}/questions/generate", response_model=list[QuestionOut])
async def generate_questions(code: str, body: QuestionGenerateRequest, db: AsyncSession = Depends(get_db)):
    room = await _get_room_or_404(db, code)
    from app.models import Resume as ResumeModel

    resume = await db.scalar(select(ResumeModel).where(ResumeModel.room_id == room.id).order_by(ResumeModel.parsed_at.desc()))
    if not resume:
        raise HTTPException(400, "upload a resume first")
    job = body.job_title or "software engineer"
    prompt = f"""You are an expert technical interviewer. Given the candidate's resume below and the target role "{job}", generate {body.count} interview questions.

Resume:
{resume.text[:4000]}

Return ONLY a JSON object: {{ "questions": ["q1", "q2", ...] }}"""
    try:
        data = chat_json(prompt, system="You output only valid JSON.")
    except Exception as e:
        raise HTTPException(500, f"LLM failed: {e}")
    qs = data.get("questions", []) if isinstance(data, dict) else []
    if not isinstance(qs, list):
        qs = []
    out = []
    for q in qs[: body.count]:
        qtext = str(q).strip()
        if not qtext:
            continue
        qrow = Question(room_id=room.id, text=qtext, source="resume")
        db.add(qrow)
        await db.commit()
        await db.refresh(qrow)
        out.append(QuestionOut(id=qrow.id, text=qrow.text, source=qrow.source, parent_id=qrow.parent_id, created_at=qrow.created_at))
    return out


@router.get("/{code}/questions", response_model=list[QuestionOut])
async def list_questions(code: str, db: AsyncSession = Depends(get_db)):
    room = await _get_room_or_404(db, code)
    rows = (await db.scalars(select(Question).where(Question.room_id == room.id).order_by(Question.created_at))).all()
    return [QuestionOut(id=r.id, text=r.text, source=r.source, parent_id=r.parent_id, created_at=r.created_at) for r in rows]


@router.post("/{code}/questions/next", response_model=QuestionOut)
async def next_question(code: str, body: NextQuestionRequest, db: AsyncSession = Depends(get_db)):
    room = await _get_room_or_404(db, code)
    from app.models import Resume as ResumeModel, Transcript

    resume = await db.scalar(select(ResumeModel).where(ResumeModel.room_id == room.id).order_by(ResumeModel.parsed_at.desc()))
    # latest candidate answer
    answer = body.previous_answer
    if not answer:
        last = await db.scalar(select(Transcript).where(Transcript.room_id == room.id, Transcript.speaker == "Candidate").order_by(Transcript.created_at.desc()))
        answer = last.text if last else ""
    last_q = await db.scalar(select(Question).where(Question.room_id == room.id).order_by(Question.created_at.desc()))
    resume_text = resume.text[:3000] if resume else "(no resume)"
    prompt = f"""You are an adaptive interviewer. Given the resume, the previous question, and the candidate's answer, generate ONE deeper follow-up question that probes gaps, inconsistencies, or areas needing more detail.

Resume: {resume_text}
Previous question: {last_q.text if last_q else "(none)"}
Candidate answer: {answer}

Return ONLY JSON: {{ "question": "..." }}"""
    try:
        data = chat_json(prompt, system="You output only valid JSON.")
    except Exception as e:
        raise HTTPException(500, f"LLM failed: {e}")
    qtext = ""
    if isinstance(data, dict):
        qtext = str(data.get("question", "")).strip()
    if not qtext:
        raise HTTPException(500, "LLM returned no question")
    qrow = Question(room_id=room.id, text=qtext, source="adaptive", parent_id=last_q.id if last_q else None)
    db.add(qrow)
    await db.commit()
    await db.refresh(qrow)
    return QuestionOut(id=qrow.id, text=qrow.text, source=qrow.source, parent_id=qrow.parent_id, created_at=qrow.created_at)


# ---------- Knowledge graph ----------
@router.get("/{code}/graph", response_model=GraphOut)
async def get_graph(code: str, db: AsyncSession = Depends(get_db)):
    room = await _get_room_or_404(db, code)
    nodes = (await db.scalars(select(GraphNode).where(GraphNode.room_id == room.id))).all()
    edges = (await db.scalars(select(GraphEdge).where(GraphEdge.room_id == room.id))).all()
    return GraphOut(
        nodes=[GraphNodeOut(id=n.node_key, label=n.label, type=n.type, meta=json.loads(n.meta) if n.meta else None) for n in nodes],
        edges=[GraphEdgeOut(id=e.id, source=e.source_key, target=e.target_key, relation=e.relation, weight=e.weight) for e in edges],
    )


@router.post("/{code}/graph/rebuild", response_model=GraphOut)
async def rebuild_graph(code: str, db: AsyncSession = Depends(get_db)):
    room = await _get_room_or_404(db, code)
    from app.models import Resume as ResumeModel, Transcript

    resume = await db.scalar(select(ResumeModel).where(ResumeModel.room_id == room.id).order_by(ResumeModel.parsed_at.desc()))
    transcripts = (await db.scalars(select(Transcript).where(Transcript.room_id == room.id).order_by(Transcript.created_at))).all()
    resume_text = resume.text[:3000] if resume else "(no resume)"
    answers_text = "\n".join(f"[{t.speaker}] {t.text}" for t in transcripts[-20:])
    prompt = f"""You are analyzing an interview. Build a knowledge graph.

Resume:
{resume_text}

Candidate/Interviewer transcript (recent):
{answers_text or "(no answers yet)"}

Extract entities (skills, projects, companies, claims, topics) and relationships.

RELATION RULES (pick exactly one per edge):
- "mentions": the target label is LITERALLY written in the resume text (e.g. resume says "Skills: Python" → edge person→Python = "mentions"). Use this for every skill, company, degree, or tool that appears verbatim in the resume.
- "supports": a candidate answer confirms or backs up a resume claim.
- "contradicts": a candidate answer conflicts with the resume.
- "related": loosely connected concepts that are NOT directly stated in the resume.

EXAMPLES:
Resume: "Skills: Python, Docker. Company: TechCorp."
  person → Python = "mentions" (grey)
  person → Docker = "mentions" (grey)
  person → TechCorp = "mentions" (grey)
  Python → Docker = "related" (blue, loosely connected)

Return ONLY JSON:
{{ "nodes": [{{"id":"n1","label":"Python","type":"skill"}}], "edges": [{{"source":"n1","target":"n2","relation":"mentions","weight":1.0}}] }}

Rules:
- node type one of: skill, topic, claim, entity
- relation one of: mentions, supports, contradicts, related
- weight 0.0-1.0 (mentions=1.0, supports=0.9, contradicts=0.9, related=0.5)
- max 40 nodes, 60 edges
- use stable ids (reuse same id for same entity across calls)"""
    try:
        data = chat_json(prompt, system="You output only valid JSON.")
    except Exception as e:
        raise HTTPException(500, f"LLM failed: {e}")
    if isinstance(data, list):
        nodes = data
        edges = []
    elif isinstance(data, dict):
        nodes = data.get("nodes", [])
        edges = data.get("edges", [])
    else:
        nodes = []
        edges = []

    from sqlalchemy import delete as sql_delete

    # clear old graph (synchronize_session=False avoids stale ORM state)
    await db.execute(sql_delete(GraphNode).where(GraphNode.room_id == room.id).execution_options(synchronize_session=False))
    await db.execute(sql_delete(GraphEdge).where(GraphEdge.room_id == room.id).execution_options(synchronize_session=False))
    await db.flush()

    # build label lookup for post-processing
    label_by_id = {}
    node_ids = set()
    for n in nodes[:40]:
        if not isinstance(n, dict):
            continue
        nid = str(n.get("id", "")).strip()
        label = str(n.get("label", "")).strip()
        ntype = str(n.get("type", "entity")).strip()
        if not nid or not label:
            continue
        node_ids.add(nid)
        label_by_id[nid] = label
        gn = GraphNode(room_id=room.id, node_key=nid, label=label, type=ntype, meta=json.dumps(n.get("meta")) if n.get("meta") else None)
        db.add(gn)

    resume_lower = resume_text.lower()
    for e in edges[:60]:
        if not isinstance(e, dict):
            continue
        src = str(e.get("source", "")).strip()
        tgt = str(e.get("target", "")).strip()
        if not src or not tgt or src not in node_ids or tgt not in node_ids:
            continue
        relation = str(e.get("relation", "related"))
        weight = float(e.get("weight", 1.0))
        # post-process: if source is a person/company/role (entity/claim) and target label is literally in resume, force "mentions"
        src_node = next((n for n in nodes if str(n.get("id", "")).strip() == src), None)
        src_type = str(src_node.get("type", "")).lower() if src_node else ""
        tgt_label = label_by_id.get(tgt, "")
        if src_type in ("entity", "claim") and tgt_label and tgt_label.lower() in resume_lower:
            relation = "mentions"
            weight = 1.0
        ge = GraphEdge(room_id=room.id, source_key=src, target_key=tgt, relation=relation, weight=weight)
        db.add(ge)
    await db.commit()

    # broadcast update
    from app.signaling import manager

    graph = await get_graph(code, db)
    await manager.broadcast(code, {"type": "graph-update", "nodes": [n.model_dump() for n in graph.nodes], "edges": [e.model_dump() for e in graph.edges]})
    return graph