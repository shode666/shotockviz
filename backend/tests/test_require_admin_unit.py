"""
bd:deps-2026-09 Phase 3b (Chris) — pure-unit test for
`api.middleware.auth.require_role`/`require_admin` (S-AC-1's underlying
dependency), with NO DB/HTTP round-trip.

Deliberately bypasses TestClient/db_session (see 14-chris-review.md
CHRIS-01/CHRIS-04: tests/api's fixture chain has two pre-existing,
independently-reproduced infra bugs — a pytest-asyncio 1.x loop-scope
mismatch and a missing `poolclass=StaticPool` on the in-memory SQLite
engine — that make new DB-backed tests under tests/api/ unreliable today).
Calling the dependency function directly with a stub `User` gives a fast,
deterministic unit test of the actual authorization logic, independent of
those infra issues.
"""
import pytest
from fastapi import HTTPException

from api.middleware.auth import require_admin, require_role
from models.user import UserRole


class _StubUser:
    def __init__(self, role: UserRole):
        self.role = role
        self.email = "stub@example.com"


class TestRequireAdmin:
    """`require_admin = require_role(UserRole.admin)` (auth.py:82) IS the
    inner `_check_role` async function itself — `Depends(get_current_user)`
    is only its *default* parameter, resolved by FastAPI's DI at request
    time. Calling it directly with an explicit `user=` kwarg bypasses DI
    entirely and exercises the real role-check logic."""

    async def test_admin_role_passes_through(self):
        user = _StubUser(UserRole.admin)
        result = await require_admin(user=user)
        assert result is user

    async def test_user_role_raises_403(self):
        user = _StubUser(UserRole.user)
        with pytest.raises(HTTPException) as exc_info:
            await require_admin(user=user)
        assert exc_info.value.status_code == 403

    async def test_guest_role_raises_403(self):
        user = _StubUser(UserRole.guest)
        with pytest.raises(HTTPException) as exc_info:
            await require_admin(user=user)
        assert exc_info.value.status_code == 403


class TestRequireRoleFactoryAllowsMultipleRoles:
    async def test_role_in_allowed_set_passes(self):
        checker = require_role(UserRole.user, UserRole.admin)
        for role in (UserRole.user, UserRole.admin):
            result = await checker(user=_StubUser(role))
            assert result.role == role

    async def test_role_outside_allowed_set_raises_403(self):
        checker = require_role(UserRole.admin)
        with pytest.raises(HTTPException):
            await checker(user=_StubUser(UserRole.guest))
