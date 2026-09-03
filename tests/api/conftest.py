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
async def _test_user(db_session):
    """Create a test user directly in the DB (no HTTP round-trip)."""
    from core.security import hash_password
    from models.user import User

    user = User(
        email="test@example.com",
        password_hash=hash_password("TestPass1"),
        display_name="Test User",
        is_active=True,
    )
    db_session.add(user)
    await db_session.flush()
    await db_session.refresh(user)
    return user


@pytest.fixture
def auth_headers(_test_user):
    """Bearer Authorization header for a directly-minted JWT.

    bd:deps-2026-09 S1 (AC-D9) — was: register+login HTTP round-trip against
    POST /api/auth/register + POST /api/auth/login, both removed by
    ADR-007. Mints the token via core.security.create_access_token instead,
    mirroring backend/tests/conftest.py:98's already-safe pattern.
    """
    from core.security import create_access_token

    token = create_access_token({
        "sub": str(_test_user.id),
        "email": _test_user.email,
        "display_name": _test_user.display_name,
        "role": _test_user.role.value,
        "created_at": _test_user.created_at.isoformat(),
    })
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
