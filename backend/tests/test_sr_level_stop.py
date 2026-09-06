"""Stops on /api/v1/sr-levels — bd:shotockviz-43y.

A stop is a `user_created` sr_levels row with `level_type='stop'`. It lives
there because there is no position entity in this product (a holding is a fold
over `transactions`), so a stop ON the position would mean a new positions
table — a THIRD place a price-per-symbol lives beside `alerts.value` and
`sr_levels.price`. The full argument is in models/sr_level.py.

Three behaviours are load-bearing and are what this file pins:

  1. A stop NEVER comes back from GET /{symbol}, owner included. That route
     feeds the chart's S/R line layer, which labels anything that is not
     'support' as "R" (ChartToolbar.tsx:219-223) — a stop drawn as a resistance
     level is a wrong label on a price the user manages money by.
  2. POST with level_type='stop' REPLACES the caller's stop instead of adding a
     second row. Two stops on one symbol is a state nothing can resolve
     honestly, so it is prevented on write — the same place bd:shotockviz-7ju
     prevents a symbol holding two currencies.
  3. A stop is never public and never another user's.

Same async_client + override_db fixture pattern as test_sr_levels_endpoint.py.
"""
import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from core.security import hash_password
from models.sr_level import SRLevel
from models.user import User


async def _stop_rows(db: AsyncSession, symbol: str) -> list[SRLevel]:
    result = await db.execute(
        select(SRLevel).where(SRLevel.symbol == symbol, SRLevel.level_type == "stop")
    )
    return list(result.scalars().all())


@pytest.mark.asyncio
class TestStopIsNotAChartLevel:
    async def test_the_sr_read_never_returns_a_stop_even_to_its_owner(
        self, async_client: AsyncClient, test_db: AsyncSession, override_db,
        test_user: User, auth_headers: dict,
    ):
        test_db.add_all([
            SRLevel(symbol="AAPL", price=150.0, level_type="support", tag="S1",
                    color=None, source="manual_import"),
            SRLevel(symbol="AAPL", price=140.0, level_type="stop", tag="my stop",
                    color=None, source="user_created", user_id=test_user.id),
        ])
        await test_db.commit()

        response = await async_client.get("/api/v1/sr-levels/AAPL", headers=auth_headers)

        assert response.status_code == 200
        body = response.json()["data"]
        # The user's own support levels still come back (bd:shotockviz-474 is
        # unchanged) — only the stop is withheld, and only from THIS route.
        assert [row["level_type"] for row in body] == ["support"]

    async def test_a_guest_sees_no_stop_either(
        self, async_client: AsyncClient, test_db: AsyncSession, override_db,
        test_user: User,
    ):
        test_db.add(SRLevel(symbol="AAPL", price=140.0, level_type="stop",
                            tag=None, color=None, source="user_created",
                            user_id=test_user.id))
        await test_db.commit()

        response = await async_client.get("/api/v1/sr-levels/AAPL")
        assert response.status_code == 200
        assert response.json()["data"] == []


@pytest.mark.asyncio
class TestGetStop:
    async def test_requires_auth(self, async_client: AsyncClient, override_db):
        response = await async_client.get("/api/v1/sr-levels/AAPL/stop")
        assert response.status_code == 401

    async def test_returns_null_not_404_when_there_is_no_stop(
        self, async_client: AsyncClient, override_db, test_user: User, auth_headers: dict,
    ):
        """"This position has no stop" is a normal state the risk report already
        names (`no_stop`), not an error."""
        response = await async_client.get("/api/v1/sr-levels/AAPL/stop", headers=auth_headers)
        assert response.status_code == 200
        assert response.json()["data"] is None

    async def test_returns_the_callers_own_stop_with_its_id(
        self, async_client: AsyncClient, test_db: AsyncSession, override_db,
        test_user: User, auth_headers: dict,
    ):
        level = SRLevel(symbol="AAPL", price=140.0, level_type="stop", tag="initial",
                        color=None, source="user_created", user_id=test_user.id)
        test_db.add(level)
        await test_db.commit()

        response = await async_client.get("/api/v1/sr-levels/aapl/stop", headers=auth_headers)

        assert response.status_code == 200
        body = response.json()["data"]
        assert body["price"] == 140.0
        assert body["level_type"] == "stop"
        # The id is here because the S/R read no longer carries it, and DELETE
        # needs it.
        assert body["id"] == level.id

    async def test_never_returns_another_users_stop(
        self, async_client: AsyncClient, test_db: AsyncSession, override_db,
        test_user: User, auth_headers: dict,
    ):
        other = User(email="other@example.com", password_hash=hash_password("password123"),
                     display_name="Other", is_active=True)
        test_db.add(other)
        await test_db.flush()
        test_db.add(SRLevel(symbol="AAPL", price=140.0, level_type="stop", tag=None,
                            color=None, source="user_created", user_id=other.id))
        await test_db.commit()

        response = await async_client.get("/api/v1/sr-levels/AAPL/stop", headers=auth_headers)
        assert response.status_code == 200
        assert response.json()["data"] is None


@pytest.mark.asyncio
class TestCreateStop:
    async def test_creates_a_user_owned_stop(
        self, async_client: AsyncClient, test_db: AsyncSession, override_db,
        test_user: User, auth_headers: dict,
    ):
        response = await async_client.post(
            "/api/v1/sr-levels/aapl",
            json={"price": 140.0, "level_type": "stop", "tag": "initial"},
            headers=auth_headers,
        )

        assert response.status_code == 201
        body = response.json()["data"]
        assert body["symbol"] == "AAPL"
        assert body["level_type"] == "stop"
        assert body["source"] == "user_created"

        rows = await _stop_rows(test_db, "AAPL")
        assert len(rows) == 1
        assert rows[0].user_id == test_user.id

    async def test_a_second_stop_replaces_the_first_in_place(
        self, async_client: AsyncClient, test_db: AsyncSession, override_db,
        test_user: User, auth_headers: dict,
    ):
        """One position, one stop. "Move my stop up" is the user's actual verb,
        and two rows is a state the read path could only resolve by guessing."""
        first = await async_client.post(
            "/api/v1/sr-levels/AAPL",
            json={"price": 140.0, "level_type": "stop", "tag": "initial"},
            headers=auth_headers,
        )
        second = await async_client.post(
            "/api/v1/sr-levels/AAPL",
            json={"price": 148.0, "level_type": "stop", "tag": "trailed"},
            headers=auth_headers,
        )

        assert second.status_code == 201
        assert second.json()["data"]["id"] == first.json()["data"]["id"]
        assert second.json()["data"]["price"] == 148.0
        assert second.json()["data"]["tag"] == "trailed"

        rows = await _stop_rows(test_db, "AAPL")
        assert len(rows) == 1
        assert rows[0].price == 148.0

    async def test_replacement_is_per_symbol_and_per_user(
        self, async_client: AsyncClient, test_db: AsyncSession, override_db,
        test_user: User, auth_headers: dict,
    ):
        other = User(email="other@example.com", password_hash=hash_password("password123"),
                     display_name="Other", is_active=True)
        test_db.add(other)
        await test_db.flush()
        test_db.add(SRLevel(symbol="AAPL", price=100.0, level_type="stop", tag="theirs",
                            color=None, source="user_created", user_id=other.id))
        await test_db.commit()

        await async_client.post(
            "/api/v1/sr-levels/AAPL",
            json={"price": 140.0, "level_type": "stop"},
            headers=auth_headers,
        )
        await async_client.post(
            "/api/v1/sr-levels/TSLA",
            json={"price": 240.0, "level_type": "stop"},
            headers=auth_headers,
        )

        # Another user's stop on the same symbol is untouched, and a second
        # SYMBOL gets its own row.
        assert len(await _stop_rows(test_db, "AAPL")) == 2
        assert len(await _stop_rows(test_db, "TSLA")) == 1

    async def test_support_and_resistance_levels_are_still_free_to_repeat(
        self, async_client: AsyncClient, test_db: AsyncSession, override_db,
        test_user: User, auth_headers: dict,
    ):
        """The replace rule is for stops only — a chart can carry as many S/R
        lines on one symbol as the user draws."""
        for price in (150.0, 160.0):
            response = await async_client.post(
                "/api/v1/sr-levels/AAPL",
                json={"price": price, "level_type": "support"},
                headers=auth_headers,
            )
            assert response.status_code == 201

        result = await test_db.execute(
            select(SRLevel).where(SRLevel.symbol == "AAPL", SRLevel.level_type == "support")
        )
        assert len(result.scalars().all()) == 2

    async def test_the_deleted_stop_is_gone_from_the_stop_read(
        self, async_client: AsyncClient, test_db: AsyncSession, override_db,
        test_user: User, auth_headers: dict,
    ):
        created = await async_client.post(
            "/api/v1/sr-levels/AAPL",
            json={"price": 140.0, "level_type": "stop"},
            headers=auth_headers,
        )
        level_id = created.json()["data"]["id"]

        deleted = await async_client.delete(
            f"/api/v1/sr-levels/{level_id}", headers=auth_headers
        )
        assert deleted.status_code == 204

        after = await async_client.get("/api/v1/sr-levels/AAPL/stop", headers=auth_headers)
        assert after.json()["data"] is None
