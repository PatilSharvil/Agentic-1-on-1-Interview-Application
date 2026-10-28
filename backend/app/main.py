import asyncio
import json

from fastapi import FastAPI, WebSocket, WebSocketDisconnect, Depends, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import create_token, decode_token, hash_password, verify_password
from app.config import settings
from app.db import get_db, init_db
from app.models import User
from app.rooms import (
    add_participant,
    create_room,
    get_room,
    mark_participant_row_left,
    participant_count,
    save_message,
    save_transcript,
)
from app.models import Message
from app.copilot import router as copilot_router
from app.graph_builder import parse_resume
from app.graph_service import schedule_rebuild, shutdown_scheduler
from app.schemas import (
    JoinRequest,
    MessageIn,
    RoomCreate,
    RoomOut,
    TokenOut,
    TranscriptOut,
    UserLogin,
    UserRegister,
)
from app.signaling import manager
from app.stt import clean_transcript, get_stt, remove_overlap

app = FastAPI(title=settings.app_name)
app.include_router(copilot_router)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Whisper calls are network-bound; a few in parallel keeps captions responsive
# without hammering the API or starving the event loop.
_AUDIO_SEM = asyncio.Semaphore(4)
# last raw transcript per (room, speaker) for overlap de-duplication
_last_utterance: dict[tuple[str, str], str] = {}
# live meeting state per room code (session lifetime, not persisted)
_recording_state: dict[str, bool] = {}


@app.on_event("startup")
async def _startup():
    try:
        await init_db()
    except Exception as e:
        print(f"[startup] init_db failed: {e}")


@app.on_event("shutdown")
async def _shutdown():
    await shutdown_scheduler()


@app.exception_handler(Exception)
async def global_exception_handler(request, exc):
    import traceback
    print(f"[error] unhandled exception: {exc}")
    traceback.print_exc()
    from fastapi.responses import JSONResponse
    return JSONResponse(status_code=500, content={"detail": str(exc)})


@app.get("/health")
async def health():
    return {"status": "ok"}


# ---- auth (optional) ----
@app.post("/api/auth/register", response_model=TokenOut)
async def register(body: UserRegister, db: AsyncSession = Depends(get_db)):
    from sqlalchemy import select

    res = await db.scalar(select(User).where(User.email == body.email))
    if res:
        raise HTTPException(400, "email already registered")
    u = User(email=body.email, name=body.name, hashed_pw=hash_password(body.password))
    db.add(u)
    await db.commit()
    return TokenOut(access_token=create_token(u.id))


@app.post("/api/auth/login", response_model=TokenOut)
async def login(body: UserLogin, db: AsyncSession = Depends(get_db)):
    from sqlalchemy import select

    u = await db.scalar(select(User).where(User.email == body.email))
    if not u or not verify_password(body.password, u.hashed_pw):
        raise HTTPException(401, "invalid credentials")
    return TokenOut(access_token=create_token(u.id))


# ---- rooms ----
@app.post("/api/rooms", response_model=RoomOut)
async def create_room_endpoint(body: RoomCreate, db: AsyncSession = Depends(get_db)):
    room = await create_room(db, body.host_name)
    return RoomOut(
        code=room.code,
        host_name=room.host_name,
        status=room.status,
        created_at=room.created_at,
        participant_count=0,
    )


@app.get("/api/rooms/{code}", response_model=RoomOut)
async def get_room_endpoint(code: str, db: AsyncSession = Depends(get_db)):
    room = await get_room(db, code)
    if not room:
        raise HTTPException(404, "room not found")
    pc = await participant_count(db, room)
    return RoomOut(
        code=room.code,
        host_name=room.host_name,
        status=room.status,
        created_at=room.created_at,
        participant_count=pc,
    )


@app.get("/api/rooms/{code}/transcript", response_model=list[TranscriptOut])
async def transcript_endpoint(code: str, db: AsyncSession = Depends(get_db)):
    room = await get_room(db, code)
    if not room:
        raise HTTPException(404, "room not found")
    from sqlalchemy import select
    from app.models import Transcript

    rows = (await db.scalars(select(Transcript).where(Transcript.room_id == room.id).order_by(Transcript.created_at))).all()
    return [TranscriptOut(id=r.id, speaker=r.speaker, text=r.text, raw_text=r.raw_text, start_ms=r.start_ms, end_ms=r.end_ms, created_at=r.created_at) for r in rows]


@app.get("/api/rooms/{code}/chat")
async def chat_history_endpoint(code: str, db: AsyncSession = Depends(get_db)):
    """Chat history so a recovered (reloaded) client rebuilds the panel."""
    room = await get_room(db, code)
    if not room:
        raise HTTPException(404, "room not found")
    from sqlalchemy import select

    rows = (await db.scalars(select(Message).where(Message.room_id == room.id).order_by(Message.created_at))).all()
    return [
        {"id": m.id, "sender": m.sender, "body": m.body, "created_at": m.created_at.isoformat()}
        for m in rows
    ]


# ---- websocket signaling ----
def _is_interviewer(speaker: str, host_name: str) -> bool:
    s = (speaker or "").strip().lower()
    return s in {"interviewer", "host", "graph-viewer"} or (host_name and s == host_name.strip().lower())


async def _stt_context(room_id: str) -> str | None:
    """Resume-derived hint for Whisper: candidate name + skills not in the base prompt.

    Whisper biases decoding towards words present in the prompt, which fixes
    names like "Sharun Patil" that are otherwise heard as "Sharon Paddle".
    """
    from sqlalchemy import select

    from app.db import SessionLocal
    from app.models import Resume

    try:
        async with SessionLocal() as session:
            text = await session.scalar(
                select(Resume.text)
                .where(Resume.room_id == room_id)
                .order_by(Resume.parsed_at.desc())
                .limit(1)
            )
    except Exception as e:  # noqa: BLE001 - hints are optional
        print(f"[stt] resume hint unavailable: {e}")
        return None
    if not text:
        return None
    profile = parse_resume(text)
    base = (settings.stt_prompt or "").lower()
    parts: list[str] = []
    if profile.name:
        parts.append(profile.name + ".")
    skills = [s for s in profile.skills if s.lower() not in base][:8]
    if skills:
        parts.append("Skills: " + ", ".join(skills) + ".")
    return " ".join(parts) or None


async def _process_audio(
    ws: WebSocket,
    room_code: str,
    room_id: str,
    host_name: str,
    payload: dict,
) -> None:
    """Transcribe one chunk without blocking signalling or other audio."""
    import base64

    b64 = payload.get("audio")
    if not b64:
        return
    speaker = (payload.get("speaker") or "").strip() or "Candidate"
    start_ms = int(payload.get("start_ms") or 0)
    end_ms = int(payload.get("end_ms") or 0)
    seq = payload.get("seq")

    try:
        audio_bytes = base64.b64decode(b64)
    except Exception:
        await _safe_send(ws, {"type": "stt-status", "status": "error", "reason": "bad_base64", "seq": seq})
        return

    hint = await _stt_context(room_id)
    # Continuation context: the tail of this speaker's previous utterance helps
    # Whisper keep casing/punctuation coherent when a chunk starts mid-thought.
    # Echoes of this tail in the output are expected and stripped downstream by
    # remove_overlap — which is why the echo guard checks the base prompt only.
    tail = (_last_utterance.get((room_code, speaker)) or "")[-220:]
    if tail:
        hint = f"{hint} {tail}".strip() if hint else tail

    async with _AUDIO_SEM:
        try:
            stt = get_stt()
            result = await asyncio.to_thread(
                stt.transcribe_detailed,
                audio_bytes,
                payload.get("suffix") or ".wav",
                hint,
            )
        except Exception as e:  # noqa: BLE001
            print(f"[ws] stt failed: {e}")
            await _safe_send(ws, {"type": "stt-status", "status": "error", "reason": str(e)[:160], "seq": seq})
            return

    if result.status != "ok" or not result.text:
        print(f"[stt] skipped ({result.status}/{result.reason})")
        await _safe_send(
            ws,
            {
                "type": "stt-status",
                "status": result.status,
                "reason": result.reason,
                "seq": seq,
                "speech_ms": result.speech_ms,
                "snr_db": result.snr_db,
            },
        )
        return

    key = (room_code, speaker)
    deduped = remove_overlap(_last_utterance.get(key, ""), result.text)
    if not deduped.strip():
        await _safe_send(ws, {"type": "stt-status", "status": "duplicate", "reason": "overlap", "seq": seq})
        return

    cleaned = await asyncio.to_thread(clean_transcript, deduped)
    if not cleaned:
        await _safe_send(ws, {"type": "stt-status", "status": "hallucination", "reason": "cleanup_empty", "seq": seq})
        return

    _last_utterance[key] = (result.text + " " + deduped).strip()[-600:]

    from app.db import SessionLocal
    from app.models import Room

    try:
        async with SessionLocal() as session:
            room = await session.get(Room, room_id)
            if not room:
                return
            tr = await save_transcript(
                session,
                room,
                speaker,
                cleaned,
                raw_text=result.text,
                start_ms=start_ms,
                end_ms=end_ms or (start_ms + result.duration_ms),
            )
            transcript_payload = {
                "type": "transcript",
                "id": tr.id,
                "speaker": speaker,
                "text": cleaned,
                "raw_text": result.text,
                "start_ms": tr.start_ms,
                "end_ms": tr.end_ms,
                "seq": seq,
                "model": result.model,
                "latency_ms": result.latency_ms,
            }
            await manager.broadcast(room_code, transcript_payload)
    except Exception as e:  # noqa: BLE001
        print(f"[ws] transcript save failed: {e}")
        await _safe_send(ws, {"type": "stt-status", "status": "error", "reason": f"save_failed: {e}"[:160], "seq": seq})
        return

    await _safe_send(
        ws,
        {
            "type": "stt-status",
            "status": "ok",
            "reason": result.reason or "ok",
            "seq": seq,
            "speech_ms": result.speech_ms,
            "snr_db": result.snr_db,
            "latency_ms": result.latency_ms,
            "model": result.model,
        },
    )
    print(f"[stt] {speaker}: {cleaned!r} ({result.latency_ms}ms, snr={result.snr_db}dB, model={result.model})")

    if speaker.strip().lower() not in {"interviewer", "host", "graph-viewer"} and not _is_interviewer(speaker, host_name):
        schedule_rebuild(room_code)


async def _safe_send(ws: WebSocket, payload: dict) -> None:
    try:
        await manager.send(ws, payload)
    except Exception:
        pass


async def _audio_worker(
    ws: WebSocket,
    room_code: str,
    room_id: str,
    host_name: str,
    queue: "asyncio.Queue[dict | None]",
) -> None:
    while True:
        item = await queue.get()
        try:
            if item is None:
                return
            await _process_audio(ws, room_code, room_id, host_name, item)
        except asyncio.CancelledError:
            raise
        except Exception as e:  # noqa: BLE001
            print(f"[ws] audio worker error: {e}")
        finally:
            queue.task_done()


@app.websocket("/ws/{code}")
async def ws_endpoint(code: str, websocket: WebSocket, name: str = "Guest"):
    from app.db import SessionLocal

    code = code.upper()
    async with SessionLocal() as session:
        room = await get_room(session, code)
        if not room:
            await websocket.close(code=4004)
            return

        pc = await participant_count(session, room)
        name = (name or "Guest").strip() or "Guest"
        is_named_host = name.lower() == (room.host_name or "").strip().lower()
        role = "host" if (is_named_host or pc == 0) else "guest"
        me_row: object | None = None
        if name.lower() != "graph-viewer":
            me_row = await add_participant(session, room, name, role)

        room_id = room.id
        host_name = room.host_name or ""

        await manager.connect(code, websocket, name)
        is_viewer = name.lower() == "graph-viewer"
        if not is_viewer:
            await manager.broadcast(code, {"type": "join", "name": name, "role": role}, exclude=websocket)
        await manager.send(
            websocket,
            {
                "type": "joined",
                "code": code,
                "name": name,
                "role": role,
                "stt": {"model": settings.stt_model, "fallback": settings.stt_fallback_model},
                # VAD chunking config so the browser worklet and the server
                # tuning stay in sync without a frontend rebuild.
                "vad": {
                    "endpoint_silence_ms": settings.stt_endpoint_silence_ms,
                    "max_chunk_ms": settings.stt_max_chunk_ms,
                },
                # Room state snapshot so a recovered client continues exactly
                # where the meeting left off.
                "recording": bool(_recording_state.get(code, False)),
                "participants": [
                    {"name": manager.names.get(ws) or "?"}
                    for ws in manager.rooms.get(code, ())
                    if ws is not websocket and (manager.names.get(ws) or "").lower() != "graph-viewer"
                ],
            },
        )

        audio_queue: "asyncio.Queue[dict | None]" = asyncio.Queue(maxsize=8)
        worker = asyncio.create_task(_audio_worker(websocket, code, room_id, host_name, audio_queue))

        try:
            while True:
                raw = await websocket.receive_text()
                try:
                    data = json.loads(raw)
                except Exception:
                    await manager.send(websocket, {"type": "error", "message": "invalid json"})
                    continue

                t = data.get("type")
                if t in ("offer", "answer", "ice-candidate", "mute", "camera", "leave", "start-recording", "stop-recording"):
                    if t == "start-recording":
                        _recording_state[code] = True
                    elif t == "stop-recording":
                        _recording_state[code] = False
                    await manager.broadcast(code, data, exclude=websocket)
                elif t == "chat":
                    body = (data.get("body") or "").strip()
                    if body:
                        try:
                            m = await save_message(session, room, name, body)
                            payload = {"type": "chat", "id": m.id, "sender": name, "body": body, "created_at": m.created_at.isoformat()}
                            await manager.broadcast(code, payload)
                        except Exception as e:
                            await session.rollback()
                            await manager.send(websocket, {"type": "error", "message": f"chat failed: {e}"})
                elif t == "transcript":
                    text = (data.get("text") or "").strip()
                    speaker = (data.get("speaker") or name).strip() or name
                    if text:
                        try:
                            tr = await save_transcript(session, room, speaker, text)
                            payload = {"type": "transcript", "id": tr.id, "speaker": speaker, "text": text, "start_ms": tr.start_ms, "end_ms": tr.end_ms}
                            await manager.broadcast(code, payload)
                            if not _is_interviewer(speaker, host_name):
                                schedule_rebuild(code)
                        except Exception as e:
                            await session.rollback()
                            await manager.send(websocket, {"type": "error", "message": f"transcript failed: {e}"})
                elif t == "audio-chunk":
                    try:
                        audio_queue.put_nowait(data)
                    except asyncio.QueueFull:
                        print(f"[ws] audio queue full for {name}; dropping chunk")
                        await _safe_send(websocket, {"type": "stt-status", "status": "dropped", "reason": "queue_full"})
                else:
                    await manager.send(websocket, {"type": "error", "message": f"unknown type {t}"})
        except WebSocketDisconnect:
            pass
        except Exception as e:
            print(f"[ws] unhandled error: {e}")
            import traceback

            traceback.print_exc()
            await session.rollback()
        finally:
            worker.cancel()
            try:
                await worker
            except (asyncio.CancelledError, Exception):
                pass
            try:
                manager.disconnect(code, websocket)
                if me_row is not None:
                    try:
                        await mark_participant_row_left(session, me_row.id)
                    except Exception:
                        await session.rollback()
                # 'leave' only when the person is really gone: after a refresh
                # the same name is usually back on its own fresh socket, and a
                # leave right after their join would tell everyone they left.
                still_here = any(
                    (manager.names.get(ws) or "").lower() == name.lower()
                    for ws in manager.rooms.get(code, ())
                )
                if not still_here and not is_viewer:
                    await manager.broadcast(code, {"type": "leave", "name": name})
            except Exception:
                pass
