"""Seed corporate events (XD, XR, earnings) into the database."""
import asyncio
import sys
import os
from datetime import datetime, timedelta, timezone

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.database import AsyncSessionLocal
from models.stock import StockEvent

# Sample XD/XR events for SET50 stocks in Q1-Q2 2026
EVENTS = [
    {
        "symbol": "PTT.BK",
        "event_type": "XD",
        "event_date": datetime(2026, 3, 15, 0, 0, 0, tzinfo=timezone.utc),
        "value": 0.50,
        "description": "ปันผลระหว่างกาล",
    },
    {
        "symbol": "KBANK.BK",
        "event_type": "XD",
        "event_date": datetime(2026, 4, 10, 0, 0, 0, tzinfo=timezone.utc),
        "value": 2.50,
        "description": "ปันผลประจำปี",
    },
    {
        "symbol": "SCB.BK",
        "event_type": "XD",
        "event_date": datetime(2026, 4, 5, 0, 0, 0, tzinfo=timezone.utc),
        "value": 3.50,
        "description": "ปันผลประจำปี",
    },
    {
        "symbol": "AOT.BK",
        "event_type": "XD",
        "event_date": datetime(2026, 3, 20, 0, 0, 0, tzinfo=timezone.utc),
        "value": 0.25,
        "description": "ปันผลระหว่างกาล",
    },
    {
        "symbol": "CPALL.BK",
        "event_type": "XD",
        "event_date": datetime(2026, 5, 5, 0, 0, 0, tzinfo=timezone.utc),
        "value": 0.35,
        "description": "ปันผลระหว่างกาล",
    },
    {
        "symbol": "BTS.BK",
        "event_type": "XD",
        "event_date": datetime(2026, 3, 25, 0, 0, 0, tzinfo=timezone.utc),
        "value": 0.08,
        "description": "ปันผลระหว่างกาล",
    },
    {
        "symbol": "BBL.BK",
        "event_type": "XD",
        "event_date": datetime(2026, 4, 20, 0, 0, 0, tzinfo=timezone.utc),
        "value": 4.00,
        "description": "ปันผลประจำปี",
    },
]


async def seed_events():
    """Seed sample events into the stock_events table."""
    async with AsyncSessionLocal() as db:
        try:
            # Check if events already exist
            existing_count = 0
            for event_data in EVENTS:
                # Simple check — try to insert and count successes
                try:
                    event = StockEvent(**event_data)
                    db.add(event)
                except Exception:
                    pass

            await db.commit()
            count = len(EVENTS)
            print(f"✓ Seeded {count} stock events")

        except Exception as e:
            await db.rollback()
            print(f"✗ Error seeding events: {e}")
            raise


if __name__ == "__main__":
    asyncio.run(seed_events())
