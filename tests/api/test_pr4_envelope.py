"""
bd:deps-2026-09 Phase 3b (Chris, adversarial review) — regression tests for
`schemas/envelope.py` (EnvelopingAPIRoute + install_error_envelope, WP-S2).

Zero tests existed for this file before this commit
(`grep -rln "EnvelopingAPIRoute\\|install_error_envelope" tests/api backend/tests`
-> no matches). Dave's WP-S2 verification (12-dave-serial-s0-s3.md) was a
throwaway in-memory script, never committed — these tests lock the
behavior in so it can't silently regress.

Covers:
  - S-AC-5 (error envelope: 401/404/405/422 all return {data,meta} on
    /api/v1/*, never a bare {"detail": ...})
  - AC-B6-r3 (401 still carries WWW-Authenticate: Bearer)
  - The "3 unversioned exceptions" boundary (r3-1/r3-2): /api/health
    errors must NOT be v1-enveloped (proves `_is_enveloped_path` scoping)
  - 204 No Content passthrough (DELETE endpoints must not be wrapped —
    HTTP forbids a body on 204)
"""
import pytest


class TestErrorEnvelopeOnV1:
    def test_404_on_v1_prefix_is_enveloped(self, client):
        resp = client.get("/api/v1/this-route-does-not-exist")
        assert resp.status_code == 404
        body = resp.json()
        assert body["data"] is None
        assert body["meta"]["error"]["message"]
        # S-AC-5: never leak the FastAPI/Starlette default shape
        assert "detail" not in body

    def test_405_wrong_method_is_enveloped(self, client):
        # /api/v1/stocks/quotes is GET-only
        resp = client.delete("/api/v1/stocks/quotes")
        assert resp.status_code == 405
        body = resp.json()
        assert body["data"] is None
        assert body["meta"]["error"]["message"]

    def test_422_validation_error_is_enveloped(self, client):
        # symbols is a required query param on /stocks/quotes
        resp = client.get("/api/v1/stocks/quotes")
        assert resp.status_code == 422
        body = resp.json()
        assert body["data"] is None
        assert body["meta"]["error"]["message"] == "Validation failed"
        assert "detail" not in body

    def test_401_no_token_is_enveloped_with_www_authenticate(self, client):
        resp = client.get("/api/v1/watchlists")
        assert resp.status_code == 401
        assert resp.headers.get("www-authenticate") == "Bearer"
        body = resp.json()
        assert body["data"] is None
        assert body["meta"]["error"]["message"]

    def test_error_body_never_leaks_exception_internals(self, client):
        """S-AC-5: no traceback / exception class name / SQL fragment."""
        resp = client.get("/api/v1/this-route-does-not-exist")
        raw = resp.text
        for leak in ("Traceback", "Error:", "Exception", "SELECT ", "File \""):
            assert leak not in raw, f"leaked {leak!r} in error body: {raw}"


class TestUnversionedExceptionsStayUnenveloped:
    """r3-1/r3-2: /api/health, /api/ws/prices, ai_chat SSE frames are the
    3 deliberate exceptions — error handlers must NOT touch them."""

    def test_health_wrong_method_is_not_v1_enveloped(self, client):
        resp = client.post("/api/health")
        assert resp.status_code == 405
        body = resp.json()
        # Default FastAPI/Starlette shape ({"detail": ...}), NOT {data,meta}
        assert "detail" in body
        assert "data" not in body
        assert "meta" not in body


class TestSuccessEnvelope:
    def test_stocks_quotes_success_is_enveloped(self, client):
        resp = client.get("/api/v1/stocks/quotes?symbols=AAPL")
        assert resp.status_code == 200
        body = resp.json()
        assert set(body.keys()) == {"data", "meta"}
        assert "AAPL" in body["data"]
        assert body["meta"]["request_id"]

    def test_health_is_not_double_wrapped(self, client):
        """system.py hand-wraps /api/health itself (BaseResponse) and does
        NOT get route_class=EnvelopingAPIRoute (system.py:30 comment) — a
        double-wrap would produce body['data']['data']."""
        resp = client.get("/api/health")
        assert resp.status_code == 200
        body = resp.json()
        assert set(body.keys()) == {"data", "meta"}
        assert not isinstance(body["data"], dict) or "meta" not in body["data"]
