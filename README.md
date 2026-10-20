# 1-to-1 Meeting Platform (Python)

FastAPI signaling server + React/Vite WebRTC client. 1-to-1 audio/video, chat, screen share, live STT captions.

## Setup

### Backend
```
cd backend
pip install -r requirements.txt
cp .env.example .env
# Edit .env with your GROQ_API_KEY and OPENROUTER_API_KEY
uvicorn app.main:app --reload --port 8000
```

### Frontend
```
cd frontend
npm install
npm run dev
```
Open http://localhost:5173

### Knowledge Graph Viewer (optional, separate port)
```
cd backend
python graph_server.py
```
Open http://localhost:5133/graph/{room_code}

### Cloudflare Tunnel (for public demo)
1. Install cloudflared (if not already):
   ```
   install-cloudflared.bat
   ```
   Or download manually from https://github.com/cloudflare/cloudflared/releases
   and place `cloudflared.exe` in the `bin/` folder.

2. Run the one-click demo launcher:
   ```
   start-demo.bat
   ```
   This starts the backend, frontend, and a Cloudflare Tunnel.
   A public URL (e.g. `https://xxx.trycloudflare.com`) will be printed.
   Share this URL with your demo audience.

## Tests
```
cd backend
pytest ../tests -q
```

## Notes
- WebRTC uses public Google STUN; strict NATs need coturn.
- STT defaults to faster-whisper (local). Set STT_PROVIDER to swap (interface in app/stt.py).
- Recording deferred; agentic interviewing layer builds on Room/Participant/Transcript.