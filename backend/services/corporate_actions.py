"""Corporate-action restatement for the portfolio book — bd:shotockviz-eb1.

THE RULE (one line):
    A split changes the UNITS a position is quoted in, not the money that was
    paid for it — so raw transactions stay raw and every read restates the
    pre-ex-date lots (qty ÷ factor, price × factor, cost basis unchanged).

Why read-time and not a stored rewrite
--------------------------------------
A transaction row is an OBSERVATION of a past event: it is what the broker
confirmation says, in the units that were in force on the trade date. That is
the same argument bd:shotockviz-fnn made for `transactions.fx_rate` — an
observation is not a derived field and must not be recomputed in place. Here the
argument is *stronger*, not weaker, because the restatement is a pure function of
(trade date, split table) and can therefore always be re-derived, while the
original observation, once overwritten, cannot. `services/price_adjuster.py`
already states the same doctrine for bars ("Raw data is NEVER modified in the DB")
and this module deliberately reads the SAME rows through the SAME loader and the
SAME Redis key (`corp_actions:{SYMBOL}`), so the chart and the book cannot come to
different conclusions about the same split. A second copy of the adjustment is
exactly what produced the three-way FX divergence bd:shotockviz-sbe/-la4 unified.

(An alert level is the opposite case and is handled the opposite way — see
`workers/corporate_actions_fetcher.py::rebase_price_alerts`. An alert is not a
record of the past, it is a standing instruction about the future, compared every
60 s against a live quote that is always in current units.)

What is restated, and what is not
---------------------------------
SPLIT   — restated. `ratio` follows the table's own convention
          (`models/corporate_action.py:41-44`): 0.5 for a 2:1 split, 0.25 for
          4:1. A lot dated strictly BEFORE `ex_date` becomes

              qty'   = qty / ratio        (100 -> 200 on a 2:1)
              price' = price * ratio      (50  -> 25  on a 2:1)
              cost'  = qty' * price' = qty * price      <- INVARIANT

          The invariant is the whole point and is asserted in the tests: a split
          moves no money, so cost basis, realized P&L and the commission are all
          untouched; only the per-share denomination moves.

          `txn_date < ex_date` is strict — the ex-date is by definition the first
          session that trades in the NEW units, so a trade ON the ex-date is
          already post-split. Same comparison `price_adjuster.adjust_prices`
          uses for bars (`action["ex_date"] > bar_date`, price_adjuster.py:87).

DIV     — NOT restated, deliberately. A cash dividend changes neither the share
          count nor the money paid for the shares. `price_adjuster` back-adjusts
          bars for dividends because a *chart* is a total-return series; a
          *position* is not. Folding dividends into cost basis would move the
          book's cost away from the cash the user actually spent while the
          valuation side still uses the raw market quote — a fabricated gain, the
          mirror image of the fabricated loss this bead removes. If dividend
          income is ever wanted it is a separate income line, not a cost-basis
          adjustment, and it needs holdings-on-ex-date data this table does not
          record.

RIGHTS  — NOT restated, and this is the part that CANNOT be done honestly with
          the data present. A rights offering only changes a holding if the
          holder SUBSCRIBED and paid; nothing in this system records whether the
          user subscribed, for how many, or at what price
          (`models/corporate_action.py` stores only symbol/ex_date/value/ratio).
          `price_adjuster` applies the RIGHTS ratio to bars anyway
          (price_adjuster.py:98-99) because the market price gapped regardless of
          what any individual holder did — that is true of the price and false of
          the position. Applying it here would invent a subscription. Positions
          in a symbol with a RIGHTS action are therefore reported by name
          (`Holding.rights_unstatable`) instead of silently adjusted or silently
          ignored — the same doctrine as `fx_unavailable_symbols`.

⚠️ General guidance from training memory (cutoff: this model's training cutoff,
   not source-verified) — the treatment above is this book's stated internal
   convention for a swing trader's own record. It is NOT tax output. Cost-basis
   and lot-relief rules for splits, rights and return-of-capital distributions
   differ by jurisdiction; validate with a Thai tax adviser / SEC Thailand and
   the user's broker statements (and, for a US book, the broker's 1099-B basis
   reporting) before any filing use. Same caveat already carried by
   `services/portfolio_service.py` rule 6.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date as _date, datetime
from typing import Iterable, Mapping, Sequence

SPLIT = "SPLIT"
RIGHTS = "RIGHTS"
DIV = "DIV"


@dataclass(frozen=True)
class SplitEvent:
    """One split, in the table's own ratio convention (0.5 == 2:1)."""

    ex_date: _date
    ratio: float


@dataclass(frozen=True)
class SymbolActions:
    """Everything this module needs to know about one symbol's actions."""

    splits: tuple[SplitEvent, ...] = ()
    # True when the symbol has a RIGHTS row. The position cannot be restated for
    # it (no subscription record) — reported, never guessed. See module docstring.
    has_rights: bool = False


EMPTY = SymbolActions()


def _parse_ex_date(value) -> _date | None:
    """`load_corporate_actions` hands back ISO strings; tolerate a real date."""
    if value is None:
        return None
    if isinstance(value, _date):
        return value.date() if isinstance(value, datetime) else value
    if isinstance(value, str):
        try:
            return _date.fromisoformat(value[:10])
        except ValueError:
            return None
    return None


def parse_actions(rows: Iterable[Mapping]) -> SymbolActions:
    """Turn one symbol's raw action dicts into the restatement inputs.

    Accepts exactly the dict shape `price_adjuster.load_corporate_actions`
    returns, so both surfaces read one table through one loader.

    A SPLIT row with a missing / non-numeric / non-positive ratio is DROPPED, not
    defaulted to 1.0: a ratio of 1.0 is a claim that the split had no effect,
    while dropping it leaves the position stated in whatever units the raw rows
    were in — the pre-existing behaviour, which is wrong in a way the user can
    already see, rather than newly wrong in a way they cannot.
    """
    splits: list[SplitEvent] = []
    has_rights = False

    for row in rows:
        action_type = str(row.get("action_type") or "").upper()
        if action_type == RIGHTS:
            has_rights = True
            continue
        if action_type != SPLIT:
            continue  # DIV and anything unknown: not a position event
        ex_date = _parse_ex_date(row.get("ex_date"))
        if ex_date is None:
            continue
        raw = row.get("ratio")
        if raw is None:
            continue
        try:
            ratio = float(raw)
        except (TypeError, ValueError):
            continue
        if not (ratio > 0) or ratio == 1.0:
            continue
        splits.append(SplitEvent(ex_date=ex_date, ratio=ratio))

    splits.sort(key=lambda s: s.ex_date)
    return SymbolActions(splits=tuple(splits), has_rights=has_rights)


def split_factor(
    actions: SymbolActions | None,
    txn_date: _date | None,
    as_of: _date | None = None,
) -> float:
    """Cumulative ratio to apply to a lot dated `txn_date`, as seen on `as_of`.

    Product of the ratios of every split with `txn_date < ex_date <= as_of`.
    `as_of=None` means "now" — every recorded split counts, which is the right
    basis for a position valued against a live quote.

    `as_of` exists for the equity curve: on day D the raw close in the OHLCV
    cache is in D's units, so the quantity multiplied by it must be too. Passing
    the walked date makes each point of the line internally consistent instead of
    valuing today's share count against a pre-split price.

    Returns 1.0 (no restatement) when the lot has no date — the units of a lot
    whose trade date is unknown cannot be established, and 1.0 is the only
    non-inventing answer. `transactions.date` is NOT NULL
    (`models/portfolio.py:59`), so this is a defensive branch, not a live path.
    """
    if actions is None or txn_date is None:
        return 1.0
    # A `datetime` is a `date` subclass and compares fine against another
    # datetime but raises against a plain date. `transactions.date` is a DATE
    # column, yet at least one caller reaches here through an
    # `isinstance(x, date)` test that a datetime also passes
    # (api/routes/portfolio_performance.py::compute_holdings_on) — normalise
    # rather than let a TypeError decide a share count.
    txn_date = _parse_ex_date(txn_date)
    as_of = _parse_ex_date(as_of)
    if txn_date is None:
        return 1.0
    factor = 1.0
    for ev in actions.splits:
        if txn_date < ev.ex_date and (as_of is None or ev.ex_date <= as_of):
            factor *= ev.ratio
    return factor


def restate(
    qty: float,
    price: float,
    factor: float,
) -> tuple[float, float]:
    """Apply a `split_factor` to one lot. `qty*price` is invariant by construction."""
    if factor == 1.0 or not (factor > 0):
        return qty, price
    return qty / factor, price * factor


async def load_actions(symbols: Sequence[str]) -> dict[str, SymbolActions]:
    """Load the action table for `symbols` through the price adjuster's loader.

    Redis L1 (`corp_actions:{SYMBOL}`, 6 h) -> PostgreSQL L2, i.e. the exact path
    and cache entry `GET /stocks/{symbol}/history?adjusted=true` already uses. No
    external call — CQRS pure-read like every other portfolio read.

    A symbol with no rows maps to `EMPTY`, so callers can index unconditionally.
    """
    from services.price_adjuster import load_corporate_actions

    out: dict[str, SymbolActions] = {}
    for symbol in {s.upper() for s in symbols}:
        try:
            rows = await load_corporate_actions(symbol)
        except Exception:
            rows = []
        out[symbol] = parse_actions(rows) if rows else EMPTY
    return out
