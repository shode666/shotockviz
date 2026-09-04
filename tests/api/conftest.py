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

# bd:deps-2026-09 iter1 (CHRIS-01/Q-4, second half) — must be set before
# `core.config` is first imported anywhere in this session (below/lazily
# by fixtures), so it has to come before `sys.path.insert` too. Without
# this, `main.py`'s lifespan runs `create_tables()`/`_sync_markettype_enum()`
# against the REAL Postgres engine (`core.database.engine` — a
# process-wide singleton) on every single `TestClient(app)` __enter__.
# Each TestClient context manager spins up its OWN event loop (anyio
# blocking portal); the singleton engine's pooled asyncpg connections are
# bound to whichever loop first opened them, so the 2nd+ test's lifespan
# reuses a connection created on an already-closed loop from the 1st test
# -> "Task ... attached to a different loop" / "Event loop is closed".
# Setting APP_ENV=test skips that dev-only auto-migrate block entirely
# (main.py:213 `if settings.app_env == "development"`) — tests never
# needed it since `get_db` is always overridden to the in-memory sqlite
# session; the real engine is simply never touched by these tests at all
# now. `close_redis()`/`init_redis()` still run every lifespan cycle
# (unaffected, no singleton-across-loops issue — a fresh client per call).
os.environ.setdefault("APP_ENV", "test")

# ── Resolve backend path ─────────────────────────────────────────────────────
ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
BACKEND = os.path.join(ROOT, "backend")
sys.path.insert(0, BACKEND)

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker
from sqlalchemy.pool import StaticPool

TEST_DATABASE_URL = "sqlite+aiosqlite:///:memory:"

# bd:deps-2026-09 iter1 (CHRIS-01/Q-4) — pytest-asyncio 1.x removed the
# `event_loop` fixture entirely (01-sara-adr-migration.md §2.3); the custom
# session-scoped override that used to live here caused real-asyncpg
# connections (opened by the app's own lifespan under TestClient) to be
# created under one event loop and torn down under another, producing
# intermittent "Future attached to a different loop" RuntimeErrors that
# made `tests/api`'s totals non-reproducible across runs (CHRIS-01/Q-4).
# Session-scoped loop semantics now come from
# `asyncio_default_fixture_loop_scope = session` in tests/api/pytest.ini —
# mirrors backend/pytest.ini's already-correct pattern exactly.


@pytest.fixture
async def test_engine():
    """Function-scoped, StaticPool-backed in-memory engine — one fresh,
    isolated schema per test.

    bd:deps-2026-09 iter1 (CHRIS-04/Q-3/Q-5) — two bugs fixed together
    here, same root cause:
      - CHRIS-04/Q-5: without `poolclass=StaticPool`, each connection
        checkout from the pool (create_all's `engine.begin()` vs. a later
        session's own checkout) can silently land on a *different*
        physical `:memory:` SQLite connection — each one its own blank
        database — producing "no such table" errors that don't reproduce
        outside a full-suite run (collection-order-dependent). StaticPool
        pins every checkout to ONE physical connection, exactly mirroring
        `backend/tests/conftest.py`'s already-proven `test_db` fixture.
      - Q-3: this engine (not `app_client`'s old ad-hoc-per-request one,
        removed below) is now the ONE shared engine `client`, `app_client`,
        `db_session`, and `auth_headers`/`_test_user` all bind to — a
        user row created by one fixture is now guaranteed visible to
        every request made through either TestClient alias.
    Also force-imports `models` before `create_all()` (Q-5's other half):
    a bare `from core.database import Base` does not import sibling model
    modules, so `Base.metadata` can be incomplete at `create_all()` time
    depending on which test file pytest happens to collect first in the
    session — explicit import makes table registration deterministic.
    """
    engine = create_async_engine(TEST_DATABASE_URL, echo=False, poolclass=StaticPool)
    from core.database import Base
    import models  # noqa: F401 — see docstring: forces full ORM registration
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


@pytest.fixture
def app_client(test_engine, db_session):
    """ASGI TestClient sharing `test_engine`/`db_session` with `client`
    above and `auth_headers`/`_test_user` below.

    bd:deps-2026-09 iter1 (Q-3) — previously module-scoped AND opened a
    brand-new in-memory SQLite engine on every single request via its own
    `_get_test_db()` override: a different, empty database per request,
    so nothing written by one request (or by a fixture using the
    session-scoped `test_engine`) was ever visible to another. That's why
    `test_api_endpoints.py::TestWatchlist` (auth_headers-authenticated
    writes, then reads) silently 401'd/lost state — documented as a known
    limitation in that file's own `registered_user` docstring at the
    time, not a hidden bug. Now function-scoped and bound to the same
    `test_engine`/`db_session` `client` uses — kept as a separate fixture
    name only so `test_api_endpoints.py`/`test_contract_v1.py`'s existing
    `def test_x(self, app_client, ...)` signatures don't need editing."""
    from main import app
    from core.database import get_db

    async def _get_test_db():
        yield db_session

    app.dependency_overrides[get_db] = _get_test_db
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()
