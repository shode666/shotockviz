"""Shared holdings + valuation computation for the portfolio book.

Single source of truth for BOTH `api/routes/portfolio.py` (`/portfolio/analytics`)
and `api/routes/dashboard.py` (`_build_portfolio_summary`). Before this module the
two routes each rebuilt the same book with different rules and disagreed on the
same instant — bd:shotockviz-msg (Tara, outputs/backlog-2026-09/10-tara-value.md N4).

Accounting rules pinned here (state them once, apply everywhere):

1. bd:shotockviz-fww — commission.
   BUY : the fee is capitalised into cost basis  -> cost += qty*price + fee,
         so `avg_cost` is the trader's real breakeven price.
   SELL: the fee reduces *proceeds*, i.e. it belongs to REALIZED P&L, not to the
         cost basis of the shares still held. It is accumulated on
         `Holding.realized_fees` and deliberately NOT folded into the open
         position — charging a closed lot's cost to the remaining shares would
         distort avg cost. Realized P&L itself is not reported by this product
         yet (Tara N9, separate bead); `realized_fees` is the hook for it.
   Cost basis removed on a SELL is `qty_sold * avg_cost` (weighted average,
   avg taken BEFORE the qty is reduced) — unchanged from the previous code.

2. bd:shotockviz-2w8 — a position with no usable quote is excluded from BOTH
   sides of the total (see `summarize`). It is never valued at zero, because a
   zero valuation against a full cost basis fabricates a loss equal to the whole
   position — the normal state for a Thai book after 16:30 ICT, i.e. exactly
   when the user looks. Unpriced positions are still returned as rows (with
   `current_price=None`) and listed in `PortfolioTotals.unpriced_symbols` so the
   caller can flag "price unavailable".

3. A quote counts as usable only when `price is not None and price > 0`
   (`usable_price`). A quote of exactly 0.0 is bad data, not a market price;
   treating it as real is the same fabricated-loss failure mode as (2).
   Note this is a *deliberate* test, not the old truthiness test — `if price:`
   and `if current_value:` also swallowed legitimate zero values.

4. bd:shotockviz-fnn / bd:shotockviz-sbe — FX. The book has ONE base currency
   (`BASE_CURRENCY` = THB); every total this module produces is in that base.
   Adding THB and USD raw (what `/portfolio/analytics` used to do) is not a
   rounding problem, it is a meaningless number.

   FX-1 rate capture. A transaction may carry `fx_rate` = units of base per 1
   unit of its own currency, observed when the trade was recorded
   (`api/routes/portfolio.py::add_transaction`). For a base-currency
   transaction the rate is 1.0 *by definition* and is never read off the
   market — so the entire existing THB book is FX-complete without a backfill.
   A non-base transaction with no stored rate stays FX-incomplete forever: the
   user's decision is that historical rates are NOT backfilled, and inventing
   one is the same class of bug as the 33.0 constant this bead removes.

   FX-2 conversion. Value is always converted at the CURRENT rate. Cost is
   converted at the rate stored per transaction when every open lot of that
   position has one (`Holding.fx_complete`), which is what makes the currency
   component separable:

       value_n·Rc − Σ(cost_i·R_i) = (value_n − cost_n)·Rc + Σ cost_i·(Rc − R_i)
                                    └── market component ──┘ └── FX component ──┘

   When a lot has no stored rate we fall back to converting cost at the current
   rate (the old behaviour, which structurally hides FX return) and say so:
   `cost_basis_source = "current_rate"` and `fx_pl_base = None`. Never 0.0 —
   zero is a claim that the currency did not move, and we do not know that.

   FX-3 no silent constant. A rate that is not `live` is marked `estimated`
   everywhere it is used, and the fallback chain is explicit:
   live quote → the user's own last recorded rate → `FX_FALLBACK_RATES`.
   A live quote outside `FX_PLAUSIBLE_RANGE` is treated as bad data, not as a
   rate — inverting a mis-quoted pair silently scales the whole US book by 1000.

   FX-4 bd:shotockviz-ss3 — the quote's ORIENTATION is derived, not assumed.
   Which way up `THBUSD=X` arrives ("1 THB in USD" ≈ 0.03, or "THB per USD"
   ≈ 33) used to be asserted by a code comment alone and the code took the
   reciprocal unconditionally. `read_fx_quote` instead picks whichever of
   {p, 1/p} lands inside `FX_PLAUSIBLE_RANGE` and reports which one it used
   (`FxRate.quote_orientation`, surfaced in the API payload). Exactly one can
   land there, because the band lies strictly above 1.0 — the invariant
   `_check_band_invariant` enforces at import. Neither landing = bad data =
   no rate. The code is therefore correct under either Yahoo convention, and
   the payload states the convention actually observed instead of a comment
   claiming it.

5. bd:shotockviz-7ju — one symbol, one currency. A position's cost basis is a
   sum of native amounts, so it is only a number if every transaction for that
   symbol is in the same currency. The old fold took the currency from the
   FIRST transaction and silently added the rest on top, mixing THB and USD
   into a single `cost_basis` that the FX conversion then inherited.
   Write path (`api/routes/portfolio.py`) now REJECTS a transaction whose
   currency disagrees with the symbol's existing rows (409). Read path keeps
   working for legacy rows already in that state, but loudly: the position is
   flagged `currency_conflict`, is never priced, never valued, and is excluded
   from both sides of the total and named in
   `PortfolioTotals.currency_conflict_symbols` — the same doctrine as rule 2
   and rule 4's `fx_unavailable_symbols`. A conflict is judged over ALL rows of
   the symbol, including fully-closed lots: for legacy data we cannot tell a
   deliberate re-denomination from a mis-entry, and the write path makes the
   same judgement, so the two paths cannot disagree. The fix for a genuine
   re-denomination is to correct the old rows.

6. bd:shotockviz-tmz — REALIZED P&L, and the cost-flow rule behind it.

   COST FLOW = MOVING WEIGHTED AVERAGE COST. Not FIFO, not specific-lot.
   A SELL releases `qty_sold * avg_cost`, where `avg_cost` is taken BEFORE the
   quantity is reduced — i.e. exactly the number rule 1 already removes from the
   open position. Three reasons, in order of weight:

     a) The open side has folded on weighted average since bd:shotockviz-msg.
        Realizing on FIFO while carrying the remainder at average cost means the
        two halves of the same book are kept on two different cost flows: the
        cost released and the cost still held would no longer add up to the cost
        put in, and "realized + unrealized" would stop reconciling to anything.
        One book, one cost flow.

     b) The data cannot support FIFO honestly. `transactions.date` is a DATE
        (`models/portfolio.py:59`), there is no lot identifier, and the read
        paths order by `date` alone — so two trades on the same day have no
        defined sequence and a FIFO answer would depend on the row order
        Postgres happened to return. Average cost is unaffected by the ordering
        of same-day BUYs, so it gives the same number every time it is asked.
        Inventing a lot sequence the ledger does not record is the same class of
        move as inventing an FX rate (rule 4 / FX-1).

     c) It is what this user's book means. This is a swing/position trader's own
        record, used to judge trades — not a filing. ⚠️ General guidance from
        training memory (not source-verified): tax lot-relief rules differ by
        jurisdiction (e.g. US brokers commonly default to FIFO with
        specific-identification available), so these numbers must NOT be treated
        as tax output — validate with a Thai tax adviser / the user's broker
        statements before any filing use.

   What a realized number contains:
     realized_pl = proceeds − cost_released − sell_fee
                 = qty*price − qty*avg_cost_before − fee
   The BUY commission is already inside `avg_cost` (rule 1), so it reaches P&L
   when the shares are sold; the SELL commission is charged here, which is what
   `Holding.realized_fees` was parked for by bd:shotockviz-fww.

   GRAIN. Two, deliberately:
     * `RealizedSale` — one per SELL row. The ledger truth; every satang of
       realized money is in exactly one of these.
     * `ClosedTrade` — one per ROUND TRIP (flat → position → flat). What the
       trader actually reads: entry, exit, holding days, result. A position that
       has been partly scaled out but is still open has realized sales and NO
       closed trade yet, so `realized_pl` (all sales) and the sum of the closed
       trades are different numbers on purpose, and both are reported.

   FX. Realized P&L in the base currency needs the rate AT DISPOSAL, which is
   the SELL row's own `fx_rate`, against a cost released at the rates the lots
   were bought at. So a sale is convertible only when the position was
   `fx_complete` at that moment AND the SELL row carries a rate. Otherwise the
   sale's base amount is None — never 0.0 — and the sale is excluded from the
   totals by name (`realized_unavailable_symbols`), the same doctrine as rules
   2/4/5. A THB book is 1.0 by definition throughout, so the common Thai case is
   always convertible with no backfill.

   Win/loss is judged in the BASE currency, because a trade that gained in USD
   can have lost in THB and THB is what this user spends. That is also why the
   ratios below refuse to count a trade they cannot convert instead of falling
   back to its native sign.

7. bd:shotockviz-eb1 — CORPORATE ACTIONS. A split changes the UNITS a position
   is quoted in, not the money that was paid for it — so raw transactions stay
   raw and the fold restates every pre-ex-date lot at READ time
   (qty ÷ factor, price × factor, `qty*price` invariant).

   The rule, its ratio convention, why dividends must NOT touch a cost basis and
   why a RIGHTS action cannot be applied to a position at all all live in
   `services/corporate_actions.py`; this module only applies the factor that
   module computes, at the single point in the fold where `qty` and `price` are
   read off a row. `splits` is passed IN rather than loaded here so this module
   stays import-free of the app (see `models/portfolio.py:7-10` — that direction
   must not cycle) and so every caller demonstrably uses the same table.

   Not passing `splits` leaves the fold behaving exactly as before, which is what
   keeps the ~40 existing `build_holdings` tests meaningful: they pin the money
   arithmetic, and a split moves no money.

   A symbol carrying a RIGHTS action is flagged `rights_unstatable` and named in
   `PortfolioTotals.rights_unstatable_symbols`. It is NOT excluded from the
   totals: unlike a missing FX rate, its cost basis is still a real number in a
   real currency — what is unknown is only whether the user subscribed, so the
   honest report is "this number may be short of shares you paid for", not "we
   cannot state this position".

Money is `float` here only because `models/portfolio.py:47-49` stores qty/price/fee
as `Float`. The Decimal/Numeric migration is a separate bead (Tara N8) and is NOT
started here. The arithmetic below adds exactly one new term per BUY (`+ fee`),
so it introduces no new rounding behaviour beyond that term.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date as _date
from typing import Callable, Iterable, Mapping, Sequence

# THE quantity epsilon. Positions at or below this size are treated as fully
# closed; it is also the float-drift guard after a SELL.
#
# bd:shotockviz-fin — this is the ONLY definition. It started as 1e-6 in
# portfolio.py against a different 0.001 "active" threshold in dashboard.py;
# those two were unified here by bd:shotockviz-msg, but a THIRD copy survived as
# a bare `0.001` literal in `api/routes/portfolio_performance.py`'s
# `compute_holdings_on`. A position between the two values (say 0.0005 of a
# fractional US share) was therefore OPEN on the holdings table and CLOSED on
# the equity curve of the same book at the same instant — the curve silently
# dropped it and, because an excluded symbol excludes the whole day, could drop
# whole days with it. Every "is this position closed?" decision in the product
# imports this constant; none re-states the number.
QTY_EPSILON = 1e-6

# The one currency every total in this module is stated in.
BASE_CURRENCY = "THB"

# Yahoo symbol carrying the rate.
#
# bd:shotockviz-ss3 — this used to read "It quotes '1 THB in USD' (e.g. 0.0317),
# so the THB-per-USD rate is its reciprocal". That was a claim in a comment that
# nobody had checked against a payload, and the code inverted unconditionally on
# the strength of it. Orientation is now DERIVED per read (`read_fx_quote`) and
# reported (`FxRate.quote_orientation`), so the comment no longer has to be
# right — see rule 4 / FX-4 in the module docstring.
FX_QUOTE_SYMBOL = "THBUSD=X"

# Last-resort rate, used ONLY when there is no live quote and the user's own book
# has never recorded one. Always surfaced as source="fallback" / estimated=True;
# it is never written to a transaction.
FX_FALLBACK_RATES = {"USD": 33.0}

# Sanity band for a base-per-unit rate, and — bd:shotockviz-ss3 — the thing that
# makes the quote's orientation DERIVABLE instead of assumed.
#
# It can serve as that discriminator only because the band lies strictly above
# 1.0: for any positive price p, at most one of {p, 1/p} can fall inside it, so
# "which way up is this pair?" has exactly one answer, or none.
# `_check_band_invariant` enforces that at import.
#
# Reference points for USD/THB: ~25 (1996), ~56 (1998 crisis peak), and 32.93 on
# 2026-09-04 (public FX quote, cross-checked while working bd:shotockviz-ss3 —
# an observation used to size the band, NOT a rate this code will ever use).
# 10-100 is deliberately far wider than any plausible market move: its job is to
# reject a mis-oriented or garbage payload, not to police the market.
FX_PLAUSIBLE_RANGE = {"USD": (10.0, 100.0)}


def _check_band_invariant() -> None:
    """A band that straddles 1.0 cannot tell a rate from its reciprocal."""
    for currency, (lo, hi) in FX_PLAUSIBLE_RANGE.items():
        if not (1.0 < lo <= hi):
            raise ValueError(
                f"FX_PLAUSIBLE_RANGE[{currency!r}] = ({lo}, {hi}) must satisfy "
                "1.0 < lo <= hi — otherwise a price and its reciprocal can both "
                "be 'plausible' and the quote's orientation is undecidable "
                "(bd:shotockviz-ss3)."
            )


_check_band_invariant()


def assert_currency_band_coverage(currencies: Iterable) -> None:
    """Every recordable currency must have a plausibility band. Enforced, not documented.

    bd:shotockviz-mh1. `FX_PLAUSIBLE_RANGE` is not a sanity nicety — it is the
    discriminator that makes a quote's orientation DERIVABLE (rule 4 / FX-4).
    `read_fx_quote` starts with `band = FX_PLAUSIBLE_RANGE.get(currency)` and
    returns None when there is none, so a currency added to
    `models.portfolio.Currency` without a band would not fail: every live quote
    for it would silently become "no rate available", the position would drop
    out of every total into `fx_unavailable_symbols`, and it would look like a
    cold cache rather than a missing constant. That is a bug that reads as data.

    So the enum cannot be extended without the band: `models/portfolio.py` calls
    this at import, immediately after `Currency` is defined, and a missing band
    stops the whole app from starting rather than degrading one screen.

    Only the BAND is mandatory. `FX_FALLBACK_RATES` is deliberately optional —
    having no last-resort constant for a currency makes `resolve_fx` decline,
    which is the honest outcome; having no band makes it decline *silently for
    the wrong reason*.

    Accepts enum members or plain strings (`Currency`, or a list of codes).
    """
    codes = {str(getattr(c, "value", c)).upper() for c in currencies}
    missing = sorted(codes - {BASE_CURRENCY} - set(FX_PLAUSIBLE_RANGE))
    if missing:
        raise ValueError(
            f"Currency {missing} has no FX_PLAUSIBLE_RANGE band in "
            "services/portfolio_service.py. Add one (strictly above 1.0, stated "
            "as base-per-1-unit) in the same commit that adds the currency — "
            "without it read_fx_quote() cannot decide the orientation of that "
            "pair's quote and every position in it would silently report 'no "
            "rate available' forever (bd:shotockviz-mh1 / -ss3)."
        )


def _currency_str(value) -> str:
    """Normalise a `Currency` enum / str / None to a plain upper-case code."""
    if value is None:
        return "THB"
    raw = getattr(value, "value", value)
    return str(raw).upper() or "THB"


@dataclass
class FxRate:
    """A currency→base rate together with how honest it is (rule 4, FX-3)."""

    currency: str
    rate: float
    source: str  # "identity" | "live" | "last_known" | "fallback"
    as_of: str | None = None  # ISO date of a "last_known" observation
    base: str = BASE_CURRENCY
    # bd:shotockviz-ss3 — which way up the live quote actually arrived
    # ("reciprocal" | "direct"), or None when the rate did not come from a
    # quote. Carried into the API payload so the orientation can be read off a
    # live response instead of trusted from a comment.
    quote_orientation: str | None = None

    @property
    def estimated(self) -> bool:
        """True when the rate is not an observed current market rate."""
        return self.source not in ("identity", "live")


FxResolver = Callable[[str], "FxRate | None"]

# How a quoted price relates to the base-per-unit rate we want.
ORIENTATION_RECIPROCAL = "reciprocal"  # quote is base-in-foreign  (0.0304)
ORIENTATION_DIRECT = "direct"          # quote is foreign-in-base  (32.93)


@dataclass(frozen=True)
class FxQuoteReading:
    """A live FX quote read WITHOUT assuming which way up the pair is."""

    rate: float          # base per 1 unit of the foreign currency
    orientation: str     # ORIENTATION_RECIPROCAL | ORIENTATION_DIRECT
    quoted_price: float  # exactly what the payload said, for the record


def read_fx_quote(quote: Mapping | None, currency: str = "USD") -> FxQuoteReading | None:
    """Derive the base-per-unit rate from a cached FX quote (rule 4 / FX-4).

    Tries both readings of the quoted price and keeps the one that lands inside
    `FX_PLAUSIBLE_RANGE[currency]`. The band sits strictly above 1.0, so at most
    one of them can — `_check_band_invariant`. Returns None when the price is
    missing / non-numeric / non-positive, when neither reading is plausible
    (garbage), or in the impossible-by-invariant case where both are (ambiguous
    — decline rather than pick).

    This is what makes a mis-oriented payload a *declined* rate instead of a
    silent ~1000x rescaling of the whole foreign book.
    """
    band = FX_PLAUSIBLE_RANGE.get(currency.upper())
    if band is None:
        return None
    price = usable_price(quote)
    if price is None:
        return None

    lo, hi = band
    readings = [
        FxQuoteReading(1.0 / price, ORIENTATION_RECIPROCAL, price),
        FxQuoteReading(price, ORIENTATION_DIRECT, price),
    ]
    plausible = [r for r in readings if lo <= r.rate <= hi]
    return plausible[0] if len(plausible) == 1 else None


def live_rate_from_thbusd(quote: Mapping | None) -> float | None:
    """THB-per-USD from a cached `THBUSD=X` quote, or None if not usable.

    Thin wrapper over `read_fx_quote` for callers that only need the number
    (e.g. stamping a rate onto a new transaction). Prefer `read_fx_quote` where
    the orientation is worth reporting.
    """
    reading = read_fx_quote(quote, "USD")
    return reading.rate if reading is not None else None


def last_known_rate(txns: Iterable, currency: str) -> tuple[float, str | None] | None:
    """Most recently *dated* rate the user's own book has recorded for `currency`.

    Preferred over `FX_FALLBACK_RATES` because it is a rate this user actually
    transacted at, not a constant frozen in source. Still `estimated`.
    """
    currency = currency.upper()
    best = None
    for t in txns:
        if _currency_str(getattr(t, "currency", None)) != currency:
            continue
        rate = getattr(t, "fx_rate", None)
        if rate is None:
            continue
        try:
            rate = float(rate)
        except (TypeError, ValueError):
            continue
        if rate <= 0:
            continue
        when = getattr(t, "date", None)
        key = (when.isoformat() if hasattr(when, "isoformat") else str(when or ""))
        if best is None or key >= best[1]:
            best = (rate, key)
    if best is None:
        return None
    return best[0], (best[1] or None)


def resolve_fx(
    currency: str,
    live_rate: float | None = None,
    last_known: tuple[float, str | None] | None = None,
    live_orientation: str | None = None,
) -> FxRate | None:
    """Pick the most honest rate available for `currency`, labelled with its source."""
    currency = currency.upper()
    if currency == BASE_CURRENCY:
        return FxRate(currency=currency, rate=1.0, source="identity")
    if live_rate is not None and live_rate > 0:
        return FxRate(currency=currency, rate=live_rate, source="live",
                      quote_orientation=live_orientation)
    if last_known is not None and last_known[0] > 0:
        return FxRate(currency=currency, rate=last_known[0], source="last_known",
                      as_of=last_known[1])
    fallback = FX_FALLBACK_RATES.get(currency)
    if fallback:
        return FxRate(currency=currency, rate=fallback, source="fallback")
    return None  # unknown currency — the caller must decline, not guess


def fx_resolver(rates: Mapping[str, FxRate]) -> FxResolver:
    """Build the `fx` callable `value_holdings` takes, from a currency->FxRate map."""
    def _resolve(currency: str) -> FxRate | None:
        currency = _currency_str(currency)
        if currency == BASE_CURRENCY:
            return FxRate(currency=BASE_CURRENCY, rate=1.0, source="identity")
        return rates.get(currency)
    return _resolve


def build_fx_rates(txns: Sequence, fx_quote: Mapping | None = None) -> dict[str, FxRate]:
    """The one place both screens get their rates from, so they cannot disagree.

    `fx_quote` is the cached `THBUSD=X` blob (None when the cache is cold — the
    normal state off-hours, which is exactly when the old 33.0 constant fired).
    """
    reading = read_fx_quote(fx_quote, "USD")
    currencies = {
        _currency_str(getattr(t, "currency", None)) for t in txns
    } - {BASE_CURRENCY}

    rates: dict[str, FxRate] = {}
    for currency in sorted(currencies):
        is_usd = currency == "USD"
        resolved = resolve_fx(
            currency,
            live_rate=reading.rate if (is_usd and reading) else None,
            last_known=last_known_rate(txns, currency),
            live_orientation=reading.orientation if (is_usd and reading) else None,
        )
        if resolved is not None:
            rates[currency] = resolved
    return rates


def default_fx(currency: str) -> FxRate | None:
    """No FX context: only the base currency is expressible; everything else is
    honestly unknown (and gets excluded from the totals, never added raw)."""
    return fx_resolver({})(currency)


@dataclass
class RealizedSale:
    """One SELL row, priced against the cost it released (rule 6).

    The ledger grain: every satang of realized money is in exactly one of these.
    `*_base` are None — never 0.0 — when this disposal cannot be converted
    (the position was not `fx_complete` at that moment, or the SELL row carries
    no rate of its own).
    """

    symbol: str
    when: _date | None
    qty: float
    price: float
    proceeds: float        # qty * price, NATIVE, gross of the sell fee
    cost_released: float   # qty * avg_cost BEFORE the qty was reduced
    fee: float             # SELL commission, charged here (bd:shotockviz-fww)
    realized_pl: float     # proceeds - cost_released - fee, NATIVE
    currency: str = BASE_CURRENCY
    fx_rate: float | None = None          # rate AT DISPOSAL (the SELL's own)
    proceeds_base: float | None = None
    cost_released_base: float | None = None
    realized_pl_base: float | None = None
    fee_base: float | None = None
    # True when more was sold than was held. The book cannot state the cost of
    # shares it has no record of buying, so `cost_released` is only what it
    # could account for and the realized figure is overstated by the rest.
    # Reported, never silently absorbed.
    oversold: bool = False


@dataclass
class ClosedTrade:
    """One completed ROUND TRIP for a symbol: flat → position → flat (rule 6).

    What the trader reads. `entry_price` is the weighted-average cost actually
    released by this round trip's sales — it INCLUDES the capitalised buy
    commission (rule 1), so it is the real breakeven, not the screen price.
    `exit_price` is the weighted-average sale price GROSS of the sell fee; the
    fee is in `fees` and is already subtracted from `realized_pl`.
    """

    symbol: str
    currency: str
    qty: float
    opened_on: _date | None
    closed_on: _date | None
    entry_price: float
    exit_price: float
    fees: float                       # sell-side commission on this round trip
    realized_pl: float                # NATIVE
    realized_pl_base: float | None    # None = this trip cannot be converted
    sales: int = 1                    # how many SELL rows closed it (scale-outs)

    @property
    def holding_days(self) -> int | None:
        if self.opened_on is None or self.closed_on is None:
            return None
        return (self.closed_on - self.opened_on).days

    @property
    def realized_pl_pct(self) -> float | None:
        """Return on the cost actually put at risk. None on a zero-cost trip —
        a percentage of nothing is undefined, not infinite (see also `ace`)."""
        cost = self.entry_price * self.qty
        return (self.realized_pl / cost * 100) if cost else None


@dataclass
class Holding:
    """Net open position for one symbol, built from raw transactions."""

    symbol: str
    qty: float = 0.0
    cost_basis: float = 0.0  # includes BUY commission (rule 1), NATIVE currency
    currency: str = "THB"
    realized_fees: float = 0.0  # SELL commission — realized side, not cost basis
    # Rule 4 / FX-2: same cost basis, each lot converted at ITS OWN stored rate.
    # Only meaningful while `fx_complete` is True.
    cost_basis_base: float = 0.0
    fx_complete: bool = True
    # Rule 5 / bd:shotockviz-7ju: every currency seen on this symbol's rows, not
    # just the first one. More than one means `cost_basis` below is a sum of
    # different units and is not a number.
    currencies: set[str] = field(default_factory=set)
    # ── rule 6 / bd:shotockviz-tmz — the realized side ───────────────────────
    # Every SELL, in order. Sales at index >= `round_open_index` belong to the
    # round trip that is still open (a scale-out on a position still held).
    sales: list[RealizedSale] = field(default_factory=list)
    closed_trades: list[ClosedTrade] = field(default_factory=list)
    # Date the CURRENT round trip opened (None while flat), so a symbol bought,
    # closed and bought again reports two trades instead of one long one.
    opened_on: _date | None = None
    round_open_index: int = 0
    # ── rule 7 / bd:shotockviz-eb1 — corporate actions ───────────────────────
    # True when at least one lot of this symbol was restated by a split, i.e.
    # the qty/avg_cost printed are NOT the numbers on the original contract
    # note. Surfaced so a doubled share count reads as an adjustment rather
    # than as data corruption.
    split_adjusted: bool = False
    # The symbol has a RIGHTS action. Nothing records whether the user
    # subscribed, so the position may be short of shares that were paid for.
    # Reported, never guessed (see services/corporate_actions.py).
    rights_unstatable: bool = False

    @property
    def currency_conflict(self) -> bool:
        """True when this symbol's transactions do not agree on a currency."""
        return len(self.currencies) > 1

    @property
    def avg_cost(self) -> float:
        return self.cost_basis / self.qty if self.qty > QTY_EPSILON else 0.0

    @property
    def avg_fx_rate(self) -> float | None:
        """Weighted average rate the open cost basis was actually bought at."""
        if not self.fx_complete or self.cost_basis <= 0:
            return None
        return self.cost_basis_base / self.cost_basis


@dataclass
class ValuedHolding:
    """A `Holding` priced against one quote. `current_*` are None when unpriced.

    `*_base` fields are the same position stated in `BASE_CURRENCY`; they are
    None when no rate is available for the position's currency at all.
    """

    symbol: str
    qty: float
    avg_cost: float | None
    cost_basis: float | None
    currency: str
    # Rule 5 / bd:shotockviz-7ju. When True, `avg_cost`/`cost_basis` are None:
    # the underlying rows disagree on a currency, so there is no cost number to
    # state. `currencies` names what was found so the user can go fix the rows.
    currency_conflict: bool = False
    currencies: list[str] = field(default_factory=list)
    current_price: float | None = None
    current_value: float | None = None
    unrealized_pl: float | None = None
    unrealized_pl_pct: float | None = None
    # ── rule 4: base-currency view ───────────────────────────────────────────
    base_currency: str = BASE_CURRENCY
    fx_rate: float | None = None          # current rate used for the VALUE side
    fx_source: str | None = None          # identity | live | last_known | fallback
    fx_as_of: str | None = None           # observation date of a "last_known" rate
    fx_estimated: bool = False
    fx_quote_orientation: str | None = None  # bd:shotockviz-ss3
    cost_basis_base: float | None = None
    cost_basis_source: str | None = None  # identity | historical | current_rate
    current_value_base: float | None = None
    unrealized_pl_base: float | None = None
    unrealized_pl_pct_base: float | None = None
    market_pl_base: float | None = None   # market move, converted at current rate
    fx_pl_base: float | None = None       # currency move on the cost basis
    avg_fx_rate: float | None = None      # weighted rate the cost was bought at
    # ── rule 7 / bd:shotockviz-eb1 ───────────────────────────────────────────
    # `qty` / `avg_cost` were restated by a split: they are the position in
    # TODAY's units, not the numbers on the original contract note.
    split_adjusted: bool = False
    # A RIGHTS action exists for this symbol and no subscription is recorded,
    # so `qty` may be short of shares that were paid for.
    rights_unstatable: bool = False

    @property
    def priced(self) -> bool:
        return self.current_price is not None

    @property
    def convertible(self) -> bool:
        """A rate exists, so this position can enter a base-currency total."""
        return self.fx_rate is not None


@dataclass
class PortfolioTotals:
    total_value: float = 0.0
    total_cost: float = 0.0
    unrealized_pl: float = 0.0
    unrealized_pl_pct: float = 0.0
    priced_symbols: list[str] = field(default_factory=list)
    unpriced_symbols: list[str] = field(default_factory=list)
    # ── rule 4 ───────────────────────────────────────────────────────────────
    base_currency: str = BASE_CURRENCY
    market_pl: float = 0.0
    # None (not 0.0) as soon as ONE included position cannot separate its FX
    # component — "unknown", never "the currency did not move".
    fx_pl: float | None = 0.0
    fx_estimated: bool = False          # some rate in use is not a live quote
    cost_basis_estimated: bool = False  # some cost converted at the current rate
    fx_rates: dict[str, FxRate] = field(default_factory=dict)
    # Priced, but no rate for its currency -> excluded from the totals rather
    # than added raw (that raw addition was bd:shotockviz-sbe).
    fx_unavailable_symbols: list[str] = field(default_factory=list)
    # Rule 5 / bd:shotockviz-7ju — the symbol's own rows disagree on a currency,
    # so its cost basis mixes units. Excluded from both sides and named.
    currency_conflict_symbols: list[str] = field(default_factory=list)
    # Rule 7 / bd:shotockviz-eb1 — restated by a split (INCLUDED in the totals;
    # the restatement is what makes them right) and, separately, symbols whose
    # share count may be short because a rights subscription is not recorded
    # (also included — see rule 7 for why this is not an exclusion).
    split_adjusted_symbols: list[str] = field(default_factory=list)
    rights_unstatable_symbols: list[str] = field(default_factory=list)


def build_holdings(
    txns: Iterable,
    splits: Mapping | None = None,
    as_of: _date | None = None,
) -> dict[str, Holding]:
    """Fold transactions (chronological order) into net positions per symbol.

    `splits` — rule 7 / bd:shotockviz-eb1. A `{SYMBOL: corporate_actions.
    SymbolActions}` map (built by `services.corporate_actions.load_actions`).
    When given, every lot dated strictly before a split's ex-date is restated
    into post-split units at read time: `qty / factor`, `price * factor`, with
    `qty*price` — the money actually paid — invariant. The raw rows are never
    written; see `services/corporate_actions.py` for why that asymmetry is
    deliberate and why dividends/rights are excluded.

    `as_of` — restate only for splits with `ex_date <= as_of`, i.e. state the
    book in the units in force on that date. `None` (the default) means today,
    which is the correct basis for a position valued against a live quote. The
    equity curve passes the day it is walking so that each point's share count
    and that day's raw close are in the same units.

    Omitting `splits` reproduces the pre-eb1 fold exactly.
    """
    from services import corporate_actions as _ca

    holdings: dict[str, Holding] = {}

    for t in txns:
        symbol = t.symbol
        if symbol not in holdings:
            holdings[symbol] = Holding(
                symbol=symbol,
                currency=_currency_str(getattr(t, "currency", None)),
            )
        h = holdings[symbol]
        # Rule 5: record every currency this symbol was ever transacted in, so a
        # mixed-unit cost basis is detectable instead of inherited silently.
        h.currencies.add(_currency_str(getattr(t, "currency", None)))

        qty = float(t.qty or 0.0)
        price = float(t.price or 0.0)

        # Rule 7: the ONE point where a corporate action touches the book. It is
        # here, before any arithmetic, so the split cannot reach cost basis,
        # realized P&L or the FX conversion by a different route on each screen.
        if splits is not None:
            actions = splits.get(symbol.upper()) or splits.get(symbol)
            if actions is not None:
                if getattr(actions, "has_rights", False):
                    h.rights_unstatable = True
                factor = _ca.split_factor(
                    actions, _as_date(getattr(t, "date", None)), as_of
                )
                if factor != 1.0:
                    qty, price = _ca.restate(qty, price, factor)
                    h.split_adjusted = True

        fee = float(getattr(t, "fee", 0.0) or 0.0)
        txn_type = getattr(t.type, "value", t.type)
        rate = _txn_fx_rate(t)  # rule 4 / FX-1; 1.0 for a base-currency txn

        if txn_type == "BUY":
            # Rule 6: the round trip opens on the first BUY made while flat, so a
            # symbol bought, fully closed and bought again is two trades.
            if h.opened_on is None:
                h.opened_on = _as_date(getattr(t, "date", None))
            h.qty += qty
            lot_cost = qty * price + fee  # rule 1: buy fee -> cost basis
            h.cost_basis += lot_cost
            if rate is None:
                # No rate for this lot and none may be invented -> this position
                # can never state a historical base cost or an FX return.
                h.fx_complete = False
            else:
                h.cost_basis_base += lot_cost * rate
        else:  # SELL
            held_before = h.qty
            fx_complete_before = h.fx_complete
            avg = h.avg_cost  # avg BEFORE reducing qty
            avg_base = (h.cost_basis_base / h.qty) if h.qty > QTY_EPSILON else 0.0
            cost_released = qty * avg
            cost_released_base = qty * avg_base
            h.qty -= qty
            h.cost_basis -= cost_released
            # Same weighted-average removal on the base side; the SELL's own rate
            # is irrelevant to the shares still held (it belongs to realized P&L).
            h.cost_basis_base -= cost_released_base
            h.realized_fees += fee  # rule 1: sell fee -> realized, not cost basis

            # ── rule 6 / bd:shotockviz-tmz: record what this disposal made ────
            proceeds = qty * price
            # Convertible only if the cost side was complete AND this SELL row
            # carries the rate at disposal. Otherwise None, never 0.0.
            convertible = fx_complete_before and rate is not None
            h.sales.append(RealizedSale(
                symbol=symbol,
                when=_as_date(getattr(t, "date", None)),
                qty=qty,
                price=price,
                proceeds=proceeds,
                cost_released=cost_released,
                fee=fee,
                realized_pl=proceeds - cost_released - fee,
                currency=_currency_str(getattr(t, "currency", None)),
                fx_rate=rate if convertible else None,
                proceeds_base=proceeds * rate if convertible else None,
                cost_released_base=cost_released_base if convertible else None,
                fee_base=fee * rate if convertible else None,
                realized_pl_base=(
                    proceeds * rate - cost_released_base - fee * rate
                    if convertible else None
                ),
                oversold=qty > held_before + QTY_EPSILON,
            ))

            if abs(h.qty) < QTY_EPSILON:  # float-drift guard
                h.qty = 0.0
                h.cost_basis = 0.0
                h.cost_basis_base = 0.0
                # bd:shotockviz-jgn — `fx_complete` describes the OPEN lots, and
                # there are now none, so it is vacuously true again. Leaving it
                # False here was sticky forever: a position closed entirely and
                # reopened with lots that ALL carry rates still reported
                # `cost_basis_source="current_rate"` and `fx_pl=None`, i.e. the
                # book claimed it could not separate an FX return it demonstrably
                # could. `currencies` is deliberately NOT reset — rule 5 judges a
                # symbol over all of its rows, closed lots included.
                h.fx_complete = True
                _close_round_trip(h)

    return holdings


def _as_date(value) -> _date | None:
    """`transactions.date` is a DATE, but tolerate a datetime from any caller."""
    if value is None:
        return None
    if isinstance(value, _date):
        # datetime is a subclass of date; normalise it so a subtraction of two
        # trade dates cannot come back as a timedelta with hours in it.
        return value.date() if hasattr(value, "hour") else value
    return None


def _close_round_trip(h: Holding) -> None:
    """Fold the sales that closed this position into one `ClosedTrade` (rule 6)."""
    legs = h.sales[h.round_open_index:]
    h.round_open_index = len(h.sales)
    opened_on, h.opened_on = h.opened_on, None
    if not legs:
        return  # position reached zero without a sale (empty/oversold edge)

    qty = sum(s.qty for s in legs)
    cost = sum(s.cost_released for s in legs)
    proceeds = sum(s.proceeds for s in legs)
    bases = [s.realized_pl_base for s in legs]
    h.closed_trades.append(ClosedTrade(
        symbol=h.symbol,
        currency=legs[-1].currency,
        qty=qty,
        opened_on=opened_on,
        closed_on=legs[-1].when,
        entry_price=cost / qty if qty else 0.0,
        exit_price=proceeds / qty if qty else 0.0,
        fees=sum(s.fee for s in legs),
        realized_pl=sum(s.realized_pl for s in legs),
        # One unconvertible leg makes the whole trip unconvertible — summing an
        # unknown as 0 is the failure mode rule 4 exists to forbid.
        realized_pl_base=None if any(b is None for b in bases) else sum(bases),
        sales=len(legs),
    ))


def _txn_fx_rate(t) -> float | None:
    """Rate to convert this transaction into `BASE_CURRENCY` (rule 4 / FX-1).

    A base-currency transaction is 1.0 by definition — that is what keeps the
    whole pre-existing THB book FX-complete with no backfill. Anything else must
    come from a rate stored on the row; absent (or nonsense) means unknown.
    """
    if _currency_str(getattr(t, "currency", None)) == BASE_CURRENCY:
        return 1.0
    raw = getattr(t, "fx_rate", None)
    if raw is None:
        return None
    try:
        rate = float(raw)
    except (TypeError, ValueError):
        return None
    return rate if rate > 0 else None


def active_holdings(holdings: Mapping[str, Holding]) -> dict[str, Holding]:
    """Positions still open (fully-sold symbols dropped)."""
    return {s: h for s, h in holdings.items() if h.qty > QTY_EPSILON}


def usable_price(quote: Mapping | None) -> float | None:
    """Extract a usable market price from a cached quote blob, else None.

    Rule 3: `None`, a non-numeric, or a non-positive price all mean
    "no price available" — never "the position is worth nothing".
    """
    if not quote:
        return None
    raw = quote.get("price")
    if raw is None:
        return None
    try:
        price = float(raw)
    except (TypeError, ValueError):
        return None
    return price if price > 0 else None


def value_holdings(
    holdings: Mapping[str, Holding],
    quotes: Mapping[str, Mapping | None],
    fx: FxResolver | None = None,
) -> list[ValuedHolding]:
    """Price each holding against `quotes` (cache blobs keyed by symbol).

    `fx` resolves a currency to the current `FxRate`. Default: only the base
    currency resolves — a foreign position then reports native numbers only and
    is left out of the base totals (rule 4), which is the honest answer when
    nobody could tell us a rate.
    """
    resolve = fx or default_fx
    valued: list[ValuedHolding] = []

    for symbol, h in holdings.items():
        # Rule 5 / bd:shotockviz-7ju — mixed cost-basis units. Nothing about
        # this position is expressible: not the cost (a sum of two currencies),
        # therefore not the P&L, therefore not the converted total. Return the
        # row so the user can SEE the broken symbol, but with every money field
        # None and the conflict named. `summarize` then excludes it by name.
        if h.currency_conflict:
            valued.append(ValuedHolding(
                symbol=symbol,
                qty=h.qty,
                avg_cost=None,
                cost_basis=None,
                currency="/".join(sorted(h.currencies)),
                currency_conflict=True,
                currencies=sorted(h.currencies),
                split_adjusted=h.split_adjusted,
                rights_unstatable=h.rights_unstatable,
            ))
            continue

        price = usable_price(quotes.get(symbol))
        value = price * h.qty if price is not None else None
        pl = (value - h.cost_basis) if value is not None else None
        pl_pct = (pl / h.cost_basis * 100) if (pl is not None and h.cost_basis) else None

        v = ValuedHolding(
            symbol=symbol,
            qty=h.qty,
            avg_cost=h.avg_cost,
            cost_basis=h.cost_basis,
            currency=h.currency,
            current_price=price,
            current_value=value,
            unrealized_pl=pl,
            unrealized_pl_pct=pl_pct,
            split_adjusted=h.split_adjusted,
            rights_unstatable=h.rights_unstatable,
        )

        rate = resolve(h.currency)
        if rate is not None:
            v.fx_rate = rate.rate
            v.fx_source = rate.source
            v.fx_as_of = rate.as_of
            v.fx_estimated = rate.estimated
            v.fx_quote_orientation = rate.quote_orientation
            v.avg_fx_rate = h.avg_fx_rate

            # Cost side (FX-2): each lot at its own stored rate when we have
            # them all, otherwise the current rate — and say which.
            if h.fx_complete:
                v.cost_basis_base = h.cost_basis_base
                v.cost_basis_source = (
                    "identity" if rate.source == "identity" else "historical"
                )
            else:
                v.cost_basis_base = h.cost_basis * rate.rate
                v.cost_basis_source = "current_rate"

            # Value side: always the current rate.
            if value is not None:
                v.current_value_base = value * rate.rate
                v.unrealized_pl_base = v.current_value_base - v.cost_basis_base
                v.unrealized_pl_pct_base = (
                    v.unrealized_pl_base / v.cost_basis_base * 100
                    if v.cost_basis_base else None
                )
                v.market_pl_base = (pl or 0.0) * rate.rate
                # FX component = cost_native·Rc − Σ(cost_i·R_i); unknown, not
                # zero, when the cost had to be converted at the current rate.
                v.fx_pl_base = (
                    h.cost_basis * rate.rate - v.cost_basis_base
                    if v.cost_basis_source != "current_rate" else None
                )

        valued.append(v)

    return valued


def summarize(valued: Sequence[ValuedHolding]) -> PortfolioTotals:
    """Aggregate priced, convertible positions — always in `BASE_CURRENCY`.

    Exclusions (all three are "we do not know", never "it is worth nothing"):
      * rows disagree on a currency -> `currency_conflict_symbols` (rule 5)
      * no usable quote             -> `unpriced_symbols`          (rule 2)
      * no rate for its currency    -> `fx_unavailable_symbols`    (rule 4)

    The FX split is carried through: `market_pl + fx_pl == unrealized_pl` whenever
    `fx_pl` is not None. `fx_pl` goes None the moment one included position cannot
    separate its currency component, because summing "unknown" as 0 is exactly the
    silent number bd:shotockviz-fnn is about.

    Conversion itself happened in `value_holdings` — this function never applies a
    rate of its own, so a caller cannot accidentally aggregate mixed currencies raw
    (bd:shotockviz-sbe).
    """
    totals = PortfolioTotals()

    for v in valued:
        # Rule 7 — recorded for EVERY row, before any exclusion: these two are
        # qualifications on a number that IS being reported, not reasons to drop
        # it, so they must not be skipped by a `continue` below.
        if v.split_adjusted:
            totals.split_adjusted_symbols.append(v.symbol)
        if v.rights_unstatable:
            totals.rights_unstatable_symbols.append(v.symbol)

        # Checked before `priced`: a conflicted position was never priced, and
        # calling it "waiting for a price" would send the user to wait for data
        # that will never fix it (rule 5).
        if v.currency_conflict:
            totals.currency_conflict_symbols.append(v.symbol)
            continue
        if not v.priced:
            totals.unpriced_symbols.append(v.symbol)
            continue
        if not v.convertible:
            totals.fx_unavailable_symbols.append(v.symbol)
            continue

        totals.total_value += v.current_value_base or 0.0
        totals.total_cost += v.cost_basis_base or 0.0
        totals.market_pl += v.market_pl_base or 0.0
        totals.priced_symbols.append(v.symbol)

        if v.fx_estimated:
            totals.fx_estimated = True
        if v.cost_basis_source == "current_rate":
            totals.cost_basis_estimated = True
        if v.fx_pl_base is None:
            totals.fx_pl = None
        elif totals.fx_pl is not None:
            totals.fx_pl += v.fx_pl_base
        if v.fx_source and v.currency.upper() not in totals.fx_rates:
            totals.fx_rates[v.currency.upper()] = FxRate(
                currency=v.currency.upper(),
                rate=v.fx_rate,
                source=v.fx_source,
                as_of=v.fx_as_of,
                quote_orientation=v.fx_quote_orientation,
            )

    totals.unrealized_pl = totals.total_value - totals.total_cost
    totals.unrealized_pl_pct = (
        totals.unrealized_pl / totals.total_cost * 100 if totals.total_cost else 0.0
    )
    return totals


# ─────────────────────────────────────────────────────────────────────────────
# Allocation — bd:shotockviz-916 (FR-PORT-002, "% allocation")
#
# The question this answers is position sizing on a 40-60 name book: "how much
# of what I can state is sitting in one name?". Everything about it follows from
# one decision:
#
#   THE DENOMINATOR IS `PortfolioTotals.total_value` — the base-currency market
#   value of exactly the positions `summarize` included, and the same number the
#   header prints. Not cost, not "the whole book".
#
# Two consequences, both deliberate:
#
# A) Weights are shares of *current market value* (`basis`), not of cost. A
#    concentration question is about exposure now, so the basis is stated in the
#    payload rather than left to be inferred from the label.
#
# B) An EXCLUDED position gets NO SLICE, and is named instead. This is the only
#    reading that survives rules 2/4/5. A slice needs an area, an area needs a
#    number, and for these three the number is exactly what is unknown:
#      * unpriced (rule 2)            — no market value exists to divide;
#      * no FX rate (rule 4)          — the value is not expressible in the base;
#      * currency conflict (rule 5)   — the position has no statable cost either.
#    The tempting fix — draw the slice at its COST basis — would mix a
#    cost-shaped area into a market-value pie, so the percentages would no longer
#    be percentages of anything. Drawing it at zero is the fabricated-loss bug of
#    rule 2 in pie form: a 0% slice reads as "this name is nothing", when the
#    truth is "we cannot say". So `excluded` carries the symbol AND the reason,
#    and a caller that renders the chart without rendering that list is showing a
#    chart of a book it silently shrank.
#
# The invariant that makes the picture trustworthy: `sum(s.value_base) ==
# total_value` exactly (both are summed from the same `current_value_base`
# values), so a renderer that draws arcs from `value_base` cannot produce a ring
# that does not close. `weight_pct` is derived from those same values and is a
# convenience for labels — geometry should use `value_base`.
# ─────────────────────────────────────────────────────────────────────────────

ALLOCATION_BASIS_CURRENT_VALUE = "current_value_base"

# Why a position is not in the pie. Same three exclusions `summarize` makes —
# read off its output, never re-decided here.
EXCLUDED_UNPRICED = "unpriced"
EXCLUDED_FX_UNAVAILABLE = "fx_unavailable"
EXCLUDED_CURRENCY_CONFLICT = "currency_conflict"
# Included by `summarize` yet carrying no base value. Unreachable given
# `summarize`'s own test (priced => value, convertible => rate => value_base);
# it exists so that if the two ever drift, the position is NAMED rather than
# quietly missing from a ring that claims to close.
EXCLUDED_UNSTATABLE = "unstatable"


@dataclass
class AllocationSlice:
    """One name's share of the stated total."""

    symbol: str
    currency: str
    value_base: float   # the slice's area — use THIS for geometry
    weight_pct: float   # value_base / total_value * 100, for labels
    split_adjusted: bool = False
    rights_unstatable: bool = False


@dataclass
class AllocationExclusion:
    """A position that has no slice, and why. Never a 0% slice."""

    symbol: str
    reason: str


@dataclass
class Allocation:
    basis: str = ALLOCATION_BASIS_CURRENT_VALUE
    base_currency: str = BASE_CURRENCY
    # The denominator. Identical to `PortfolioTotals.total_value`, so the pie and
    # the header total are the same book.
    total_value: float = 0.0
    slices: list[AllocationSlice] = field(default_factory=list)
    excluded: list[AllocationExclusion] = field(default_factory=list)
    # Some rate in the denominator is not a live quote — the weights inherit that.
    fx_estimated: bool = False

    @property
    def top_weight_pct(self) -> float | None:
        """Largest single-name weight. None when nothing is statable — 0 would
        claim the book is perfectly diversified, which is not what "we cannot
        price anything" means."""
        return self.slices[0].weight_pct if self.slices else None


def build_allocation(
    valued: Sequence[ValuedHolding],
    totals: PortfolioTotals,
) -> Allocation:
    """Split `totals.total_value` across the positions that produced it.

    Takes the SUMMARY, not the raw book, on purpose: inclusion is decided in
    exactly one place (`summarize`) and read here. A second inclusion test would
    be a fourth surface able to disagree with the other three about one book —
    the failure this module exists to prevent (bd:shotockviz-msg / -la4).
    """
    by_symbol = {v.symbol: v for v in valued}

    alloc = Allocation(
        base_currency=totals.base_currency,
        total_value=totals.total_value,
        fx_estimated=totals.fx_estimated,
    )

    for symbol in totals.currency_conflict_symbols:
        alloc.excluded.append(AllocationExclusion(symbol, EXCLUDED_CURRENCY_CONFLICT))
    for symbol in totals.unpriced_symbols:
        alloc.excluded.append(AllocationExclusion(symbol, EXCLUDED_UNPRICED))
    for symbol in totals.fx_unavailable_symbols:
        alloc.excluded.append(AllocationExclusion(symbol, EXCLUDED_FX_UNAVAILABLE))

    # A percentage of nothing is undefined, not zero (same doctrine as
    # `ClosedTrade.realized_pl_pct`). An all-unpriced book therefore reports the
    # exclusions and NO slices, rather than a ring of 0% wedges.
    if totals.total_value > 0:
        for symbol in totals.priced_symbols:
            v = by_symbol.get(symbol)
            value = v.current_value_base if v is not None else None
            if value is None:
                alloc.excluded.append(AllocationExclusion(symbol, EXCLUDED_UNSTATABLE))
                continue
            alloc.slices.append(AllocationSlice(
                symbol=symbol,
                currency=v.currency,
                value_base=value,
                weight_pct=value / totals.total_value * 100,
                split_adjusted=v.split_adjusted,
                rights_unstatable=v.rights_unstatable,
            ))

    # Heaviest first — the concentration question is read from the top.
    alloc.slices.sort(key=lambda s: (-s.value_base, s.symbol))
    alloc.excluded.sort(key=lambda e: e.symbol)
    return alloc


# ─────────────────────────────────────────────────────────────────────────────
# Realized P&L — bd:shotockviz-tmz. Cost flow: moving weighted average (rule 6).
# ─────────────────────────────────────────────────────────────────────────────


@dataclass
class RealizedBook:
    """The closed side of the book, stated in `BASE_CURRENCY` like every total.

    `realized_pl` counts EVERY sale — including a scale-out on a position still
    held, which is real money already taken off the table. `closed_positions_pl`
    counts only completed round trips, so the two differ by exactly the partial
    sales of still-open positions. Both are reported because a header that
    disagrees with the table underneath it is how this book got into trouble
    before (bd:shotockviz-la4).

    Exclusions follow the same doctrine as rules 2/4/5 — never "it was zero":
      * rows disagree on a currency -> `currency_conflict_symbols`
      * a disposal that cannot be converted -> `realized_unavailable_symbols`
    """

    base_currency: str = BASE_CURRENCY
    realized_pl: float = 0.0            # all convertible sales
    realized_fees: float = 0.0          # sell-side commission inside the above
    # How many disposals the two numbers above actually counted. Zero is what
    # distinguishes "nothing has been sold" from "the sales netted to exactly
    # 0.00" — a caller must be able to tell those apart before printing.
    counted_sales: int = 0
    closed_positions_pl: float = 0.0    # completed round trips only
    closed_positions: list[ClosedTrade] = field(default_factory=list)
    total_trades: int = 0               # convertible closed round trips
    wins: int = 0
    losses: int = 0
    scratches: int = 0                  # exactly 0.0 — neither, and counted
    gross_profit: float = 0.0
    gross_loss: float = 0.0             # positive magnitude
    currency_conflict_symbols: list[str] = field(default_factory=list)
    realized_unavailable_symbols: list[str] = field(default_factory=list)
    oversold_symbols: list[str] = field(default_factory=list)

    @property
    def win_rate(self) -> float | None:
        """Wins / closed trips, in percent. None when nothing has closed yet —
        0% would claim every trade lost. A scratch (exactly 0.0) sits in the
        denominator only: it was not a win."""
        return (self.wins / self.total_trades * 100) if self.total_trades else None

    @property
    def profit_factor(self) -> float | None:
        """Gross profit / gross loss. None when there is no loss to divide by —
        that is undefined, not "infinitely good"."""
        return (self.gross_profit / self.gross_loss) if self.gross_loss > 0 else None


def build_realized(holdings: Mapping[str, Holding]) -> RealizedBook:
    """Aggregate the realized side of `build_holdings`'s fold (rule 6).

    Takes the holdings map rather than the raw transactions on purpose: the
    realized records are produced by the SAME fold that maintains the open
    position, so the cost released here and the cost still carried there cannot
    drift apart. A second fold over the transactions is what this module exists
    to prevent.
    """
    book = RealizedBook()
    unconvertible: set[str] = set()
    oversold: set[str] = set()

    for symbol in sorted(holdings):
        h = holdings[symbol]
        # Rule 5: a symbol whose rows mix currencies has no statable cost, so it
        # has no statable realized P&L either. Named, not silently dropped.
        if h.currency_conflict:
            book.currency_conflict_symbols.append(symbol)
            continue

        for s in h.sales:
            if s.oversold:
                oversold.add(symbol)
            if s.realized_pl_base is None:
                unconvertible.add(symbol)
                continue
            book.realized_pl += s.realized_pl_base
            book.realized_fees += s.fee_base or 0.0
            book.counted_sales += 1

        for trade in h.closed_trades:
            book.closed_positions.append(trade)
            if trade.realized_pl_base is None:
                continue  # already named via its legs above
            book.closed_positions_pl += trade.realized_pl_base
            book.total_trades += 1
            if trade.realized_pl_base > 0:
                book.wins += 1
                book.gross_profit += trade.realized_pl_base
            elif trade.realized_pl_base < 0:
                book.losses += 1
                book.gross_loss += -trade.realized_pl_base
            else:
                book.scratches += 1

    # Most recent trade first — a trade log is read from the top.
    book.closed_positions.sort(
        key=lambda t: (t.closed_on.isoformat() if t.closed_on else "", t.symbol),
        reverse=True,
    )
    book.realized_unavailable_symbols = sorted(unconvertible)
    book.oversold_symbols = sorted(oversold)
    return book


# ─────────────────────────────────────────────────────────────────────────────
# Equity curve — bd:shotockviz-la4
#
# The third surface. `api/routes/portfolio_performance.py` walked every held
# symbol and did `total_value += price * qty` with NO conversion at all, then
# fed that number to the Dashboard sparkline — so a mixed book's equity curve
# was the raw THB+USD addition rule 4 exists to forbid, on a screen that also
# showed the correctly-converted total right next to it.
#
# What a *correct* curve would need is a rate PER DAY, i.e. historical FX. The
# user's standing decision is that historical rates are not backfilled (rule 4 /
# FX-1), and this module does not invent numbers. So the curve is stated on the
# only honest basis left:
#
#   CURVE_BASIS_CONSTANT_RATE — every day of the curve is converted at ONE rate,
#   today's. The line therefore shows how the MARKET moved; it deliberately does
#   not show currency return, and its historical levels are not what the book was
#   worth in THB on those dates. Constant-currency reporting, declared as such:
#   the basis, the rate, and its source travel with the payload so the screen can
#   say it. Anything else would be inventing a rate per day.
#
#   CURVE_BASIS_SINGLE_CURRENCY — the book is entirely in the base currency, so
#   no conversion happens and there is nothing to qualify. The common Thai case.
#
# A symbol whose currency has no rate at all, or whose rows disagree on a
# currency (rule 5), cannot enter the curve. Note the curve excludes the whole
# DAY rather than the position: dropping a position out of a time series makes
# the line fall, which reads as a loss that never happened. That is the same
# reason the existing code skips a day with any unpriced symbol.
# ─────────────────────────────────────────────────────────────────────────────

CURVE_BASIS_SINGLE_CURRENCY = "single_currency"
CURVE_BASIS_CONSTANT_RATE = "constant_current_rate"


@dataclass
class CurveFxPlan:
    """Everything the equity curve needs to state itself honestly."""

    basis: str
    # symbol -> the one rate used for EVERY day of the curve. A symbol missing
    # from here cannot be converted and must exclude the days it is held on.
    rate_by_symbol: dict[str, float] = field(default_factory=dict)
    base_currency: str = BASE_CURRENCY
    fx_rates: dict[str, FxRate] = field(default_factory=dict)
    fx_estimated: bool = False
    fx_unavailable_symbols: list[str] = field(default_factory=list)
    currency_conflict_symbols: list[str] = field(default_factory=list)

    def convertible(self, symbol: str) -> bool:
        return symbol in self.rate_by_symbol


def curve_fx_plan(
    holdings: Mapping[str, Holding],
    fx_rates: Mapping[str, FxRate],
) -> CurveFxPlan:
    """Fix ONE rate per symbol for the whole curve, and say what that means.

    `fx_rates` is the same map `/portfolio/analytics` and the dashboard use
    (`build_fx_rates`), so all three surfaces convert at the same rate at the
    same instant — which is the point of bd:shotockviz-la4.
    """
    resolve = fx_resolver(dict(fx_rates))
    plan = CurveFxPlan(basis=CURVE_BASIS_SINGLE_CURRENCY)

    for symbol, h in holdings.items():
        if h.currency_conflict:
            plan.currency_conflict_symbols.append(symbol)
            continue
        currency = _currency_str(h.currency)
        rate = resolve(currency)
        if rate is None:
            plan.fx_unavailable_symbols.append(symbol)
            continue
        plan.rate_by_symbol[symbol] = rate.rate
        if currency != BASE_CURRENCY:
            plan.basis = CURVE_BASIS_CONSTANT_RATE
            plan.fx_rates[currency] = rate
            if rate.estimated:
                plan.fx_estimated = True

    plan.currency_conflict_symbols.sort()
    plan.fx_unavailable_symbols.sort()
    return plan
