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
    participant_count,
    save_message,
    save_transcript,
)
from app.copilot import router as copilot_router
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
from app.stt import get_stt

app = FastAPI(title=settings.app_name)
app.include_router(copilot_router)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.on_event("startup")
async def _startup():
    try:
        await init_db()
    except Exception as e:
        print(f"[startup] init_db failed: {e}")


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
    existing = await db.get(User, body.email)  # by email? PK is id; check via query
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


# ---- websocket signaling ----
@app.websocket("/ws/{code}")
async def ws_endpoint(code: str, websocket: WebSocket, name: str = "Guest"):
    # db param not injectable for ws; create session manually
    from app.db import SessionLocal

    code = code.upper()
    async with SessionLocal() as session:
        room = await get_room(session, code)
        if not room:
            await websocket.close(code=4004)
            return

        # determine role: first participant = host
        pc = await participant_count(session, room)
        role = "host" if pc == 0 else "guest"
        await add_participant(session, room, name, role)

        await manager.connect(code, websocket, name)
        await manager.broadcast(code, {"type": "join", "name": name, "role": role}, exclude=websocket)
        await manager.send(websocket, {"type": "joined", "code": code, "name": name, "role": role})

        try:
            while True:
                raw = await websocket.receive_text()
                try:
                    data = json.loads(raw)
                except Exception:
                    await manager.send(websocket, {"type": "error", "message": "invalid json"})
                    continue

                t = data.get("type")
                if t in ("offer", "answer", "ice-candidate", "mute", "camera", "leave", "transcript", "start-recording", "stop-recording"):
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
                    if text:
                        try:
                            tr = await save_transcript(session, room, data.get("speaker", name), text)
                            payload = {"type": "transcript", "id": tr.id, "speaker": data.get("speaker", name), "text": text, "start_ms": tr.start_ms, "end_ms": tr.end_ms}
                            await manager.broadcast(code, payload)
                        except Exception as e:
                            await session.rollback()
                            await manager.send(websocket, {"type": "error", "message": f"transcript failed: {e}"})
                elif t == "audio-chunk":
                    # data: {type, audio (base64), suffix?}
                    import base64
                    print(f"[ws] audio-chunk from {name}: {len(data.get('audio',''))} b64 chars")

                    b64 = data.get("audio")
                    if b64:
                        try:
                            audio_bytes = base64.b64decode(b64)
                            stt = get_stt()
                            raw = await asyncio.to_thread(stt.transcribe_bytes, audio_bytes, data.get("suffix", ".webm"), data.get("prompt"))
                            print(f"[ws] stt raw: {raw!r}")
                            if raw:
                                from app.stt import clean_transcript
                                cleaned = await asyncio.to_thread(clean_transcript, raw)
                                print(f"[ws] cleaned: {cleaned!r}")
                                speaker = data.get("speaker") or name
                                if cleaned:
                                    tr = await save_transcript(session, room, speaker, cleaned, raw_text=raw)
                                    payload = {"type": "transcript", "id": tr.id, "speaker": speaker, "text": cleaned, "raw_text": raw, "start_ms": tr.start_ms, "end_ms": tr.end_ms}
                                    await manager.broadcast(code, payload)
                                    print(f"[ws] broadcast transcript to room {code}")
                                else:
                                    print("[ws] skipped (hallucination or empty)")
                        except Exception as e:
                            import traceback
                            print(f"[ws] stt error: {e}")
                            traceback.print_exc()
                            await session.rollback()
                            await manager.send(websocket, {"type": "error", "message": f"stt failed: {e}"})
                else:
                    await manager.send(websocket, {"type": "error", "message": f"unknown type {t}"})
        except WebSocketDisconnect:
            pass
        except Exception as e:
            import traceback
            print(f"[ws] unhandled error: {e}")
            traceback.print_exc()
            await session.rollback()
        finally:
            try:
                manager.disconnect(code, websocket)
                await manager.broadcast(code, {"type": "leave", "name": name})
            except Exception:
                pass