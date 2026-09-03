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
UNVERSIONED_PREFIXES = ("/api/ai/", "/api/ws/")

# Substrings that must never appear in an error envelope body (S-AC-5:
# no exception class / traceback / SQL fragment / filesystem path leak).
LEAK_MARKERS = ("Traceback", "Exception", "  File \"", "/home/", "/backend/", "SELECT ", "INSERT ", "sqlalchemy")


def _iter_api_routes(app):
    """Yield (path, methods) for every HTTP route under /api on the live app.

    bd:deps-2026-09 iter1 (Dave-discovered, not in Chris's/Quinn's original
    reports) — starlette 1.6.0 / fastapi 0.141.1 changed `include_router()`
    to build a lazy `fastapi.routing._IncludedRouter` wrapper instead of
    eagerly flattening child routes onto `app.routes` at call time (matching
    is now done dynamically via `_IncludedRouter.effective_candidates()`).
    Confirmed via direct introspection: `app.routes` has only 4 top-level
    entries for the ENTIRE 13-router /api/v1 aggregate + health_router +
    ai_chat.router combined, all as opaque `_IncludedRouter` objects with
    `path=None`/`methods=None` (and no usable public flat `.routes` either —
    `.original_router.routes` just recurses into the same problem one level
    down, since api_v1 itself nests 13 more `include_router()` calls).
    Walking `app.routes` for HTTP route introspection no longer works on
    this fastapi version — this is why /api/health "went missing" and every
    `/api/v1/*` route silently vanished from every test in this file at
    once. `app.openapi()["paths"]` is the version-stable replacement: it's
    the SAME flattened path/method map FastAPI's own schema generation
    resolves through `_IncludedRouter.effective_candidates()` internally
    (CHRIS-06 depends on this exact call already, for openapi-v1.json).
    WebSocket routes have no OpenAPI entry and still live directly on
    `app.routes` unwrapped — confirmed `APIWebSocketRoute` objects are NOT
    touched by `include_router()`, only routers passed to it are — so
    `/api/ws/prices` below still finds it via the old path.
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
            f"routes outside /api/v1 and outside the 3 named exceptions "
            f"(/api/health, /api/ai/*, /api/ws/*): {violations}"
        )

    def test_named_exceptions_actually_exist_and_are_reachable(self, client):
        """The 3 documented exceptions must be real, not just 'nothing violates
        the rule because nothing matches the exact path' (vacuous-pass guard)."""
        from main import app

        seen_prefixes = {"/api/ai/": False, "/api/health": False}
        for path, _methods in _iter_api_routes(app):
            if path == "/api/health":
                seen_prefixes["/api/health"] = True
            if path.startswith("/api/ai/"):
                seen_prefixes["/api/ai/"] = True
        assert seen_prefixes["/api/health"], "/api/health route missing entirely"
        assert seen_prefixes["/api/ai/"], "no /api/ai/* routes found"
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
            # bd:deps-2026-09 iter1 (Dave-discovered, not in Chris's/Quinn's
            # original reports) — was ("/api/v1/watchlists", "get"). With a
            # VALID authed user, GET /api/v1/watchlists legitimately returns
            # 200 {data:[],meta:...} (empty list for a fresh test user) —
            # not an error at all, so it can't belong in an "error body"
            # leak-marker check. It only ever produced >=400 here because
            # `auth_headers`/`client` bound to two DIFFERENT sqlite engines
            # pre-fix (missing StaticPool, CHRIS-04/Q-5): the minted JWT's
            # user row lived in a database `get_current_user`'s lookup could
            # never see, so every request 401'd regardless of token
            # validity — a false pass riding on the exact bug CHRIS-04/Q-5
            # fixed. Reproduced in isolation post-fix: `assert 200 >= 400`.
            # Replaced with the already-proven-erroring admin/403 case
            # doubled up via POST (no body -> 422) to keep 3 genuinely
            # erroring authed scenarios covering 3 different 4xx classes.
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
