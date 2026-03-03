"""Check international market symbols in database.

Usage (inside backend container):
  docker-compose -f docker-compose.dev.yml exec backend python scripts/check_intl_symbols.py
"""
import asyncio
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


async def main():
    from sqlalchemy import text
    from core.database import AsyncSessionLocal

    async with AsyncSessionLocal() as db:
        # ── Count by market ──
        result = await db.execute(text("""
            SELECT market, COUNT(*) as cnt
            FROM stocks
            WHERE is_active = true
            GROUP BY market
            ORDER BY cnt DESC
        """))
        rows = result.fetchall()
        total = sum(r[1] for r in rows)
        print(f"\n{'='*50}")
        print(f"  Stock count by market (total: {total})")
        print(f"{'='*50}")
        for r in rows:
            print(f"  {r[0]:6s} : {r[1]:>4d} symbols")

        # ── Check each international market ──
        targets = ['JP', 'CN', 'HK', 'UK', 'DE', 'FR', 'NL']
        print(f"\n{'='*50}")
        print(f"  International markets detail")
        print(f"{'='*50}")

        for mkt in targets:
            result = await db.execute(text("""
                SELECT symbol, name FROM stocks
                WHERE market = :mkt AND is_active = true
                ORDER BY symbol
                LIMIT 5
            """), {'mkt': mkt})
            rows = result.fetchall()
            count_res = await db.execute(text("""
                SELECT COUNT(*) FROM stocks
                WHERE market = :mkt AND is_active = true
            """), {'mkt': mkt})
            count = count_res.scalar()

            if count > 0:
                print(f"\n  {mkt} ({count} symbols):")
                for r in rows:
                    print(f"    {r[0]:16s}  {r[1]}")
                if count > 5:
                    print(f"    ... and {count - 5} more")
            else:
                print(f"\n  {mkt}: ❌ NO DATA — needs index_populator to run")

        # ── Check if index_populator has ever run ──
        print(f"\n{'='*50}")
        print(f"  Diagnostics")
        print(f"{'='*50}")

        # Check for any international index symbols
        result = await db.execute(text("""
            SELECT symbol, name, market FROM stocks
            WHERE symbol IN ('^N225', '^HSI', '000001.SS', '^FTSE', '^GDAXI', '^FCHI', '^AEX')
        """))
        idx_rows = result.fetchall()
        if idx_rows:
            print(f"\n  International indices found ({len(idx_rows)}):")
            for r in idx_rows:
                print(f"    {r[0]:16s}  {r[1]:30s}  [{r[2]}]")
        else:
            print(f"\n  ❌ No international indices — index_populator has NEVER run")
            print(f"     Fix: docker-compose -f docker-compose.dev.yml exec backend celery -A workers.celery_app call workers.index_populator.populate_index_constituents")


if __name__ == "__main__":
    asyncio.run(main())
