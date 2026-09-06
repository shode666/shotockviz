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
        "workers.alert_symbol_refresher",
        "workers.housekeeping",
        "workers.name_fetcher",
        "workers.fundamentals_fetcher",
        "workers.fund_fetcher",
        "workers.history_prefetcher",
        "workers.on_demand_listener",
        "workers.symbol_registrar",
        "workers.index_populator",
        "workers.news_fetcher",
        "workers.sr_auto_pivot",
        "workers.sr_proximity_digest",
        # V2 workers
        "workers.corporate_actions_fetcher",
        "workers.financials_history_fetcher",
        "workers.earnings_events_fetcher",
        "workers.fgi_fetcher",
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

# ─── Logging hygiene in worker processes ────────────────────────────────────
#
# bd:shotockviz-pdb — `core.logger.setup_logging()` was only ever called by
# `main.py`, i.e. the FastAPI process. Celery workers and beat never called
# it, so httpx logged every request URL at INFO — and the Telegram bot token
# is a PATH SEGMENT of that URL, so the token was printed in plaintext to
# `docker logs` on every alert and every digest send.
#
# `after_setup_logger` / `after_setup_task_logger` fire AFTER Celery has
# installed its own handlers, which is the only point where attaching a
# handler-level filter actually covers what the worker emits. Celery's
# `setup_logging` signal is deliberately NOT used: connecting to it disables
# Celery's logging configuration wholesale, which is a much larger change
# than this bug calls for.
from celery.signals import after_setup_logger, after_setup_task_logger  # noqa: E402
from core.logger import install_secret_redaction  # noqa: E402


@after_setup_logger.connect
@after_setup_task_logger.connect
def _harden_worker_logging(logger=None, **kwargs):
    import logging as _logging

    for noisy in ("httpx", "httpcore", "httpcore.http11", "httpcore.connection",
                  "redis.connection", "redis.asyncio.connection"):
        _logging.getLogger(noisy).setLevel(_logging.WARNING)
    install_secret_redaction()


# ─── Scheduled Tasks (Celery Beat) ──────────────────────────────────────────
#
# ⚠️ bd:shotockviz-rwq — EVERY `crontab()` BELOW IS IN ICT (Asia/Bangkok),
# NOT UTC. `conf.timezone` is set to `settings.tz` = "Asia/Bangkok" above,
# and Celery evaluates crontab schedules against `conf.timezone`;
# `enable_utc=True` only controls the timezone stamped into message
# headers, it does NOT make crontab UTC. Until 2026-09-06 every entry here
# was written as if it were UTC (with a `# = HH:MM ICT` comment doing the
# conversion), so all 8 of them fired 7 hours early — the S/R digest
# reached the user at 02:30 and 12:30 ICT instead of 09:30 and 19:30, and
# `db-housekeeping` was deleting rows at 20:00 ICT (US pre-market) rather
# than 03:00. Write the ICT wall-clock time you actually want; do not
# convert.

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
    # bd:shotockviz-cm3(b) — refresh quotes for symbols with an ACTIVE
    # PRICE_ABOVE/PRICE_BELOW alert every 60s (independent of the 6-slot
    # round-robin above), so alert_checker never compares against a quote
    # older than ~1 min for those specific symbols. Market-hours gated
    # per symbol inside the task, so this adds yfinance calls only for
    # alert-bearing symbols whose market is open right now — worst case
    # (every watched symbol has an alert, one market open) this raises
    # that subset's fetch cadence from ~once per 4-6 min to once per
    # minute; zero extra calls for symbols with no alert, zero calls when
    # no alert symbol's market is open.
    "refresh-alert-symbols": {
        "task": "workers.alert_symbol_refresher.refresh_alert_symbols",
        "schedule": 60.0,
    },
    # DB housekeeping at 03:00 ICT
    "db-housekeeping": {
        "task": "workers.housekeeping.run_housekeeping",
        "schedule": crontab(hour=3, minute=0),
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
    # Fetch Thai mutual fund NAVs at 19:00 ICT (SEC publishes T+1)
    "fetch-fund-navs": {
        "task": "workers.fund_fetcher.fetch_thai_fund_navs",
        "schedule": crontab(hour=19, minute=0),
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
    # Prefetch news for watched symbols every 30 minutes
    "prefetch-news": {
        "task": "workers.news_fetcher.prefetch_news",
        "schedule": crontab(minute="*/30"),
    },
    # Refresh index constituents weekly (Sunday 00:00 ICT)
    "populate-index-constituents": {
        "task": "workers.index_populator.populate_index_constituents",
        "schedule": crontab(hour=0, minute=0, day_of_week=0),
    },
    # ── V2 Workers ──────────────────────────────────────────────────────────
    # Fetch corporate actions (dividends, splits) — daily at 02:00 ICT
    "fetch-corporate-actions": {
        "task": "workers.corporate_actions_fetcher.fetch_corporate_actions",
        "schedule": crontab(hour=2, minute=0),
    },
    # Fetch 10-year financial history — daily at 01:00 ICT
    "fetch-financials-history": {
        "task": "workers.financials_history_fetcher.fetch_financials_history",
        "schedule": crontab(hour=1, minute=0),
    },
    # Fetch earnings events (EPS surprise) — daily at 06:00 ICT
    "fetch-earnings-events": {
        "task": "workers.earnings_events_fetcher.fetch_earnings_events",
        "schedule": crontab(hour=6, minute=0),
    },
    # CNN Fear & Greed Index — every 30 minutes
    "fetch-fear-greed": {
        "task": "workers.fgi_fetcher.fetch_fear_greed",
        "schedule": crontab(minute="*/30"),
    },
    # bd:features-2026-09 slice A — daily-only, no dirty-flag/recompute
    # avoidance by design (Tara: over-engineering for this workload).
    # 18:00 ICT — after SET close (16:30 ICT), before US open (21:30 ICT).
    "compute-auto-pivots": {
        "task": "workers.sr_auto_pivot.compute_auto_pivots",
        "schedule": crontab(hour=18, minute=0),
    },
    # bd:features-2026-09 iter 8 — S/R proximity Telegram digest, 2x/day
    # (16-sara-sr-proximity-digest-spec.md §2). 09:30 ICT is 30 min before
    # SET opens (10:00); 19:30 ICT is 30 min before US pre-market (20:00).
    # Both are gated on the target market's own trading day inside the
    # task (bd:shotockviz-3fx) — beat has no weekday concept per slot.
    "sr-digest-set-open": {
        "task": "workers.sr_proximity_digest.send_sr_proximity_digest",
        "schedule": crontab(hour=9, minute=30),  # 09:30 ICT
        "args": ("set_open",),
    },
    "sr-digest-us-premarket": {
        "task": "workers.sr_proximity_digest.send_sr_proximity_digest",
        "schedule": crontab(hour=19, minute=30),  # 19:30 ICT
        "args": ("us_premarket",),
    },
}
