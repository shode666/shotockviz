from pydantic_settings import BaseSettings, SettingsConfigDict
from pydantic import field_validator
from functools import lru_cache

# bd:deps-2026-09 iter1 (CHRIS-09) — module-level, not a class attribute:
# pydantic v2 turns any leading-underscore class attribute on a
# BaseModel/BaseSettings subclass into a `ModelPrivateAttr` DESCRIPTOR
# placeholder (not the plain value) unless explicitly declared via
# `PrivateAttr()` — `cls._X` inside a `@field_validator` would raise
# `TypeError: argument of type 'ModelPrivateAttr' is not iterable`.
_KNOWN_PLACEHOLDER_SECRETS = frozenset({
    "dev-secret-key-change-in-prod",
    "change-me-with-openssl-rand-hex-32",
})


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8")

    # App
    app_env: str = "development"
    debug: bool = True
    workers: int = 4

    # Database
    database_url: str = "postgresql+asyncpg://stockviz:password@db:5432/stockviz_db"

    @field_validator("database_url")
    @classmethod
    def _check_async_driver(cls, v: str) -> str:
        # bd:deps-2026-09 fix — core/database.py's engine is async-only;
        # fail loudly at config load, not deep inside SQLAlchemy's asyncio extension.
        if "+asyncpg" not in v:
            raise ValueError(f"DATABASE_URL must use 'postgresql+asyncpg://' (found: {v!r}).")
        return v

    # Redis
    redis_url: str = "redis://redis:6379/0"

    # JWT
    jwt_secret_key: str = "dev-secret-key-change-in-prod"
    jwt_algorithm: str = "HS256"
    access_token_expire_minutes: int = 480   # 8 hours — avoids constant re-logins in dev
    refresh_token_expire_days: int = 30      # 30 days — stays logged in across restarts

    @field_validator("jwt_secret_key")
    @classmethod
    def _check_jwt_secret(cls, v: str) -> str:
        import os
        import warnings
        # bd:deps-2026-09 iter1 (CHRIS-09) — was a single hardcoded string
        # compared with `==`; `.env.example:17`'s OWN placeholder
        # (`change-me-with-openssl-rand-hex-32`) is equally public and
        # equally "default-looking" but wasn't in the set, so someone who
        # copies .env.example verbatim into a prod .env without rotating
        # it booted cleanly with a known-guessable secret — exactly the
        # SEC-4 scenario this check exists to close, only half-closed.
        # Both known placeholders now reject identically; kept as an
        # explicit set (not a generic entropy heuristic) so the failure
        # message can name exactly which placeholder was found, and to
        # avoid false-positive-rejecting a real secret that happens to
        # look low-entropy.
        if v in _KNOWN_PLACEHOLDER_SECRETS:
            # bd:deps-2026-09 WP-B2 (S-AC-10, 05-sentinel-threat-model.md
            # SEC-4/§3): boot must FAIL if the default secret reaches
            # production, not just warn — a warning is silently swallowed
            # in prod logs. `app_env` isn't parsed yet at validator time
            # (field order/pydantic validates independently), so read the
            # raw env var directly rather than depend on another field.
            if os.environ.get("APP_ENV", "development") == "production":
                raise ValueError(
                    f"JWT_SECRET_KEY is still the default dev value in a "
                    f"production environment (found: {v!r}, APP_ENV=production) "
                    "— set a strong, unique JWT_SECRET_KEY in .env before boot."
                )
            warnings.warn(
                f"JWT_SECRET_KEY is still the default dev value "
                f"(found: {v!r})! Set a strong, unique JWT_SECRET_KEY in "
                ".env for production.",
                stacklevel=2,
            )
        if len(v) < 16:
            raise ValueError("JWT_SECRET_KEY must be at least 16 characters")
        return v

    # APIs
    finnhub_api_key: str = ""
    telegram_bot_token: str = ""

    # SEC Open Data API (Thai mutual fund NAV)
    # Register free at https://api-portal.sec.or.th
    sec_fund_factsheet_key: str = ""   # Subscribe to "Fund Factsheet" API
    sec_fund_daily_info_key: str = ""  # Subscribe to "Fund Daily Info" API

    # CORS
    cors_origins: str = "http://localhost:5173"

    # bd:deps-2026-09 iter1 (CHRIS-03) — comma-separated list of IPs and/or
    # CIDR blocks for reverse-proxy hops whose X-Forwarded-For header is
    # safe to trust. Empty (default) = trust NOTHING; every request's rate
    # -limit/client-IP identity falls back to the raw ASGI socket peer
    # (request.client.host), which a remote caller cannot spoof — safest
    # possible default. See .env.example for how to size this for the
    # Caddy-fronted deployment topology (api/middleware/rate_limit.py's
    # _is_trusted_proxy()).
    trusted_proxies: str = ""

    # Timezone
    tz: str = "Asia/Bangkok"

    # Google OAuth
    google_client_id: str = ""

    @property
    def cors_origins_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",")]

    @property
    def trusted_proxies_list(self) -> list[str]:
        return [p.strip() for p in self.trusted_proxies.split(",") if p.strip()]

    @property
    def is_production(self) -> bool:
        return self.app_env == "production"

    @property
    def sync_database_url(self) -> str:
        """PostgreSQL URL for sync operations (Alembic)."""
        return self.database_url.replace("+asyncpg", "")


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
