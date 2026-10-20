"""Direct backend check: WS audio-chunk -> Groq -> transcript broadcast."""
import asyncio
import base64
import json
import sys

import websockets

AUDIO = r"C:\Users\patil\AppData\Local\Temp\opencode\speech.wav"
BASE = "ws://127.0.0.1:8000"


async def main():
    try:
        async with websockets.connect(f"{BASE}/ws/ZZZZZZZZ?name=Tester"):
            print("connected (unexpected, room should not exist)")
    except Exception as e:
        print("nonexistent room rejected:", type(e).__name__)

    # create room via http
    import httpx

    async with httpx.AsyncClient() as c:
        r = await c.post(f"http://127.0.0.1:8000/api/rooms", json={"host_name": "Tester"})
        code = r.json()["code"]
    print("room:", code)

    audio = base64.b64encode(open(AUDIO, "rb").read()).decode()
    async with websockets.connect(f"{BASE}/ws/{code}?name=Tester") as ws:
        print("joined:", json.loads(await ws.recv()))
        await ws.send(json.dumps({"type": "audio-chunk", "audio": audio, "suffix": ".wav"}))
        for _ in range(5):
            msg = json.loads(await asyncio.wait_for(ws.recv(), timeout=60))
            print("recv:", msg)
            if msg.get("type") == "transcript":
                return 0
            if msg.get("type") == "error":
                return 1
    return 1


sys.exit(asyncio.run(main()))
