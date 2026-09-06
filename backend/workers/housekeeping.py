"""Celery task for database housekeeping — compress old price data.

Reads retention policy from Redis config (set via Admin API).
Falls back to defaults if no policy is configured.
"""
import json
import time
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

    Reads policy from Redis (set by PUT /api/v1/admin/retention-policy).
    Default:
      - 1m data: keep 7 days
      - 5m data: keep 90 days
      - 1d data: keep 730 days (2 years)

    bd:shotockviz-s3k — two defects fixed here:
      1. `ohlcv_bars` has no `time` column (models/ohlcv.py) — its PK is
         `time_unix`, a BigInteger of unix seconds, not a timestamp, so
         `time_unix < NOW() - INTERVAL` is a type error (BigInteger vs
         timestamptz). The cutoff is computed as a unix-seconds integer
         in Python instead and compared directly.
      2. Every rule used to run inside one `engine.begin()` transaction,
         so the 5m/1d rules raising rolled back the 1m rule too — nothing
         was ever actually deleted, including rules that would have
         succeeded. Each rule now gets its own connection/transaction;
         one rule failing is logged and skipped, the rest still commit.
    """
    from sqlalchemy import text

    try:
        import redis as redis_lib
        from sqlalchemy import create_engine
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
    except Exception as setup_exc:
        # Infra-level failure (Redis/DB unreachable) — this genuinely
        # deserves a task retry, unlike a single rule's DELETE failing.
        logger.error("Housekeeping setup failed", error=str(setup_exc))
        raise self.retry(exc=setup_exc)

    deleted_total = 0
    rule_errors = []

    for rule in policy:
        resolution = rule.get("resolution", "")
        max_age_days = rule.get("max_age_days", 7)

        try:
            with engine.begin() as conn:
                if resolution == "1m":
                    # stock_prices_1m.time IS a real timestamptz column.
                    result = conn.execute(text("""
                        DELETE FROM stock_prices_1m
                        WHERE time < NOW() - INTERVAL :days
                    """), {"days": f"{max_age_days} days"})
                    deleted = result.rowcount

                elif resolution == "5m":
                    cutoff_unix = int(time.time()) - (max_age_days * 86400)
                    result = conn.execute(text("""
                        DELETE FROM ohlcv_bars
                        WHERE timeframe = '5m'
                        AND time_unix < :cutoff
                    """), {"cutoff": cutoff_unix})
                    deleted = result.rowcount

                elif resolution == "1d":
                    cutoff_unix = int(time.time()) - (max_age_days * 86400)
                    result = conn.execute(text("""
                        DELETE FROM ohlcv_bars
                        WHERE timeframe = '1D'
                        AND time_unix < :cutoff
                    """), {"cutoff": cutoff_unix})
                    deleted = result.rowcount

                else:
                    logger.warning("Housekeeping: unknown resolution, skipped", resolution=resolution)
                    continue

            deleted_total += deleted
            logger.info("Housekeeping rule complete", resolution=resolution, deleted=deleted, max_age_days=max_age_days)

        except Exception as rule_exc:
            # One rule's failure must not roll back or block the others —
            # log it, record it, move on to the next rule.
            rule_errors.append({"resolution": resolution, "error": str(rule_exc)})
            logger.error("Housekeeping rule failed", resolution=resolution, error=str(rule_exc))
            continue

    logger.info("Housekeeping complete", deleted_total=deleted_total, rule_errors=rule_errors)

    if rule_errors:
        return {"deleted_total": deleted_total, "rule_errors": rule_errors}
    return {"deleted_total": deleted_total}
