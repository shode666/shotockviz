"""bd:shotockviz-4d9 — a dev stack must not message the user's real phone.

The dev DB's user 1 carries the same live `telegram_chat_id` as production
and the dev stack has a real `TELEGRAM_BOT_TOKEN`, so every scheduled
notification in this project reaches the user's actual phone from a laptop.
Two S/R digests did exactly that on 2026-09-06, at 02:30 and 12:30 on a
Sunday. The only guard was a sentence in CLAUDE.md telling agents not to
send; a rule an agent has to remember is not a guard.
"""
from unittest.mock import MagicMock, patch

import pytest

from core.config import settings
from services import telegram_notify


@pytest.fixture
def dry_run_on(monkeypatch):
    """Undo conftest's suite-wide override — this file tests the default."""
    monkeypatch.setattr(settings, "telegram_dry_run", None)
    monkeypatch.setattr(settings, "app_env", "development")
    monkeypatch.setattr(settings, "telegram_bot_token", "8646452470:FAKE")


@pytest.fixture
def production(monkeypatch):
    monkeypatch.setattr(settings, "telegram_dry_run", None)
    monkeypatch.setattr(settings, "app_env", "production")
    monkeypatch.setattr(settings, "telegram_bot_token", "8646452470:FAKE")


# ── the resolver ────────────────────────────────────────────────────────────

def test_dry_run_is_on_by_default_outside_production(dry_run_on):
    assert settings.telegram_is_dry_run is True


def test_dry_run_is_off_in_production(production):
    assert settings.telegram_is_dry_run is False


@pytest.mark.parametrize("env", ["development", "staging", "test", "production"])
def test_explicit_setting_wins_in_both_directions(monkeypatch, env):
    monkeypatch.setattr(settings, "app_env", env)
    monkeypatch.setattr(settings, "telegram_dry_run", True)
    assert settings.telegram_is_dry_run is True
    monkeypatch.setattr(settings, "telegram_dry_run", False)
    assert settings.telegram_is_dry_run is False


def test_an_unrecognised_env_is_treated_as_not_production(monkeypatch):
    """Fail safe: anything that is not literally production suppresses."""
    monkeypatch.setattr(settings, "telegram_dry_run", None)
    monkeypatch.setattr(settings, "app_env", "prod")  # near-miss typo
    assert settings.telegram_is_dry_run is True


# ── the chokepoint ──────────────────────────────────────────────────────────

def test_dry_run_makes_no_http_call_at_all(dry_run_on):
    with patch("httpx.post") as mock_post:
        sent = telegram_notify.send_telegram_message("8367875747", "hello", context="t")
    mock_post.assert_not_called()
    assert sent is True, (
        "a suppressed send must report success, or the caller retries forever "
        "on a message that is never going to leave"
    )


def test_production_does_make_the_call(production):
    with patch("httpx.post", return_value=MagicMock(status_code=200)) as mock_post:
        sent = telegram_notify.send_telegram_message("8367875747", "hello", context="t")
    assert mock_post.call_count == 1
    assert sent is True


@pytest.mark.asyncio
async def test_async_twin_is_also_suppressed(dry_run_on):
    with patch("httpx.AsyncClient") as mock_client_cls:
        ok, err = await telegram_notify.send_telegram_message_async(
            "8367875747", "hello", context="t"
        )
    mock_client_cls.assert_not_called()
    assert (ok, err) == (True, "")


def test_dry_run_logs_the_message_it_suppressed(dry_run_on):
    """A silent no-op is not verifiable. The developer must be able to see
    what would have gone out, and to whom. (Asserted against the structlog
    logger directly — structlog does not route through pytest's caplog.)"""
    with patch.object(telegram_notify, "logger") as mock_logger:
        telegram_notify.send_telegram_message(
            "8367875747", "the digest body", context="sr_proximity_digest"
        )
    assert mock_logger.info.call_count == 1
    msg, kwargs = mock_logger.info.call_args[0][0], mock_logger.info.call_args[1]
    assert "DRY RUN" in msg
    assert kwargs["text"] == "the digest body"
    assert kwargs["chat_id"] == "8367875747"
    assert kwargs["context"] == "sr_proximity_digest"


# ── nobody bypasses it ──────────────────────────────────────────────────────

def test_no_module_builds_the_telegram_url_itself():
    """Five call sites each built the URL and POSTed it before this bead.
    A guard that lives in one place only works if nothing goes around it."""
    import pathlib

    root = pathlib.Path(__file__).resolve().parents[1]
    offenders = []
    for path in list(root.glob("workers/*.py")) + list(root.glob("api/routes/**/*.py")):
        if "api.telegram.org" in path.read_text():
            offenders.append(str(path.relative_to(root)))
    assert offenders == [], (
        f"{offenders} build the Telegram API URL directly instead of going "
        f"through services/telegram_notify.py — the dry-run guard does not "
        f"apply to them"
    )
