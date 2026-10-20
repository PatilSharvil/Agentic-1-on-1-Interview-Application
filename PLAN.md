# 1-to-1 Meeting Platform — Plan

Goal: build a 1-to-1 video meeting app (Teams/Meet-style) in Python, structured so it can later become an agentic AI interviewing app.

## Decisions (locked from user)
- Database: SQLite for v1 (SQLAlchemy, swap to Postgres later).
- Auth: guest join with display name (optional account).
- Recording: NOT needed now.
- Frontend: React + Vite.
- STT (speech-to-text) for interviewer AND candidate is a core requirement (live captions + saved transcript).

## Scope (v1, what we build now)
- Create/join a meeting room by link/code, exactly 2 participants.
- Real-time audio + video (WebRTC) between the two peers.
- In-meeting chat (text).
- Mute/unmute, camera on/off, screen share.
- Join/leave, room expiry.
- Real-time STT transcription for both speakers (live captions + transcript persisted).
- (Later) agentic AI interviewing layer on top.

Out of scope for v1 (defer): multi-party (>2), breakout rooms, persistent chat history across sessions, calendar integration, E2EE, mobile native apps, recording.

## Architecture

```
React (Vite) WebRTC client  <--WebSocket signaling-->  FastAPI signaling server
        |                                                    |
        | STUN/TURN (coturn) for NAT traversal                |
        |                                                    v
        +-- media flows peer-to-peer  -->  SQLite (users/rooms/transcripts) + STT service
```

STT approach: browser captures mic audio -> streams chunks over WebSocket to FastAPI -> STT engine transcribes -> broadcast transcript events to both peers + persist. Options: faster-whisper (local, best accuracy for offline), Deepgram (best real-time streaming), OpenAI Whisper API (simple). Recommend faster-whisper for dev/offline + Deepgram for prod real-time, behind a single `STTService` interface.

Key decision: peer-to-peer WebRTC for 1-to-1 (no SFU). Signaling only. Keeps Python side simple.

## Tech stack
Backend (Python):
- FastAPI + Uvicorn (async) — HTTP + WebSocket signaling + STT streaming.
- Native FastAPI WebSocket.
- SQLAlchemy 2.0 async + Alembic + SQLite (aiosqlite).
- Pydantic v2 for schemas.
- Auth: JWT (python-jose) + passlib/bcrypt; guest join allowed.
- STT: faster-whisper (default, local) with pluggable provider (Deepgram/OpenAI) via env.
- ffmpeg for audio chunk normalization (optional).

Frontend:
- React + Vite + TypeScript.
- WebRTC API for media; socket.io-client OR native WebSocket client.
- Tailwind CSS for UI.

## Data model
- User(id, email, name, hashed_pw, created_at)
- Room(id, code, host_name, created_at, expires_at, status)
- Participant(room_id, display_name, role, joined_at, left_at)  role in {host, guest, agent}
- Message(id, room_id, sender, body, created_at)
- Transcript(id, room_id, speaker, text, start_ms, end_ms, created_at)

## Signaling protocol (WebSocket JSON)
Events: `join`, `offer`, `answer`, `ice-candidate`, `chat`, `transcript`, `leave`, `mute`, `camera`.
Room code -> both peers connect to same WS channel; server relays SDP/ICE between the two peers only. STT audio chunks flow over a separate WS or same channel with `audio-chunk` event.

## API surface
- POST /api/rooms  -> create room, return code + link
- GET  /api/rooms/{code} -> room info
- POST /api/auth/register, /api/auth/login (optional)
- WS   /ws/{room_code}?name=...
- GET  /api/rooms/{code}/transcript -> full transcript
- Frontend served by Vite dev server (proxy to FastAPI) in dev; static build in prod.

## Project layout
```
interview application/
  backend/
    app/
      main.py
      config.py
      db.py
      models.py
      schemas.py
      auth.py
      signaling.py
      rooms.py
      stt.py            # STTService interface + providers
    alembic/
    requirements.txt
  frontend/
    (Vite + React app)
    src/
      App.tsx
      pages/Landing.tsx
      pages/Room.tsx
      lib/webrtc.ts
      lib/signaling.ts
    package.json
    vite.config.ts
  tests/
    test_rooms.py
    test_signaling.py
    test_stt.py
  .env.example
  README.md
```

## Phases
1. Skeleton: FastAPI app, config, DB, models, migrations, health check.
2. Rooms REST API + tests.
3. React+Vite scaffold + landing (create/join) + proxy to backend.
4. WebSocket signaling relay + Room page with WebRTC (audio/video).
5. Chat, mute/camera/screen share controls.
6. STT pipeline: audio capture -> WS chunks -> faster-whisper -> transcript events + persistence + UI captions.
7. Polish: expiry, reconnection, transcript export, README.
8. (Future) Agentic interviewing layer: AI interviewer agent (langgraph) joins as "agent" participant, uses transcript, rubric scoring.

## Extensibility for agentic AI interviewing
- Keep Room generic; add InterviewProfile config (role, rubric, persona) as JSON.
- Participant role enum includes `agent` reserved for future AI interviewer.
- Transcript events stored with timestamps so agent can replay/analyze.
- STT service reusable for agent's own speech synthesis later.

## Risks / decisions
1. Browser WebRTC requires HTTPS in prod (localhost ok). Dev on localhost; prod behind reverse proxy with TLS.
2. NAT traversal: public STUN enough for most; document coturn for strict networks.
3. STT latency: faster-whisper is batch-ish; for true real-time use Deepgram streaming. Abstract behind STTService so swap is one env var.
4. Python 3.14 — verify faster-whisper/torch compatibility (torch already installed). Prefer `faster-whisper` (ctranslate2) — installed.
5. React+Vite dev server proxies /api and /ws to FastAPI.

## Verification
- Unit tests: room create/join/expiry, auth, STT service (mock).
- Integration: two browser tabs establish audio/video + see live captions.
- WebSocket test: signaling relay delivers offer/answer/ice + transcript.
- Lint: ruff (backend), eslint (frontend).

## Next step
Reply "go" and I'll implement Phase 1-4 first (backend skeleton + rooms + React scaffold + WebRTC), then iterate with STT.
