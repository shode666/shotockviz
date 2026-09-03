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

    async def dispatch(self, request: Request, call_next):
        # bd:deps-2026-09 S1 (ADR-007 + Sentinel S-AC-3/AB-6) — /api/auth/login
        # was removed; re-point brute-force protection to the one remaining
        # unauthenticated auth endpoint. S2 lifts this to /api/v1/auth/google.
        if request.url.path == "/api/auth/google" and request.method == "POST":
            client_ip = request.client.host if request.client else "unknown"
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
