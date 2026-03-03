"""Yahoo Finance authentication — cookie + crumb management.

Handles session management for Yahoo Finance API access.
"""
import asyncio
import time as _time
from typing import Optional

import httpx

from core.logger import get_logger

logger = get_logger(__name__)

# ── Yahoo Finance HTTP headers ────────────────────────────────────────────────
_YF_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
    ),
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "en-US,en;q=0.9",
    "Accept-Encoding": "gzip, deflate, br",
    "Referer": "https://finance.yahoo.com/",
    "Origin": "https://finance.yahoo.com",
}

# ── Yahoo Finance session management (cookie + crumb) ─────────────────────────
# The v8 chart API requires: (1) session cookies from finance.yahoo.com homepage
# and (2) a crumb token from the /v1/test/getcrumb endpoint.

_yf_crumb: str = ""
_yf_crumb_cookies: dict = {}
_yf_crumb_ts: float = 0.0
_YF_CRUMB_TTL = 1800.0   # Refresh crumb every 30 min

# NOTE: asyncio primitives MUST be created inside a running event loop.
# We use lazy getters that create them on first async access.
_yf_crumb_lock: asyncio.Lock | None = None
_yf_http_sem: asyncio.Semaphore | None = None


def _get_crumb_lock() -> asyncio.Lock:
    """Lazily create the crumb lock inside the running event loop."""
    global _yf_crumb_lock
    if _yf_crumb_lock is None:
        _yf_crumb_lock = asyncio.Lock()
    return _yf_crumb_lock


def _get_http_sem() -> asyncio.Semaphore:
    """Lazily create the HTTP semaphore inside the running event loop.

    8 permits — sidebar makes 12 concurrent quote requests; Semaphore(3)
    queued 9 of them, starving the event loop. 8 balances rate-limit avoidance
    with concurrency.
    """
    global _yf_http_sem
    if _yf_http_sem is None:
        _yf_http_sem = asyncio.Semaphore(8)
    return _yf_http_sem


# Alternative crumb endpoints (tried in order if query2 fails)
_YF_CRUMB_URLS = [
    "https://query2.finance.yahoo.com/v1/test/getcrumb",
    "https://query1.finance.yahoo.com/v1/test/getcrumb",
]


async def _get_yf_auth() -> tuple[dict, str]:
    """Return (cookies, crumb) for Yahoo Finance API auth.

    Cached in memory for 30 minutes. Uses a lock to prevent thundering herd
    on cache miss. Tries two crumb endpoints for resilience.
    On failure returns whatever was last cached so callers fall back gracefully.

    Returns:
        (cookies_dict, crumb_string) tuple. On failure, returns stale cache.
    """
    global _yf_crumb, _yf_crumb_cookies, _yf_crumb_ts

    now = _time.monotonic()
    if _yf_crumb and (now - _yf_crumb_ts) < _YF_CRUMB_TTL:
        return _yf_crumb_cookies, _yf_crumb

    async with _get_crumb_lock():
        # Re-check under lock (another coroutine may have refreshed while we waited)
        now = _time.monotonic()
        if _yf_crumb and (now - _yf_crumb_ts) < _YF_CRUMB_TTL:
            return _yf_crumb_cookies, _yf_crumb

        # 2 attempts max, 5 s timeout per request — fail fast when rate-limited.
        for attempt in range(2):
            try:
                async with httpx.AsyncClient(
                    headers=_YF_HEADERS, timeout=httpx.Timeout(4.0, connect=3.0), follow_redirects=True
                ) as client:
                    if attempt > 0:
                        await asyncio.sleep(0.5)  # minimal back-off

                    # Step 1: get session cookies from Yahoo Finance homepage
                    r1 = await client.get("https://finance.yahoo.com/")
                    cookies = dict(r1.cookies)

                    # Step 2: try each crumb endpoint
                    crumb = ""
                    for crumb_url in _YF_CRUMB_URLS:
                        try:
                            r2 = await client.get(
                                crumb_url,
                                cookies=cookies,
                                headers={**_YF_HEADERS, "Accept": "*/*"},
                            )
                            candidate = r2.text.strip() if r2.status_code == 200 else ""
                            if candidate and "Too Many" not in candidate and 3 < len(candidate) < 20:
                                crumb = candidate
                                break
                        except Exception:
                            continue

                    if crumb:
                        _yf_crumb = crumb
                        _yf_crumb_cookies = cookies
                        _yf_crumb_ts = _time.monotonic()
                        logger.info("Yahoo Finance crumb refreshed", attempt=attempt + 1)
                        return _yf_crumb_cookies, _yf_crumb
            except Exception as e:
                logger.warning("Failed to get Yahoo Finance crumb", attempt=attempt + 1, error=str(e))

    # All attempts failed — return stale cache (better than nothing)
    return _yf_crumb_cookies, _yf_crumb
