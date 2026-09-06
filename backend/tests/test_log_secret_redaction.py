"""bd:shotockviz-pdb — the Telegram bot token must never reach a log line.

The token is a PATH SEGMENT of the Telegram API URL
(`https://api.telegram.org/bot<TOKEN>/sendMessage`), so any library that logs
a request URL logs the secret. httpx did exactly that at INFO in every Celery
worker — `core.logger.setup_logging()` was only ever called by `main.py`, so
the httpx-to-WARNING suppression never applied to workers, and the token sat
in plaintext in `docker logs` for both dev and prod.
"""
import io
import logging

import pytest

from core import logger as logger_mod


@pytest.fixture
def token(monkeypatch):
    fake = "8646452470:AAFAKEfaketokenfaketokenfaketoken"
    monkeypatch.setattr(logger_mod.settings, "telegram_bot_token", fake)
    return fake


@pytest.fixture
def captured(token):
    """A root handler with the redaction filter installed, exactly as
    install_secret_redaction() would set it up in a worker."""
    stream = io.StringIO()
    handler = logging.StreamHandler(stream)
    handler.setFormatter(logging.Formatter("%(message)s"))
    root = logging.getLogger()
    root.addHandler(handler)
    try:
        logger_mod.install_secret_redaction()
        yield stream
    finally:
        root.removeHandler(handler)


def test_token_in_message_is_redacted(captured, token):
    logging.getLogger("httpx").warning(
        'HTTP Request: POST https://api.telegram.org/bot%s/sendMessage "HTTP/1.1 200 OK"' % token
    )
    out = captured.getvalue()
    assert token not in out
    assert "<redacted>" in out
    # the line is rewritten, not dropped — a redacted log is still useful
    assert "api.telegram.org" in out


def test_token_in_lazy_args_is_redacted(captured, token):
    logging.getLogger("httpx").warning("HTTP Request: %s %s", "POST",
                                       f"https://api.telegram.org/bot{token}/sendMessage")
    out = captured.getvalue()
    assert token not in out
    assert "<redacted>" in out


def test_records_without_the_token_are_untouched(captured, token):
    logging.getLogger("workers.test").warning("fetched 31 quotes")
    assert captured.getvalue().strip().endswith("fetched 31 quotes")


def test_install_is_idempotent(captured, token):
    before = sum(
        1 for h in logging.getLogger().handlers
        for f in h.filters if isinstance(f, logger_mod._SecretRedactingFilter)
    )
    logger_mod.install_secret_redaction()
    logger_mod.install_secret_redaction()
    after = sum(
        1 for h in logging.getLogger().handlers
        for f in h.filters if isinstance(f, logger_mod._SecretRedactingFilter)
    )
    assert before == after


def test_no_token_configured_is_a_no_op(captured, monkeypatch):
    monkeypatch.setattr(logger_mod.settings, "telegram_bot_token", "")
    logging.getLogger("workers.test").warning("nothing to redact here")
    assert "nothing to redact here" in captured.getvalue()


def test_filter_never_raises_on_a_weird_record(captured, token):
    """A logging filter that throws takes down the call site it was meant to
    protect, so it must survive non-str msg/args."""
    logging.getLogger("workers.test").warning({"not": "a string"})
    logging.getLogger("workers.test").warning("count=%d", 3)
    assert "count=3" in captured.getvalue()


def test_celery_signal_handler_hardens_worker_logging(token):
    """The worker-side entry point: after_setup_logger must raise httpx out of
    INFO (where it logs request URLs) and install the filter."""
    from workers.celery_app import _harden_worker_logging

    logging.getLogger("httpx").setLevel(logging.NOTSET)
    _harden_worker_logging()
    assert logging.getLogger("httpx").level == logging.WARNING
    assert logging.getLogger("httpcore").level == logging.WARNING
