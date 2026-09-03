"""
bd:deps-2026-09 Phase 3b (Chris, adversarial review) — ADR-004 pagination
meta regression test for `GET /api/v1/stocks/{symbol}/earnings`.

Zero pagination tests existed before this file (confirmed: `grep -rln
"pagination\\|request.state.pagination" tests/api backend/tests` -> no
matches). This is the ONE list endpoint that opted into
`request.state.pagination` (schemas/envelope.py) per Dave's WP-S2 open
item #4 (12-dave-serial-s0-s3.md) — locking it in so the
opt-in mechanism doesn't silently break for the only current adopter.

Uses the real Redis instance (REDIS_URL) directly to seed the
`earnings:{symbol}` cache key the handler reads first
(api/routes/stocks/fundamentals.py:136-144) — avoids the Postgres
fallback path entirely (keeps this a fast, deterministic unit test, and
sidesteps the cross-event-loop test-infra bug documented in
14-chris-review.md finding CHRIS-01/CHRIS-04, which affects the
Postgres-backed `client`/`db_session` fixtures for tests that need real
async ORM round-trips).
"""
import json
import os

import pytest
import redis as redis_sync

TEST_SYMBOL = "ZZZCHRISTEST"
CACHE_KEY = f"earnings:{TEST_SYMBOL}"


@pytest.fixture
def seeded_earnings_cache():
    """Directly seed + clean up the redis cache key the handler reads."""
    r = redis_sync.from_url(os.environ["REDIS_URL"], decode_responses=True)
    events = [
        {"report_date": f"2026-0{i}-01", "eps_actual": 1.0 + i, "eps_estimate": 1.0}
        for i in range(1, 6)  # 5 events total
    ]
    r.set(CACHE_KEY, json.dumps(events), ex=60)
    yield events
    r.delete(CACHE_KEY)


class TestEarningsPaginationMeta:
    def test_pagination_meta_reflects_requested_window(self, client, seeded_earnings_cache):
        resp = client.get(f"/api/v1/stocks/{TEST_SYMBOL}/earnings?limit=2&offset=1")
        assert resp.status_code == 200, resp.text
        body = resp.json()

        assert body["meta"]["total"] == 5
        assert body["meta"]["limit"] == 2
        assert body["meta"]["offset"] == 1
        # sliced correctly: events[1:3]
        assert len(body["data"]["earnings"]) == 2
        assert body["data"]["earnings"][0]["eps_actual"] == seeded_earnings_cache[1]["eps_actual"]

    def test_default_pagination_is_first_8(self, client, seeded_earnings_cache):
        resp = client.get(f"/api/v1/stocks/{TEST_SYMBOL}/earnings")
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["meta"]["total"] == 5
        assert body["meta"]["limit"] == 8
        assert body["meta"]["offset"] == 0
        assert len(body["data"]["earnings"]) == 5  # only 5 exist, capped by total


class TestNonPaginatedEndpointsLeaveMetaNull:
    def test_watchlists_list_has_no_pagination_meta(self, client):
        """ADR-004: additive/optional — endpoints that don't opt in must
        leave total/limit/offset as None, not 0 or some other falsy-but-
        wrong sentinel."""
        resp = client.get("/api/v1/watchlists")
        # unauthenticated -> 401, but the envelope shape (meta present,
        # pagination fields null) must hold even on the error path
        assert resp.status_code == 401
        meta = resp.json()["meta"]
        assert meta.get("total") is None
        assert meta.get("limit") is None
        assert meta.get("offset") is None
