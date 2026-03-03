from pydantic_settings import BaseSettings
from functools import lru_cache


class Settings(BaseSettings):
    # App
    app_env: str = "development"
    debug: bool = True
    workers: int = 4

    # Database
    database_url: str = "postgresql+asyncpg://stockviz:password@db:5432/stockviz_db"

    # Redis
    redis_url: str = "redis://redis:6379/0"

    # JWT
    jwt_secret_key: str = "dev-secret-key-change-in-prod"
    jwt_algorithm: str = "HS256"
    access_token_expire_minutes: int = 480   # 8 hours — avoids constant re-logins in dev
    refresh_token_expire_days: int = 30      # 30 days — stays logged in across restarts

    # APIs
    finnhub_api_key: str = ""
    telegram_bot_token: str = ""

    # SEC Open Data API (Thai mutual fund NAV)
    # Register free at https://api-portal.sec.or.th
    sec_fund_factsheet_key: str = ""   # Subscribe to "Fund Factsheet" API
    sec_fund_daily_info_key: str = ""  # Subscribe to "Fund Daily Info" API

    # CORS
    cors_origins: str = "http://localhost:5173"

    # Timezone
    tz: str = "Asia/Bangkok"

    # Optional AI
    ollama_url: str = ""

    # Google OAuth
    google_client_id: str = ""

    @property
    def cors_origins_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",")]

    @property
    def is_production(self) -> bool:
        return self.app_env == "production"

    @property
    def sync_database_url(self) -> str:
        """PostgreSQL URL for sync operations (Alembic)."""
        return self.database_url.replace("+asyncpg", "")

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
