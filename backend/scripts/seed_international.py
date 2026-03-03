"""Seed international market symbols directly into DB (no Celery needed).

Usage (inside backend container):
  docker-compose -f docker-compose.dev.yml exec backend python scripts/seed_international.py
"""
import asyncio
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# ── JP: Nikkei 225 top 30 ─────────────────────────────────────────────────────
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

# ── HK: Hang Seng top 26 ──────────────────────────────────────────────────────
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

# ── UK: FTSE 100 top 24 ───────────────────────────────────────────────────────
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

# ── DE: DAX top 20 ────────────────────────────────────────────────────────────
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

# ── CN: SSE 50 top 16 ─────────────────────────────────────────────────────────
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

# ── FR: CAC 40 top 20 ─────────────────────────────────────────────────────────
CAC40_TOP = [
    ("MC.PA", "LVMH"), ("OR.PA", "L'Oréal"),
    ("SAN.PA", "Sanofi"), ("AI.PA", "Air Liquide"),
    ("SU.PA", "Schneider Electric"), ("BNP.PA", "BNP Paribas"),
    ("TTE.PA", "TotalEnergies"), ("CS.PA", "AXA"),
    ("DG.PA", "Vinci"), ("SAF.PA", "Safran"),
    ("RI.PA", "Pernod Ricard"), ("KER.PA", "Kering"),
    ("CAP.PA", "Capgemini"), ("DSY.PA", "Dassault Systèmes"),
    ("BN.PA", "Danone"), ("SGO.PA", "Saint-Gobain"),
    ("RMS.PA", "Hermès"), ("EL.PA", "EssilorLuxottica"),
    ("LR.PA", "Legrand"), ("HO.PA", "Thales"),
]

# ── NL: AEX top 15 ────────────────────────────────────────────────────────────
AEX_TOP = [
    ("ASML.AS", "ASML Holding"), ("INGA.AS", "ING Group"),
    ("AD.AS", "Ahold Delhaize"), ("PHIA.AS", "Philips"),
    ("WKL.AS", "Wolters Kluwer"), ("UNA.AS", "Unilever"),
    ("HEIA.AS", "Heineken"), ("ABN.AS", "ABN AMRO"),
    ("RAND.AS", "Randstad"), ("AGN.AS", "Aegon"),
    ("ASM.AS", "ASM International"), ("AKZA.AS", "AkzoNobel"),
    ("DSM.AS", "DSM-Firmenich"), ("NN.AS", "NN Group"),
    ("PRX.AS", "Prosus"),
]

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
    ("^TWII", "TAIEX", "TW"),
    ("^STI", "Straits Times Index", "SG"),
]

# ── Suffix → market mapping ───────────────────────────────────────────────────
SUFFIX_TO_MARKET = {
    ".T": "JP", ".HK": "HK", ".L": "UK", ".DE": "DE",
    ".PA": "FR", ".SS": "CN", ".SZ": "CN", ".AS": "NL",
}


def _detect_market(symbol: str) -> str:
    for suffix, market in SUFFIX_TO_MARKET.items():
        if symbol.endswith(suffix):
            return market
    return "US"


async def main():
    from sqlalchemy import text
    from core.database import AsyncSessionLocal, engine

    # ── Step 1: Ensure enum values exist ──
    print("\n[1/3] Ensuring MarketType enum values...")
    new_markets = ["JP", "CN", "HK", "UK", "DE", "FR", "NL", "KR", "AU", "CA", "TW", "SG", "IT"]
    async with engine.begin() as conn:
        for mkt in new_markets:
            try:
                await conn.execute(text(f"ALTER TYPE markettype ADD VALUE IF NOT EXISTS '{mkt}'"))
            except Exception:
                pass
    print(f"  ✅ Enum values ensured: {', '.join(new_markets)}")

    # ── Step 2: Insert all symbols ──
    print("\n[2/3] Inserting international symbols...")
    all_lists = [
        ("JP  — Nikkei 225 top", NIKKEI225_TOP),
        ("HK  — Hang Seng top", HANGSENG_TOP),
        ("UK  — FTSE 100 top", FTSE100_TOP),
        ("DE  — DAX top", DAX_TOP),
        ("CN  — SSE 50 top", SSE50_TOP),
        ("FR  — CAC 40 top", CAC40_TOP),
        ("NL  — AEX top", AEX_TOP),
    ]

    total_inserted = 0
    total_skipped = 0

    async with AsyncSessionLocal() as db:
        for label, symbols_list in all_lists:
            inserted = 0
            skipped = 0
            for sym, name in symbols_list:
                market = _detect_market(sym)
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
            print(f"  {label}: +{inserted} inserted, {skipped} skipped")

        # ── Insert indices ──
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
        print(f"  Indices: +{idx_inserted} inserted")

    # ── Step 3: Summary ──
    print(f"\n[3/3] Done!")
    print(f"  ✅ Total inserted: {total_inserted}")
    print(f"  ⏭  Total skipped (already exist): {total_skipped}")
    print(f"\n  Run check script to verify:")
    print(f"    python scripts/check_intl_symbols.py")


if __name__ == "__main__":
    asyncio.run(main())
