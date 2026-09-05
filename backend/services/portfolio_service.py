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

Money is `float` here only because `models/portfolio.py:33-35` stores qty/price/fee
as `Float`. The Decimal/Numeric migration is a separate bead (Tara N8) and is NOT
started here. The arithmetic below adds exactly one new term per BUY (`+ fee`),
so it introduces no new rounding behaviour beyond that term.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable, Iterable, Mapping, Sequence

# Positions below this size are treated as fully closed. Also used as the
# float-drift guard after a SELL (the previous code used 1e-6 in portfolio.py
# and a *different* 0.001 "active" threshold in dashboard.py — unified here).
QTY_EPSILON = 1e-6


def _currency_str(value) -> str:
    """Normalise a `Currency` enum / str / None to a plain upper-case code."""
    if value is None:
        return "THB"
    raw = getattr(value, "value", value)
    return str(raw).upper() or "THB"


@dataclass
class Holding:
    """Net open position for one symbol, built from raw transactions."""

    symbol: str
    qty: float = 0.0
    cost_basis: float = 0.0  # includes BUY commission (rule 1)
    currency: str = "THB"
    realized_fees: float = 0.0  # SELL commission — realized side, not cost basis

    @property
    def avg_cost(self) -> float:
        return self.cost_basis / self.qty if self.qty > QTY_EPSILON else 0.0


@dataclass
class ValuedHolding:
    """A `Holding` priced against one quote. `current_*` are None when unpriced."""

    symbol: str
    qty: float
    avg_cost: float
    cost_basis: float
    currency: str
    current_price: float | None = None
    current_value: float | None = None
    unrealized_pl: float | None = None
    unrealized_pl_pct: float | None = None

    @property
    def priced(self) -> bool:
        return self.current_price is not None


@dataclass
class PortfolioTotals:
    total_value: float = 0.0
    total_cost: float = 0.0
    unrealized_pl: float = 0.0
    unrealized_pl_pct: float = 0.0
    priced_symbols: list[str] = field(default_factory=list)
    unpriced_symbols: list[str] = field(default_factory=list)


def build_holdings(txns: Iterable) -> dict[str, Holding]:
    """Fold transactions (chronological order) into net positions per symbol."""
    holdings: dict[str, Holding] = {}

    for t in txns:
        symbol = t.symbol
        if symbol not in holdings:
            holdings[symbol] = Holding(
                symbol=symbol,
                currency=_currency_str(getattr(t, "currency", None)),
            )
        h = holdings[symbol]

        qty = float(t.qty or 0.0)
        price = float(t.price or 0.0)
        fee = float(getattr(t, "fee", 0.0) or 0.0)
        txn_type = getattr(t.type, "value", t.type)

        if txn_type == "BUY":
            h.qty += qty
            h.cost_basis += qty * price + fee  # rule 1: buy fee -> cost basis
        else:  # SELL
            avg = h.avg_cost  # avg BEFORE reducing qty
            h.qty -= qty
            h.cost_basis -= qty * avg
            h.realized_fees += fee  # rule 1: sell fee -> realized, not cost basis
            if abs(h.qty) < QTY_EPSILON:  # float-drift guard
                h.qty = 0.0
                h.cost_basis = 0.0

    return holdings


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
) -> list[ValuedHolding]:
    """Price each holding against `quotes` (cache blobs keyed by symbol)."""
    valued: list[ValuedHolding] = []

    for symbol, h in holdings.items():
        price = usable_price(quotes.get(symbol))
        value = price * h.qty if price is not None else None
        pl = (value - h.cost_basis) if value is not None else None
        pl_pct = (pl / h.cost_basis * 100) if (pl is not None and h.cost_basis) else None

        valued.append(ValuedHolding(
            symbol=symbol,
            qty=h.qty,
            avg_cost=h.avg_cost,
            cost_basis=h.cost_basis,
            currency=h.currency,
            current_price=price,
            current_value=value,
            unrealized_pl=pl,
            unrealized_pl_pct=pl_pct,
        ))

    return valued


def summarize(
    valued: Sequence[ValuedHolding],
    fx: Callable[[str], float] | None = None,
) -> PortfolioTotals:
    """Aggregate priced positions only (rule 2).

    `fx` maps a currency code to a multiplier applied to BOTH value and cost of
    that position (dashboard normalises to THB; portfolio analytics passes None
    = identity, keeping its existing native-currency behaviour — the FX honesty
    problem there is bd:shotockviz-fnn, out of scope here).
    """
    rate = fx or (lambda _currency: 1.0)
    totals = PortfolioTotals()

    for v in valued:
        if not v.priced:
            totals.unpriced_symbols.append(v.symbol)
            continue
        f = rate(v.currency)
        totals.total_value += (v.current_value or 0.0) * f
        totals.total_cost += v.cost_basis * f
        totals.priced_symbols.append(v.symbol)

    totals.unrealized_pl = totals.total_value - totals.total_cost
    totals.unrealized_pl_pct = (
        totals.unrealized_pl / totals.total_cost * 100 if totals.total_cost else 0.0
    )
    return totals
