"""Celery task: populate stocks table with major index constituents.

Pre-loads S&P 500, NASDAQ 100, and SET 100 symbols into the stocks table
so that search works instantly from local DB instead of Yahoo fallback.

Sources:
  - S&P 500: Wikipedia table
  - NASDAQ 100: Wikipedia table
  - SET 100: Hardcoded list (updated periodically from SET website)

Run once on setup, then periodically (weekly) to catch index rebalances.
"""
from __future__ import annotations
import time
import re

from celery import shared_task
from core.logger import get_logger

logger = get_logger(__name__)


# ── SET 100 constituents (as of 2026-03, from set.or.th) ─────────────────────
# These are the top SET100 symbols. Update periodically from SET website.
SET100_SYMBOLS = [
    "ADVANC", "AOT", "AWC", "BANPU", "BBL", "BCH", "BCP", "BCPG", "BDMS",
    "BEM", "BGRIM", "BH", "BJC", "BPP", "BTS", "CBG", "CENTEL", "CHG",
    "CK", "CKP", "COM7", "CPALL", "CPF", "CPN", "CRC", "DELTA", "DOHOME",
    "DTT", "EA", "EGCO", "EPG", "ERW", "GLOBAL", "GPSC", "GULF", "GUNKUL",
    "HMPRO", "INTUCH", "ITC", "IVL", "JMART", "JMT", "KBANK", "KCE",
    "KKP", "KTB", "KTC", "LH", "MAJOR", "MAKRO", "MEGA", "MINT",
    "MTC", "NRF", "OR", "ORI", "OSP", "PLANB", "PRM", "PSL",
    "PTG", "PTT", "PTTEP", "PTTGC", "QH", "RATCH", "RS", "SAWAD",
    "SCB", "SCC", "SCGP", "SINGER", "SPALI", "SPRC", "STA", "STEC",
    "STGT", "SUPER", "TASCO", "TCAP", "THAI", "THANI", "TISCO",
    "TKN", "TMB", "TOA", "TOP", "TPIPP", "TQM", "TRUE", "TTB",
    "TU", "TVO", "VGI", "WHA", "WHAUP",
]


def _fetch_sp500_symbols() -> list[tuple[str, str]]:
    """Fetch S&P 500 constituents from Wikipedia.

    Returns: [(symbol, company_name), ...]
    """
    import requests
    from io import StringIO

    url = "https://en.wikipedia.org/wiki/List_of_S%26P_500_companies"
    try:
        resp = requests.get(url, timeout=15, headers={"User-Agent": "ShotockViz/1.0"})
        resp.raise_for_status()
        html = resp.text

        # Parse the first table (S&P 500 constituent list)
        # Find rows with ticker symbols
        results = []
        # Simple regex to extract from wiki table: Symbol | Security | ...
        # Table rows: <td><a ...>AAPL</a></td><td>Apple Inc.</td>...
        rows = re.findall(
            r'<tr>\s*<td[^>]*>.*?<a[^>]*>([A-Z.]+)</a>.*?</td>\s*<td[^>]*>(.*?)</td>',
            html, re.DOTALL
        )
        for sym, name in rows:
            name_clean = re.sub(r'<[^>]+>', '', name).strip()
            if sym and len(sym) <= 10:
                results.append((sym.strip(), name_clean))

        logger.info("Fetched S&P 500 from Wikipedia", count=len(results))
        return results
    except Exception as e:
        logger.error("Failed to fetch S&P 500 list", error=str(e))
        return []


# ── International index constituents (top ~30 per market for fast search) ──────
# These are the major constituents. Full lists can be expanded later.
# Suffix mapping: .T=JP, .HK=HK, .L=UK, .DE=DE, .PA=FR, .SS=CN, .KS=KR

NIKKEI225_TOP = [
    ("7203.T", "Toyota Motor"), ("6758.T", "Sony Group"), ("6861.T", "Keyence"),
    ("8306.T", "Mitsubishi UFJ Financial"), ("9984.T", "SoftBank Group"),
    ("6501.T", "Hitachi"), ("9432.T", "NTT"), ("6902.T", "Denso"),
    ("4063.T", "Shin-Etsu Chemical"), ("8035.T", "Tokyo Electron"),
    ("7741.T", "HOYA"), ("4519.T", "Chugai Pharmaceutical"),
    ("9433.T", "KDDI"), ("6098.T", "Recruit Holdings"),
    ("7267.T", "Honda Motor"), ("8766.T", "Tokio Marine"),
    ("4568.T", "Daiichi Sankyo"), ("6367.T", "Daikin Industries"),
    ("7974.T", "Nintendo"), ("8001.T", "ITOCHU"),
    ("6594.T", "Nidec"), ("3382.T", "Seven & i Holdings"),
    ("4661.T", "Oriental Land"), ("9983.T", "Fast Retailing"),
    ("6988.T", "Nitto Denko"), ("8058.T", "Mitsubishi Corp"),
    ("8031.T", "Mitsui & Co"), ("4502.T", "Takeda Pharmaceutical"),
    ("6753.T", "Sharp"), ("2914.T", "Japan Tobacco"),
]

HANGSENG_TOP = [
    ("0700.HK", "Tencent Holdings"), ("9988.HK", "Alibaba Group"),
    ("0005.HK", "HSBC Holdings"), ("0941.HK", "China Mobile"),
    ("1299.HK", "AIA Group"), ("3690.HK", "Meituan"),
    ("0388.HK", "Hong Kong Exchanges"), ("9618.HK", "JD.com"),
    ("2318.HK", "Ping An Insurance"), ("0001.HK", "CK Hutchison"),
    ("0011.HK", "Hang Seng Bank"), ("0016.HK", "SHK Properties"),
    ("1398.HK", "ICBC"), ("0688.HK", "China Overseas Land"),
    ("0002.HK", "CLP Holdings"), ("0003.HK", "HK & China Gas"),
    ("2388.HK", "BOC Hong Kong"), ("0027.HK", "Galaxy Entertainment"),
    ("1928.HK", "Sands China"), ("0006.HK", "Power Assets"),
    ("9999.HK", "NetEase"), ("1810.HK", "Xiaomi"),
    ("9888.HK", "Baidu"), ("2020.HK", "ANTA Sports"),
    ("0883.HK", "CNOOC"), ("0175.HK", "Geely Automobile"),
]

FTSE100_TOP = [
    ("SHEL.L", "Shell plc"), ("AZN.L", "AstraZeneca"),
    ("HSBA.L", "HSBC Holdings"), ("ULVR.L", "Unilever"),
    ("BP.L", "BP plc"), ("GSK.L", "GSK plc"),
    ("RIO.L", "Rio Tinto"), ("REL.L", "RELX"),
    ("DGE.L", "Diageo"), ("LSEG.L", "London Stock Exchange Group"),
    ("BATS.L", "British American Tobacco"), ("NG.L", "National Grid"),
    ("CRH.L", "CRH plc"), ("CPG.L", "Compass Group"),
    ("VOD.L", "Vodafone Group"), ("PRU.L", "Prudential"),
    ("BA.L", "BAE Systems"), ("AAL.L", "Anglo American"),
    ("LLOY.L", "Lloyds Banking Group"), ("BARC.L", "Barclays"),
    ("ABF.L", "Associated British Foods"), ("BKG.L", "Berkeley Group"),
    ("RKT.L", "Reckitt Benckiser"), ("AHT.L", "Ashtead Group"),
]

DAX_TOP = [
    ("SAP.DE", "SAP SE"), ("SIE.DE", "Siemens AG"),
    ("ALV.DE", "Allianz SE"), ("DTE.DE", "Deutsche Telekom"),
    ("AIR.DE", "Airbus SE"), ("MBG.DE", "Mercedes-Benz Group"),
    ("MUV2.DE", "Munich Re"), ("BMW.DE", "BMW AG"),
    ("BAS.DE", "BASF SE"), ("IFX.DE", "Infineon Technologies"),
    ("VOW3.DE", "Volkswagen AG"), ("DHL.DE", "Deutsche Post DHL"),
    ("ADS.DE", "adidas AG"), ("HEN3.DE", "Henkel AG"),
    ("EOAN.DE", "E.ON SE"), ("BEI.DE", "Beiersdorf AG"),
    ("DB1.DE", "Deutsche Börse"), ("DTG.DE", "Daimler Truck"),
    ("P911.DE", "Porsche AG"), ("RHM.DE", "Rheinmetall AG"),
]

# China SSE 50 top constituents
SSE50_TOP = [
    ("600519.SS", "Kweichow Moutai"), ("601318.SS", "Ping An Insurance"),
    ("600036.SS", "China Merchants Bank"), ("600276.SS", "Jiangsu Hengrui"),
    ("601166.SS", "Industrial Bank"), ("600900.SS", "China Yangtze Power"),
    ("600887.SS", "Inner Mongolia Yili"), ("601888.SS", "China Tourism Group"),
    ("600309.SS", "Wanhua Chemical"), ("600030.SS", "CITIC Securities"),
    ("601012.SS", "LONGi Green Energy"), ("603259.SS", "WuXi AppTec"),
    ("600809.SS", "Shanxi Fenjiu"), ("601668.SS", "China State Construction"),
    ("600000.SS", "Shanghai Pudong Dev Bank"), ("601398.SS", "ICBC"),
]

# ── Yahoo suffix → market mapping for DB insert ──────────────────────────────
SUFFIX_TO_MARKET = {
    ".T": "JP", ".HK": "HK", ".L": "UK", ".DE": "DE",
    ".PA": "FR", ".SS": "CN", ".SZ": "CN", ".KS": "KR",
    ".AX": "AU", ".TO": "CA", ".TW": "TW", ".SI": "SG",
    ".MI": "IT", ".AS": "NL",
}

def _detect_market(symbol: str) -> str:
    """Detect market from Yahoo Finance suffix."""
    for suffix, market in SUFFIX_TO_MARKET.items():
        if symbol.endswith(suffix):
            return market
    return "US"


def _fetch_nasdaq100_symbols() -> list[tuple[str, str]]:
    """Fetch NASDAQ 100 constituents from Wikipedia.

    Wikipedia NASDAQ-100 table uses plain text tickers (no <a> tag around symbol).
    Format: <td>AAPL</td><td><a ...>Apple Inc.</a></td>

    Returns: [(symbol, company_name), ...]
    """
    import requests

    url = "https://en.wikipedia.org/wiki/Nasdaq-100"
    try:
        resp = requests.get(url, timeout=15, headers={"User-Agent": "ShotockViz/1.0"})
        resp.raise_for_status()
        html = resp.text

        results = []
        # NASDAQ table: <td>TICKER</td><td><a>Company Name</a></td>
        # Ticker is plain text, company name has <a> link
        rows = re.findall(
            r'<td[^>]*>\s*([A-Z]{1,5})\s*</td>\s*<td[^>]*>(.*?)</td>',
            html, re.DOTALL
        )
        for sym, name_cell in rows:
            name_clean = re.sub(r'<[^>]+>', '', name_cell).strip()
            if sym and name_clean and len(sym) <= 5:
                results.append((sym.strip(), name_clean))

        logger.info("Fetched NASDAQ 100 from Wikipedia", count=len(results))
        return results
    except Exception as e:
        logger.error("Failed to fetch NASDAQ 100 list", error=str(e))
        return []


@shared_task(bind=True, max_retries=2, default_retry_delay=120)
def populate_index_constituents(self):
    """Populate stocks table with S&P 500, NASDAQ 100, and SET 100 symbols.

    Uses ON CONFLICT DO NOTHING to avoid overwriting existing data.
    Fetches company names from Wikipedia (US) or yfinance (Thai).
    """
    start = time.time()
    try:
        from sqlalchemy import create_engine, text
        from core.config import settings

        engine = create_engine(settings.sync_database_url, pool_pre_ping=True)

        # ── Ensure new MarketType enum values exist in DB ──────────────────
        new_markets = ["JP", "CN", "HK", "UK", "DE", "FR", "NL", "KR", "AU", "CA", "TW", "SG", "IT"]
        with engine.begin() as conn:
            for mkt in new_markets:
                try:
                    conn.execute(text(f"ALTER TYPE markettype ADD VALUE IF NOT EXISTS '{mkt}'"))
                except Exception:
                    pass  # already exists or unsupported
        logger.info("MarketType enum values ensured", markets=new_markets)

        inserted = 0
        skipped = 0

        # ── S&P 500 ──────────────────────────────────────────────────────────
        sp500 = _fetch_sp500_symbols()
        with engine.begin() as conn:
            for sym, name in sp500:
                result = conn.execute(text("""
                    INSERT INTO stocks (symbol, name, market, is_active)
                    VALUES (:symbol, :name, 'US', true)
                    ON CONFLICT (symbol) DO NOTHING
                """), {"symbol": sym, "name": name})
                if result.rowcount > 0:
                    inserted += 1
                else:
                    skipped += 1

        logger.info("S&P 500 populated", inserted=inserted, skipped=skipped)

        # ── NASDAQ 100 ───────────────────────────────────────────────────────
        nq_inserted = 0
        nasdaq100 = _fetch_nasdaq100_symbols()
        with engine.begin() as conn:
            for sym, name in nasdaq100:
                result = conn.execute(text("""
                    INSERT INTO stocks (symbol, name, market, is_active)
                    VALUES (:symbol, :name, 'US', true)
                    ON CONFLICT (symbol) DO NOTHING
                """), {"symbol": sym, "name": name})
                if result.rowcount > 0:
                    nq_inserted += 1
        inserted += nq_inserted
        logger.info("NASDAQ 100 populated", inserted=nq_inserted)

        # ── SET 100 ──────────────────────────────────────────────────────────
        set_inserted = 0
        with engine.begin() as conn:
            for sym in SET100_SYMBOLS:
                bk_sym = f"{sym}.BK"
                result = conn.execute(text("""
                    INSERT INTO stocks (symbol, name, market, is_active)
                    VALUES (:symbol, :name, 'SET', true)
                    ON CONFLICT (symbol) DO NOTHING
                """), {"symbol": bk_sym, "name": sym})
                if result.rowcount > 0:
                    set_inserted += 1
        inserted += set_inserted
        logger.info("SET 100 populated", inserted=set_inserted)

        # ── International indices (Nikkei, HSI, FTSE, DAX, SSE) ────────────
        intl_lists = [
            ("Nikkei 225 (top)", NIKKEI225_TOP),
            ("Hang Seng (top)", HANGSENG_TOP),
            ("FTSE 100 (top)", FTSE100_TOP),
            ("DAX (top)", DAX_TOP),
            ("SSE 50 (top)", SSE50_TOP),
        ]
        intl_inserted = 0
        for label, symbols_list in intl_lists:
            count = 0
            with engine.begin() as conn:
                for sym, name in symbols_list:
                    market = _detect_market(sym)
                    result = conn.execute(text("""
                        INSERT INTO stocks (symbol, name, market, is_active)
                        VALUES (:symbol, :name, :market, true)
                        ON CONFLICT (symbol) DO NOTHING
                    """), {"symbol": sym, "name": name, "market": market})
                    if result.rowcount > 0:
                        count += 1
            intl_inserted += count
            logger.info(f"{label} populated", inserted=count)
        inserted += intl_inserted

        # ── Overview index symbols (^N225, ^HSI, etc.) ─────────────────────
        overview_indices = [
            ("^N225", "Nikkei 225", "JP"),
            ("^HSI", "Hang Seng Index", "HK"),
            ("000001.SS", "Shanghai Composite", "CN"),
            ("^FTSE", "FTSE 100", "UK"),
            ("^GDAXI", "DAX", "DE"),
            ("^FCHI", "CAC 40", "FR"),
            ("^KS11", "KOSPI", "KR"),
            ("^TWII", "TAIEX", "TW"),
            ("^STI", "Straits Times Index", "SG"),
            ("^AEX", "AEX Index", "NL"),
            ("^DJI", "Dow Jones Industrial", "US"),
            ("^GSPC", "S&P 500", "US"),
            ("^IXIC", "NASDAQ Composite", "US"),
            ("^SET.BK", "SET Index", "SET"),
        ]
        idx_inserted = 0
        with engine.begin() as conn:
            for sym, name, market in overview_indices:
                result = conn.execute(text("""
                    INSERT INTO stocks (symbol, name, market, is_active)
                    VALUES (:symbol, :name, :market, true)
                    ON CONFLICT (symbol) DO NOTHING
                """), {"symbol": sym, "name": name, "market": market})
                if result.rowcount > 0:
                    idx_inserted += 1
        inserted += idx_inserted
        logger.info("Overview indices populated", inserted=idx_inserted)

        # ── Trigger name_fetcher to fill in proper names ───────────────────
        try:
            from workers.celery_app import celery_app
            celery_app.send_task("workers.name_fetcher.prefetch_names")
            logger.info("Triggered name_fetcher to fill stock names")
        except Exception:
            pass

        elapsed = time.time() - start
        logger.info(
            "Index population complete",
            total_inserted=inserted,
            total_skipped=skipped,
            elapsed_sec=f"{elapsed:.2f}",
        )

    except Exception as exc:
        elapsed = time.time() - start
        logger.error("populate_index_constituents failed", error=str(exc), elapsed_sec=f"{elapsed:.2f}")
        raise self.retry(exc=exc)
