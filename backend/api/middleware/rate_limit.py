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
        # bd:deps-2026-09 iter1 — reuse core.redis's shared client (bound
        # fresh to the current event loop every lifespan) instead of a
        # second, independently-lifecycled one: a middleware-owned client
        # cached on the process-lifetime `app` singleton breaks across
        # per-test event loops ("Event loop is closed", CHRIS-02/Q-2).
        return await get_shared_redis()

    @staticmethod
    def _is_trusted_proxy(peer_ip: str) -> bool:
        """True if `peer_ip` (the actual TCP socket peer, not attacker-
        controllable) is in `settings.TRUSTED_PROXIES` (IPs or CIDRs;
        malformed entries fail safe — skipped, not fatal). CHRIS-03."""
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
    def _rightmost_untrusted_ip(xff: str) -> str | None:
        """Walk `X-Forwarded-For` from the right, skipping any hop that is
        itself a trusted proxy, and return the first untrusted entry —
        each proxy in a real chain APPENDS its observed peer, so the
        trustworthy value is the rightmost one NOT itself a trusted proxy
        (matches uvicorn's own `_TrustedHosts` algorithm; reimplemented
        here as defense-in-depth for paths that never hit that ASGI
        middleware, e.g. `TestClient`-based tests). CHRIS-16/Q-10 — was
        `xff.split(",")[0]` (leftmost = whatever the original caller
        claimed, trivially spoofable). Falls back to the leftmost entry if
        every hop is trusted (malformed/attacker chain, no client segment
        left), matching uvicorn's own documented edge-case behavior."""
        hops = [h.strip() for h in xff.split(",") if h.strip()]
        if not hops:
            return None
        for hop in reversed(hops):
            if not RateLimitMiddleware._is_trusted_proxy(hop):
                return hop
        return hops[0]

    @staticmethod
    def _client_ip(request: Request) -> str:
        """Real client IP behind Caddy (ADR-002, Sentinel S-AC-4).

        CHRIS-03: only trusts X-Forwarded-For when the request's socket
        peer is itself a configured trusted proxy (`settings.
        TRUSTED_PROXIES`, default empty = trust nothing = identity is the
        raw socket peer). Without this, anyone reaching the backend port
        directly (`docker-compose.dev.yml` exposes it alongside Caddy)
        could set any XFF and get a fresh rate-limit bucket per request
        (AB-2/AB-6 bypass).

        CHRIS-16/Q-10: `request.client.host` itself is NOT unconditionally
        the real unspoofable TCP peer — the ASGI server (uvicorn/gunicorn)
        can be configured to trust proxy headers UPSTREAM of this check
        (its own `forwarded_allow_ips`, see `gunicorn.conf.py`) and rewrite
        it first. That layer must be closed at the ASGI-server config, not
        here; this function stays correct given whatever peer the ASGI
        layer hands it, and now parses multi-hop XFF chains correctly
        (rightmost-untrusted-hop, not leftmost-claimed).
        """
        peer_ip = request.client.host if request.client else None
        if not peer_ip:
            return "unknown"
        xff = request.headers.get("x-forwarded-for")
        if not xff or not RateLimitMiddleware._is_trusted_proxy(peer_ip):
            return peer_ip
        return RateLimitMiddleware._rightmost_untrusted_ip(xff) or peer_ip

    async def dispatch(self, request: Request, call_next):
        # ADR-001 r3-2 / S-AC-3/AB-6 — the one unauthenticated auth endpoint.
        if request.url.path == "/api/v1/auth/google" and request.method == "POST":
            client_ip = self._client_ip(request)
            redis = await self.get_redis()
            key = f"rate:login:{client_ip}"

            count = await redis.incr(key)
            if count == 1:
                await redis.expire(key, self.LOGIN_WINDOW)

            if count > self.LOGIN_LIMIT:
                # CHRIS-02/Q-2 — was `raise HTTPException(429, ...)`, but this
                # BaseHTTPMiddleware sits outside ExceptionMiddleware in the
                # ASGI stack, so a raised HTTPException skips
                # install_error_envelope's handlers and hits
                # ServerErrorMiddleware -> raw non-JSON 500 (verified live).
                # Build the same enveloped body directly instead.
                ttl = await redis.ttl(key)
                return JSONResponse(
                    content=enveloped_error_body(
                        request, f"Too many login attempts. Try again in {ttl} seconds."
                    ),
                    status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                )

        return await call_next(request)
