"""Tests for auth endpoints."""
import pytest


def test_register_success(client):
    resp = client.post("/api/auth/register", json={
        "email": "new@example.com",
        "password": "NewPass1",
        "display_name": "New User",
    })
    assert resp.status_code == 201
    data = resp.json()
    assert data["email"] == "new@example.com"
    assert "password_hash" not in data


def test_register_duplicate_email(client):
    payload = {"email": "dup@example.com", "password": "DupPass1", "display_name": "Dup"}
    client.post("/api/auth/register", json=payload)
    resp = client.post("/api/auth/register", json=payload)
    assert resp.status_code == 409


def test_register_weak_password(client):
    resp = client.post("/api/auth/register", json={
        "email": "weak@example.com",
        "password": "short",
        "display_name": "Weak",
    })
    assert resp.status_code == 422


def test_login_success(client, auth_headers):
    # Already registered in fixture — just verify we can get /me
    resp = client.get("/api/auth/me", headers=auth_headers)
    assert resp.status_code == 200
    assert "email" in resp.json()


def test_login_wrong_password(client):
    client.post("/api/auth/register", json={
        "email": "good@example.com", "password": "GoodPass1", "display_name": "Good",
    })
    resp = client.post("/api/auth/login", json={
        "email": "good@example.com", "password": "WrongPass1",
    })
    assert resp.status_code == 401


def test_me_unauthenticated(client):
    resp = client.get("/api/auth/me")
    assert resp.status_code == 401
