"""
bd:deps-2026-09 Phase 3b (Chris, adversarial review) — S-AC-3 / S-AC-4 /
AC-B6 regression tests for `api/middleware/rate_limit.py`.

Zero rate-limit tests existed before this file (confirmed:
`grep -rln "rate_limit\\|429\\|RateLimit" tests/api backend/tests` -> no
matches; Bella's own RTM (02-bella-brd-ac.md §5, row B6) flags this as
"NEW (no existing rate-limit test found)").

Two CONFIRMED bugs reproduced here (own-run evidence, `outputs/deps-2026-09/
14-chris-review.md` findings CHRIS-02 / CHRIS-03):

  CHRIS-02 (High): the 6th rate-limited request does NOT return the
  documented 429 {data,meta} envelope. `HTTPException(429)` is raised
  inside `RateLimitMiddleware.dispatch` — a `BaseHTTPMiddleware` — which
  sits OUTSIDE Starlette's `ExceptionMiddleware` in the ASGI stack. The
  exception propagates past both `install_error_envelope`'s handlers and
  FastAPI's own defaults straight to `ServerErrorMiddleware`, which
  returns a raw, non-JSON `500 Internal Server Error` (verified live via
  curl against a running uvicorn instance — see review report). This
  breaks AC-B6 (429 with envelope) and the frontend's
  `body.meta.error.message` parser (frontend/src/services/api.ts:95),
  which would get `body` as a *string*, not an object, on this path.

  CHRIS-03 (High): `_client_ip()` (rate_limit.py:28-43) trusts the FIRST
  X-Forwarded-For value unconditionally, without validating that the
  request actually arrived via a trusted hop (Caddy). Confirmed live via
  curl with `-H "X-Forwarded-For: <fake>"` directly against the backend
  (as would happen if the backend port is ever reachable without Caddy in
  front, e.g. `docker-compose.dev.yml:76 "8000:8000"`).

These tests assert the CORRECT, spec'd behavior (S-AC-3/S-AC-4/AC-B6) and
are therefore EXPECTED TO FAIL until Dave fixes the two bugs above.
"""
import pytest


LOGIN_PATH = "/api/v1/auth/google"


def _hit(client, xff: str | None):
    headers = {"Content-Type": "application/json"}
    if xff is not None:
        headers["X-Forwarded-For"] = xff
    return client.post(LOGIN_PATH, json={"credential": "not-a-real-token"}, headers=headers)


class TestRateLimitEnvelope:
    def test_sixth_attempt_from_same_ip_returns_429_with_envelope(self, client):
        """S-AC-3 / AC-B6: 6th attempt in the window -> 429, enveloped
        JSON body, NOT a bare 500."""
        xff = "203.0.113.50"  # TEST-NET-3, RFC 5737 — won't collide with other tests
        responses = [_hit(client, xff) for _ in range(6)]
        sixth = responses[-1]

        assert sixth.status_code == 429, (
            f"expected 429 on the 6th attempt, got {sixth.status_code} "
            f"body={sixth.text!r} — CHRIS-02: middleware-raised HTTPException "
            f"bypasses ExceptionMiddleware, becomes an unhandled 500"
        )
        assert sixth.headers.get("content-type", "").startswith("application/json"), (
            f"429 body is not JSON: content-type={sixth.headers.get('content-type')!r} "
            f"body={sixth.text!r}"
        )
        body = sixth.json()
        assert body["data"] is None
        assert "meta" in body and "error" in body["meta"]


class TestRateLimitKeyingNotSpoofable:
    def test_distinct_spoofed_xff_per_request_still_gets_rate_limited(self, client):
        """S-AC-4: a caller that varies X-Forwarded-For on every request
        (bypassing Caddy, or hitting the backend directly — the dev compose
        exposes 8000:8000) must NOT get a fresh rate-limit bucket every
        time. Real defense = only trust XFF when the connection's actual
        peer is a known/trusted proxy hop; this repo has no such check."""
        responses = [_hit(client, f"198.51.100.{i}") for i in range(1, 7)]
        sixth = responses[-1]
        assert sixth.status_code == 429, (
            f"expected the 6th request to still be blocked (real attacker, "
            f"forged X-Forwarded-For) but got {sixth.status_code} — "
            f"CHRIS-03: rate_limit.py._client_ip() trusts client-supplied "
            f"X-Forwarded-For unconditionally, giving every spoofed value "
            f"its own bucket (AB-2/AB-6 bypass)"
        )
