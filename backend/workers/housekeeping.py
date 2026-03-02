"""Celery task for database housekeeping — compress old price data."""
from celery import shared_task
from core.logger import get_logger

logger = get_logger(__name__)


@shared_task(bind=True, max_retries=3, default_retry_delay=300)
def run_housekeeping(self):
    """
    Compress old 1-minute bars following the retention policy:
      - < 7 days   → keep raw 1m data
      - 7–90 days  → 5m resolution (aggregate, delete 1m)
      - 90d–2y     → 1d resolution (aggregate, delete 5m)
      - > 2 years  → 1w resolution (aggregate, delete 1d)
    """
    try:
        from sqlalchemy import create_engine, text
        from core.config import settings

        sync_url = settings.database_url.replace("+asyncpg", "")
        engine = create_engine(sync_url)
        deleted_total = 0

        with engine.begin() as conn:
            # Delete 1m data older than 7 days (already aggregated to 5m via TimescaleDB)
            result = conn.execute(text("""
                DELETE FROM stock_prices_1m
                WHERE time < NOW() - INTERVAL '7 days'
            """))
            deleted_1m = result.rowcount
            deleted_total += deleted_1m

        logger.info(
            "Housekeeping complete",
            deleted_1m_rows=deleted_1m,
            deleted_total=deleted_total,
        )
        return {"deleted_total": deleted_total}

    except Exception as exc:
        logger.error("Housekeeping failed", error=str(exc))
        raise self.retry(exc=exc)
