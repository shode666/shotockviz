"""
bd:deps-2026-09 Phase 3b (Chris, adversarial review) — S-AC-1 / AC-D5
regression tests for `require_admin` on the 3 admin.py endpoints.

Sentinel's threat model (05-sentinel-threat-model.md AB-1) proved this was
a real privilege-escalation-adjacent data-loss bug pre-fix: any
authenticated (non-admin) user could wipe historical OHLCV bars via
PUT retention-policy + POST run-now. Dave's WP-S2 fix (admin.py ->
Depends(require_admin)) was verified only via a throwaway in-memory
script (12-dave-serial-s0-s3.md), never committed as a test. Before this
file: zero admin tests existed anywhere in the repo
(`grep -rln admin tests/api backend/tests` -> no matches).
"""
import pytest
from core.security import create_access_token

# bd:deps-2026-09 Phase 3b (Chris) — NOT using core.security.hash_password()
# here: it is unconditionally broken in THIS repo's pinned dependency set
# (passlib==1.7.4 + bcrypt==5.0.0, backend/requirements.txt:17-18) —
# reproduced standalone AND confirmed pre-existing at baseline 73fac00 (same
# pins, unchanged by this migration). See 14-chris-review.md finding
# CHRIS-01. password_hash is a required NOT NULL column but its value is
# never read anywhere post-ADR-007 (password login removed) — a fixed
# placeholder is safe and avoids depending on the broken code path.
_UNUSED_PASSWORD_HASH = "unused-post-adr-007-no-password-login"


@pytest.fixture
async def _admin_user(db_session):
    from models.user import User, UserRole

    user = User(
        email="admin@example.com",
        password_hash=_UNUSED_PASSWORD_HASH,
        display_name="Admin User",
        is_active=True,
        role=UserRole.admin,
    )
    db_session.add(user)
    await db_session.flush()
    await db_session.refresh(user)
    return user


@pytest.fixture
def admin_auth_headers(_admin_user):
    token = create_access_token({
        "sub": str(_admin_user.id),
        "email": _admin_user.email,
        "display_name": _admin_user.display_name,
        "role": _admin_user.role.value,
        "created_at": _admin_user.created_at.isoformat(),
    })
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture
async def _regular_user(db_session):
    """Local fixture, NOT conftest.py's auth_headers/_test_user — those
    call core.security.hash_password() which is broken pre-existing (see
    module docstring / _UNUSED_PASSWORD_HASH above)."""
    from models.user import User, UserRole

    user = User(
        email="regular@example.com",
        password_hash=_UNUSED_PASSWORD_HASH,
        display_name="Regular User",
        is_active=True,
        role=UserRole.user,
    )
    db_session.add(user)
    await db_session.flush()
    await db_session.refresh(user)
    return user


@pytest.fixture
def regular_auth_headers(_regular_user):
    token = create_access_token({
        "sub": str(_regular_user.id),
        "email": _regular_user.email,
        "display_name": _regular_user.display_name,
        "role": _regular_user.role.value,
        "created_at": _regular_user.created_at.isoformat(),
    })
    return {"Authorization": f"Bearer {token}"}


class TestGetRetentionPolicyAuthz:
    def test_regular_user_is_forbidden(self, client, regular_auth_headers):
        resp = client.get("/api/v1/admin/retention-policy", headers=regular_auth_headers)
        assert resp.status_code == 403, resp.text
        body = resp.json()
        assert body["data"] is None
        assert "admin" in body["meta"]["error"]["message"].lower()

    def test_admin_user_is_allowed(self, client, admin_auth_headers):
        resp = client.get("/api/v1/admin/retention-policy", headers=admin_auth_headers)
        assert resp.status_code == 200, resp.text
        assert "policy" in resp.json()["data"]

    def test_unauthenticated_is_401_not_403(self, client):
        resp = client.get("/api/v1/admin/retention-policy")
        assert resp.status_code == 401


class TestUpdateRetentionPolicyAuthz:
    """AB-1 (Sentinel): this is the destructive endpoint — a non-admin
    setting {"1d": 1} + run-now deletes ~2 years of daily bars."""

    def test_regular_user_is_forbidden(self, client, regular_auth_headers):
        resp = client.put(
            "/api/v1/admin/retention-policy",
            headers=regular_auth_headers,
            json={"policy": [{"resolution": "1d", "max_age_days": 1}]},
        )
        assert resp.status_code == 403, resp.text

    def test_admin_user_is_allowed(self, client, admin_auth_headers):
        resp = client.put(
            "/api/v1/admin/retention-policy",
            headers=admin_auth_headers,
            json={"policy": [{"resolution": "1d", "max_age_days": 365}]},
        )
        assert resp.status_code == 200, resp.text


class TestRunHousekeepingNowAuthz:
    def test_regular_user_is_forbidden(self, client, regular_auth_headers):
        resp = client.post("/api/v1/admin/retention-policy/run-now", headers=regular_auth_headers)
        assert resp.status_code == 403, resp.text

    def test_admin_user_is_allowed(self, client, admin_auth_headers):
        resp = client.post("/api/v1/admin/retention-policy/run-now", headers=admin_auth_headers)
        assert resp.status_code == 200, resp.text
