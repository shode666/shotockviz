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

    install_secret_redaction()


class _SecretRedactingFilter(logging.Filter):
    """Scrub the Telegram bot token out of any log record that carries it.

    bd:shotockviz-pdb — the token is not a header we control, it is a path
    segment of the Telegram API URL
    (`https://api.telegram.org/bot<TOKEN>/sendMessage`), so ANY library that
    logs a request URL logs the secret. httpx did exactly that at INFO in
    every Celery worker (workers never called `setup_logging()`, so the
    WARNING suppression above only ever applied to the FastAPI process), and
    the token sat in plaintext in `docker logs` for both dev and prod.

    Raising httpx to WARNING fixes the one library we know about. This
    filter is the part that does not depend on knowing about them: it runs
    on the handler, so it sees every record from every logger, and it
    rewrites the message instead of dropping it — a redacted line is still
    a useful line. It never raises: a logging filter that throws would take
    down the call site it was meant to protect.
    """

    def filter(self, record: logging.LogRecord) -> bool:
        token = settings.telegram_bot_token
        if not token:
            return True
        try:
            if isinstance(record.msg, str) and token in record.msg:
                record.msg = record.msg.replace(token, "<redacted>")
            if record.args:
                if isinstance(record.args, dict):
                    record.args = {
                        k: (v.replace(token, "<redacted>") if isinstance(v, str) else v)
                        for k, v in record.args.items()
                    }
                elif isinstance(record.args, tuple):
                    record.args = tuple(
                        v.replace(token, "<redacted>") if isinstance(v, str) else v
                        for v in record.args
                    )
        except Exception:  # never let logging hygiene break the caller
            pass
        return True


def install_secret_redaction():
    """Attach `_SecretRedactingFilter` to every root handler, idempotently.

    Called from `setup_logging()` (FastAPI) and from Celery's
    `after_setup_logger`/`after_setup_task_logger` signals in
    `workers/celery_app.py` — Celery installs its OWN handlers after the
    worker boots, so a filter attached at import time would not be on them.
    """
    root = logging.getLogger()
    for handler in root.handlers:
        if not any(isinstance(f, _SecretRedactingFilter) for f in handler.filters):
            handler.addFilter(_SecretRedactingFilter())


def get_logger(name: str = __name__):
    return structlog.get_logger(name)
