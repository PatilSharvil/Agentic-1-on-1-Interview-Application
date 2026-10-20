import json
from collections import defaultdict

from fastapi import WebSocket


class ConnectionManager:
    def __init__(self):
        self.rooms: dict[str, set[WebSocket]] = defaultdict(set)
        self.names: dict[WebSocket, str] = {}

    async def connect(self, code: str, ws: WebSocket, name: str):
        await ws.accept()
        self.rooms[code].add(ws)
        self.names[ws] = name

    def disconnect(self, code: str, ws: WebSocket):
        self.rooms[code].discard(ws)
        self.names.pop(ws, None)
        if not self.rooms[code]:
            del self.rooms[code]

    async def broadcast(self, code: str, payload: dict, exclude: WebSocket | None = None):
        dead = []
        for ws in list(self.rooms.get(code, ())):
            if ws is exclude:
                continue
            try:
                await ws.send_text(json.dumps(payload))
            except Exception:
                dead.append(ws)
        for ws in dead:
            self.disconnect(code, ws)

    async def send(self, ws: WebSocket, payload: dict):
        await ws.send_text(json.dumps(payload))


manager = ConnectionManager()