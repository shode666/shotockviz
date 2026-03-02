"""Seed initial stock metadata into the database."""
import asyncio
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

SET_STOCKS = [
    ("PTT.BK", "PTT Public Company Limited", "ปตท.", "Energy"),
    ("CPALL.BK", "CP All Public Company Limited", "ซีพีออลล์", "Commerce"),
    ("ADVANC.BK", "Advanced Info Service PCL", "แอดวานซ์ฯ", "Technology"),
    ("TRUE.BK", "True Corporation PCL", "ทรู คอร์ปฯ", "Technology"),
    ("SCB.BK", "The Siam Commercial Bank PCL", "ไทยพาณิชย์", "Financials"),
    ("KBANK.BK", "Kasikornbank PCL", "กสิกรไทย", "Financials"),
    ("BBL.BK", "Bangkok Bank PCL", "กรุงเทพ", "Financials"),
    ("AOT.BK", "Airports of Thailand PCL", "ท่าอากาศยานไทย", "Transportation"),
    ("BDMS.BK", "Bangkok Dusit Medical Services", "กรุงเทพดุสิตเวชการ", "Healthcare"),
    ("SCC.BK", "The Siam Cement PCL", "ปูนซิเมนต์ไทย", "Industrials"),
    ("GULF.BK", "Gulf Energy Development PCL", "กัลฟ์", "Energy"),
    ("MINT.BK", "Minor International PCL", "ไมเนอร์ อินเตอร์", "Consumer"),
    ("BH.BK", "Bumrungrad Hospital PCL", "บำรุงราษฎร์", "Healthcare"),
    ("CRC.BK", "Central Retail Corporation PCL", "เซ็นทรัล รีเทล", "Commerce"),
    ("HMPRO.BK", "Home Product Center PCL", "โฮม โปรดักส์", "Commerce"),
]

US_STOCKS = [
    ("AAPL", "Apple Inc.", None, "Technology"),
    ("NVDA", "NVIDIA Corporation", None, "Technology"),
    ("TSLA", "Tesla, Inc.", None, "Consumer"),
    ("META", "Meta Platforms, Inc.", None, "Technology"),
    ("GOOGL", "Alphabet Inc.", None, "Technology"),
    ("AMZN", "Amazon.com, Inc.", None, "Technology"),
    ("MSFT", "Microsoft Corporation", None, "Technology"),
    ("NFLX", "Netflix, Inc.", None, "Technology"),
    ("AMD", "Advanced Micro Devices", None, "Technology"),
    ("INTC", "Intel Corporation", None, "Technology"),
]

INDICES = [
    ("^SET", "SET Index", "ดัชนีหุ้นไทย", "Index"),
    ("^GSPC", "S&P 500", None, "Index"),
    ("^IXIC", "NASDAQ Composite", None, "Index"),
    ("^DJI", "Dow Jones Industrial Average", None, "Index"),
]

# Thai mutual funds (กองทุนรวม) — priced by NAV, traded via broker/app
THAI_FUNDS = [
    # Muang Thai
    ("MPDIFMF", "Muang Thai Dividend Income Fund", "กองทุนเมืองไทย ดิวิเดนด์ อินคัม", "Mutual Fund"),
    ("MPGFUND", "Muang Thai Growth Fund", "กองทุนเมืองไทย โกรท", "Mutual Fund"),
    # PRINCIPAL
    ("PRINCIPAL iPROP-D", "Principal Thai Property & Infrastructure Dividend Fund", "พรินซิเพิล ไทย พร็อพเพอร์ตี้ ดิวิเดนด์", "Mutual Fund"),
    ("PRINCIPAL HAPRO-D", "Principal Property & Infrastructure Dividend Fund", "พรินซิเพิล พร็อพเพอร์ตี้ ดิวิเดนด์", "Mutual Fund"),
    ("PRINCIPAL VAYUPAK1", "Principal Vayupak One Fund", "พรินซิเพิล วายุภักษ์ 1", "Mutual Fund"),
    ("PRINCIPAL DEF", "Principal Daily Equity Fund", "พรินซิเพิล เดลี อิควิตี้", "Mutual Fund"),
    # SCB
    ("SCBS&P500", "SCB S&P 500 Index Fund", "เอสซีบี เอส แอนด์ พี 500 อินเด็กซ์", "Mutual Fund"),
    ("SCBDOW", "SCB Dow Jones Industrial Average Index Fund", "เอสซีบี ดาวโจนส์", "Mutual Fund"),
    ("SCBLT1", "SCB Long-Term Equity Fund 1", "เอสซีบี แอลทีเอฟ 1", "Mutual Fund"),
    ("SCBGIF", "SCB Global Income Fund", "เอสซีบี โกลบอล อินคัม", "Mutual Fund"),
    ("SCBTMB", "SCB Thai Mid-Large Cap Equity Fund", "เอสซีบี ไทย มิด-ลาร์จ แคป", "Mutual Fund"),
    # Kasikorn (KAsset)
    ("KMASTER", "Kasikorn Master Fund", "กองทุนกสิกรไทย มาสเตอร์", "Mutual Fund"),
    ("K-GINCOME", "Kasikorn Global Income Fund", "กสิกรไทย โกลบอล อินคัม", "Mutual Fund"),
    ("K-US500X", "Kasikorn US 500 Index Fund", "กสิกรไทย ยูเอส 500 อินเด็กซ์", "Mutual Fund"),
    ("KFSDIV", "Kasikorn Stock Dividend Fund", "กสิกรไทย สต็อก ดิวิเดนด์", "Mutual Fund"),
    ("KFHAPPY", "Kasikorn Happy Fund", "กสิกรไทย แฮปปี้", "Mutual Fund"),
    # Bualuang (BBL)
    ("BBLAM", "BBL Asset Management Fund", "บัวหลวง แอสเซท แมเนจเมนท์", "Mutual Fund"),
    ("BSIP", "Bualuang Structured Investment Plan", "บัวหลวงโครงสร้าง", "Mutual Fund"),
    # Tisco
    ("TISCOGF", "Tisco Global Equity Fund", "ทิสโก้ โกลบอล อิควิตี้", "Mutual Fund"),
    ("TISCOEGF", "Tisco European Growth Fund", "ทิสโก้ ยุโรป โกรท", "Mutual Fund"),
    # One Asset
    ("ONE-UGG-RA", "One UGG Fund Retirement", "วัน ยูจีจี รีไทร์เม้นท์", "Mutual Fund"),
    # Krungsri (AYUD)
    ("KFLTF70", "Krungsri LTF 70% Equity Fund", "กรุงศรี แอลทีเอฟ 70", "Mutual Fund"),
    ("KFINFRA", "Krungsri Infrastructure Fund", "กรุงศรี โครงสร้างพื้นฐาน", "Mutual Fund"),
]


async def main():
    from core.database import AsyncSessionLocal, create_tables
    from models.stock import Stock, MarketType
    from sqlalchemy import text, select

    await create_tables()

    async with AsyncSessionLocal() as db:
        # Ensure FUND enum value exists in PostgreSQL (safe to run multiple times)
        try:
            await db.execute(text("ALTER TYPE markettype ADD VALUE IF NOT EXISTS 'FUND'"))
            await db.commit()
        except Exception:
            await db.rollback()  # already exists or not a PG enum — continue

        count = 0
        for symbol, name, name_th, sector in SET_STOCKS:
            existing = await db.execute(select(Stock).where(Stock.symbol == symbol))
            if not existing.scalar_one_or_none():
                db.add(Stock(symbol=symbol, name=name, name_th=name_th, market=MarketType.SET, sector=sector))
                count += 1

        for symbol, name, name_th, sector in US_STOCKS:
            existing = await db.execute(select(Stock).where(Stock.symbol == symbol))
            if not existing.scalar_one_or_none():
                db.add(Stock(symbol=symbol, name=name, name_th=name_th, market=MarketType.US, sector=sector))
                count += 1

        for symbol, name, name_th, sector in THAI_FUNDS:
            existing = await db.execute(select(Stock).where(Stock.symbol == symbol))
            if not existing.scalar_one_or_none():
                db.add(Stock(symbol=symbol, name=name, name_th=name_th, market=MarketType.FUND, sector=sector))
                count += 1

        await db.commit()
        print(f"✅ Seeded {count} new records ({len(SET_STOCKS)} SET + {len(US_STOCKS)} US + {len(THAI_FUNDS)} Funds)")


if __name__ == "__main__":
    asyncio.run(main())
