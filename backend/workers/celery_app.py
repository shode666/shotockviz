"""Celery application configuration with scheduled tasks."""
from celery import Celery
from celery.schedules import crontab
from core.config import settings

# Import signal handlers
import workers  # noqa: F401 — registers task_success/failure handlers

celery_app = Celery(
    "stockviz",
    broker=settings.redis_url,
    backend=settings.redis_url,
    include=[
        "workers.price_fetcher",
        "workers.alert_checker",
        "workers.housekeeping",
        "workers.name_fetcher",
        "workers.fundamentals_fetcher",
        "workers.fund_fetcher",
        "workers.history_prefetcher",
        "workers.on_demand_listener",
        "workers.symbol_registrar",
        "workers.index_populator",
    ],
)

celery_app.conf.update(
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    timezone=settings.tz,
    enable_utc=True,
    task_track_started=True,
    task_acks_late=True,
    worker_prefetch_multiplier=1,
    # Retry policy
    task_max_retries=3,
    task_default_retry_delay=60,
)

# ─── Scheduled Tasks (Celery Beat) ──────────────────────────────────────────

celery_app.conf.beat_schedule = {
    # ── Unified round-robin price fetcher ──────────────────────────────────
    # Runs every 1 min.  Rotates through 5 market slots:
    #   SET → US → Asia(JP/HK/CN) → Europe(UK/DE/FR/NL) → Overview
    # Each market updates every ~5 min.  Closed markets are auto-skipped
    # so open markets get more frequent updates.
    "fetch-prices": {
        "task": "workers.price_fetcher.fetch_prices",
        "schedule": 60.0,  # every 1 minute, round-robin
    },
    # Backup overview (indices, USD/THB, Gold) every 5 min
    # In case round-robin skips overview during busy rotation
    "fetch-overview-prices": {
        "task": "workers.price_fetcher.fetch_overview_prices",
        "schedule": 300.0,  # every 5 minutes
    },
    # Check alerts every minute
    "check-alerts": {
        "task": "workers.alert_checker.check_all_alerts",
        "schedule": 60.0,  # every 60 seconds
    },
    # DB housekeeping at 03:00 ICT (= 20:00 UTC prev day)
    "db-housekeeping": {
        "task": "workers.housekeeping.run_housekeeping",
        "schedule": crontab(hour=20, minute=0),
    },
    # Prefetch company names every 6 hours
    "prefetch-names": {
        "task": "workers.name_fetcher.prefetch_names",
        "schedule": crontab(minute=30, hour="*/6"),
    },
    # Prefetch fundamentals every 4 hours
    "prefetch-fundamentals": {
        "task": "workers.fundamentals_fetcher.prefetch_fundamentals",
        "schedule": crontab(minute=15, hour="*/4"),
    },
    # Fetch Thai mutual fund NAVs at 12:00 UTC (19:00 ICT)
    "fetch-fund-navs": {
        "task": "workers.fund_fetcher.fetch_thai_fund_navs",
        "schedule": crontab(hour=12, minute=0),
    },
    # Prefetch history every 30 minutes
    "prefetch-history": {
        "task": "workers.history_prefetcher.prefetch_history",
        "schedule": crontab(minute="*/30"),
    },
    # Scan for unregistered symbols every 15 minutes
    "scan-unregistered-symbols": {
        "task": "workers.symbol_registrar.scan_unregistered",
        "schedule": crontab(minute="*/15"),
    },
    # Refresh index constituents weekly (Sunday 00:00 UTC)
    "populate-index-constituents": {
        "task": "workers.index_populator.populate_index_constituents",
        "schedule": crontab(hour=0, minute=0, day_of_week=0),
    },
}
