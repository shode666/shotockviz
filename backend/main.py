"""StockViz FastAPI Application Entry Point."""
import asyncio
import json
from contextlib import asynccontextmanager
from typing import Set

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware

from core.config import settings
from core.database import create_tables
from core.logger import setup_logging, get_logger
from core.redis import init_redis, close_redis
from api.routes import auth, stocks, watchlist, portfolio, alerts, drawings, system, screener
from api.routes import dashboard, ai_chat, notes, portfolio_performance, admin, backtesting
from api.middleware.rate_limit import RateLimitMiddleware
from api.middleware.request_id import RequestIDMiddleware

# Import the configured Celery app so it becomes Celery's *current app* in this
# process (Celery() defaults set_as_current=True). Without this, @shared_task
# (e.g. workers.on_demand_listener.process_fetch_request) binds to Celery's
# unconfigured default app on first .delay() in a fresh gunicorn worker —
# broker_url=None -> amqp://localhost -> Errno 111 Connection refused.
# bd:ops-01
import workers.celery_app  # noqa: F401

logger = get_logger(__name__)


# ─── Startup Cache Warm-up ──────────────────────────────────────────────────

async def _warmup_cache() -> None:
    """
    Async warm-up: pre-populate Redis quote cache without touching Celery.

    Runs 8 seconds after startup to give Redis time to be ready.
    Uses _cache_quote_background() which is fully async (no sync broker connect).
    """
    await asyncio.sleep(8)
    try:
        from services.stock_service import _cache_quote_background
        warm_symbols = [
            "NVDA", "AAPL", "TSLA", "MSFT", "GOOGL", "AMZN",  # US
            "PTT.BK", "ADVANC.BK", "KBANK.BK",                  # Thai
            "^GSPC", "^IXIC",                                    # Indices
        ]
        results = await asyncio.gather(
            *[_cache_quote_background(sym) for sym in warm_symbols],
            return_exceptions=True,
        )
        ok = sum(1 for r in results if not isinstance(r, Exception))
        logger.info("Startup cache warm-up complete", cached=ok, total=len(warm_symbols))
    except Exception as e:
        logger.warning("Startup cache warm-up failed", error=str(e))


# ─── WebSocket Connection Manager ──────────────────────────────────────────

class ConnectionManager:
    """Manages active WebSocket connections for real-time price updates."""

    def __init__(self):
        self.active: Set[WebSocket] = set()
        self.subscriptions: dict[WebSocket, Set[str]] = {}

    async def connect(self, ws: WebSocket):
        await ws.accept()
        self.active.add(ws)
        self.subscriptions[ws] = set()

    def disconnect(self, ws: WebSocket):
        self.active.discard(ws)
        self.subscriptions.pop(ws, None)

    def subscribe(self, ws: WebSocket, symbol: str):
        if ws in self.subscriptions:
            self.subscriptions[ws].add(symbol.upper())

    async def broadcast_price(self, symbol: str, data: dict):
        """Send price update to all subscribers of a symbol."""
        disconnected = []
        for ws, symbols in self.subscriptions.items():
            if symbol.upper() in symbols:
                try:
                    await ws.send_json(data)
                except Exception:
                    disconnected.append(ws)
        for ws in disconnected:
            self.disconnect(ws)

    async def broadcast_all(self, data: dict):
        """Send a message to ALL connected WebSocket clients (e.g. alert notifications)."""
        disconnected = []
        for ws in list(self.active):
            try:
                await ws.send_json(data)
            except Exception:
                disconnected.append(ws)
        for ws in disconnected:
            self.disconnect(ws)


manager = ConnectionManager()


# ─── Redis → WebSocket Price Broadcaster ───────────────────────────────────

async def _redis_price_broadcaster() -> None:
    """
    Subscribe to the Redis 'price_updates' channel and forward each message
    to all relevant WebSocket subscribers.

    Uses a SEPARATE Redis connection — pub/sub hijacks the connection and
    cannot share the main pool from core.redis.get_redis().

    Published by: workers/price_fetcher.py  _cache_and_publish()
    Consumed by:  manager.broadcast_price() → WebSocket clients
    """
    import json as _json
    import redis.asyncio as aioredis

    while True:
        sub_client = None
        try:
            sub_client = await aioredis.from_url(
                settings.redis_url,
                encoding="utf-8",
                decode_responses=True,
                socket_connect_timeout=5,
                socket_timeout=None,  # blocking read — no timeout on subscribe
            )
            pubsub = sub_client.pubsub()
            await pubsub.subscribe("price_updates")
            logger.info("Redis pub/sub listener started on 'price_updates'")

            async for message in pubsub.listen():
                if message.get("type") != "message":
                    continue
                try:
                    data = _json.loads(message["data"])
                    msg_type = data.get("type", "")
                    symbol = data.get("symbol", "")

                    if msg_type == "alert_triggered":
                        # Alert notifications go to ALL connected clients
                        await manager.broadcast_all(data)
                    elif msg_type == "data_ready":
                        # Backend finished fetching external data — tell ALL clients
                        # to re-fetch. Sent by stock_service._notify_data_ready()
                        await manager.broadcast_all(data)
                    elif symbol:
                        # Price updates go only to symbol subscribers
                        await manager.broadcast_price(symbol, data)
                except Exception as e:
                    logger.debug("Price broadcast error", error=str(e))

        except asyncio.CancelledError:
            break
        except Exception as e:
            logger.warning("Redis pub/sub disconnected, reconnecting in 5s", error=str(e))
            await asyncio.sleep(5)
        finally:
            if sub_client is not None:
                try:
                    await sub_client.aclose()
                except Exception:
                    pass


# ─── DB Enum Sync ──────────────────────────────────────────────────────────

async def _sync_markettype_enum() -> None:
    """Add any missing MarketType values to the PostgreSQL enum.

    SQLAlchemy's create_all() won't alter existing enum types, so new values
    (JP, CN, HK, etc.) must be added explicitly via ALTER TYPE.
    Also syncs AlertType and AlertChannel enums.
    """
    from sqlalchemy import text
    from core.database import engine
    from models.stock import MarketType
    from models.alert import AlertType, AlertChannel

    enum_map = {
        "markettype": [e.value for e in MarketType],
        "alerttype": [e.value for e in AlertType],
        "alertchannel": [e.value for e in AlertChannel],
    }

    async with engine.begin() as conn:
        for pg_type, values in enum_map.items():
            for val in values:
                try:
                    # DDL: can't use parameter binding for enum values
                    safe_val = val.replace("'", "''")
                    await conn.execute(
                        text(f"ALTER TYPE {pg_type} ADD VALUE IF NOT EXISTS '{safe_val}'")
                    )
                except Exception:
                    pass  # already exists or type doesn't exist yet
    logger.info("PostgreSQL enum types synced")


# ─── App Lifecycle ──────────────────────────────────────────────────────────

@asynccontextmanager
async def lifespan(app: FastAPI):
    setup_logging()
    logger.info("Starting StockViz", env=settings.app_env)

    # Create tables on startup (dev only; use Alembic in prod)
    if settings.app_env == "development":
        await create_tables()
        # Ensure all MarketType enum values exist in PostgreSQL
        # (create_all only creates new types, doesn't add values to existing enums)
        await _sync_markettype_enum()
        logger.info("Database tables created")

    # Shared Redis connection pool
    await init_redis()

    # Warm up quote cache in background — fully async, no Celery dependency
    # apply_async() is synchronous and opens its own broker connection which conflicts
    # with the asyncio event loop. Use _cache_quote_background() instead.
    asyncio.create_task(_warmup_cache())

    # Bridge: Redis pub/sub 'price_updates' → WebSocket broadcast
    # Celery workers publish price updates; this loop forwards them to connected clients
    broadcaster_task = asyncio.create_task(_redis_price_broadcaster())

    yield

    broadcaster_task.cancel()
    try:
        await broadcaster_task
    except asyncio.CancelledError:
        pass

    await close_redis()
    logger.info("Shutting down StockViz")


# ─── FastAPI App ────────────────────────────────────────────────────────────

app = FastAPI(
    title="StockViz API",
    version="0.1.0",
    description="Self-hosted stock analysis platform for Thai and US markets",
    docs_url="/docs" if not settings.is_production else None,
    redoc_url="/redoc" if not settings.is_production else None,
    lifespan=lifespan,
)

# NOTE: Starlette applies middleware in REVERSE registration order.
# Execution order: RequestID → RateLimit → CORS → route handler

# CORS (outermost — must run first so browsers get CORS headers even on 429)
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*", "X-Request-ID"],
    expose_headers=["X-Request-ID"],
)

# Rate limiting (before routing, after CORS)
app.add_middleware(RateLimitMiddleware, redis_url=settings.redis_url)

# Request-ID (innermost — runs first, so request_id is available to all downstream)
app.add_middleware(RequestIDMiddleware)

# ─── Routers ────────────────────────────────────────────────────────────────

app.include_router(system.router)
app.include_router(auth.router)
app.include_router(stocks.router)
app.include_router(watchlist.router)
app.include_router(portfolio.router)
app.include_router(portfolio_performance.router)   # equity curve
app.include_router(alerts.router)
app.include_router(drawings.router)
app.include_router(screener.router)
app.include_router(dashboard.router)               # market overview
app.include_router(ai_chat.router)                 # AI assistant
app.include_router(notes.router)                   # stock notes
app.include_router(admin.router)                   # admin settings
app.include_router(backtesting.router)             # strategy backtesting


# ─── WebSocket ──────────────────────────────────────────────────────────────

@app.websocket("/api/ws/prices")
async def websocket_prices(ws: WebSocket):
    """Real-time price subscription WebSocket."""
    await manager.connect(ws)
    logger.info("WebSocket connected")
    try:
        while True:
            data = await ws.receive_text()
            try:
                msg = json.loads(data)
                action = msg.get("action")
                symbol = msg.get("symbol", "")

                if action == "subscribe" and symbol:
                    manager.subscribe(ws, symbol)
                    await ws.send_json({"type": "subscribed", "symbol": symbol.upper()})
                elif action == "unsubscribe" and symbol:
                    if ws in manager.subscriptions:
                        manager.subscriptions[ws].discard(symbol.upper())
                    await ws.send_json({"type": "unsubscribed", "symbol": symbol.upper()})
                elif action == "ping":
                    await ws.send_json({"type": "pong"})
            except json.JSONDecodeError:
                await ws.send_json({"type": "error", "message": "Invalid JSON"})
    except WebSocketDisconnect:
        manager.disconnect(ws)
        logger.info("WebSocket disconnected")
