import pytest
from httpx import ASGITransport, AsyncClient

from app.main import app


@pytest.mark.asyncio
async def test_health():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        r = await c.get("/health")
        assert r.status_code == 200
        assert r.json() == {"status": "ok"}


@pytest.mark.asyncio
async def test_create_and_get_room():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        r = await c.post("/api/rooms", json={"host_name": "Alice"})
        assert r.status_code == 200
        code = r.json()["code"]
        r2 = await c.get(f"/api/rooms/{code}")
        assert r2.status_code == 200
        assert r2.json()["host_name"] == "Alice"


@pytest.mark.asyncio
async def test_room_not_found():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        r = await c.get("/api/rooms/NOPE1234")
        assert r.status_code == 404