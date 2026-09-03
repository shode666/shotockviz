"""Pytest configuration and shared fixtures for API tests."""
import os
from typing import AsyncGenerator
from unittest.mock import AsyncMock, patch

import pytest
from fastapi.testclient import TestClient
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine, async_sessionmaker
from sqlalchemy.pool import StaticPool

from core.database import Base, get_db
from core.config import settings
from core.security import create_access_token, hash_password
from models.user import User
from main import app


# ─────────────────────────────────────────────────────────────────────────────
# Test Database Setup
# ─────────────────────────────────────────────────────────────────────────────

# bd:deps-2026-09 WP-B2 — the `event_loop` fixture override is REMOVED
# (pytest-asyncio 1.x removed the `event_loop` fixture entirely —
# 01-sara-adr-migration.md §2.3). Session-scoped loop semantics now come
# from `asyncio_default_fixture_loop_scope = session` in backend/pytest.ini.


@pytest.fixture
async def test_db() -> AsyncGenerator[AsyncSession, None]:
    """Create a fresh in-memory SQLite database for each test."""
    # Use SQLite in-memory for testing (faster, isolated)
    engine = create_async_engine(
        "sqlite+aiosqlite:///:memory:",
        echo=False,
        poolclass=StaticPool,
    )

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    async_session_local = async_sessionmaker(
        engine, class_=AsyncSession, expire_on_commit=False
    )

    async with async_session_local() as session:
        yield session

    await engine.dispose()


@pytest.fixture
async def override_db(test_db):
    """Override the FastAPI dependency for database."""
    async def get_test_db():
        yield test_db

    app.dependency_overrides[get_db] = get_test_db
    yield
    app.dependency_overrides.clear()


# ─────────────────────────────────────────────────────────────────────────────
# Test User Fixtures
# ─────────────────────────────────────────────────────────────────────────────

@pytest.fixture
async def test_user(test_db: AsyncSession) -> User:
    """Create a test user in the database."""
    user = User(
        email="test@example.com",
        password_hash=hash_password("password123"),
        display_name="Test User",
        is_active=True,
    )
    test_db.add(user)
    await test_db.flush()
    await test_db.refresh(user)
    return user


@pytest.fixture
def valid_token(test_user: User) -> str:
    """Generate a valid JWT token for the test user."""
    return create_access_token({
        "sub": str(test_user.id),
        "email": test_user.email,
        "display_name": test_user.display_name,
        "role": test_user.role.value,
        "created_at": test_user.created_at.isoformat(),
    })


@pytest.fixture
def auth_headers(valid_token: str) -> dict:
    """Return authorization headers with valid JWT token."""
    return {"Authorization": f"Bearer {valid_token}"}


# ─────────────────────────────────────────────────────────────────────────────
# Async HTTP Client Fixture
# ─────────────────────────────────────────────────────────────────────────────

@pytest.fixture
async def async_client(override_db) -> AsyncGenerator[AsyncClient, None]:
    """Create an async HTTP client for testing."""
    # bd:deps-2026-09 WP-B2 — httpx 0.28 removed the `AsyncClient(app=...)`
    # shortcut; must build the ASGI transport explicitly (pre-existing
    # breakage per 01-sara-adr-migration.md §2.3, fixed in this pass — this
    # fixture had zero currently-passing callers per the B0 audit, so this
    # is not a regression source).
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        yield client


# ─────────────────────────────────────────────────────────────────────────────
# Redis Mock Fixture
# ─────────────────────────────────────────────────────────────────────────────

@pytest.fixture
def mock_redis():
    """Mock Redis client for testing."""
    mock = AsyncMock()
    # Mock get/set operations
    mock.get = AsyncMock(return_value=None)
    mock.set = AsyncMock(return_value=True)
    mock.pipeline = AsyncMock(return_value=AsyncMock(
        execute=AsyncMock(return_value=[])
    ))
    mock.exists = AsyncMock(return_value=False)
    mock.ping = AsyncMock(return_value=b"PONG")
    return mock


# ─────────────────────────────────────────────────────────────────────────────
# Stock Service Mocks
# ─────────────────────────────────────────────────────────────────────────────

@pytest.fixture
def mock_stock_service():
    """Mock the stock_service module."""
    with patch("services.stock_service") as mock:
        mock.get_redis = AsyncMock()
        mock.fetch_quote_now = AsyncMock()
        mock.fetch_stock_history = AsyncMock()
        mock.fetch_stock_fundamentals = AsyncMock()
        mock.search_stocks = AsyncMock()
        yield mock


# ─────────────────────────────────────────────────────────────────────────────
# Sample Data Fixtures
# ─────────────────────────────────────────────────────────────────────────────

@pytest.fixture
def sample_quote():
    """Return a sample stock quote response."""
    return {
        "symbol": "NVDA",
        "price": 875.50,
        "change": 12.30,
        "change_pct": 1.42,
        "open": 870.00,
        "high": 885.00,
        "low": 865.00,
        "volume": 45_000_000,
        "market_cap": 2_150_000_000_000,
    }


@pytest.fixture
def sample_history():
    """Return a sample stock history response."""
    return {
        "symbol": "NVDA",
        "timeframe": "1D",
        "bars": [
            {"t": 1700000000, "o": 850.0, "h": 855.0, "l": 845.0, "c": 852.5, "v": 50_000_000},
            {"t": 1700086400, "o": 852.5, "h": 870.0, "l": 850.0, "c": 868.0, "v": 55_000_000},
            {"t": 1700172800, "o": 868.0, "h": 875.0, "l": 860.0, "c": 872.5, "v": 48_000_000},
        ]
    }


@pytest.fixture
def sample_fundamentals():
    """Return a sample stock fundamentals response."""
    return {
        "symbol": "NVDA",
        "pe_ratio": 45.2,
        "pb_ratio": 18.5,
        "eps": 19.32,
        "dividend_yield": 0.05,
        "market_cap": 2_150_000_000_000,
        "revenue": 60_900_000_000,
        "profit_margin": 0.31,
    }


@pytest.fixture
def sample_watchlist_item():
    """Return sample watchlist creation data."""
    return {
        "symbol": "NVDA",
    }


@pytest.fixture
def sample_transaction():
    """Return sample transaction creation data."""
    return {
        "symbol": "NVDA",
        "type": "BUY",
        "date": "2024-01-15",
        "qty": 10.0,
        "price": 750.00,
        "fee": 50.00,
        "notes": "Initial position",
    }


@pytest.fixture
def sample_alert():
    """Return sample alert creation data."""
    return {
        "symbol": "NVDA",
        "alert_type": "PRICE",
        "condition": "ABOVE",
        "value": 900.0,
        "channel": "EMAIL",
    }


@pytest.fixture
def sample_drawing():
    """Return sample drawing creation data."""
    return {
        "tool_type": "line",
        "data_json": '{"x1": 100, "y1": 200, "x2": 300, "y2": 400}',
        "style_json": '{"color": "#FF0000"}',
    }


@pytest.fixture
def sample_note():
    """Return sample note creation data."""
    return {
        "content": "Strong technical setup, waiting for breakout above 900.",
    }
