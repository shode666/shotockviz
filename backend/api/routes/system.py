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
from datetime import datetime, timedelta, timezone

import json as _json

from fastapi import APIRouter, Depends, Request
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from core.database import get_db
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

# ── bd:shotockviz-d71 — /api/health cost ─────────────────────────────────────
# Measured on production 2026-09-06: 2.23 s. That is not slow work, it is a
# FIXED WAIT: `inspect.ping()` is a broadcast RPC with no idea how many replies
# to expect, so it sits out its whole `timeout=2.0` on every single call. Nothing
# about the probe can be made faster; what can change is whether a request has to
# stand next to it.
#
# The user rejected the WONTFIX, and the constraint that rejection implies is
# that a fast endpoint which no longer proves the workers are alive is WORSE than
# a slow one. So the probe is kept EXACTLY as it is — same broadcast, same 2 s
# timeout, same "ok"/"fail" meaning — and only its position moves: the result is
# published to Redis and served from there, refreshed off the request path.
#
# What the `celery` field means after this change, stated precisely because the
# meaning is the thing that must not silently move: "a Celery worker answered a
# broadcast ping at `celery_checked_at`", where that timestamp is at most
# _CELERY_PROBE_REFRESH_AFTER + one probe old, and never more than
# _CELERY_PROBE_TTL old (past that the cache is gone and the next caller pays the
# 2 s inline probe rather than being told something stale). Before this change it
# meant the same thing with the timestamp always equal to "now".
#
# Is a ≤ ~22 s lag acceptable for this contract? The consumer is the compose
# healthcheck (`docker-compose.dev.yml:69`, `.prod.yml:60`, `.ghcr.yml:73` —
# `curl -f`, interval 30 s, 3 retries), which already takes up to 90 s to act on
# a failure and which — note — never acted on `celery` at all: a celery "fail"
# does NOT set `degraded` below and never has, so the endpoint returns 200
# either way. The lag is well inside the noise of the only thing reading it.
#
# TTL > refresh-after on purpose: the gap is what lets a stale-but-live value be
# served while a refresh is in flight, instead of a thundering herd of 2 s pings.
_CELERY_PROBE_KEY = "health:celery:probe"
_CELERY_PROBE_TTL = 90               # seconds a probe result may still be served
_CELERY_PROBE_REFRESH_AFTER = 20     # seconds before a background re-probe fires

# Single-flight guard for the background refresh, and a strong reference to the
# task so the event loop's weak set cannot collect it mid-flight.
_celery_refresh_inflight = False
_celery_refresh_tasks: set = set()


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


async def _probe_and_store() -> tuple[str, str]:
    """Run the real 2 s broadcast probe and publish the result. Returns (status, iso)."""
    status_str = await asyncio.to_thread(_check_celery_health)
    checked_at = datetime.now(timezone.utc).isoformat()
    try:
        r = await get_redis()
        await r.setex(
            _CELERY_PROBE_KEY,
            _CELERY_PROBE_TTL,
            _json.dumps({"status": status_str, "checked_at": checked_at}),
        )
    except Exception:
        # No Redis -> no sharing between gunicorn workers, so every call probes
        # inline. Slow, correct, and exactly the pre-d71 behaviour.
        pass
    return status_str, checked_at


async def _refresh_celery_probe() -> None:
    """Background re-probe. One at a time per process (`_celery_refresh_inflight`)."""
    global _celery_refresh_inflight
    try:
        await _probe_and_store()
    except Exception:
        pass
    finally:
        _celery_refresh_inflight = False


def _schedule_celery_refresh() -> None:
    global _celery_refresh_inflight
    if _celery_refresh_inflight:
        return
    _celery_refresh_inflight = True
    try:
        task = asyncio.create_task(_refresh_celery_probe())
    except RuntimeError:  # no running loop — cannot happen inside a request
        _celery_refresh_inflight = False
        return
    _celery_refresh_tasks.add(task)
    task.add_done_callback(_celery_refresh_tasks.discard)


async def _celery_liveness() -> tuple[str, str]:
    """The `celery` field, off the request's critical path (bd:shotockviz-d71).

    Returns (status, checked_at_iso). Serves the last published probe result and
    kicks off a background re-probe once it is older than
    `_CELERY_PROBE_REFRESH_AFTER`. Falls back to probing INLINE — the full 2 s —
    when there is nothing published at all, which is the honest answer for a
    cold process: "no worker has been proven alive yet" must not be reported as
    "ok", and a 2 s first call is not a contract this endpoint has to keep.
    """
    try:
        r = await get_redis()
        raw = await r.get(_CELERY_PROBE_KEY)
    except Exception:
        raw = None

    if raw:
        try:
            payload = _json.loads(raw)
            status_str = payload["status"]
            checked_at = payload["checked_at"]
            age = datetime.now(timezone.utc) - datetime.fromisoformat(checked_at)
            if age > timedelta(seconds=_CELERY_PROBE_REFRESH_AFTER):
                _schedule_celery_refresh()
            return status_str, checked_at
        except Exception:
            pass  # corrupt entry — fall through and re-probe

    return await _probe_and_store()


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
            "celery":   "ok" | "fail",
            # bd:shotockviz-d71 — ADDITIVE field. When the celery probe last
            # actually ran; see the block above _check_celery_health for why the
            # probe no longer runs inside this request and what "ok" now means.
            # The 3 keys above are unchanged in name, values and semantics, and
            # the only consumer (compose `curl -f`) reads the status code alone.
            "celery_checked_at": "<ISO-8601>"
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
    # bd:shotockviz-d71 — was `aioredis.from_url(...)` + ping + aclose, i.e. a
    # brand-new TCP connection (and AUTH round-trip) on every healthcheck tick.
    # `/system/ready` below already carries this project's own ruling on that —
    # "Use the shared connection pool — never create a new connection per poll"
    # (system.py, cache_ready_check) — and the healthcheck polls harder than the
    # frontend does. A pooled `ping()` still proves the server is answering; if
    # it is not, redis-py raises here exactly as before.
    try:
        r = await get_redis()
        await r.ping()
        checks["redis"] = "ok"
    except Exception:
        checks["redis"] = "error"
        degraded = True

    # ── Celery ────────────────────────────────────────────────────────────────
    # bd:ops-01 kept the 2 s kombu/amqp `inspect().ping()` on the request path
    # and merely stopped it freezing the event loop (`asyncio.to_thread`) — the
    # RESPONSE was still ~2.2 s because the request still waited for it.
    # bd:shotockviz-d71 moves the wait off the request instead of weakening the
    # probe: same broadcast, same timeout, same meaning, served from the last
    # published result and refreshed in the background. See the block above
    # `_check_celery_health` for the meaning statement and the staleness budget.
    checks["celery"], checks["celery_checked_at"] = await _celery_liveness()

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
