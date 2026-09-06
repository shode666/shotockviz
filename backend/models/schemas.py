"""Pydantic schemas for request/response validation."""
from datetime import datetime, date
from datetime import date as _date_type  # noqa: F401 — see TransactionUpdate.date
from typing import Optional, List, Literal
from pydantic import BaseModel, ConfigDict, Field


# ─── Auth ──────────────────────────────────────────────────────────────────
# bd:deps-2026-09 S1 (ADR-007) — RegisterRequest, LoginRequest, RefreshRequest
# removed with their routes (POST /register, /login, /refresh, /logout).
# TokenResponse no longer carries refresh_token — /google issues an access
# token only (no server-side refresh lifecycle, CLAUDE.md rule 5).

class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"


class GoogleAuthRequest(BaseModel):
    credential: str  # Google ID token from frontend


class UserResponse(BaseModel):
    id: int
    email: str
    display_name: str
    role: str
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


# bd:features-2026-09 slice 3 — Sara spec §5. `pattern` matches Telegram
# chat id shape (int64, negative for groups); this is the ONE write path
# for `users.telegram_chat_id`, so it is the enforcement point for the
# numeric-shape invariant the DB CHECK (Postgres-only, see models/user.py
# deviation note) can't be mirrored for in SQLite tests.
class UserSettingsResponse(BaseModel):
    telegram_chat_id: Optional[str] = None

    model_config = ConfigDict(from_attributes=True)


class UserSettingsUpdate(BaseModel):
    telegram_chat_id: Optional[str] = Field(
        default=None, pattern=r"^-?\d{1,20}$"
    )


# ─── Stock ─────────────────────────────────────────────────────────────────

class StockSearchResult(BaseModel):
    symbol: str
    name: str
    name_th: Optional[str] = None
    market: str


class StockQuote(BaseModel):
    symbol: str
    price: float
    open: float
    high: float
    low: float
    prev_close: float
    change: float
    change_pct: float
    volume: int
    timestamp: datetime


class OHLCVBar(BaseModel):
    time: int | str  # Unix timestamp (seconds) for intraday; "YYYY-MM-DD" for daily+
    open: float
    high: float
    low: float
    close: float
    volume: int


class StockHistory(BaseModel):
    symbol: str
    timeframe: str
    bars: List[OHLCVBar]
    is_fund: bool = False  # True for Thai mutual funds — no chart data available


class StockFundamentals(BaseModel):
    symbol: str
    pe_ratio: Optional[float] = None
    pb_ratio: Optional[float] = None
    eps: Optional[float] = None
    dividend_yield: Optional[float] = None
    market_cap: Optional[float] = None
    beta: Optional[float] = None
    week_52_high: Optional[float] = None
    week_52_low: Optional[float] = None
    avg_volume: Optional[float] = None


# ─── Watchlist ─────────────────────────────────────────────────────────────

class WatchlistCreate(BaseModel):
    name: str


class WatchlistUpdate(BaseModel):
    name: Optional[str] = None
    sort_order: Optional[int] = None


class WatchlistItemAdd(BaseModel):
    symbol: str


class WatchlistItemOrder(BaseModel):
    symbol: str
    sort_order: int


class WatchlistReorderRequest(BaseModel):
    items: List[WatchlistItemOrder]


class WatchlistItemResponse(BaseModel):
    id: int
    symbol: str
    sort_order: int
    added_at: datetime
    # Enriched fields from live data
    price: Optional[float] = None
    change_pct: Optional[float] = None

    model_config = ConfigDict(from_attributes=True)


class WatchlistResponse(BaseModel):
    id: int
    name: str
    sort_order: int
    created_at: datetime
    items: List[WatchlistItemResponse] = []

    model_config = ConfigDict(from_attributes=True)


# ─── Portfolio ─────────────────────────────────────────────────────────────

# ── bd:shotockviz-ace — what a transaction's numbers are allowed to be ───────
# The spec question was "is qty=0 / price=0 a validation error?". F7's AC is an
# emptiness check, and `formValidation.ts` correctly treats the STRING "0" as
# non-empty; that is a different question from whether the VALUE is a legal
# transaction. Answered here, server-side, once, for all three numeric fields:
#
#   qty   > 0   A transaction of zero shares is not an event. A negative qty is
#               a DIRECTION, and direction is `type` (BUY/SELL) — allowing it
#               would let "BUY -10" act as a sell that bypasses every SELL-side
#               rule (realized P&L, sell-fee treatment, close detection).
#   price >= 0  ZERO IS LEGAL AND DELIBERATE. A bonus-share issue / stock
#               dividend / free warrant allotment really is acquired at 0, and a
#               SET book meets those. The consequence — `cost_basis` 0, so
#               `unrealized_pl_pct` is None — is the CORRECT answer (a return on
#               a zero cost basis is undefined, not infinite), not the bug; the
#               bug would be printing a percentage for it. Negative is never a
#               price.
#   fee   >= 0  A negative fee is a rebate, not a commission. Today it flows
#               straight into `cost_basis` on a BUY and LOWERS the trader's
#               stated breakeven, and inflates realized P&L on a SELL — money
#               invented by a minus sign. A genuine rebate belongs in its own
#               field or the note, not in the commission.
#
# `allow_inf_nan=False` on all three: `Field(gt=0)` already rejects NaN (every
# NaN comparison is False), but `inf` passes gt/ge and would poison cost basis,
# every total, and the equity curve. Non-finite money is not money.
#
# Frontend half (another agent — see hand-off): mirror qty>0 / price>=0 / fee>=0
# as inline field errors so the user is not told "422" by the server, and
# confirm a zero PRICE explicitly ("ราคา 0 — หุ้นปันผล/ได้รับแจก?") because it
# is legal but is far more often a typo.

class TransactionCreate(BaseModel):
    symbol: str
    type: str  # BUY or SELL
    qty: float = Field(gt=0, allow_inf_nan=False)
    price: float = Field(ge=0, allow_inf_nan=False)
    fee: float = Field(default=0.0, ge=0, allow_inf_nan=False)
    currency: str = "THB"  # THB or USD
    date: date
    note: Optional[str] = None
    # bd:shotockviz-fnn — THB per 1 unit of `currency` at the time of the trade.
    # Optional: leave it out and the server records the rate it can actually
    # observe *today* (and records nothing for a back-dated trade, rather than
    # stamping today's rate onto a trade from six months ago). Supply it when
    # you know the real fill rate — that is the only way a back-dated foreign
    # trade can ever report an FX return, since historical rates are not
    # backfilled.
    fx_rate: Optional[float] = Field(default=None, gt=0)


class TransactionUpdate(BaseModel):
    # bd:shotockviz-ace — same rule as TransactionCreate above. The edit route
    # writes qty/price/fee straight onto the row (`_ALLOWED_UPDATE_FIELDS`), so
    # an unvalidated PUT was a second door to exactly the values the POST is
    # about to start refusing. `Optional` means "not supplied"; a supplied value
    # is held to the same standard.
    qty: Optional[float] = Field(default=None, gt=0, allow_inf_nan=False)
    price: Optional[float] = Field(default=None, ge=0, allow_inf_nan=False)
    fee: Optional[float] = Field(default=None, ge=0, allow_inf_nan=False)
    currency: Optional[str] = None
    # bd:shotockviz-qml — the field name `date` shadows the `datetime.date`
    # import once a default is present: pydantic v2 resolves the annotation
    # via `vars(cls)` as localns, which now holds the class attribute `date`
    # (the FieldInfo/default), so `Optional[date]` resolved to
    # `Optional[NoneType]` instead of `Optional[datetime.date]` — every PUT
    # carrying a `date` key 422'd regardless of value. `TransactionCreate.date`
    # and `TransactionResponse.date` are unaffected: both are REQUIRED (no
    # `= None` default), so there is no class attribute named `date` to shadow
    # the import. Using the `_date_type` alias (imported once, module top)
    # only in the annotation — not renaming the field itself — keeps the wire
    # contract (`{"date": "..."}"`) and the attribute name (`.date`) identical;
    # only the name looked up during annotation resolution changes.
    date: Optional[_date_type] = None
    note: Optional[str] = None
    # Explicit correction only — never recomputed silently on any other edit.
    fx_rate: Optional[float] = Field(default=None, gt=0, allow_inf_nan=False)


class TransactionResponse(BaseModel):
    id: int
    symbol: str
    type: str
    qty: float
    price: float
    fee: float
    currency: str
    date: date
    note: Optional[str] = None
    created_at: datetime
    # None = no rate was recorded for this row (pre-existing or back-dated).
    fx_rate: Optional[float] = None

    model_config = ConfigDict(from_attributes=True)


class FxRateInfo(BaseModel):
    """Which rate was used, and how much it can be trusted (bd:shotockviz-fnn)."""
    currency: str
    base: str = "THB"
    rate: float
    source: str  # identity | live | last_known | fallback
    as_of: Optional[str] = None
    estimated: bool = False
    # bd:shotockviz-ss3 — "reciprocal" | "direct": which way up the live FX quote
    # arrived. None when the rate did not come from a quote. Present so the pair's
    # orientation can be READ off a live payload; it used to be a code comment.
    quote_orientation: Optional[str] = None


class HoldingResponse(BaseModel):
    symbol: str
    qty: float
    # None when `currency_conflict` — a cost basis summed across two currencies
    # is not a number and must not be printed as one (bd:shotockviz-7ju).
    avg_cost: Optional[float] = None
    currency: str = "THB"
    # bd:shotockviz-7ju — this symbol's transactions disagree on a currency.
    # Every money field on the row is None; the position is excluded from the
    # totals and named in PortfolioAnalytics.currency_conflict_symbols.
    currency_conflict: bool = False
    currencies: List[str] = []
    # bd:shotockviz-eb1 — `qty`/`avg_cost` were restated by a stock split and are
    # in TODAY's units, not the units on the original contract note. The raw
    # transaction rows are untouched (services/corporate_actions.py).
    split_adjusted: bool = False
    # A RIGHTS action exists for this symbol and nothing records whether the user
    # subscribed, so `qty` may be short of shares that were paid for. Reported,
    # never guessed — the position is still counted in the totals.
    rights_unstatable: bool = False
    current_price: Optional[float] = None
    current_value: Optional[float] = None
    unrealized_pl: Optional[float] = None
    unrealized_pl_pct: Optional[float] = None
    # ── base-currency view (bd:shotockviz-fnn / -sbe) ─────────────────────────
    base_currency: str = "THB"
    fx_rate: Optional[float] = None          # current rate used for the value
    fx_source: Optional[str] = None
    fx_estimated: bool = False
    cost_basis_base: Optional[float] = None
    # identity = same currency as the book; historical = every lot converted at
    # its own recorded rate; current_rate = at least one lot had no recorded
    # rate, so cost was converted at today's rate and fx_pl is unknowable.
    cost_basis_source: Optional[str] = None
    current_value_base: Optional[float] = None
    unrealized_pl_base: Optional[float] = None
    unrealized_pl_pct_base: Optional[float] = None
    market_pl_base: Optional[float] = None
    fx_pl_base: Optional[float] = None       # None = unavailable, NOT zero


class AllocationSliceResponse(BaseModel):
    """One name's share of the stated total (bd:shotockviz-916, FR-PORT-002)."""
    symbol: str
    currency: str = "THB"
    # The slice's AREA. `sum(value_base)` equals `PortfolioAllocation.total_value`
    # exactly, so a renderer that draws arcs from this cannot close short.
    value_base: float
    weight_pct: float  # for labels; geometry should use value_base
    split_adjusted: bool = False
    rights_unstatable: bool = False


class AllocationExclusionResponse(BaseModel):
    """A position with NO slice, and why — never a 0% wedge."""
    symbol: str
    # unpriced | fx_unavailable | currency_conflict | unstatable
    reason: str


class PortfolioAllocation(BaseModel):
    """% allocation — FR-PORT-002 (bd:shotockviz-916).

    `total_value` IS the denominator and is the same number as
    `PortfolioAnalytics.total_value`: the base-currency market value of the
    positions that entered the totals. Everything the totals excluded (rules
    2/4/5 in services/portfolio_service.py) is in `excluded` with its reason and
    has no slice — a position whose value is unknown has no honest area, and a
    0% wedge would read as "this name is worth nothing".
    """
    basis: str = "current_value_base"  # shares of market value, not of cost
    base_currency: str = "THB"
    total_value: float = 0.0
    slices: List[AllocationSliceResponse] = []
    excluded: List[AllocationExclusionResponse] = []
    fx_estimated: bool = False


class PortfolioAnalytics(BaseModel):
    # bd:shotockviz-sbe — these four are now unambiguously in `base_currency`.
    # They used to be a raw sum of THB and USD amounts.
    base_currency: str = "THB"
    total_value: float
    total_cost: float
    unrealized_pl: float
    unrealized_pl_pct: float
    # unrealized_pl == market_pl + fx_pl whenever fx_pl is not None.
    market_pl: Optional[float] = None
    fx_pl: Optional[float] = None
    fx_estimated: bool = False          # a rate in use is not a live quote
    cost_basis_estimated: bool = False  # some cost converted at today's rate
    fx_rates: List[FxRateInfo] = []
    fx_unavailable_symbols: List[str] = []
    # bd:shotockviz-7ju — symbols excluded because their own rows mix currencies.
    currency_conflict_symbols: List[str] = []
    # bd:shotockviz-eb1 — restated for a split (still INCLUDED in the totals: the
    # restatement is what makes them right) / share count possibly short because
    # a rights subscription is not recorded (also included).
    split_adjusted_symbols: List[str] = []
    rights_unstatable_symbols: List[str] = []
    day_change: Optional[float] = None
    holdings: List[HoldingResponse]
    has_pending_prices: bool = False
    # bd:shotockviz-916 / FR-PORT-002 — the same book, split by weight. Its
    # denominator is `total_value` above; see PortfolioAllocation.
    allocation: Optional[PortfolioAllocation] = None
    # ── realized side (bd:shotockviz-tmz) ─────────────────────────────────────
    # Summary only, in `base_currency`. The per-trade log lives on
    # GET /portfolio/realized so this hot path does not grow with the user's
    # trade history. Cost flow is MOVING WEIGHTED AVERAGE — see
    # services/portfolio_service.py rule 6.
    # None (not 0.0) whenever nothing convertible has been realized: 0 would
    # claim the closed trades made nothing.
    realized_pl: Optional[float] = None          # every sale, incl. scale-outs
    realized_fees: Optional[float] = None        # sell commission inside the above
    closed_positions_pl: Optional[float] = None  # completed round trips only
    total_trades: int = 0                        # completed round trips
    win_rate: Optional[float] = None             # % of round trips with base P&L > 0
    profit_factor: Optional[float] = None        # None when there is no loss yet
    # Symbols whose disposals cannot be converted to base (no rate at disposal,
    # or the position was not FX-complete when sold) — excluded, not zeroed.
    realized_unavailable_symbols: List[str] = []


class ClosedPositionResponse(BaseModel):
    """One completed round trip — flat → position → flat (bd:shotockviz-tmz)."""
    symbol: str
    currency: str = "THB"
    base_currency: str = "THB"
    qty: float
    opened_on: Optional[date] = None
    closed_on: Optional[date] = None
    holding_days: Optional[int] = None
    # Weighted-average cost released by this trip, INCLUDING the capitalised buy
    # commission — the real breakeven, not the screen price.
    entry_price: float
    # Weighted-average sale price, GROSS of the sell fee (which is in `fees` and
    # is already subtracted from realized_pl).
    exit_price: float
    fees: float
    realized_pl: float                       # native currency
    realized_pl_pct: Optional[float] = None  # None on a zero-cost trip
    realized_pl_base: Optional[float] = None  # None = not convertible, NOT zero
    sales: int = 1                           # SELL rows that closed it


class RealizedBookResponse(BaseModel):
    """GET /portfolio/realized — the closed-trade record (bd:shotockviz-tmz)."""
    base_currency: str = "THB"
    cost_flow: str = "moving_average"   # stated, not implied — see rule 6
    realized_pl: Optional[float] = None
    realized_fees: Optional[float] = None
    closed_positions_pl: Optional[float] = None
    total_trades: int = 0
    wins: int = 0
    losses: int = 0
    scratches: int = 0                  # exactly 0.0 — in the denominator only
    win_rate: Optional[float] = None
    profit_factor: Optional[float] = None
    closed_positions: List[ClosedPositionResponse] = []
    realized_unavailable_symbols: List[str] = []
    currency_conflict_symbols: List[str] = []
    # More was sold than the book records buying — the realized figure for these
    # is overstated by the cost of the shares it has no record of.
    oversold_symbols: List[str] = []


# ─── Alert ─────────────────────────────────────────────────────────────────

class AlertCreate(BaseModel):
    symbol: str
    alert_type: str
    condition: str
    value: Optional[float] = None
    channel: str = "TELEGRAM"


class AlertUpdate(BaseModel):
    condition: Optional[str] = None
    value: Optional[float] = None
    channel: Optional[str] = None


class AlertResponse(BaseModel):
    id: int
    symbol: str
    alert_type: str
    condition: str
    value: Optional[float] = None
    is_active: bool
    status: str
    channel: str
    triggered_at: Optional[datetime] = None
    created_at: datetime
    # bd:shotockviz-eb1 — the date `value` was last written, i.e. the trading
    # units the level is stated in. Surfaced so a level that has been rebased by
    # a split is readable as such off the API instead of looking like the user
    # mistyped it. NULL on a legacy row whose units could not be established.
    value_as_of: Optional[date] = None

    model_config = ConfigDict(from_attributes=True)


# ─── Drawing ───────────────────────────────────────────────────────────────

class DrawingCreate(BaseModel):
    tool_type: str
    data_json: dict
    style_json: dict


class DrawingUpdate(BaseModel):
    data_json: Optional[dict] = None
    style_json: Optional[dict] = None


class DrawingResponse(BaseModel):
    id: int
    symbol: str
    timeframe: str
    tool_type: str
    data_json: dict
    style_json: dict
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


# ─── SR Level ──────────────────────────────────────────────────────────────
# bd:features-2026-09 slice 2 — GET-only response schema for sr_levels
# (models/sr_level.py). All 3 sources (manual_import/auto_pivot/user_created)
# are returned, not just manual_import — future-proofs the endpoint for
# slice-3 auto-pivot/user-drawn rows without another schema/endpoint change.

class SRLevelResponse(BaseModel):
    id: int
    symbol: str
    price: float
    level_type: str
    tag: Optional[str] = None
    color: Optional[str] = None
    source: str

    model_config = ConfigDict(from_attributes=True)


# bd:shotockviz-474 — request body for POST /sr-levels/{symbol}. `source` and
# `user_id` are deliberately NOT accepted from the client — the route sets
# `source="user_created"` and `user_id=<caller>` itself (see sr_levels.py),
# so a caller can never mint a `manual_import`/`auto_pivot` row or attribute
# a level to someone else. `color` is also not accepted here: user-created
# rows get color=None and fall through to srLevelColor.ts's by-type fallback,
# same as every other un-colored row — no per-row color picker in scope.
class SRLevelCreate(BaseModel):
    price: float = Field(gt=0)
    level_type: Literal["support", "resistance"]
    tag: Optional[str] = Field(default=None, max_length=50)


# ─── News ──────────────────────────────────────────────────────────────────

class NewsItem(BaseModel):
    title: str
    url: str
    source: str
    published_at: Optional[datetime] = None
    summary: Optional[str] = None
    sentiment: Optional[str] = None  # positive, negative, neutral
    related_symbols: List[str] = []
