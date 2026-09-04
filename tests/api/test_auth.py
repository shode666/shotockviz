"""Tests for auth endpoints.

bd:deps-2026-09 S1 (ADR-007) — POST /api/v1/auth/register, POST
/api/v1/auth/login, POST /api/v1/auth/refresh, POST /api/v1/auth/logout were
removed (dead code / client-side-refresh lifecycle CLAUDE.md rule 5
prohibits). This file previously tested those routes directly; now it
proves removal (AC-D7) and re-verifies the 2 surviving routes that don't
call Google (AC-D8) — /me. /google itself needs a live Google ID token
and is out of this offline suite's reach (unchanged from before).
"""
import pytest


def test_register_route_removed(client):
    resp = client.post("/api/v1/auth/register", json={
        "email": "new@example.com",
        "password": "NewPass1",
        "display_name": "New User",
    })
    assert resp.status_code in (404, 405)


def test_login_route_removed(client):
    resp = client.post("/api/v1/auth/login", json={
        "email": "good@example.com", "password": "GoodPass1",
    })
    assert resp.status_code in (404, 405)


def test_refresh_route_removed(client):
    resp = client.post("/api/v1/auth/refresh", json={"refresh_token": "anything"})
    assert resp.status_code in (404, 405)


def test_logout_route_removed(client):
    resp = client.post("/api/v1/auth/logout", json={"refresh_token": "anything"})
    assert resp.status_code in (404, 405)


def test_login_success(client, auth_headers):
    # AC-D9: auth_headers now mints its token directly via
    # core.security.create_access_token (no HTTP round-trip through the
    # removed /register+/login routes) — just verify we can get /me.
    #
    # bd:deps-2026-09 iter1 (Dave-discovered, same class as Quinn's Q-1
    # envelope-unwrap findings in test_api_endpoints.py) — was
    # `assert "email" in resp.json()`, reading the raw body; S2's ADR-002
    # envelope flip wraps every /api/v1 2xx body as {data, meta}, so
    # "email" is at resp.json()["data"], not top-level. Was previously
    # masked by the auth-fixture/StaticPool bugs (CHRIS-04/Q-3/Q-5) making
    # this request fail with a DIFFERENT error before this assertion ever
    # ran; now that auth resolves correctly, the real envelope-unwrap bug
    # surfaces on its own.
    resp = client.get("/api/v1/auth/me", headers=auth_headers)
    assert resp.status_code == 200
    body = resp.json()
    assert "email" in body["data"], f"expected 'email' in body['data'], got {body}"


def test_me_unauthenticated(client):
    resp = client.get("/api/v1/auth/me")
    assert resp.status_code == 401
