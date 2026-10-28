import json
import sys
from pathlib import Path

import requests
import websocket

code = requests.post("http://localhost:8000/api/rooms", json={"host_name": "VadCheck"}).json()["code"]
ws = websocket.create_connection(f"ws://127.0.0.1:8000/ws/{code}?name=VadProbe", timeout=10)
joined = json.loads(ws.recv())
print("vad snapshot:", json.dumps(joined.get("vad")))
ok = joined.get("vad", {}).get("endpoint_silence_ms") == 1200 and joined.get("vad", {}).get("max_chunk_ms") == 15000
print("PASS" if ok else "FAIL")
ws.close()
sys.exit(0 if ok else 1)
