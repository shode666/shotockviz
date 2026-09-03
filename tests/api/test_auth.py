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
    resp = client.get("/api/v1/auth/me", headers=auth_headers)
    assert resp.status_code == 200
    assert "email" in resp.json()


def test_me_unauthenticated(client):
    resp = client.get("/api/v1/auth/me")
    assert resp.status_code == 401
