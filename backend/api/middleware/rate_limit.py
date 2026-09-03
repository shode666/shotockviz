import ipaddress
import time
from fastapi import Request, status
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import JSONResponse
from core.config import settings
from core.redis import get_redis as get_shared_redis
from schemas.envelope import enveloped_error_body


class RateLimitMiddleware(BaseHTTPMiddleware):
    """
    Per-IP rate limiting using Redis sliding window.
    Limits: guest=30/min, user=120/min (not yet enforced — only the login
    endpoint below is actually rate-limited today; see CHRIS-11).
    This middleware handles login endpoint brute-force protection.
    """

    LOGIN_LIMIT = 5
    LOGIN_WINDOW = 15 * 60  # 15 minutes

    def __init__(self, app):
        super().__init__(app)

    async def get_redis(self):
        # bd:deps-2026-09 iter1 (Dave-discovered, not in Chris's/Quinn's
        # original reports) — was its own lazily-created, permanently-
        # cached `aioredis.from_url(...)` client on `self`, independent of
        # `main.py`'s lifespan. `BaseHTTPMiddleware` instances are built
        # once by Starlette's `build_middleware_stack()` and cached on the
        # `app` singleton for the life of the PROCESS; a redis-py asyncio
        # client's pooled connections bind to whichever event loop first
        # opened them. In production there's exactly one event loop for
        # the process's lifetime, so this was invisible — but every
        # `TestClient(app)` __enter__ spins up its own event loop, so a
        # 2nd+ test that hit the login rate-limit path reused a connection
        # from an already-closed loop ("RuntimeError: Event loop is
        # closed", surfaced fixing CHRIS-02/Q-2 above — this middleware's
        # dispatch() previously never returned far enough to reach a
        # second real redis call in the same test session, masking it).
        # `core.redis.get_redis()` is the ALREADY-correct pattern
        # (`init_redis()`/`close_redis()` cycle every lifespan, so tests
        # get a fresh client bound to the current loop every time) — reuse
        # it instead of a second, differently-lifecycled connection.
        return await get_shared_redis()

    @staticmethod
    def _is_trusted_proxy(peer_ip: str) -> bool:
        """True if `peer_ip` (the ACTUAL TCP socket peer — not attacker-
        controllable) is in `settings.TRUSTED_PROXIES`.

        bd:deps-2026-09 iter1 (CHRIS-03). Entries may be single IPs or
        CIDR blocks (e.g. a Docker bridge network subnet). Malformed
        entries are skipped, not fatal — a typo in one entry shouldn't
        take down the whole allowlist (fails safe: that entry just never
        matches, defaulting toward "don't trust").
        """
        try:
            peer = ipaddress.ip_address(peer_ip)
        except ValueError:
            return False
        for entry in settings.trusted_proxies_list:
            try:
                if "/" in entry:
                    if peer in ipaddress.ip_network(entry, strict=False):
                        return True
                elif peer == ipaddress.ip_address(entry):
                    return True
            except ValueError:
                continue
        return False

    @staticmethod
    def _client_ip(request: Request) -> str:
        """Real client IP behind Caddy (bd:deps-2026-09 S2, Sentinel S-AC-4).

        bd:deps-2026-09 iter1 (CHRIS-03) — was: trust the FIRST
        X-Forwarded-For value unconditionally, with no check that the
        request actually arrived via Caddy. `docker-compose.dev.yml`
        exposes the backend directly on the host (`8000:8000`) alongside
        Caddy; any caller that reaches that port directly can set
        `X-Forwarded-For: <anything>` and get a fresh rate-limit bucket on
        every request (AB-2/AB-6 bypass — confirmed live via curl, Chris's
        review CHRIS-03). Now only trusts X-Forwarded-For when the
        request's ACTUAL socket peer (`request.client.host` — NOT
        attacker-controllable; you can't fake who opened the TCP
        connection) is itself a configured trusted proxy
        (`settings.TRUSTED_PROXIES`, default empty = trust nothing = every
        request's identity is its raw socket peer, safe by default). See
        .env.example for sizing this for the Caddy-fronted topology.
        """
        peer_ip = request.client.host if request.client else None
        xff = request.headers.get("x-forwarded-for")
        if xff and peer_ip and RateLimitMiddleware._is_trusted_proxy(peer_ip):
            return xff.split(",")[0].strip()
        return peer_ip or "unknown"

    async def dispatch(self, request: Request, call_next):
        # bd:deps-2026-09 S2 (ADR-001 r3-2, Sentinel S-AC-3/AB-6) — path
        # literal lifted to /api/v1 alongside the prefix flip; S1 already
        # re-pointed protection from the removed /api/auth/login to the one
        # remaining unauthenticated auth endpoint.
        if request.url.path == "/api/v1/auth/google" and request.method == "POST":
            client_ip = self._client_ip(request)
            redis = await self.get_redis()
            key = f"rate:login:{client_ip}"

            count = await redis.incr(key)
            if count == 1:
                await redis.expire(key, self.LOGIN_WINDOW)

            if count > self.LOGIN_LIMIT:
                # bd:deps-2026-09 iter1 (CHRIS-02/Q-2) — was
                # `raise HTTPException(429, ...)`. This middleware is a
                # `BaseHTTPMiddleware`, which sits OUTSIDE Starlette's
                # `ExceptionMiddleware` in the ASGI stack (added via
                # `app.add_middleware`, not route-scoped `Depends()`); an
                # HTTPException raised here propagates straight past both
                # `install_error_envelope`'s handlers AND FastAPI's own
                # defaults to `ServerErrorMiddleware`, which returns a raw
                # non-JSON 500 — verified live via curl (14-chris-review.md
                # CHRIS-02, independently reproduced by Quinn against the
                # 73fac00 baseline app too — pre-existing, architecturally,
                # not a Starlette 0.52->1.6 version-bump artifact). Return
                # the same enveloped error body `install_error_envelope`
                # produces for router-level errors directly, instead of
                # raising — reuses `enveloped_error_body` so both code
                # paths stay in sync (single source of truth for the
                # {data:null, meta:{error:{message}}} shape, S-AC-5-safe:
                # no exception class/traceback/SQL fragment).
                ttl = await redis.ttl(key)
                return JSONResponse(
                    content=enveloped_error_body(
                        request, f"Too many login attempts. Try again in {ttl} seconds."
                    ),
                    status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                )

        return await call_next(request)
