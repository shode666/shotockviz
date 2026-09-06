"""bd:shotockviz-649.1 — "concentration limit is client-remembered only — no
server-side per-user setting".

bd:shotockviz-649 shipped `GET /portfolio/analytics?concentration_limit_pct=`
with the client (localStorage) as the only place the trader's choice
survived a reload; falling back to DEFAULT_CONCENTRATION_LIMIT_PCT whenever
no query param arrived, with no way to tell "chose 25%" from "cleared site
data". This closes that gap: `users.concentration_limit_pct`
(models/user.py, migration 20260906_0011) plus `PATCH /settings/trader`
(api/routes/settings.py) as its sole write path.

Under test:
  1. The route's THREE-WAY precedence (query param > saved column > default),
     not just "does the default still work" (test_649_concentration_limit.py
     already covers that half).
  2. A query-param override never mutates the saved column — "preview
     without saving" must stay a preview.
  3. PATCH /settings/trader actually persists, GET reads it back, and a
     PATCH that only mentions one field never clobbers the other (the
     `model_fields_set` partial-update contract — the concrete regression
     this proves is a second setting silently disappearing under a save
     from an unrelated form).
  4. Explicit `null` clears a previously-chosen value back to "unset" —
     verified via `user.concentration_limit_pct is None`, not merely "the
     response looked empty", since the whole point is column-level
     unset-vs-chosen state.
  5. Out-of-range values still 422 at this route the same as the analytics
     route already does (rule 1 — one bounds definition, two enforcement
     points, same constants).
"""
from unittest.mock import AsyncMock, patch

import pytest
from fastapi import HTTPException

from api.routes.portfolio import get_analytics
from api.routes.settings import get_trader_settings, update_trader_settings
from models.schemas import TraderSettingsUpdate
from services import portfolio_service as ps
from tests.test_portfolio_valuation import _FakeRedis, _no_corporate_actions, _redis_store


async def _one_ptt_holding(test_db, test_user):
    """Same one-position book as test_649_concentration_limit.py's route
    tests: 100% of book, so ANY sane limit below 100 is a breach — the
    exact limit that carried through is what's under test, not the math."""
    from datetime import date
    from models.portfolio import Transaction, TransactionType

    test_db.add(Transaction(
        user_id=test_user.id, symbol="PTT.BK", type=TransactionType.BUY,
        qty=1000, price=30.0, fee=0.0, date=date(2024, 1, 1),
    ))
    await test_db.flush()
    return _redis_store({"PTT.BK": {"symbol": "PTT.BK", "price": 40.0}})


# ─────────────────────────────────────────────────────────────────────────────
# GET /portfolio/analytics — three-way precedence
# ─────────────────────────────────────────────────────────────────────────────

async def test_saved_column_is_used_when_no_query_param_is_given(test_db, test_user):
    """RED against the old code: before this bd, `user.concentration_limit_pct`
    did not exist as a column at all, so this test could not even construct
    its fixture — AttributeError on `test_user.concentration_limit_pct = 10.0`.
    After the model change but before the route change, the route ignored the
    column entirely and always fell back to DEFAULT (25.0) whenever the query
    param was omitted — this test would still fail, asserting 10.0 got 25.0."""
    store = await _one_ptt_holding(test_db, test_user)
    test_user.concentration_limit_pct = 10.0
    await test_db.flush()

    with patch("services.stock_service.get_redis", AsyncMock(return_value=_FakeRedis(store))), \
         patch("services.stock_service.request_data_fetch", AsyncMock()), \
         _no_corporate_actions():
        analytics = await get_analytics(user=test_user, db=test_db)

    assert analytics.concentration.limit_pct == 10.0


async def test_default_still_applies_when_column_is_unset(test_db, test_user):
    """The trader has genuinely never set one (column is NULL, its actual
    initial state) — DEFAULT applies, same as bd:shotockviz-649 always did."""
    store = await _one_ptt_holding(test_db, test_user)
    assert test_user.concentration_limit_pct is None  # the fixture default

    with patch("services.stock_service.get_redis", AsyncMock(return_value=_FakeRedis(store))), \
         patch("services.stock_service.request_data_fetch", AsyncMock()), \
         _no_corporate_actions():
        analytics = await get_analytics(user=test_user, db=test_db)

    assert analytics.concentration.limit_pct == ps.DEFAULT_CONCENTRATION_LIMIT_PCT


async def test_query_param_overrides_the_saved_column_without_persisting_it(test_db, test_user):
    """RED against a naive 'query param wins, and while we're at it save it'
    implementation: this proves the override is read-only. If the route ever
    started writing `concentration_limit_pct` back onto `user` from the query
    param, the second assertion (`== 10.0`, not `== 50.0`) would fail."""
    store = await _one_ptt_holding(test_db, test_user)
    test_user.concentration_limit_pct = 10.0
    await test_db.flush()

    with patch("services.stock_service.get_redis", AsyncMock(return_value=_FakeRedis(store))), \
         patch("services.stock_service.request_data_fetch", AsyncMock()), \
         _no_corporate_actions():
        analytics = await get_analytics(user=test_user, db=test_db, concentration_limit_pct=50.0)

    assert analytics.concentration.limit_pct == 50.0
    assert test_user.concentration_limit_pct == 10.0  # untouched by the override


# ─────────────────────────────────────────────────────────────────────────────
# PATCH/GET /settings/trader
# ─────────────────────────────────────────────────────────────────────────────

async def test_patch_persists_and_get_reads_it_back(test_db, test_user):
    await update_trader_settings(
        TraderSettingsUpdate(concentration_limit_pct=42.0), user=test_user, db=test_db,
    )
    assert test_user.concentration_limit_pct == 42.0

    resp = await get_trader_settings(user=test_user)
    assert resp.concentration_limit_pct == 42.0


async def test_patching_one_field_leaves_the_other_untouched(test_db, test_user):
    """RED against a naive '`user.x = body.x; user.y = body.y`, always'
    handler: saving the concentration limit alone would silently null out
    an already-set gap threshold (or vice versa). Proves the two settings
    genuinely update independently through the SAME endpoint."""
    await update_trader_settings(
        TraderSettingsUpdate(concentration_limit_pct=30.0, gap_min_pct=2.0),
        user=test_user, db=test_db,
    )
    assert (test_user.concentration_limit_pct, test_user.gap_min_pct) == (30.0, 2.0)

    # Only concentration_limit_pct is present in this second body.
    await update_trader_settings(
        TraderSettingsUpdate(concentration_limit_pct=40.0), user=test_user, db=test_db,
    )
    assert test_user.concentration_limit_pct == 40.0
    assert test_user.gap_min_pct == 2.0  # untouched


async def test_explicit_null_clears_a_previously_chosen_value(test_db, test_user):
    """RED against a handler that treats `None` as 'no change' instead of
    'clear it': the acceptance criteria's own wording ('do not leave it
    ambiguous') is exactly this case — the trader must be able to go back
    to 'unset' on purpose, not just to another number."""
    await update_trader_settings(
        TraderSettingsUpdate(gap_min_pct=2.0), user=test_user, db=test_db,
    )
    assert test_user.gap_min_pct == 2.0

    await update_trader_settings(
        TraderSettingsUpdate(gap_min_pct=None), user=test_user, db=test_db,
    )
    assert test_user.gap_min_pct is None


async def test_patch_422s_on_an_out_of_range_concentration_limit(test_db, test_user):
    with pytest.raises(HTTPException) as exc_info:
        await update_trader_settings(
            TraderSettingsUpdate(concentration_limit_pct=150.0), user=test_user, db=test_db,
        )
    assert exc_info.value.status_code == 422
    # Rejected value must never reach the ORM object.
    assert test_user.concentration_limit_pct is None


async def test_patch_422s_on_an_out_of_range_gap_min_pct(test_db, test_user):
    with pytest.raises(HTTPException) as exc_info:
        await update_trader_settings(
            TraderSettingsUpdate(gap_min_pct=0.0), user=test_user, db=test_db,
        )
    assert exc_info.value.status_code == 422
    assert test_user.gap_min_pct is None

    with pytest.raises(HTTPException):
        await update_trader_settings(
            TraderSettingsUpdate(gap_min_pct=999.0), user=test_user, db=test_db,
        )
