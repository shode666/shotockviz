"""Celery task for database housekeeping — compress old price data.

Reads retention policy from Redis config (set via Admin API).
Falls back to defaults if no policy is configured.
"""
import json
from celery import shared_task
from core.logger import get_logger

logger = get_logger(__name__)

RETENTION_CONFIG_KEY = "config:retention_policy"

# Default retention policy (if not configured via Admin API)
DEFAULT_POLICY = [
    {"resolution": "1m", "max_age_days": 7},
    {"resolution": "5m", "max_age_days": 90},
    {"resolution": "1d", "max_age_days": 730},
]


@shared_task(bind=True, max_retries=3, default_retry_delay=300)
def run_housekeeping(self):
    """
    Compress old price data following the retention policy.

    Reads policy from Redis (set by PUT /api/admin/retention-policy).
    Default:
      - 1m data: keep 7 days
      - 5m data: keep 90 days
      - 1d data: keep 730 days (2 years)
    """
    try:
        import redis as redis_lib
        from sqlalchemy import create_engine, text
        from core.config import settings

        redis_client = redis_lib.from_url(settings.redis_url, decode_responses=True)
        engine = create_engine(settings.sync_database_url, pool_pre_ping=True)

        # Read policy from Redis (or use defaults)
        raw_policy = redis_client.get(RETENTION_CONFIG_KEY)
        if raw_policy:
            try:
                policy = json.loads(raw_policy)
            except json.JSONDecodeError:
                policy = DEFAULT_POLICY
        else:
            policy = DEFAULT_POLICY

        deleted_total = 0

        with engine.begin() as conn:
            for rule in policy:
                resolution = rule.get("resolution", "")
                max_age_days = rule.get("max_age_days", 7)

                if resolution == "1m":
                    result = conn.execute(text("""
                        DELETE FROM stock_prices_1m
                        WHERE time < NOW() - INTERVAL :days
                    """), {"days": f"{max_age_days} days"})
                    deleted = result.rowcount
                    deleted_total += deleted
                    logger.info("Housekeeping 1m", deleted=deleted, max_age_days=max_age_days)

                elif resolution == "5m":
                    # Delete 5m OHLCV bars older than configured days
                    result = conn.execute(text("""
                        DELETE FROM ohlcv_bars
                        WHERE timeframe = '5m'
                        AND time < NOW() - INTERVAL :days
                    """), {"days": f"{max_age_days} days"})
                    deleted = result.rowcount
                    deleted_total += deleted
                    logger.info("Housekeeping 5m", deleted=deleted, max_age_days=max_age_days)

                elif resolution == "1d":
                    # Delete daily OHLCV bars older than configured days
                    result = conn.execute(text("""
                        DELETE FROM ohlcv_bars
                        WHERE timeframe = '1D'
                        AND time < NOW() - INTERVAL :days
                    """), {"days": f"{max_age_days} days"})
                    deleted = result.rowcount
                    deleted_total += deleted
                    logger.info("Housekeeping 1d", deleted=deleted, max_age_days=max_age_days)

            # Also clean up old document embeddings (> 90 days)
            try:
                result = conn.execute(text("""
                    DELETE FROM document_embeddings
                    WHERE created_at < NOW() - INTERVAL '90 days'
                """))
                embed_deleted = result.rowcount
                deleted_total += embed_deleted
                if embed_deleted > 0:
                    logger.info("Housekeeping embeddings", deleted=embed_deleted)
            except Exception:
                pass  # Table may not exist yet

        logger.info("Housekeeping complete", deleted_total=deleted_total)
        return {"deleted_total": deleted_total}

    except Exception as exc:
        logger.error("Housekeeping failed", error=str(exc))
        raise self.retry(exc=exc)
