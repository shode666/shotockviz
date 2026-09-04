"""
Health-check endpoint.

Returns BaseResponse so clients/monitoring tools get a consistent envelope.
data_status reflects real service health:
  fresh       → all dependencies healthy
  degraded    → one or more dependencies unhealthy (data_status = partial)
  unavailable → critical failure (not returned here; health will 500)
"""
import asyncio
import threading
from datetime import datetime, timezone

import json as _json

import redis.asyncio as aioredis
from fastapi import APIRouter, Depends, Request
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from core.database import get_db
from core.config import settings
from core.redis import get_redis
from schemas.common import BaseResponse, CachedLayer
from schemas.envelope import EnvelopingAPIRoute

# bd:deps-2026-09 S2 (ADR-001 r3-2) — system.py splits into two routers:
#   health_router — GET /health only, mounted bare at /api (infra contract:
#     compose healthchecks curl this exact path unversioned; frozen, AC-B9).
#     Already hand-wraps BaseResponse itself — no route_class needed/wanted.
#   router — /system/ready, /system/celery-stats, /market/fgi — mounted
#     under /api/v1 in main.py (so they become /api/v1/system/ready etc.);
#     route_class = envelope wrap (ADR-002), same as the other 11 modules.
health_router = APIRouter(prefix="/api", tags=["system"])
router = APIRouter(tags=["system"], route_class=EnvelopingAPIRoute)

# Key symbols that must be in cache for us to declare "ready"
# Now includes both Thai (SET) and US stocks
_READY_PROBE_KEYS = [
    "quote:PTT.BK",  # Thai stock
    "quote:^GSPC",   # US S&P 500
    "quote:^IXIC",   # US NASDAQ
    "quote:NVDA",    # US stock (Nvidia)
    "quote:AAPL",    # US stock (Apple)
]
_READY_THRESHOLD = 3  # at least 3 of the probe keys must be cached

# Serializes the sys.stdout/sys.stderr swap below — that swap is a process-global
# mutation, not thread-local. Now that _check_celery_health() runs via
# asyncio.to_thread() (bd:ops-01), two overlapping /api/health calls on the same
# gunicorn worker could interleave the swap/restore and permanently bury the
# real sys.stdout under a discarded io.StringIO(). [Chris review §2, High]
_celery_health_lock = threading.Lock()


def _check_celery_health() -> str:
    """
    Check if Celery workers are active and healthy.

    Returns "ok" if at least one worker responds to ping, "fail" otherwise.
    Suppresses stdout/stderr during inspect to prevent kombu/amqp debug noise.
    """
    import io
    import sys

    with _celery_health_lock:
        # Suppress stdout/stderr — kombu prints AMQP connection debug info to stdout
        _old_stdout, _old_stderr = sys.stdout, sys.stderr
        sys.stdout = sys.stderr = io.StringIO()
        try:
            from workers.celery_app import celery_app

            inspect = celery_app.control.inspect(timeout=2.0)

            # Ping is lighter than active() — just checks worker liveness
            try:
                pong = inspect.ping()
                if pong and isinstance(pong, dict) and len(pong) > 0:
                    return "ok"
            except Exception:
                pass

            return "fail"

        except Exception:
            return "fail"
        finally:
            sys.stdout, sys.stderr = _old_stdout, _old_stderr


@health_router.get("/health", response_model=BaseResponse[dict])
async def health_check(
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """
    Liveness + readiness probe.

    Response shape::

        {
          "data": {
            "database": "ok" | "error",
            "redis":    "ok" | "error",
            "celery":   "ok" | "fail"
          },
          "meta": {
            "request_id":   "...",
            "data_status":  "fresh" | "partial",
            "as_of":        "<ISO-8601>",
            "cached_layer": "provider"
          }
        }
    """
    request_id: str = getattr(request.state, "request_id", "unknown")
    checks: dict[str, str] = {}
    degraded = False

    # ── Database ─────────────────────────────────────────────────────────────
    try:
        await db.execute(text("SELECT 1"))
        checks["database"] = "ok"
    except Exception:
        checks["database"] = "error"
        degraded = True

    # ── Redis ─────────────────────────────────────────────────────────────────
    try:
        r = await aioredis.from_url(settings.redis_url)
        await r.ping()
        await r.aclose()
        checks["redis"] = "ok"
    except Exception:
        checks["redis"] = "error"
        degraded = True

    # ── Celery ────────────────────────────────────────────────────────────────
    # _check_celery_health() is synchronous (kombu/amqp inspect().ping() blocks
    # up to ~2s waiting for a broker reply) — offload to a thread so this
    # gunicorn/uvicorn worker's event loop is never frozen while handling
    # /api/health (hit by Docker healthcheck + Caddy). Measured event-loop
    # freeze without to_thread: ~2.1s per call (see outputs/ops-01/01-dave-fix.md).
    # bd:ops-01
    checks["celery"] = await asyncio.to_thread(_check_celery_health)

    as_of = datetime.now(timezone.utc)

    if degraded:
        return BaseResponse.partial(
            data=checks,
            request_id=request_id,
            as_of=as_of,
            cached_layer=CachedLayer.PROVIDER,
        )

    return BaseResponse.ok(
        data=checks,
        request_id=request_id,
        as_of=as_of,
        cached_layer=CachedLayer.PROVIDER,
    )


@router.get("/system/ready")
async def cache_ready_check():
    """
    Lightweight cache-readiness probe for the frontend.

    Returns ``{"ready": true, "cached": N}`` once the startup warm-up tasks
    have populated at least ``_READY_THRESHOLD`` of the probe keys in Redis.
    Probe keys include both Thai (SET) and US stocks to ensure all markets are ready.
    The frontend polls this endpoint (every 3 s) and triggers a data
    refresh as soon as ``ready`` flips to ``true``.
    """
    try:
        # Use the shared connection pool — never create a new connection per poll.
        r = await get_redis()
        hits = 0
        for key in _READY_PROBE_KEYS:
            if await r.exists(key):
                hits += 1
        ready = hits >= _READY_THRESHOLD
        return {"ready": ready, "cached": hits, "total": len(_READY_PROBE_KEYS)}
    except Exception:
        return {"ready": False, "cached": 0, "total": len(_READY_PROBE_KEYS)}


@router.get("/system/celery-stats")
async def get_celery_stats():
    """
    Get Celery task success/failure statistics from Redis.

    Returns task counters and last execution timestamps for monitoring
    task queue health and troubleshooting silent failures.

    Response shape::

        {
          "success_count": 42,
          "failure_count": 1,
          "last_success_at": "2026-03-02T12:34:56.789123+00:00",
          "last_failure_at": "2026-03-02T11:20:00.123456+00:00",
          "last_error": "ConnectionError: Failed to connect to yfinance",
          "last_success_elapsed": "2.34"
        }
    """
    try:
        r = await get_redis()

        success = await r.get('celery:stats:success')
        failure = await r.get('celery:stats:failure')
        last_success = await r.get('celery:stats:last_success_at')
        last_failure = await r.get('celery:stats:last_failure_at')
        last_error = await r.get('celery:stats:last_error')
        last_elapsed = await r.get('celery:task:last_success_elapsed')

        return {
            "success_count": int(success or 0),
            "failure_count": int(failure or 0),
            "last_success_at": last_success if last_success else None,
            "last_failure_at": last_failure if last_failure else None,
            "last_error": last_error if last_error else None,
            "last_success_elapsed": last_elapsed if last_elapsed else None,
        }
    except Exception as e:
        return {
            "success_count": 0,
            "failure_count": 0,
            "last_success_at": None,
            "last_failure_at": None,
            "last_error": str(e)[:500],
            "last_success_elapsed": None,
        }


@router.get("/market/fgi")
async def get_fear_greed_index():
    """Get CNN Fear & Greed Index — pure-read from Redis cache.

    Returns cached FGI data: score (0-100), label, and change.
    Data is populated by ``workers.fgi_fetcher`` every 30 min.
    If cache is empty, triggers an on-demand fetch.
    """
    try:
        r = await get_redis()
        cached = await r.get("fgi:current")
        if cached:
            return _json.loads(cached)
    except Exception:
        pass

    # No cache — trigger on-demand fetch
    try:
        from workers.fgi_fetcher import fetch_fear_greed
        fetch_fear_greed.delay()
    except Exception:
        pass

    return {"score": None, "label": None, "change": None}
