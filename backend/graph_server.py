"""Standalone knowledge-graph viewer on port 5133.

Serves the D3 force-directed graph page. The page talks to the main backend
(port 8000) for the initial graph and for live WebSocket updates.

Run:  python graph_server.py
Open: http://localhost:5133/graph/{room_code}
"""
import os
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import HTMLResponse

app = FastAPI(title="knowledge-graph-viewer")
HTML_PATH = Path(__file__).resolve().parent.parent / "frontend" / "public" / "graph.html"
API_BASE = os.getenv("GRAPH_API_BASE", "http://127.0.0.1:8000").rstrip("/")


@app.get("/")
@app.get("/graph/{code}")
def index(code: str = ""):
    if HTML_PATH.exists():
        html = HTML_PATH.read_text(encoding="utf-8")
        html = html.replace("__ROOM_CODE__", code).replace("__API_BASE__", API_BASE)
        return HTMLResponse(html)
    return HTMLResponse("<h1>graph.html not found</h1>", status_code=404)


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=5133)
