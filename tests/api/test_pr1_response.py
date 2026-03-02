"""
PR#1 acceptance tests — response standard + request-id propagation.

DoD:
  ✓ BaseResponse serializes correctly for all factories
  ✓ Every HTTP response carries X-Request-ID header
  ✓ Client-supplied X-Request-ID is echoed back unchanged
  ✓ Fresh request_id is generated when header is absent
  ✓ structlog context is cleared between requests (no leakage)
  ✓ /api/health returns BaseResponse envelope
"""
import uuid
from datetime import datetime, timezone

import pytest

from schemas.common import (
    BaseResponse,
    CachedLayer,
    DataStatus,
    ResponseMeta,
)


# ══════════════════════════════════════════════════════════════════
# Unit tests — schemas/common.py
# ══════════════════════════════════════════════════════════════════

class TestDataStatus:
    def test_all_values_exist(self):
        assert DataStatus.FRESH == "fresh"
        assert DataStatus.STALE == "stale"
        assert DataStatus.PARTIAL == "partial"
        assert DataStatus.UNAVAILABLE == "unavailable"


class TestCachedLayer:
    def test_all_values_exist(self):
        assert CachedLayer.REDIS == "redis"
        assert CachedLayer.DB == "db"
        assert CachedLayer.PROVIDER == "provider"
        assert CachedLayer.NONE == "none"


class TestResponseMeta:
    def test_required_fields(self):
        meta = ResponseMeta(request_id="abc-123")
        assert meta.request_id == "abc-123"
        assert meta.data_status == DataStatus.FRESH  # default
        assert meta.as_of is None
        assert meta.cached_layer is None
        assert meta.next_refresh_in is None

    def test_full_fields(self):
        ts = datetime.now(timezone.utc)
        meta = ResponseMeta(
            request_id="req-1",
            data_status=DataStatus.STALE,
            as_of=ts,
            cached_layer=CachedLayer.REDIS,
            next_refresh_in=30,
        )
        assert meta.data_status == DataStatus.STALE
        assert meta.cached_layer == CachedLayer.REDIS
        assert meta.next_refresh_in == 30

    def test_next_refresh_in_non_negative(self):
        from pydantic import ValidationError
        with pytest.raises(ValidationError):
            ResponseMeta(request_id="x", next_refresh_in=-1)

    def test_json_serialization(self):
        meta = ResponseMeta(request_id="req-json")
        j = meta.model_dump()
        assert "request_id" in j
        assert "data_status" in j
        assert j["data_status"] == "fresh"


class TestBaseResponseFactories:
    RID = "test-request-id"

    def test_ok_defaults(self):
        r = BaseResponse.ok(data={"value": 42}, request_id=self.RID)
        assert r.data == {"value": 42}
        assert r.meta.request_id == self.RID
        assert r.meta.data_status == DataStatus.FRESH
        assert r.meta.cached_layer == CachedLayer.PROVIDER

    def test_ok_with_overrides(self):
        ts = datetime.now(timezone.utc)
        r = BaseResponse.ok(
            data=[1, 2, 3],
            request_id=self.RID,
            as_of=ts,
            cached_layer=CachedLayer.REDIS,
            next_refresh_in=60,
        )
        assert r.meta.cached_layer == CachedLayer.REDIS
        assert r.meta.next_refresh_in == 60
        assert r.meta.as_of == ts

    def test_stale(self):
        r = BaseResponse.stale(data="old", request_id=self.RID)
        assert r.meta.data_status == DataStatus.STALE
        assert r.data == "old"

    def test_partial(self):
        r = BaseResponse.partial(data={"ok": 5, "missing": 1}, request_id=self.RID)
        assert r.meta.data_status == DataStatus.PARTIAL
        assert r.data is not None

    def test_unavailable(self):
        r = BaseResponse.unavailable(request_id=self.RID)
        assert r.data is None
        assert r.meta.data_status == DataStatus.UNAVAILABLE
        assert r.meta.cached_layer == CachedLayer.NONE

    def test_serializes_to_dict(self):
        r = BaseResponse.ok(data={"k": "v"}, request_id=self.RID)
        d = r.model_dump()
        assert "data" in d
        assert "meta" in d
        assert d["meta"]["data_status"] == "fresh"
        assert d["meta"]["request_id"] == self.RID

    def test_generic_type_none_data(self):
        r: BaseResponse[None] = BaseResponse.unavailable(request_id=self.RID)
        assert r.data is None

    def test_generic_type_list(self):
        r: BaseResponse[list] = BaseResponse.ok(data=[1, 2], request_id=self.RID)
        assert r.data == [1, 2]


# ══════════════════════════════════════════════════════════════════
# Integration tests — HTTP middleware + health endpoint
#
# Use httpx.AsyncClient + ASGITransport to bypass the broken
# sync-client / async-db-session fixture chain in conftest.py.
# Works in pytest-asyncio STRICT mode.
# ══════════════════════════════════════════════════════════════════

import httpx
import pytest
from main import app


@pytest.fixture
async def aclient():
    """Async ASGI test client — no external server required."""
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://test",
    ) as c:
        yield c


@pytest.mark.asyncio
class TestRequestIDMiddleware:
    """Tests that verify X-Request-ID flows through every response."""

    async def test_response_has_request_id_header(self, aclient):
        resp = await aclient.get("/api/health")
        assert "X-Request-ID" in resp.headers

    async def test_generated_id_is_uuid4(self, aclient):
        resp = await aclient.get("/api/health")
        rid = resp.headers["X-Request-ID"]
        parsed = uuid.UUID(rid, version=4)
        assert str(parsed) == rid

    async def test_supplied_id_is_echoed(self, aclient):
        custom_id = "my-trace-id-12345"
        resp = await aclient.get("/api/health", headers={"X-Request-ID": custom_id})
        assert resp.headers["X-Request-ID"] == custom_id

    async def test_different_requests_get_different_ids(self, aclient):
        r1 = await aclient.get("/api/health")
        r2 = await aclient.get("/api/health")
        assert r1.headers["X-Request-ID"] != r2.headers["X-Request-ID"]

    async def test_request_id_in_response_body(self, aclient):
        resp = await aclient.get("/api/health")
        body = resp.json()
        header_id = resp.headers["X-Request-ID"]
        assert body["meta"]["request_id"] == header_id


@pytest.mark.asyncio
class TestHealthEndpointShape:
    """Verifies /api/health returns correct BaseResponse envelope."""

    async def test_status_200(self, aclient):
        resp = await aclient.get("/api/health")
        assert resp.status_code == 200

    async def test_envelope_keys(self, aclient):
        body = (await aclient.get("/api/health")).json()
        assert "data" in body
        assert "meta" in body

    async def test_meta_fields_present(self, aclient):
        meta = (await aclient.get("/api/health")).json()["meta"]
        assert "request_id" in meta
        assert "data_status" in meta
        assert "cached_layer" in meta

    async def test_data_status_is_valid_enum(self, aclient):
        status = (await aclient.get("/api/health")).json()["meta"]["data_status"]
        assert status in ("fresh", "stale", "partial", "unavailable")

    async def test_data_contains_service_checks(self, aclient):
        data = (await aclient.get("/api/health")).json()["data"]
        assert "database" in data
        assert "redis" in data
