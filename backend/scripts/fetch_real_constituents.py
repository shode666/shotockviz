"""Fetch REAL index constituents from Wikipedia and insert into DB.

Usage (inside backend container):
  docker-compose -f docker-compose.dev.yml exec backend python scripts/fetch_real_constituents.py

Sources:
  - Nikkei 225: https://en.wikipedia.org/wiki/Nikkei_225
  - Hang Seng:  https://en.wikipedia.org/wiki/Hang_Seng_Index
  - FTSE 100:   https://en.wikipedia.org/wiki/FTSE_100_Index
  - DAX:        https://en.wikipedia.org/wiki/DAX
  - SSE 50:     https://en.wikipedia.org/wiki/SSE_50_Index
  - CAC 40:     https://en.wikipedia.org/wiki/CAC_40
  - AEX:        https://en.wikipedia.org/wiki/AEX_index
"""
import asyncio
import sys
import os
import re

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import requests
from bs4 import BeautifulSoup

HEADERS = {"User-Agent": "Mozilla/5.0 (ShotockViz/0.1)"}

# ── suffix → market / yahoo suffix per index ──────────────────────────────────
SUFFIX_TO_MARKET = {
    ".T": "JP", ".HK": "HK", ".L": "UK", ".DE": "DE",
    ".PA": "FR", ".SS": "CN", ".SZ": "CN", ".AS": "NL",
    ".KS": "KR",
}


def detect_market(symbol: str) -> str:
    for suffix, market in SUFFIX_TO_MARKET.items():
        if symbol.endswith(suffix):
            return market
    return "US"


# ═══════════════════════════════════════════════════════════════════════════════
# Fetchers — each returns [(yahoo_symbol, company_name), ...]
# ═══════════════════════════════════════════════════════════════════════════════

def fetch_nikkei225() -> list[tuple[str, str]]:
    """Nikkei 225 from Wikipedia — ticker column + company name."""
    url = "https://en.wikipedia.org/wiki/Nikkei_225"
    print(f"  Fetching {url} ...")
    resp = requests.get(url, headers=HEADERS, timeout=30)
    soup = BeautifulSoup(resp.text, "html.parser")

    results = []
    # Find tables with "Ticker" or "Code" header
    for table in soup.find_all("table", class_="wikitable"):
        headers = [th.get_text(strip=True).lower() for th in table.find_all("th")]
        # Look for ticker/code column and company column
        ticker_idx = None
        name_idx = None
        for i, h in enumerate(headers):
            if h in ("ticker", "code", "ticker symbol", "stock code"):
                ticker_idx = i
            if h in ("company", "company name", "name"):
                name_idx = i

        if ticker_idx is None:
            continue

        for tr in table.find_all("tr")[1:]:
            cells = tr.find_all(["td", "th"])
            if len(cells) <= max(ticker_idx, name_idx or 0):
                continue

            raw_ticker = cells[ticker_idx].get_text(strip=True)
            # Extract just digits from ticker
            ticker_digits = re.sub(r'[^\d]', '', raw_ticker)
            if not ticker_digits or len(ticker_digits) < 4:
                continue

            name = cells[name_idx].get_text(strip=True) if name_idx is not None else ""
            # Clean name
            name = re.sub(r'\[.*?\]', '', name).strip()

            yahoo_sym = f"{ticker_digits}.T"
            results.append((yahoo_sym, name))

    print(f"    → Found {len(results)} symbols")
    return results


def fetch_hangseng() -> list[tuple[str, str]]:
    """Hang Seng Index from Wikipedia."""
    url = "https://en.wikipedia.org/wiki/Hang_Seng_Index"
    print(f"  Fetching {url} ...")
    resp = requests.get(url, headers=HEADERS, timeout=30)
    soup = BeautifulSoup(resp.text, "html.parser")

    results = []
    for table in soup.find_all("table", class_="wikitable"):
        headers = [th.get_text(strip=True).lower() for th in table.find_all("th")]

        ticker_idx = None
        name_idx = None
        for i, h in enumerate(headers):
            if any(k in h for k in ("ticker", "code", "stock code", "hkex")):
                ticker_idx = i
            if any(k in h for k in ("company", "name")):
                name_idx = i

        if ticker_idx is None:
            continue

        for tr in table.find_all("tr")[1:]:
            cells = tr.find_all(["td", "th"])
            if len(cells) <= max(ticker_idx, name_idx or 0):
                continue

            raw = cells[ticker_idx].get_text(strip=True)
            digits = re.sub(r'[^\d]', '', raw)
            if not digits:
                continue

            name = cells[name_idx].get_text(strip=True) if name_idx is not None else ""
            name = re.sub(r'\[.*?\]', '', name).strip()

            # HK tickers are zero-padded to 4 digits
            yahoo_sym = f"{digits.zfill(4)}.HK"
            results.append((yahoo_sym, name))

    print(f"    → Found {len(results)} symbols")
    return results


def fetch_ftse100() -> list[tuple[str, str]]:
    """FTSE 100 from Wikipedia."""
    url = "https://en.wikipedia.org/wiki/FTSE_100_Index"
    print(f"  Fetching {url} ...")
    resp = requests.get(url, headers=HEADERS, timeout=30)
    soup = BeautifulSoup(resp.text, "html.parser")

    results = []
    for table in soup.find_all("table", class_="wikitable"):
        headers = [th.get_text(strip=True).lower() for th in table.find_all("th")]

        ticker_idx = None
        name_idx = None
        for i, h in enumerate(headers):
            if any(k in h for k in ("epic", "ticker", "lse")):
                ticker_idx = i
            if "company" in h:
                name_idx = i

        if ticker_idx is None or name_idx is None:
            continue

        for tr in table.find_all("tr")[1:]:
            cells = tr.find_all(["td", "th"])
            if len(cells) <= max(ticker_idx, name_idx):
                continue

            ticker = cells[ticker_idx].get_text(strip=True).upper()
            name = cells[name_idx].get_text(strip=True)
            name = re.sub(r'\[.*?\]', '', name).strip()

            if not ticker or len(ticker) > 6:
                continue

            yahoo_sym = f"{ticker}.L"
            results.append((yahoo_sym, name))

    print(f"    → Found {len(results)} symbols")
    return results


def fetch_dax() -> list[tuple[str, str]]:
    """DAX from Wikipedia."""
    url = "https://en.wikipedia.org/wiki/DAX"
    print(f"  Fetching {url} ...")
    resp = requests.get(url, headers=HEADERS, timeout=30)
    soup = BeautifulSoup(resp.text, "html.parser")

    results = []
    for table in soup.find_all("table", class_="wikitable"):
        headers = [th.get_text(strip=True).lower() for th in table.find_all("th")]

        ticker_idx = None
        name_idx = None
        for i, h in enumerate(headers):
            if any(k in h for k in ("ticker", "symbol", "xetra")):
                ticker_idx = i
            if "company" in h or "name" in h:
                name_idx = i

        if ticker_idx is None or name_idx is None:
            continue

        for tr in table.find_all("tr")[1:]:
            cells = tr.find_all(["td", "th"])
            if len(cells) <= max(ticker_idx, name_idx):
                continue

            ticker = cells[ticker_idx].get_text(strip=True).upper()
            name = cells[name_idx].get_text(strip=True)
            name = re.sub(r'\[.*?\]', '', name).strip()

            if not ticker or len(ticker) > 8:
                continue

            yahoo_sym = f"{ticker}.DE"
            results.append((yahoo_sym, name))

    print(f"    → Found {len(results)} symbols")
    return results


def fetch_sse50() -> list[tuple[str, str]]:
    """SSE 50 from Wikipedia."""
    url = "https://en.wikipedia.org/wiki/SSE_50_Index"
    print(f"  Fetching {url} ...")
    resp = requests.get(url, headers=HEADERS, timeout=30)
    soup = BeautifulSoup(resp.text, "html.parser")

    results = []
    for table in soup.find_all("table", class_="wikitable"):
        headers = [th.get_text(strip=True).lower() for th in table.find_all("th")]

        ticker_idx = None
        name_idx = None
        for i, h in enumerate(headers):
            if any(k in h for k in ("ticker", "code", "stock code")):
                ticker_idx = i
            if any(k in h for k in ("company", "name", "stock name")):
                name_idx = i

        if ticker_idx is None:
            continue

        for tr in table.find_all("tr")[1:]:
            cells = tr.find_all(["td", "th"])
            if len(cells) <= max(ticker_idx, name_idx or 0):
                continue

            raw = cells[ticker_idx].get_text(strip=True)
            digits = re.sub(r'[^\d]', '', raw)
            if not digits or len(digits) < 6:
                continue

            name = cells[name_idx].get_text(strip=True) if name_idx is not None else ""
            name = re.sub(r'\[.*?\]', '', name).strip()

            yahoo_sym = f"{digits}.SS"
            results.append((yahoo_sym, name))

    print(f"    → Found {len(results)} symbols")
    return results


def fetch_cac40() -> list[tuple[str, str]]:
    """CAC 40 from Wikipedia."""
    url = "https://en.wikipedia.org/wiki/CAC_40"
    print(f"  Fetching {url} ...")
    resp = requests.get(url, headers=HEADERS, timeout=30)
    soup = BeautifulSoup(resp.text, "html.parser")

    results = []
    for table in soup.find_all("table", class_="wikitable"):
        headers = [th.get_text(strip=True).lower() for th in table.find_all("th")]

        ticker_idx = None
        name_idx = None
        for i, h in enumerate(headers):
            if any(k in h for k in ("ticker", "symbol", "euronext")):
                ticker_idx = i
            if "company" in h or "name" in h:
                name_idx = i

        if ticker_idx is None or name_idx is None:
            continue

        for tr in table.find_all("tr")[1:]:
            cells = tr.find_all(["td", "th"])
            if len(cells) <= max(ticker_idx, name_idx):
                continue

            ticker = cells[ticker_idx].get_text(strip=True).upper()
            name = cells[name_idx].get_text(strip=True)
            name = re.sub(r'\[.*?\]', '', name).strip()

            if not ticker or len(ticker) > 6:
                continue

            yahoo_sym = f"{ticker}.PA"
            results.append((yahoo_sym, name))

    print(f"    → Found {len(results)} symbols")
    return results


def fetch_aex() -> list[tuple[str, str]]:
    """AEX from Wikipedia."""
    url = "https://en.wikipedia.org/wiki/AEX_index"
    print(f"  Fetching {url} ...")
    resp = requests.get(url, headers=HEADERS, timeout=30)
    soup = BeautifulSoup(resp.text, "html.parser")

    results = []
    for table in soup.find_all("table", class_="wikitable"):
        headers = [th.get_text(strip=True).lower() for th in table.find_all("th")]

        ticker_idx = None
        name_idx = None
        for i, h in enumerate(headers):
            if any(k in h for k in ("ticker", "symbol", "euronext")):
                ticker_idx = i
            if "company" in h or "name" in h:
                name_idx = i

        if ticker_idx is None or name_idx is None:
            continue

        for tr in table.find_all("tr")[1:]:
            cells = tr.find_all(["td", "th"])
            if len(cells) <= max(ticker_idx, name_idx):
                continue

            ticker = cells[ticker_idx].get_text(strip=True).upper()
            name = cells[name_idx].get_text(strip=True)
            name = re.sub(r'\[.*?\]', '', name).strip()

            if not ticker or len(ticker) > 6:
                continue

            yahoo_sym = f"{ticker}.AS"
            results.append((yahoo_sym, name))

    print(f"    → Found {len(results)} symbols")
    return results


# ── International indices ──────────────────────────────────────────────────────
INTL_INDICES = [
    ("^N225", "Nikkei 225", "JP"),
    ("^HSI", "Hang Seng Index", "HK"),
    ("000001.SS", "Shanghai Composite", "CN"),
    ("^FTSE", "FTSE 100", "UK"),
    ("^GDAXI", "DAX", "DE"),
    ("^FCHI", "CAC 40", "FR"),
    ("^AEX", "AEX Index", "NL"),
    ("^KS11", "KOSPI", "KR"),
]


# ═══════════════════════════════════════════════════════════════════════════════
# Main
# ═══════════════════════════════════════════════════════════════════════════════

async def main():
    from sqlalchemy import text
    from core.database import AsyncSessionLocal, engine

    # ── Step 1: Ensure enum values ──
    print("\n[1/4] Ensuring MarketType enum values...")
    new_markets = ["JP", "CN", "HK", "UK", "DE", "FR", "NL", "KR"]
    async with engine.begin() as conn:
        for mkt in new_markets:
            try:
                await conn.execute(text(f"ALTER TYPE markettype ADD VALUE IF NOT EXISTS '{mkt}'"))
            except Exception:
                pass
    print(f"  ✅ Done")

    # ── Step 2: Fetch real data from Wikipedia ──
    print("\n[2/4] Fetching real constituents from Wikipedia...")
    fetchers = [
        ("JP  — Nikkei 225", fetch_nikkei225),
        ("HK  — Hang Seng", fetch_hangseng),
        ("UK  — FTSE 100", fetch_ftse100),
        ("DE  — DAX", fetch_dax),
        ("CN  — SSE 50", fetch_sse50),
        ("FR  — CAC 40", fetch_cac40),
        ("NL  — AEX", fetch_aex),
    ]

    all_data: list[tuple[str, list[tuple[str, str]]]] = []
    for label, fn in fetchers:
        try:
            symbols = fn()
            all_data.append((label, symbols))
        except Exception as e:
            print(f"  ❌ {label} FAILED: {e}")
            all_data.append((label, []))

    # ── Step 3: Insert into DB ──
    print(f"\n[3/4] Inserting into database...")
    total_inserted = 0
    total_skipped = 0

    async with AsyncSessionLocal() as db:
        for label, symbols_list in all_data:
            inserted = 0
            skipped = 0
            for sym, name in symbols_list:
                market = detect_market(sym)
                result = await db.execute(text("""
                    INSERT INTO stocks (symbol, name, market, is_active)
                    VALUES (:symbol, :name, :market, true)
                    ON CONFLICT (symbol) DO NOTHING
                """), {"symbol": sym, "name": name, "market": market})
                if result.rowcount > 0:
                    inserted += 1
                else:
                    skipped += 1
            await db.commit()
            total_inserted += inserted
            total_skipped += skipped
            status = f"+{inserted} new" + (f", {skipped} exist" if skipped else "")
            print(f"  {label}: {status}")

        # ── Indices ──
        idx_inserted = 0
        for sym, name, market in INTL_INDICES:
            result = await db.execute(text("""
                INSERT INTO stocks (symbol, name, market, is_active)
                VALUES (:symbol, :name, :market, true)
                ON CONFLICT (symbol) DO NOTHING
            """), {"symbol": sym, "name": name, "market": market})
            if result.rowcount > 0:
                idx_inserted += 1
        await db.commit()
        total_inserted += idx_inserted
        print(f"  Indices: +{idx_inserted} new")

    # ── Step 4: Summary ──
    print(f"\n[4/4] Summary")
    print(f"{'='*50}")
    print(f"  ✅ Total inserted: {total_inserted}")
    print(f"  ⏭  Already existed: {total_skipped}")
    print(f"\n  Verify: python scripts/check_intl_symbols.py")


if __name__ == "__main__":
    asyncio.run(main())
