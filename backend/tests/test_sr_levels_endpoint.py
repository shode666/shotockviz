"""Unit/integration tests for /api/v1/sr-levels — bd:features-2026-09 slice 2
(GET) + bd:shotockviz-474 (POST/DELETE, user-owned horizontal levels).

Follows the async_client + override_db fixture pattern from conftest.py
(same pattern test_next_features.py uses for /api/v1/* routes).

bd:features-2026-09 iter3 (Chris Finding 1 + Quinn Finding Q3) — endpoint now
excludes source='user_created' (unauthenticated route, no ownership filter);
tests updated to assert the new behavior + a dedicated exclusion test added.

bd:shotockviz-474 — GET additionally returns the CALLER's OWN user_created
rows when authenticated (still none for guests/other users); POST creates
one; DELETE removes one the caller owns and 404s on anything else (someone
else's row, or a manual_import/auto_pivot row with no owner to match).
"""
import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from core.security import hash_password
from models.sr_level import SRLevel
from models.user import User


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

    async def test_authenticated_caller_sees_own_user_created_row(
        self, async_client: AsyncClient, test_db: AsyncSession, override_db,
        test_user: User, auth_headers: dict,
    ):
        """bd:shotockviz-474 — the exclusion above is for guests/other users
        only; the owner must see their own row alongside public sources."""
        test_db.add_all([
            SRLevel(symbol="TSLA", price=250.0, level_type="support", tag="S1",
                    color="#fde047", source="manual_import"),
            SRLevel(symbol="TSLA", price=999.0, level_type="resistance", tag="MINE",
                    color=None, source="user_created", user_id=test_user.id),
        ])
        await test_db.commit()

        response = await async_client.get("/api/v1/sr-levels/TSLA", headers=auth_headers)

        assert response.status_code == 200
        body = response.json()["data"]
        assert len(body) == 2
        assert {row["source"] for row in body} == {"manual_import", "user_created"}
        mine = next(r for r in body if r["source"] == "user_created")
        assert mine["tag"] == "MINE"

    async def test_authenticated_caller_never_sees_another_users_row(
        self, async_client: AsyncClient, test_db: AsyncSession, override_db,
        test_user: User, auth_headers: dict,
    ):
        other = User(
            email="other@example.com",
            password_hash=hash_password("password123"),
            display_name="Other User",
            is_active=True,
        )
        test_db.add(other)
        await test_db.flush()
        test_db.add(SRLevel(symbol="TSLA", price=999.0, level_type="resistance",
                             tag="NOT MINE", color=None, source="user_created",
                             user_id=other.id))
        await test_db.commit()

        response = await async_client.get("/api/v1/sr-levels/TSLA", headers=auth_headers)

        assert response.status_code == 200
        assert response.json()["data"] == []


@pytest.mark.asyncio
class TestCreateSrLevel:
    async def test_requires_auth(self, async_client: AsyncClient, override_db):
        response = await async_client.post(
            "/api/v1/sr-levels/AAPL",
            json={"price": 150.0, "level_type": "support"},
        )
        assert response.status_code == 401

    async def test_creates_user_created_row_owned_by_caller(
        self, async_client: AsyncClient, test_db: AsyncSession, override_db,
        test_user: User, auth_headers: dict,
    ):
        response = await async_client.post(
            "/api/v1/sr-levels/aapl",
            json={"price": 150.5, "level_type": "resistance", "tag": "entry"},
            headers=auth_headers,
        )

        assert response.status_code == 201
        body = response.json()["data"]
        assert body["symbol"] == "AAPL"  # uppercased server-side
        assert body["price"] == 150.5
        assert body["level_type"] == "resistance"
        assert body["tag"] == "entry"
        assert body["source"] == "user_created"

        result = await test_db.execute(select(SRLevel).where(SRLevel.id == body["id"]))
        row = result.scalar_one()
        assert row.user_id == test_user.id
        assert row.color is None

    async def test_client_cannot_override_source_or_user_id(
        self, async_client: AsyncClient, override_db, auth_headers: dict,
    ):
        """SRLevelCreate has no `source`/`user_id` field — extra keys in the
        body are ignored by Pydantic, never trusted."""
        response = await async_client.post(
            "/api/v1/sr-levels/AAPL",
            json={"price": 100.0, "level_type": "support", "source": "manual_import", "user_id": 999},
            headers=auth_headers,
        )
        assert response.status_code == 201
        assert response.json()["data"]["source"] == "user_created"

    async def test_rejects_non_positive_price(
        self, async_client: AsyncClient, override_db, auth_headers: dict,
    ):
        response = await async_client.post(
            "/api/v1/sr-levels/AAPL",
            json={"price": 0, "level_type": "support"},
            headers=auth_headers,
        )
        assert response.status_code == 422

    async def test_rejects_invalid_level_type(
        self, async_client: AsyncClient, override_db, auth_headers: dict,
    ):
        response = await async_client.post(
            "/api/v1/sr-levels/AAPL",
            json={"price": 100.0, "level_type": "sideways"},
            headers=auth_headers,
        )
        assert response.status_code == 422


@pytest.mark.asyncio
class TestDeleteSrLevel:
    async def test_requires_auth(self, async_client: AsyncClient, override_db):
        response = await async_client.delete("/api/v1/sr-levels/1")
        assert response.status_code == 401

    async def test_owner_can_delete_own_level(
        self, async_client: AsyncClient, test_db: AsyncSession, override_db,
        test_user: User, auth_headers: dict,
    ):
        level = SRLevel(symbol="AAPL", price=150.0, level_type="support",
                         tag=None, color=None, source="user_created", user_id=test_user.id)
        test_db.add(level)
        await test_db.commit()
        await test_db.refresh(level)

        response = await async_client.delete(f"/api/v1/sr-levels/{level.id}", headers=auth_headers)

        assert response.status_code == 204
        result = await test_db.execute(select(SRLevel).where(SRLevel.id == level.id))
        assert result.scalar_one_or_none() is None

    async def test_cannot_delete_another_users_level(
        self, async_client: AsyncClient, test_db: AsyncSession, override_db,
        test_user: User, auth_headers: dict,
    ):
        other = User(email="other2@example.com", password_hash=hash_password("password123"),
                      display_name="Other User 2", is_active=True)
        test_db.add(other)
        await test_db.flush()
        level = SRLevel(symbol="AAPL", price=150.0, level_type="support",
                         tag=None, color=None, source="user_created", user_id=other.id)
        test_db.add(level)
        await test_db.commit()
        await test_db.refresh(level)

        response = await async_client.delete(f"/api/v1/sr-levels/{level.id}", headers=auth_headers)

        assert response.status_code == 404
        result = await test_db.execute(select(SRLevel).where(SRLevel.id == level.id))
        assert result.scalar_one_or_none() is not None  # untouched

    async def test_cannot_delete_manual_import_row(
        self, async_client: AsyncClient, test_db: AsyncSession, override_db,
        auth_headers: dict,
    ):
        """user_id is NULL on manual_import/auto_pivot rows — can never match
        `user_id == caller`, but this pins that no caller can ever delete
        curated/computed data through this route."""
        level = SRLevel(symbol="AAPL", price=150.0, level_type="support",
                         tag="S1", color="#fde047", source="manual_import")
        test_db.add(level)
        await test_db.commit()
        await test_db.refresh(level)

        response = await async_client.delete(f"/api/v1/sr-levels/{level.id}", headers=auth_headers)

        assert response.status_code == 404
        result = await test_db.execute(select(SRLevel).where(SRLevel.id == level.id))
        assert result.scalar_one_or_none() is not None

    async def test_delete_unknown_id_returns_404(
        self, async_client: AsyncClient, override_db, auth_headers: dict,
    ):
        response = await async_client.delete("/api/v1/sr-levels/999999", headers=auth_headers)
        assert response.status_code == 404
