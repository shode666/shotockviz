"""Stocks router package.

bd:deps-2026-09 WP-B5 — mechanical split of the former single-file
`backend/api/routes/stocks.py` (672 LOC / 11 handlers) into this package,
per 03-stan-refactor-strategy.md §2.1. Zero handler-body edits in this
commit; `main.py:277 app.include_router(stocks.router)` needs NO change —
this package's `__init__.py` still exports a `router` with the exact same
prefix, so the import site is unaffected.

🔴 ROUTING-ORDER CONSTRAINT (AC-A3, 02-bella-brd-ac.md §cross-read):
FastAPI matches routes in REGISTRATION order. Sub-routers with static
paths (`search.py`'s /search /names, `quotes.py`'s /quotes) MUST be
included BEFORE sub-routers/routes with `/{symbol}/*` dynamic paths —
otherwise `GET /api/stocks/quotes` could get shadow-matched by
`/{symbol}/quote`'s parent pattern space. `quotes.py` itself defines BOTH
a static (`/quotes`) and a dynamic (`/{symbol}/quote`) route in ONE file;
its internal @router.get() order (static first) matters just as much as
the include_router() order below — see quotes.py's own docstring.
DO NOT reorder the four `include_router` calls below without re-verifying
this constraint (smoke test: `GET /api/stocks/quotes` must hit the batch
handler, not be captured by a `/{symbol}/quote`-shaped route).
"""
from fastapi import APIRouter

from . import fundamentals, history, news_events, quotes, search

router = APIRouter(prefix="/api/stocks", tags=["stocks"])

# ORDER MATTERS — see module docstring. Static-path routers first.
router.include_router(search.router)        # /search, /names — static
router.include_router(quotes.router)        # /quotes (static, defined first in-file) then /{symbol}/quote (dynamic)
router.include_router(history.router)       # /{symbol}/history, /{symbol}/rs — dynamic
router.include_router(fundamentals.router)  # /{symbol}/fundamentals, /financials, /earnings — dynamic
router.include_router(news_events.router)   # /{symbol}/news, /{symbol}/events — dynamic

__all__ = ["router"]
