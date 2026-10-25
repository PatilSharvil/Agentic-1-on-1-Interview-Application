import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from app.main import app

RESUME = """Sharun Patil
Backend Engineer
Skills: Python, FastAPI, React, Docker, PostgreSQL, Kubernetes
Experience: 3 years at TechCorp building REST APIs
Projects
Interview Copilot: FastAPI and React application for interview practice
Education
B.Tech in Computer Science, Pune University, 2020
"""


@pytest_asyncio.fixture
async def client():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test", timeout=60) as c:
        yield c


async def _room_with_resume(client):
    r = await client.post("/api/rooms", json={"host_name": "Alice"})
    code = r.json()["code"]
    r = await client.post(
        f"/api/rooms/{code}/resume",
        files={"file": ("resume.txt", RESUME.encode(), "text/plain")},
    )
    assert r.status_code == 200, r.text
    return code, r.json()


@pytest.mark.asyncio
async def test_resume_upload_seeds_graph(client):
    code, body = await _room_with_resume(client)
    assert body["graph_built"] is True
    assert "Python" in body["skills"]

    r = await client.get(f"/api/rooms/{code}/graph")
    assert r.status_code == 200
    graph = r.json()
    labels = {n["label"] for n in graph["nodes"]}
    assert "Sharun Patil" in labels
    assert "Python" in labels
    assert any(e["relation"] == "has_skill" for e in graph["edges"])


@pytest.mark.asyncio
async def test_question_generation_uses_llm_and_validates(client, monkeypatch):
    code, _ = await _room_with_resume(client)

    async def fake_chat_json(*args, **kwargs):
        return {"questions": ["How did you use FastAPI at TechCorp?", "not a question", ""]}

    monkeypatch.setattr("app.copilot.chat_json", fake_chat_json)
    r = await client.post(
        f"/api/rooms/{code}/questions/generate",
        json={"job_title": "backend engineer", "count": 2},
    )
    assert r.status_code == 200
    questions = r.json()
    assert len(questions) == 2  # invalid items replaced by deterministic fallback
    assert all(q["text"].endswith("?") for q in questions)
    assert questions[0]["text"] == "How did you use FastAPI at TechCorp?"


@pytest.mark.asyncio
async def test_question_generation_falls_back_when_llm_is_down(client, monkeypatch):
    code, _ = await _room_with_resume(client)

    async def boom(*args, **kwargs):
        raise RuntimeError("provider down")

    monkeypatch.setattr("app.copilot.chat_json", boom)
    r = await client.post(
        f"/api/rooms/{code}/questions/generate",
        json={"job_title": "backend engineer", "count": 3},
    )
    assert r.status_code == 200
    questions = r.json()
    assert len(questions) == 3
    assert all(q["text"].endswith("?") for q in questions)


@pytest.mark.asyncio
async def test_adaptive_question_falls_back(client, monkeypatch):
    code, _ = await _room_with_resume(client)

    async def boom(*args, **kwargs):
        raise RuntimeError("provider down")

    monkeypatch.setattr("app.copilot.chat_json", boom)
    r = await client.post(
        f"/api/rooms/{code}/questions/next",
        json={"previous_answer": "I used FastAPI and PostgreSQL to build the payments API."},
    )
    assert r.status_code == 200
    q = r.json()
    assert q["source"] == "adaptive"
    assert q["text"].endswith("?")


@pytest.mark.asyncio
async def test_adaptive_question_accepts_llm_output(client, monkeypatch):
    code, _ = await _room_with_resume(client)

    async def fake_chat_json(*args, **kwargs):
        return {"question": "You mentioned PostgreSQL — how did you handle schema migrations?"}

    monkeypatch.setattr("app.copilot.chat_json", fake_chat_json)
    r = await client.post(f"/api/rooms/{code}/questions/next", json={})
    assert r.status_code == 200
    assert "PostgreSQL" in r.json()["text"]


@pytest.mark.asyncio
async def test_resume_only_rebuild(client):
    code, _ = await _room_with_resume(client)
    r = await client.post(f"/api/rooms/{code}/graph/rebuild?source=resume")
    assert r.status_code == 200
    graph = r.json()
    assert graph["nodes"]
    assert all(e["relation"] != "contradicts" for e in graph["edges"])


@pytest.mark.asyncio
async def test_questions_require_resume(client):
    r = await client.post("/api/rooms", json={"host_name": "Alice"})
    code = r.json()["code"]
    r = await client.post(f"/api/rooms/{code}/questions/generate", json={"count": 3})
    assert r.status_code == 400
