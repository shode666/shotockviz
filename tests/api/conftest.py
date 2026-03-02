"""
pytest configuration for ShotockViz API tests.

This project lives in {root}/tests/api/ — outside the Docker build contexts.
We add the backend directory to sys.path so imports resolve correctly.

Run:
    cd tests/api && pytest -v
    cd tests/api && pytest -v -k "TestAuth"  # specific class
    cd tests/api && pytest -v --tb=short     # short tracebacks

Requires:
    pip install -r requirements.txt
    Docker stack running (or SQLite in-memory for unit-level tests)
"""
import sys
import os
import asyncio

# ── Resolve backend path ─────────────────────────────────────────────────────
ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
BACKEND = os.path.join(ROOT, "backend")
sys.path.insert(0, BACKEND)

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker

TEST_DATABASE_URL = "sqlite+aiosqlite:///:memory:"


@pytest.fixture(scope="session")
def event_loop():
    loop = asyncio.new_event_loop()
    yield loop
    loop.close()


@pytest.fixture(scope="session")
async def test_engine():
    engine = create_async_engine(TEST_DATABASE_URL, echo=False)
    from core.database import Base
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield engine
    await engine.dispose()


@pytest.fixture
async def db_session(test_engine):
    session_factory = async_sessionmaker(bind=test_engine, expire_on_commit=False)
    async with session_factory() as session:
        yield session
        await session.rollback()


@pytest.fixture
def client(db_session):
    """Function-scoped TestClient with per-test DB session.
    Used by existing tests (test_auth.py, test_timeout_handling.py, etc.)."""
    from main import app
    from core.database import get_db

    async def override_get_db():
        yield db_session

    app.dependency_overrides[get_db] = override_get_db
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()


@pytest.fixture
def auth_headers(client):
    """Register a test user and return Authorization header."""
    client.post("/api/auth/register", json={
        "email": "test@example.com",
        "password": "TestPass1",
        "display_name": "Test User",
    })
    resp = client.post("/api/auth/login", json={
        "email": "test@example.com",
        "password": "TestPass1",
    })
    token = resp.json()["access_token"]
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture(scope="module")
def app_client():
    """Module-scoped ASGI TestClient — reuses in-memory DB within a module.
    Used by test_api_endpoints.py."""
    from main import app
    from core.database import get_db

    async def _get_test_db():
        engine = create_async_engine(TEST_DATABASE_URL, echo=False)
        from core.database import Base
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        session_factory = async_sessionmaker(bind=engine, expire_on_commit=False)
        async with session_factory() as session:
            yield session

    app.dependency_overrides[get_db] = _get_test_db
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()
