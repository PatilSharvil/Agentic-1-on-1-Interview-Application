import pytest
import pytest_asyncio

from app.db import init_db


@pytest_asyncio.fixture(autouse=True, loop_scope="function")
async def _init_db():
    await init_db()
    yield