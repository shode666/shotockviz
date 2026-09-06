"""bd:shotockviz-zz8 — only one process may long-poll a bot token.

python-telegram-bot's `getUpdates` allows exactly one consumer. The dev stack
on the developer's Mac and production ran `workers/telegram_bot.py` against
the SAME token (verified identical, prefix `8646452470:`), so each killed the
other's poll in a loop — 9 `telegram.error.Conflict: terminated by other
getUpdates request` tracebacks in 5 minutes on each side, observed right after
the 2026-09-06 deploy.

Beyond log noise: `/start` is how the trader obtains their chat id, and
whichever instance won the race answered it — so a reply could come from a
laptop instead of production, or not at all.

bd:shotockviz-4d9 closed the OUTBOUND half of dev and prod sharing one bot
(sends are dry-run outside production). This is the inbound half.
"""
from unittest.mock import MagicMock, patch

import pytest

from core.config import settings
from workers import telegram_bot


@pytest.fixture
def token(monkeypatch):
    monkeypatch.setattr(settings, "telegram_bot_token", "8646452470:FAKE")


def test_a_dry_run_environment_does_not_poll(token, monkeypatch):
    monkeypatch.setattr(settings, "telegram_dry_run", None)
    monkeypatch.setattr(settings, "app_env", "development")
    assert settings.telegram_is_dry_run is True  # premise

    with patch.object(telegram_bot, "logger") as log:
        # If polling were attempted, the telegram import/builder would run.
        # Patching nothing else: reaching it at all would raise or hang.
        polled = telegram_bot.main()

    assert polled is False, (
        "main() must report that it did not poll, so __main__ can idle instead "
        "of exiting — a clean exit is restarted by `restart: unless-stopped`, "
        "which made the container flap every ~3s repeating this same line"
    )
    assert log.warning.call_count == 1
    msg = log.warning.call_args[0][0]
    assert "NOT started" in msg
    assert "getUpdates" in msg, "the log must say WHY, not just that it stopped"


def test_production_does_poll(token, monkeypatch):
    monkeypatch.setattr(settings, "telegram_dry_run", None)
    monkeypatch.setattr(settings, "app_env", "production")
    assert settings.telegram_is_dry_run is False  # premise

    fake_app = MagicMock()
    with patch("telegram.ext.Application.builder") as builder:
        builder.return_value.token.return_value.build.return_value = fake_app
        polled = telegram_bot.main()

    assert polled is True
    assert fake_app.run_polling.call_count == 1, (
        "production is the one environment that must consume the stream"
    )


def test_an_explicit_opt_in_polls_from_a_non_production_environment(token, monkeypatch):
    """`TELEGRAM_DRY_RUN=false` is the documented escape hatch — a deliberate
    act, so it must actually work rather than being silently ignored."""
    monkeypatch.setattr(settings, "telegram_dry_run", False)
    monkeypatch.setattr(settings, "app_env", "development")

    fake_app = MagicMock()
    with patch("telegram.ext.Application.builder") as builder:
        builder.return_value.token.return_value.build.return_value = fake_app
        assert telegram_bot.main() is True

    assert fake_app.run_polling.call_count == 1


def test_no_token_still_exits_without_polling(monkeypatch):
    """Pre-existing behaviour must survive: a missing token exits quietly
    rather than crash-looping under `restart: unless-stopped`."""
    monkeypatch.setattr(settings, "telegram_bot_token", "")
    with patch("telegram.ext.Application.builder") as builder:
        assert telegram_bot.main() is False
    assert builder.call_count == 0


def test_the_gate_reuses_the_4d9_switch_rather_than_a_second_one():
    """One switch for 'this environment must not act on the real bot'. A
    second flag would drift from the first, which is the defect shape this
    codebase keeps paying for."""
    import inspect

    src = inspect.getsource(telegram_bot.main)
    assert "telegram_is_dry_run" in src
    assert "TELEGRAM_BOT_POLL" not in src, "no second, parallel switch"


def test_idle_forever_exists_so_a_non_polling_container_does_not_flap():
    """`restart: unless-stopped` restarts a clean exit, so returning from
    main() is not enough — the container relaunched every ~3 seconds and
    repeated its explanation forever until this was added. Measured on the
    dev stack, not assumed."""
    import inspect

    assert callable(telegram_bot._idle_forever)
    entry = inspect.getsource(telegram_bot).rsplit('if __name__ ==', 1)[1]
    assert "_idle_forever()" in entry
    assert "if not main():" in entry
