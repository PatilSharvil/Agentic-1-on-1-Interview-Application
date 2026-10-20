# 1-to-1 Meeting Platform (Python)

FastAPI signaling server + React/Vite WebRTC client. 1-to-1 audio/video, chat, screen share, live STT captions.

## Run backend
```
cd backend
pip install -r requirements.txt
cp .env.example .env
uvicorn app.main:app --reload --port 8000
```

## Run frontend
```
cd frontend
npm install
npm run dev
```
Open http://localhost:5173

## Tests
```
cd backend
pytest ../tests -q
```

## Notes
- WebRTC uses public Google STUN; strict NATs need coturn.
- STT defaults to faster-whisper (local). Set STT_PROVIDER to swap (interface in app/stt.py).
- Recording deferred; agentic interviewing layer builds on Room/Participant/Transcript.