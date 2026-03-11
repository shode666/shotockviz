"""Celery task: fetch Thai mutual fund NAV data.

Primary source: SEC Open Data API (api.sec.or.th)
  - Requires 2 free API keys from https://api-portal.sec.or.th
  - "Fund Factsheet" key → list AMCs + funds → get proj_id mapping
  - "Fund Daily Info" key → daily NAV by proj_id

Fallback: Finnomena public API (no auth required, less reliable)

Flow:
  1. Build proj_id ↔ fund_abbr_name mapping (cached in Redis 24h)
  2. For each FUND symbol in stocks table → lookup proj_id → fetch daily NAV
  3. Cache in Redis fund:{symbol} with 24h TTL
  4. Publish WS nav_update notification
"""
from __future__ import annotations
import json
import time
from datetime import datetime, timezone, timedelta

from celery import shared_task
from core.logger import get_logger
from core import cache_keys

logger = get_logger(__name__)

import re
_SAFE_SYMBOL_RE = re.compile(r'^[A-Za-z0-9&\s._\-]{1,50}$')

def _validate_symbol(symbol: str) -> bool:
    """Return True if symbol contains only safe characters."""
    return bool(_SAFE_SYMBOL_RE.match(symbol))

# ── SEC Open Data API endpoints ─────────────────────────────────────────────
SEC_AMC_LIST_URL = "https://api.sec.or.th/FundFactsheet/fund/amc"
SEC_AMC_FUNDS_URL = "https://api.sec.or.th/FundFactsheet/fund/amc/{unique_id}"
SEC_DAILY_NAV_URL = "https://api.sec.or.th/FundDailyInfo/{proj_id}/dailynav/{nav_date}"

# ── Finnomena fallback endpoint ─────────────────────────────────────────────
FINNOMENA_FUND_URL = "https://www.finnomena.com/fn3/api/fund/public/list"

# Redis cache key for proj_id mapping (rebuilt daily)
PROJ_MAP_CACHE_KEY = "cache:sec:proj_id_map"
PROJ_MAP_TTL = 86400  # 24 hours


def _build_proj_id_map(factsheet_key: str) -> dict[str, str]:
    """Build mapping: fund_abbr_name (uppercase) → proj_id from SEC API.

    Calls SEC FundFactsheet API to enumerate ALL Thai mutual funds.
    Caches the result in Redis for 24h to avoid repeated enumeration.

    Returns: {"MPDIVMF": "P0001234", "SCBS&P500": "P0005678", ...}
    """
    import requests
    import redis
    from core.config import settings

    # Check Redis cache first
    try:
        redis_client = redis.from_url(settings.redis_url)
        cached = redis_client.get(PROJ_MAP_CACHE_KEY)
        if cached:
            logger.debug("Using cached proj_id map")
            return json.loads(cached)
    except Exception:
        pass

    headers = {"Ocp-Apim-Subscription-Key": factsheet_key, "Accept": "application/json"}
    mapping: dict[str, str] = {}

    try:
        # Step 1: Get all AMC (Asset Management Companies)
        resp = requests.get(SEC_AMC_LIST_URL, headers=headers, timeout=15)
        resp.raise_for_status()
        amcs = resp.json()
        logger.info("SEC API: found AMCs", count=len(amcs))

        # Step 2: For each AMC, get their funds
        for amc in amcs:
            unique_id = amc.get("unique_id")
            if not unique_id:
                continue
            try:
                fund_resp = requests.get(
                    SEC_AMC_FUNDS_URL.format(unique_id=unique_id),
                    headers=headers,
                    timeout=10,
                )
                if fund_resp.status_code != 200:
                    continue
                funds = fund_resp.json()
                for fund in funds:
                    proj_id = fund.get("proj_id")
                    abbr = fund.get("proj_abbr_name", "").strip()
                    status = fund.get("fund_status", "")
                    if proj_id and abbr and status == "RG":  # RG = registered (active)
                        mapping[abbr.upper()] = proj_id
                # Be nice to API
                time.sleep(0.15)
            except Exception as e:
                logger.debug("Failed to list funds for AMC", unique_id=unique_id, error=str(e))
                continue

        logger.info("SEC proj_id map built", total_funds=len(mapping))

        # Cache in Redis
        try:
            redis_client = redis.from_url(settings.redis_url)
            redis_client.setex(PROJ_MAP_CACHE_KEY, PROJ_MAP_TTL, json.dumps(mapping))
        except Exception:
            pass

    except Exception as e:
        logger.error("Failed to build proj_id map", error=str(e))

    return mapping


def _fetch_nav_sec(proj_id: str, daily_info_key: str, symbol: str = "", nav_date: str | None = None) -> dict | None:
    """Fetch NAV from SEC FundDailyInfo API by proj_id.

    SEC returns multiple share classes per proj_id (e.g. -A, -C, -D, -R).
    We match class_abbr_name to the user's symbol to pick the right class.

    Args:
        proj_id: SEC project ID (e.g., "M0939_2553")
        daily_info_key: SEC Fund Daily Info API subscription key
        symbol: User-entered fund symbol for class matching (e.g., "PRINCIPAL IPROP-D")
        nav_date: Date string "YYYY-MM-DD". Defaults to yesterday (T-1).

    Returns: {"nav": 10.56, "date": "2026-03-02"} or None
    """
    import requests

    if not nav_date:
        # NAV is typically T-1 (published next business day)
        yesterday = datetime.now(timezone.utc) + timedelta(hours=7) - timedelta(days=1)
        nav_date = yesterday.strftime("%Y-%m-%d")

    headers = {"Ocp-Apim-Subscription-Key": daily_info_key, "Accept": "application/json"}
    sym_upper = symbol.upper().strip()

    # Try yesterday, then day before (weekend/holiday adjustment)
    for lookback in range(5):
        check_date = (datetime.strptime(nav_date, "%Y-%m-%d") - timedelta(days=lookback)).strftime("%Y-%m-%d")
        try:
            url = SEC_DAILY_NAV_URL.format(proj_id=proj_id, nav_date=check_date)
            resp = requests.get(url, headers=headers, timeout=10)
            if resp.status_code == 200:
                data = resp.json()
                if not isinstance(data, list) or not data:
                    continue

                # Try to find the matching share class
                item = None

                # 1. Exact class_abbr_name match (case-insensitive)
                for entry in data:
                    cls_name = (entry.get("class_abbr_name") or "").upper().strip()
                    if cls_name == sym_upper:
                        item = entry
                        break

                # 2. If symbol has suffix like -D, match class ending with same suffix
                if item is None and len(data) > 1:
                    import re
                    suffix_match = re.search(r'(-[A-Z]+)$', sym_upper)
                    if suffix_match:
                        suffix = suffix_match.group(1)
                        for entry in data:
                            cls_name = (entry.get("class_abbr_name") or "").upper().strip()
                            if cls_name.endswith(suffix):
                                item = entry
                                break

                # 3. Fallback: first entry (single class fund)
                if item is None:
                    item = data[0]

                nav_val = item.get("last_val") or item.get("nav")
                if nav_val:
                    result = {
                        "nav": float(nav_val),
                        "date": check_date,
                        "fund_name": item.get("proj_name_th") or item.get("proj_name_en") or item.get("class_abbr_name"),
                    }
                    # Try to get previous day NAV for change calculation
                    prev_nav = _find_prev_nav(item, data, proj_id, daily_info_key, check_date, sym_upper, headers)
                    if prev_nav is not None and prev_nav > 0:
                        result["prev_nav"] = prev_nav
                        result["change"] = round(float(nav_val) - prev_nav, 4)
                        result["change_pct"] = round(((float(nav_val) - prev_nav) / prev_nav) * 100, 2)
                    return result
            elif resp.status_code == 204:
                # No data for this date — try previous day
                continue
        except Exception:
            continue

    return None


def _fetch_nav_finnomena(symbol: str) -> dict | None:
    """Fallback: try to get NAV from Finnomena fund page.

    This is a best-effort approach using public fund data.
    """
    import requests

    if not _validate_symbol(symbol):
        logger.warning("Invalid fund symbol rejected", symbol=symbol)
        return None

    try:
        from urllib.parse import quote as url_quote
        safe_symbol = url_quote(symbol, safe='')
        # Try Finnomena's fund detail page API
        url = f"https://www.finnomena.com/fn3/api/fund/{safe_symbol}/nav/q?range=1D"
        resp = requests.get(url, timeout=10, headers={"Accept": "application/json"})
        if resp.status_code == 200:
            data = resp.json()
            if isinstance(data, list) and data:
                last = data[-1]
                nav = last.get("value") or last.get("nav")
                date_val = last.get("date") or last.get("nav_date")
                if nav:
                    return {
                        "nav": float(nav),
                        "date": str(date_val)[:10] if date_val else None,
                        "fund_name": symbol,
                    }
    except Exception as e:
        logger.debug("Finnomena fallback failed", symbol=symbol, error=str(e))

    return None


def _find_prev_nav(current_item: dict, current_data: list, proj_id: str,
                    daily_info_key: str, current_date: str, sym_upper: str,
                    headers: dict) -> float | None:
    """Find the previous day's NAV for change calculation.

    Looks back up to 5 business days from current_date.
    """
    import requests

    for lookback in range(1, 6):
        prev_date = (datetime.strptime(current_date, "%Y-%m-%d") - timedelta(days=lookback)).strftime("%Y-%m-%d")
        try:
            url = SEC_DAILY_NAV_URL.format(proj_id=proj_id, nav_date=prev_date)
            resp = requests.get(url, headers=headers, timeout=10)
            if resp.status_code == 200:
                data = resp.json()
                if not isinstance(data, list) or not data:
                    continue
                # Match same share class
                for entry in data:
                    cls_name = (entry.get("class_abbr_name") or "").upper().strip()
                    if cls_name == sym_upper:
                        val = entry.get("last_val")
                        if val:
                            return float(val)
                # Fallback: first entry for single-class funds
                if len(data) == 1:
                    val = data[0].get("last_val")
                    if val:
                        return float(val)
            elif resp.status_code == 204:
                continue
        except Exception:
            continue
    return None


def _resolve_proj_id(symbol: str, proj_map: dict[str, str]) -> str | None:
    """Fuzzy-match a user-entered fund symbol to SEC proj_abbr_name.

    Matching strategy (first match wins):
      0. Manual alias table for known mismatches
      1. Exact match: SCBS&P500FUND → SCBS&P500FUND
      2. Add common suffixes: SCBS&P500 + FUND → SCBS&P500FUND
      3. Strip common suffixes: PRINCIPAL IPROP-D → PRINCIPAL IPROP
      4. Strip suffixes like MF: MPDIVMF → MPDIV → check
      5. Best prefix match (>= 6 chars, unique)
    """
    # Manual aliases: user-entered symbol → SEC proj_abbr_name
    # Add entries here when automatic matching fails
    ALIASES: dict[str, str] = {
        "MPDIVMF": "M-PROP DIV",
    }

    sym = symbol.upper().strip()

    # 0. Manual alias
    alias = ALIASES.get(sym)
    if alias and alias in proj_map:
        return proj_map[alias]

    # 1. Exact match
    if sym in proj_map:
        return proj_map[sym]

    # 2. Try adding common suffixes
    for suffix in ["FUND", "-A", "-D"]:
        candidate = sym + suffix
        if candidate in proj_map:
            return proj_map[candidate]

    # 3. Strip common suffixes
    import re
    stripped = re.sub(r'(-D|-A|-R|-RA|-RD|-SSF|-SSFX|FUND|MF)$', '', sym)
    if stripped != sym and stripped in proj_map:
        return proj_map[stripped]

    # Also try stripped + FUND
    if stripped != sym:
        candidate = stripped + "FUND"
        if candidate in proj_map:
            return proj_map[candidate]

    # 4. Prefix match (at least 6 chars, must be unique)
    if len(sym) >= 6:
        matches = [(k, v) for k, v in proj_map.items() if k.startswith(sym)]
        if len(matches) == 1:
            return matches[0][1]

    # Also try stripped as prefix
    if stripped != sym and len(stripped) >= 5:
        matches = [(k, v) for k, v in proj_map.items() if k.startswith(stripped)]
        if len(matches) == 1:
            return matches[0][1]

    return None


@shared_task(bind=True, max_retries=2, default_retry_delay=60)
def fetch_thai_fund_navs(self):
    """
    Fetch Thai mutual fund NAV — primary: SEC Open Data API, fallback: Finnomena.

    Flow:
      1. Query DB for symbols with market type FUND
      2. Build proj_id mapping from SEC API (cached 24h)
      3. For each fund: SEC daily NAV → Finnomena fallback
      4. Cache in Redis fund:{symbol} as JSON with 86400s (24h) TTL
      5. Publish nav_update on price_updates channel
    """
    start = time.time()
    try:
        import redis
        from sqlalchemy import create_engine, text
        from core.config import settings

        # Connect to sync DB
        engine = create_engine(settings.sync_database_url, pool_pre_ping=True)

        # Query all FUND market symbols
        with engine.connect() as conn:
            rows = conn.execute(text(
                "SELECT symbol, name FROM stocks WHERE is_active = true AND market = 'FUND' ORDER BY symbol"
            )).fetchall()

        if not rows:
            logger.info("No fund symbols to fetch NAVs for")
            return

        redis_client = redis.from_url(settings.redis_url)

        # Determine data source based on API key availability
        has_sec_keys = bool(settings.sec_fund_factsheet_key and settings.sec_fund_daily_info_key)

        proj_map: dict[str, str] = {}
        if has_sec_keys:
            proj_map = _build_proj_id_map(settings.sec_fund_factsheet_key)
            if proj_map:
                logger.info("SEC API mode: proj_id map loaded", size=len(proj_map))
            else:
                logger.warning("SEC API: failed to build proj_id map, falling back to Finnomena")
        else:
            logger.info("No SEC API keys configured — using Finnomena fallback only")

        updated_count = 0
        failed_symbols = []

        for symbol, name in rows:
            try:
                result = None

                # Strategy 1: SEC API (if keys available + proj_id found)
                if has_sec_keys and proj_map:
                    proj_id = _resolve_proj_id(symbol, proj_map)
                    if proj_id:
                        result = _fetch_nav_sec(proj_id, settings.sec_fund_daily_info_key, symbol=symbol)
                        if result:
                            logger.info("Fund NAV fetched via SEC", symbol=symbol, proj_id=proj_id, nav=result["nav"])
                    else:
                        logger.debug("No proj_id match for fund", symbol=symbol)

                # Strategy 2: Finnomena fallback
                if result is None:
                    result = _fetch_nav_finnomena(symbol)

                if result is None:
                    failed_symbols.append(symbol)
                    logger.debug("Fund NAV not found from any source", symbol=symbol)
                    continue

                nav_val = result["nav"]
                nav_date = result.get("date") or datetime.now(timezone.utc).isoformat()

                # 1) Cache as fund:{symbol} (fund-specific data with NAV date)
                fund_payload = {
                    "symbol": symbol,
                    "fund_name": result.get("fund_name") or name or symbol,
                    "nav": nav_val,
                    "date": nav_date,
                    "ts": int(time.time()),
                }
                redis_client.setex(cache_keys.fund(symbol), 86400, json.dumps(fund_payload))

                # 2) Also cache as quote:{symbol} — same format as price_fetcher
                #    so portfolio, sidebar, dashboard read it without special fund logic
                quote_payload = {
                    "symbol": symbol,
                    "price": nav_val,
                    "change": result.get("change", 0.0),
                    "change_pct": result.get("change_pct", 0.0),
                    "volume": 0,
                    "type": "fund_nav",
                    "nav_date": str(nav_date)[:10],
                    "ts": int(time.time()),
                }
                redis_client.setex(cache_keys.quote(symbol), 86400, json.dumps(quote_payload))

                updated_count += 1

            except Exception as e:
                failed_symbols.append(symbol)
                logger.debug("Error fetching fund NAV", symbol=symbol, error=str(e))
                continue

        # Publish nav-update notification
        try:
            msg = {
                "type": "nav_update",
                "count": updated_count,
                "ts": int(time.time()),
            }
            redis_client.publish("price_updates", json.dumps(msg))
        except Exception as e:
            logger.debug("Failed to publish nav_update", error=str(e))

        elapsed = time.time() - start
        logger.info(
            "Fund NAVs prefetch complete",
            total=len(rows),
            updated=updated_count,
            failed=len(failed_symbols),
            failed_symbols=failed_symbols[:10],
            source="SEC+Finnomena" if has_sec_keys else "Finnomena",
            elapsed_sec=f"{elapsed:.2f}",
            ts=datetime.now(timezone.utc).isoformat(),
        )

    except Exception as exc:
        elapsed = time.time() - start
        logger.error("fetch_thai_fund_navs failed", error=str(exc), elapsed_sec=f"{elapsed:.2f}")
        raise self.retry(exc=exc)
