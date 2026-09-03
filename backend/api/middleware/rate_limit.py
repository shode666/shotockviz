import time
from fastapi import Request, HTTPException, status
from starlette.middleware.base import BaseHTTPMiddleware
import redis.asyncio as aioredis
from core.config import settings


class RateLimitMiddleware(BaseHTTPMiddleware):
    """
    Per-IP rate limiting using Redis sliding window.
    Limits: guest=30/min, user=120/min (enforced at route level via dependency).
    This middleware handles login endpoint brute-force protection.
    """

    LOGIN_LIMIT = 5
    LOGIN_WINDOW = 15 * 60  # 15 minutes

    def __init__(self, app, redis_url: str):
        super().__init__(app)
        self.redis_url = redis_url
        self._redis: aioredis.Redis | None = None

    async def get_redis(self) -> aioredis.Redis:
        if self._redis is None:
            self._redis = await aioredis.from_url(self.redis_url, decode_responses=True)
        return self._redis

    @staticmethod
    def _client_ip(request: Request) -> str:
        """Real client IP behind Caddy (bd:deps-2026-09 S2, Sentinel S-AC-4).

        Caddy (`caddy/Caddyfile:47`) is the ONLY reverse proxy in front of
        this service (single hop, Docker network) and always sets
        X-Forwarded-For — trust its first value. Without this, gunicorn/
        uvicorn see every request as coming from the Caddy container's IP
        (single global bucket — SEC-2/AB-2: one attacker locks out every
        user). Falls back to the raw ASGI peer when no header is present
        (e.g. direct connection in dev, no Caddy in front).
        """
        xff = request.headers.get("x-forwarded-for")
        if xff:
            return xff.split(",")[0].strip()
        return request.client.host if request.client else "unknown"

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
                ttl = await redis.ttl(key)
                raise HTTPException(
                    status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                    detail=f"Too many login attempts. Try again in {ttl} seconds.",
                )

        return await call_next(request)
