import asyncio
import json
from collections import defaultdict

from fastapi import WebSocket

# A stalled client socket (e.g. a weak mobile link through the tunnel) must
# never block the event loop or hold up broadcasts for everyone else.
_SEND_TIMEOUT_S = 3.0


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
        if not self.rooms.get(code):
            self.rooms.pop(code, None)

    async def broadcast(self, code: str, payload: dict, exclude: WebSocket | None = None):
        """Send to every client concurrently and drop sockets that stall.

        The previous implementation awaited sends one-by-one, so a single slow
        client back-pressured the event loop and froze all transcript and graph
        broadcasts for the whole room while the backend kept working.
        """
        sockets = [ws for ws in list(self.rooms.get(code, ())) if ws is not exclude]
        if not sockets:
            return
        text = json.dumps(payload)
        dead: list[WebSocket] = []

        async def _send(ws: WebSocket) -> None:
            try:
                await asyncio.wait_for(ws.send_text(text), timeout=_SEND_TIMEOUT_S)
            except (Exception, asyncio.TimeoutError):
                dead.append(ws)

        await asyncio.gather(*(_send(ws) for ws in sockets))
        for ws in dead:
            self.disconnect(code, ws)

    async def send(self, ws: WebSocket, payload: dict):
        await ws.send_text(json.dumps(payload))


manager = ConnectionManager()
