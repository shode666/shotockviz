"""
Contract tests for /api/v1 prefix + {data,meta} envelope (bd:deps-2026-09 Phase
3b, Quinn — AC-B2/B3/B7, S-AC-1, S-AC-3, S-AC-5).

Scope: mechanical/structural contract checks, not endpoint business logic
(that's Chris's/Dave's territory). Uses the sqlite in-memory fixtures already
defined in tests/api/conftest.py — no Docker/Postgres required to run this
file (CI-runnable). A subset of assertions here were additionally verified
against a REAL Postgres + Redis backend during Quinn's Phase 3b review (see
outputs/deps-2026-09/15-quinn-review.md for that evidence — this file only
captures what's reproducible on the sqlite fixtures used in CI).

Known root-cause note (do NOT "fix" by weakening this file): the
`auth_headers` fixture in this conftest mints a JWT against `db_session`'s
engine. Only the DEFAULT `client` fixture (also `db_session`-backed) is
consistent with it. `test_api_endpoints.py` locally overrides `client` to be
the module-scoped `app_client` (its OWN separate sqlite engine) — combining
that `client` override with `auth_headers` silently 401s (see Quinn's
review, Finding Q-3). This file deliberately does NOT import that override,
so `client`/`auth_headers` here resolve to the consistent pair.
"""
from __future__ import annotations

import os
import sys

import pytest

# Force full ORM model registration on Base.metadata BEFORE any fixture in
# this session runs `Base.metadata.create_all()`. tests/api/conftest.py's
# `test_engine` fixture is session-scoped and creates tables from whatever
# is registered on Base.metadata AT THAT MOMENT — if this is the first file
# pytest collects/runs and nothing has imported `models`/`main` yet, tables
# like `stocks` silently don't exist ("no such table: stocks"), a
# collection-order-dependent flake in the shared fixture, not this file.
# Reproduced standalone: `pytest tests/api/test_contract_v1.py::...[/api/v1/screener]`
# fails with sqlite3.OperationalError: no such table: stocks unless something
# already imported the model package first. See Quinn's review, Finding Q-5.
_BACKEND_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__)))), "backend")
if _BACKEND_DIR not in sys.path:
    sys.path.insert(0, _BACKEND_DIR)
import models  # noqa: E402,F401 — side effect: registers all tables on Base.metadata

# Exact unversioned-exception path set per ADR-001 r3 / CLAUDE.md architecture
# diagram. Anything else under /api/* MUST start with /api/v1.
UNVERSIONED_EXACT_PATHS = {"/api/health"}
UNVERSIONED_PREFIXES = ("/api/ws/",)

# Substrings that must never appear in an error envelope body (S-AC-5:
# no exception class / traceback / SQL fragment / filesystem path leak).
LEAK_MARKERS = ("Traceback", "Exception", "  File \"", "/home/", "/backend/", "SELECT ", "INSERT ", "sqlalchemy")


def _iter_api_routes(app):
    """Yield (path, methods) for every HTTP route under /api on the live app.

    bd:deps-2026-09 iter1 — `app.routes` no longer flattens child routes on
    this fastapi version (`include_router()` builds a lazy wrapper instead),
    so walking it directly misses everything under /api/v1. `app.openapi()
    ["paths"]` is the version-stable replacement (same flattened map
    FastAPI's own schema generation resolves internally). WebSocket routes
    have no OpenAPI entry and still live directly on `app.routes`
    unwrapped, so `/api/ws/prices` below still finds it via the old path.
    """
    for path, methods_map in app.openapi()["paths"].items():
        if not path.startswith("/api"):
            continue
        yield path, set(methods_map.keys())


# ── AC-B2/B3: prefix whitelist (mechanical, whole app) ──────────────────────

class TestPrefixWhitelist:
    def test_every_api_route_is_v1_or_a_named_exception(self, client):
        from main import app

        violations = []
        for path, _methods in _iter_api_routes(app):
            if path in UNVERSIONED_EXACT_PATHS:
                continue
            if path.startswith("/api/v1"):
                continue
            if path.startswith(UNVERSIONED_PREFIXES):
                continue
            violations.append(path)
        assert violations == [], (
            f"routes outside /api/v1 and outside the 2 named exceptions "
            f"(/api/health, /api/ws/*): {violations}"
        )

    def test_named_exceptions_actually_exist_and_are_reachable(self, client):
        """The 2 documented exceptions must be real, not just 'nothing violates
        the rule because nothing matches the exact path' (vacuous-pass guard)."""
        from main import app

        seen_prefixes = {"/api/health": False}
        for path, _methods in _iter_api_routes(app):
            if path == "/api/health":
                seen_prefixes["/api/health"] = True
        assert seen_prefixes["/api/health"], "/api/health route missing entirely"
        # /api/ws/prices is a WebSocketRoute (no `methods` attr) — checked
        # separately since _iter_api_routes skips it by design.
        ws_paths = [r.path for r in app.routes if getattr(r, "path", "") == "/api/ws/prices"]
        assert ws_paths, "/api/ws/prices WebSocket route missing entirely"


# ── AC-B1/B3: {data,meta} envelope shape on 2xx GET responses ───────────────

# Curated list of GET endpoints reachable with zero seed data against the
# sqlite fixtures (empty DB is a valid, deterministic state for all of
# these — no symbol/user pre-seeding required beyond auth for the
# auth-required ones).
PUBLIC_GET_ENDPOINTS = [
    "/api/v1/auth/config",
    "/api/v1/stocks/names",          # empty symbols param -> {}
    "/api/v1/screener",              # no filters -> empty/short list
]

AUTHED_GET_ENDPOINTS = [
    "/api/v1/watchlists",
    "/api/v1/portfolio",
    "/api/v1/alerts",
    "/api/v1/auth/me",
]


class TestEnvelopeShapePublic:
    @pytest.mark.parametrize("path", PUBLIC_GET_ENDPOINTS)
    def test_envelope_has_data_and_meta(self, client, path):
        resp = client.get(path)
        assert resp.status_code == 200, f"{path} -> {resp.status_code}: {resp.text[:300]}"
        body = resp.json()
        assert "data" in body, f"{path}: missing 'data' key, got keys={list(body.keys())}"
        assert "meta" in body, f"{path}: missing 'meta' key, got keys={list(body.keys())}"
        assert "request_id" in body["meta"], f"{path}: meta missing request_id"

    def test_stocks_quotes_payload_lands_under_data(self, client):
        """Merged from test_pr4_envelope.py — a real payload, not just the
        empty/short responses PUBLIC_GET_ENDPOINTS above exercises."""
        resp = client.get("/api/v1/stocks/quotes?symbols=AAPL")
        assert resp.status_code == 200
        body = resp.json()
        assert set(body.keys()) == {"data", "meta"}
        assert "AAPL" in body["data"]


class TestEnvelopeShapeAuthed:
    @pytest.mark.parametrize("path", AUTHED_GET_ENDPOINTS)
    def test_envelope_has_data_and_meta(self, client, auth_headers, path):
        resp = client.get(path, headers=auth_headers)
        assert resp.status_code == 200, f"{path} -> {resp.status_code}: {resp.text[:300]}"
        body = resp.json()
        assert "data" in body, f"{path}: missing 'data' key, got keys={list(body.keys())}"
        assert "meta" in body, f"{path}: missing 'meta' key, got keys={list(body.keys())}"


# ── AC-B4-r3 / S-AC-5: error envelope shape + no-leak, all 4xx classes ──────

class TestErrorEnvelope:
    def test_401_no_token(self, client):
        resp = client.get("/api/v1/watchlists")
        assert resp.status_code == 401
        # AC-B6-r3: 401 still carries the WWW-Authenticate challenge header
        # (merged from test_pr4_envelope.py, was its own test)
        assert resp.headers.get("www-authenticate") == "Bearer"
        body = resp.json()
        assert body["data"] is None
        assert "error" in body["meta"] and "message" in body["meta"]["error"]

    def test_403_wrong_role(self, client, auth_headers):
        """S-AC-1: non-admin -> 403 on admin routes."""
        resp = client.get("/api/v1/admin/retention-policy", headers=auth_headers)
        assert resp.status_code == 403, f"expected 403, got {resp.status_code}: {resp.text[:300]}"
        body = resp.json()
        assert body["data"] is None
        assert "admin" in body["meta"]["error"]["message"].lower()

    def test_404_unknown_v1_path(self, client):
        resp = client.get("/api/v1/this-does-not-exist")
        assert resp.status_code == 404
        body = resp.json()
        assert body["data"] is None
        assert "error" in body["meta"]

    def test_405_wrong_method(self, client):
        # /api/v1/stocks/search only defines GET
        resp = client.delete("/api/v1/stocks/search")
        assert resp.status_code == 405
        body = resp.json()
        assert body["data"] is None
        assert "error" in body["meta"]

    def test_422_validation_error(self, client):
        # /stocks/search requires `q` — omit it
        resp = client.get("/api/v1/stocks/search")
        assert resp.status_code == 422
        body = resp.json()
        assert body["data"] is None
        assert "error" in body["meta"]

    @pytest.mark.parametrize(
        "path,method",
        [
            # bd:deps-2026-09 iter1 — 3 genuinely-erroring authed scenarios
            # (POST /watchlists with no body -> 422, 403, 404) covering 3
            # different 4xx classes; NOT a GET on /watchlists (that 200s
            # for a valid authed user — see CHRIS-04/Q-5, git history).
            ("/api/v1/watchlists", "post"),
            ("/api/v1/admin/retention-policy", "get"),
            ("/api/v1/this-does-not-exist", "get"),
        ],
    )
    def test_no_leak_markers_in_error_body(self, client, auth_headers, path, method):
        resp = getattr(client, method)(path, headers=auth_headers)
        assert resp.status_code >= 400
        raw = resp.text
        for marker in LEAK_MARKERS:
            assert marker not in raw, (
                f"{path} error body contains leak marker {marker!r}: {raw[:500]}"
            )


# ── AC-B7: /api/health shape — documents ACTUAL behavior + the known gap ────

class TestHealthEndpointContract:
    def test_health_returns_enveloped_shape_not_flat_status(self, client):
        """system.py:82 (BaseResponse[dict]) returns {data:{database,redis,
        celery}, meta:{...}} — there is NO top-level `status` key. This test
        documents the REAL contract. tests/e2e/health.spec.ts:12 currently
        asserts `body.status === 'ok'`, which this shape does NOT satisfy —
        see Quinn's review Finding Q-1 (AC-B7 not actually closed)."""
        resp = client.get("/api/health")
        assert resp.status_code == 200
        body = resp.json()
        assert "data" in body and "meta" in body
        assert "status" not in body, (
            "if this starts failing because a top-level `status` key was "
            "added, AC-B7 has been closed the other way (compat field) — "
            "update this test's docstring/assertion, don't just delete it"
        )
        assert set(body["data"].keys()) >= {"database", "redis", "celery"}

    def test_health_needs_no_auth(self, client):
        resp = client.get("/api/health")
        assert resp.status_code == 200

    def test_health_is_not_double_wrapped(self, client):
        """system.py hand-wraps /api/health itself (BaseResponse) and does
        NOT get route_class=EnvelopingAPIRoute — a double-wrap would
        produce body['data']['data']. (merged from test_pr4_envelope.py)"""
        body = client.get("/api/health").json()
        assert not isinstance(body["data"], dict) or "meta" not in body["data"]

    def test_health_wrong_method_is_not_v1_enveloped(self, client):
        """r3-1/r3-2: /api/health is one of the 3 deliberate unversioned
        exceptions — install_error_envelope must NOT touch it, so a 405
        here keeps FastAPI's default {"detail": ...} shape, not {data,meta}.
        (merged from test_pr4_envelope.py)"""
        resp = client.post("/api/health")
        assert resp.status_code == 405
        body = resp.json()
        assert "detail" in body
        assert "data" not in body and "meta" not in body


# ── Frozen-path guard: old unversioned REST paths must be gone (no alias,
#    per user decision #4 / ADR-001 r2 "no dual mount") ─────────────────────

class TestNoLegacyAlias:
    @pytest.mark.parametrize(
        "legacy_path",
        ["/api/watchlists", "/api/stocks/search", "/api/portfolio", "/api/alerts"],
    )
    def test_old_unversioned_rest_path_404s(self, client, legacy_path):
        resp = client.get(legacy_path)
        assert resp.status_code == 404, (
            f"{legacy_path} should 404 (no legacy alias per ADR-001 r2) but "
            f"got {resp.status_code} — if this is intentional, it's a scope "
            f"change from user decision #4 and needs Oliver sign-off"
        )
