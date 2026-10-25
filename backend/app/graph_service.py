"""Persist and broadcast knowledge graphs.

All rebuilds for a room are serialised with an asyncio lock, so an automatic
(post-answer) rebuild can never race a manual one. Automatic rebuilds are
debounced: while the candidate keeps talking, we wait, then build once.
"""
from __future__ import annotations

import asyncio
import hashlib
import json

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.db import SessionLocal
from app.graph_builder import build_graph_data
from app.models import GraphEdge, GraphNode, Resume, Room, Transcript

_locks: dict[str, asyncio.Lock] = {}
_last_signature: dict[str, str] = {}
_pending: dict[str, asyncio.Task] = {}


def _lock_for(code: str) -> asyncio.Lock:
    lock = _locks.get(code)
    if lock is None:
        lock = asyncio.Lock()
        _locks[code] = lock
    return lock


def _signature(resume_text: str, transcripts: list[dict], use_llm: bool) -> str:
    h = hashlib.sha1()
    h.update((resume_text or "").encode("utf-8", "ignore"))
    h.update(b"|llm:" + str(use_llm).encode())
    h.update(b"|gb:v3")
    for t in transcripts:
        h.update((t.get("text") or "").encode("utf-8", "ignore"))
        h.update(b"\x00")
    return h.hexdigest()


async def _load_inputs(db: AsyncSession, room: Room) -> tuple[str, list[dict]]:
    resume = await db.scalar(
        select(Resume).where(Resume.room_id == room.id).order_by(Resume.parsed_at.desc())
    )
    rows = (
        await db.scalars(
            select(Transcript).where(Transcript.room_id == room.id).order_by(Transcript.created_at)
        )
    ).all()
    transcripts = [
        {
            "id": t.id,
            "speaker": t.speaker,
            "text": t.text,
            "start_ms": t.start_ms,
            "end_ms": t.end_ms,
        }
        for t in rows
    ]
    return (resume.text if resume else ""), transcripts


async def rebuild_graph(
    db: AsyncSession,
    room: Room,
    *,
    use_llm: bool | None = None,
    force: bool = False,
) -> dict:
    """Build, persist and return the graph for `room`."""
    async with _lock_for(room.code):
        resume_text, transcripts = await _load_inputs(db, room)
        use_llm = settings.graph_llm_enrich if use_llm is None else use_llm
        # No point paying for LLM enrichment when nobody has spoken yet.
        use_llm = bool(use_llm and transcripts)
        signature = _signature(resume_text, transcripts, use_llm)
        if not force and _last_signature.get(room.code) == signature:
            existing = await _read_graph(db, room)
            if existing["nodes"] or existing["edges"]:
                return existing

        data = await asyncio.to_thread(
            build_graph_data,
            resume_text,
            transcripts,
            room.host_name,
            None,
            use_llm,
        )

        await db.execute(delete(GraphEdge).where(GraphEdge.room_id == room.id))
        await db.execute(delete(GraphNode).where(GraphNode.room_id == room.id))
        await db.flush()

        for node in data["nodes"]:
            db.add(
                GraphNode(
                    room_id=room.id,
                    node_key=node["id"],
                    label=node["label"][:255],
                    type=node.get("type", "entity"),
                    meta=json.dumps(node.get("meta") or {}),
                )
            )
        valid = {n["id"] for n in data["nodes"]}
        for edge in data["edges"]:
            if edge["source"] not in valid or edge["target"] not in valid:
                continue
            db.add(
                GraphEdge(
                    room_id=room.id,
                    source_key=edge["source"],
                    target_key=edge["target"],
                    relation=edge["relation"],
                    weight=float(edge.get("weight", 0.5)),
                )
            )
        await db.commit()
        _last_signature[room.code] = signature

        graph = await _read_graph(db, room)
        await broadcast_graph(room.code, graph)
        print(
            f"[graph] room {room.code}: {len(graph['nodes'])} nodes / {len(graph['edges'])} edges"
            f" (llm={use_llm}, resume_skills={data['stats'].get('resume_skills', 0)},"
            f" claims={data['stats'].get('claims', 0)})"
        )
        return graph


async def _read_graph(db: AsyncSession, room: Room) -> dict:
    nodes = (await db.scalars(select(GraphNode).where(GraphNode.room_id == room.id))).all()
    edges = (await db.scalars(select(GraphEdge).where(GraphEdge.room_id == room.id))).all()
    out_nodes = []
    for n in nodes:
        try:
            meta = json.loads(n.meta) if n.meta else {}
        except Exception:
            meta = {}
        out_nodes.append({"id": n.node_key, "label": n.label, "type": n.type, "meta": meta})
    out_edges = [
        {
            "id": e.id,
            "source": e.source_key,
            "target": e.target_key,
            "relation": e.relation,
            "weight": e.weight,
        }
        for e in edges
    ]
    return {"nodes": out_nodes, "edges": out_edges}


async def broadcast_graph(code: str, graph: dict) -> None:
    try:
        from app.signaling import manager

        await manager.broadcast(code, {"type": "graph-update", **graph})
    except Exception as e:  # noqa: BLE001
        print(f"[graph] broadcast failed: {e}")


def schedule_rebuild(code: str, delay: float | None = None) -> None:
    """Debounced automatic rebuild after new transcript text."""
    if not settings.graph_auto_rebuild:
        return
    delay = settings.graph_rebuild_debounce_s if delay is None else delay
    previous = _pending.pop(code, None)
    if previous and not previous.done():
        previous.cancel()

    async def _run() -> None:
        try:
            await asyncio.sleep(max(0.5, delay))
            async with SessionLocal() as session:
                room = await session.scalar(select(Room).where(Room.code == code))
                if not room:
                    return
                await rebuild_graph(session, room)
        except asyncio.CancelledError:
            return
        except Exception as e:  # noqa: BLE001
            print(f"[graph] auto rebuild failed for {code}: {e}")
        finally:
            _pending.pop(code, None)

    _pending[code] = asyncio.create_task(_run())


async def shutdown_scheduler() -> None:
    for task in list(_pending.values()):
        task.cancel()
    _pending.clear()
