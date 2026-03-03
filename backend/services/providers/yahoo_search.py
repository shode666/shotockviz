"""Yahoo Finance search functionality — isolated from data fetching.

Handles search_yahoo_direct() + Thai exchange detection + symbol normalization.
"""
import re
from typing import Optional

import httpx

from core.logger import get_logger
from .yahoo_auth import _get_yf_auth, _get_http_sem, _YF_HEADERS

logger = get_logger(__name__)


async def search_yahoo_direct(query: str) -> list[dict]:
    """Search stocks using Yahoo Finance v1 search API.

    Searches both the raw query AND query+".BK" to catch Thai SET/MAI stocks.
    Yahoo often returns Thai stocks without .BK suffix — we detect them by
    exchange field and normalize the symbol.

    Pure async function. Returns list of dicts with symbol, name, market, type.
    """
    cookies, crumb = await _get_yf_auth()
    url = "https://query2.finance.yahoo.com/v1/finance/search"

    # Thai stock exchanges on Yahoo Finance
    _THAI_EXCHANGES = {"SET", "MAI", "BKK", "Bangkok"}

    async def _do_search(q: str) -> list[dict]:
        params: dict = {
            "q": q, "quotesCount": 10,
            "newsCount": 0, "listsCount": 0,
            "enableFuzzyQuery": "false", "enableCb": "false",
        }
        if crumb:
            params["crumb"] = crumb
        async with _get_http_sem():
            async with httpx.AsyncClient(
                headers=_YF_HEADERS, cookies=cookies or None,
                timeout=httpx.Timeout(8.0, connect=5.0)
            ) as client:
                res = await client.get(url, params=params)
                if res.status_code != 200:
                    return []
                return res.json().get("quotes", [])

    try:
        # Search both raw query and Thai variant (.BK suffix)
        queries = [query]
        # Only add .BK search if query looks like a plain symbol (no dots, no spaces)
        if re.match(r'^[A-Za-z0-9]+$', query.strip()):
            queries.append(f"{query.strip()}.BK")

        all_quotes: list[dict] = []
        seen_symbols: set[str] = set()

        for q in queries:
            quotes = await _do_search(q)
            for item in quotes[:10]:
                sym = item.get("symbol", "")
                if not sym or sym in seen_symbols:
                    continue
                seen_symbols.add(sym)
                all_quotes.append(item)

        out = []
        for q in all_quotes[:10]:
            sym = q.get("symbol", "")
            exchange = q.get("exchange", "")
            quote_type = q.get("quoteType", "")

            # Determine market from suffix or exchange
            _SUFFIX_MARKET = {
                ".BK": "SET", ".T": "JP", ".SS": "CN", ".SZ": "CN",
                ".HK": "HK", ".L": "UK", ".DE": "DE", ".PA": "FR",
                ".AS": "NL", ".MI": "IT", ".TO": "CA", ".AX": "AU",
                ".KS": "KR", ".TW": "TW", ".SI": "SG",
            }
            market = "US"  # default
            if sym.endswith(".BK") or exchange in _THAI_EXCHANGES:
                market = "SET"
                if not sym.endswith(".BK"):
                    sym = f"{sym}.BK"
            else:
                for suffix, mkt in _SUFFIX_MARKET.items():
                    if sym.endswith(suffix):
                        market = mkt
                        break

            out.append({
                "symbol": sym,
                "name": q.get("longname") or q.get("shortname", ""),
                "market": market,
                "type": quote_type,
            })
        return out
    except httpx.TimeoutException as e:
        logger.warning("Yahoo Finance search timed out", query=query, error=str(e))
        return []
    except Exception as e:
        logger.error("Yahoo Finance search error", query=query, error=str(e))
        return []
