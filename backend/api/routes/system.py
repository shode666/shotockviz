"""
Health-check endpoint.

Returns BaseResponse so clients/monitoring tools get a consistent envelope.
data_status reflects real service health:
  fresh       → all dependencies healthy
  degraded    → one or more dependencies unhealthy (data_status = partial)
  unavailable → critical failure (not returned here; health will 500)
"""
from datetime import datetime, timezone

import redis.asyncio as aioredis
from fastapi import APIRouter, Depends, Request
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from core.database import get_db
from core.config import settings
from core.redis import get_redis
from schemas.common import BaseResponse, CachedLayer

router = APIRouter(prefix="/api", tags=["system"])

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


def _check_celery_health() -> str:
    """
    Check if Celery workers are active and healthy.

    Returns "ok" if at least one worker responds to ping, "fail" otherwise.
    Suppresses stdout/stderr during inspect to prevent kombu/amqp debug noise.
    """
    import io
    import sys

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


@router.get("/health", response_model=BaseResponse[dict])
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
    checks["celery"] = _check_celery_health()

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
            "last_success_at": last_success.decode() if last_success else None,
            "last_failure_at": last_failure.decode() if last_failure else None,
            "last_error": last_error.decode() if last_error else None,
            "last_success_elapsed": last_elapsed.decode() if last_elapsed else None,
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
