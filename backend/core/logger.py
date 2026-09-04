import logging
import sys
import structlog
from core.config import settings


def setup_logging():
    """Configure structured logging."""
    log_level = logging.DEBUG if settings.debug else logging.INFO

    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            structlog.processors.add_log_level,
            structlog.processors.StackInfoRenderer(),
            structlog.dev.set_exc_info,
            structlog.processors.TimeStamper(fmt="iso"),
            structlog.dev.ConsoleRenderer() if settings.debug else structlog.processors.JSONRenderer(),
        ],
        wrapper_class=structlog.make_filtering_bound_logger(log_level),
        context_class=dict,
        logger_factory=structlog.PrintLoggerFactory(),
        cache_logger_on_first_use=True,
    )

    # Configure standard logging to go through structlog
    logging.basicConfig(
        format="%(message)s",
        stream=sys.stdout,
        level=log_level,
    )

    # Suppress verbose TCP-level lifecycle events from httpx/httpcore.
    # In debug mode these log EVERY connect/send/receive event per HTTP call,
    # flooding stdout with hundreds of lines and degrading performance.
    # Also: redis-py 8.1's "auto" maint-notifications handshake retry
    # (redis/connection.py:667, redis/asyncio/connection.py:429) logs a
    # DEBUG line per connection against our Redis 7 server (no
    # MAINT_NOTIFICATIONS subcommand) — every sync worker connection +
    # the Celery broker (kombu builds its own ConnectionPool, no opt-out
    # kwarg exposed) hits this; core/redis.py's own async pool is opted
    # out directly via maint_notifications_config.
    for noisy in ("httpx", "httpcore", "httpcore.http11", "httpcore.connection",
                  "redis.connection", "redis.asyncio.connection"):
        logging.getLogger(noisy).setLevel(logging.WARNING)


def get_logger(name: str = __name__):
    return structlog.get_logger(name)
