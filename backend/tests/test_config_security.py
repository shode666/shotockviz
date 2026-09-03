"""bd:deps-2026-09 WP-B2 — S-AC-10 (05-sentinel-threat-model.md §3): boot
must FAIL, not just warn, if the default JWT secret reaches production.
"""
import warnings

import pytest

from core.config import Settings


def test_default_jwt_secret_raises_in_production(monkeypatch):
    """APP_ENV=production + default jwt_secret_key -> Settings() raises."""
    monkeypatch.setenv("APP_ENV", "production")
    with pytest.raises(ValueError, match="default dev value in a production"):
        Settings(
            _env_file=None,
            jwt_secret_key="dev-secret-key-change-in-prod",
        )


def test_default_jwt_secret_warns_in_development(monkeypatch):
    """Non-production + default jwt_secret_key -> warns only, boot succeeds."""
    monkeypatch.delenv("APP_ENV", raising=False)
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        settings = Settings(
            _env_file=None,
            jwt_secret_key="dev-secret-key-change-in-prod",
        )
    assert settings.jwt_secret_key == "dev-secret-key-change-in-prod"
    assert any("default dev value" in str(w.message) for w in caught)


def test_custom_jwt_secret_in_production_boots_clean(monkeypatch):
    """A real secret in production raises nothing."""
    monkeypatch.setenv("APP_ENV", "production")
    settings = Settings(
        _env_file=None,
        jwt_secret_key="a-real-32-character-secret-value",
    )
    assert settings.jwt_secret_key == "a-real-32-character-secret-value"
