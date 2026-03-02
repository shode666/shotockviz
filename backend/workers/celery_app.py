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
    # Fetch prices every minute during market hours
    "fetch-set-prices": {
        "task": "workers.price_fetcher.fetch_set_prices",
        "schedule": crontab(
            minute="*/1",
            hour="2-9",        # 09:30-16:30 ICT = 02:30-09:30 UTC
            day_of_week="1-5", # Mon-Fri
        ),
    },
    "fetch-us-prices": {
        "task": "workers.price_fetcher.fetch_us_prices",
        "schedule": crontab(
            minute="*/1",
            hour="14-21",       # 09:30-16:00 ET = 14:30-21:00 UTC
            day_of_week="1-5",
        ),
    },
    # Always-on overview prices (indices, USD/THB, Gold) every 2 min
    "fetch-overview-prices": {
        "task": "workers.price_fetcher.fetch_overview_prices",
        "schedule": 120.0,  # every 2 minutes, no market-hours restriction
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
}
