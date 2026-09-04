"""Unit/integration tests for GET /api/v1/sr-levels/{symbol} — bd:features-2026-09 slice 2.

Follows the async_client + override_db fixture pattern from conftest.py
(same pattern test_next_features.py uses for /api/v1/* routes).

bd:features-2026-09 iter3 (Chris Finding 1 + Quinn Finding Q3) — endpoint now
excludes source='user_created' (unauthenticated route, no ownership filter);
tests updated to assert the new behavior + a dedicated exclusion test added.
"""
import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from models.sr_level import SRLevel


@pytest.mark.asyncio
class TestGetSrLevels:
    async def test_returns_manual_import_and_auto_pivot_rows(
        self, async_client: AsyncClient, test_db: AsyncSession, override_db
    ):
        test_db.add_all([
            SRLevel(symbol="AAPL", price=150.5, level_type="support", tag="S1",
                    color="#fde047", source="manual_import"),
            SRLevel(symbol="AAPL", price=210.0, level_type="resistance", tag="R1",
                    color="#a78bfa", source="manual_import"),
            SRLevel(symbol="AAPL", price=180.0, level_type="support", tag=None,
                    color=None, source="auto_pivot"),
        ])
        await test_db.commit()

        response = await async_client.get("/api/v1/sr-levels/AAPL")

        assert response.status_code == 200
        body = response.json()["data"]
        assert len(body) == 3
        sources = sorted(row["source"] for row in body)
        assert sources == ["auto_pivot", "manual_import", "manual_import"]
        # ordered by price ascending
        prices = [row["price"] for row in body]
        assert prices == sorted(prices)

    async def test_excludes_user_created_rows(
        self, async_client: AsyncClient, test_db: AsyncSession, override_db
    ):
        """Chris Finding 1 (02-chris-review.md) — unauthenticated route must
        never leak a per-user-owned level. A user_created row alongside
        public-source rows for the same symbol must be filtered out, not
        just "happen to be absent" because none exist yet."""
        test_db.add_all([
            SRLevel(symbol="TSLA", price=250.0, level_type="support", tag="S1",
                    color="#fde047", source="manual_import"),
            SRLevel(symbol="TSLA", price=999.0, level_type="resistance", tag="MINE",
                    color="#ff00ff", source="user_created", user_id=None),
        ])
        await test_db.commit()

        response = await async_client.get("/api/v1/sr-levels/TSLA")

        assert response.status_code == 200
        body = response.json()["data"]
        assert len(body) == 1
        assert body[0]["source"] == "manual_import"
        assert all(row["source"] != "user_created" for row in body)
        assert all(row["tag"] != "MINE" for row in body)

    async def test_symbol_with_only_user_created_rows_returns_empty(
        self, async_client: AsyncClient, test_db: AsyncSession, override_db
    ):
        test_db.add(SRLevel(symbol="GME", price=20.0, level_type="support",
                             tag="MINE", color=None, source="user_created"))
        await test_db.commit()

        response = await async_client.get("/api/v1/sr-levels/GME")

        assert response.status_code == 200
        assert response.json()["data"] == []

    async def test_returns_empty_list_for_unknown_symbol(
        self, async_client: AsyncClient, override_db
    ):
        response = await async_client.get("/api/v1/sr-levels/ZZZNOPE")
        assert response.status_code == 200
        assert response.json()["data"] == []

    async def test_symbol_matched_case_insensitively(
        self, async_client: AsyncClient, test_db: AsyncSession, override_db
    ):
        test_db.add(SRLevel(symbol="NVDA", price=900.0, level_type="resistance",
                             tag="R2", color=None, source="manual_import"))
        await test_db.commit()

        response = await async_client.get("/api/v1/sr-levels/nvda")

        assert response.status_code == 200
        body = response.json()["data"]
        assert len(body) == 1
        assert body[0]["symbol"] == "NVDA"

    async def test_no_auth_required(self, async_client: AsyncClient, override_db):
        # No Authorization header sent at all — must not 401 (matches
        # stocks/* public-read convention, unlike drawings.py per-user CRUD).
        response = await async_client.get("/api/v1/sr-levels/AAPL")
        assert response.status_code == 200
