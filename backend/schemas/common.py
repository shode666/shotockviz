"""
Standard API response envelope.

Every endpoint MUST return BaseResponse so clients can always inspect:
  data_status  — freshness of the payload (fresh | stale | partial | unavailable)
  as_of        — timestamp of the newest data point returned
  cached_layer — where the data came from (redis | db | provider | none)
  next_refresh_in — hint for client polling (seconds), if known
  request_id   — unique ID for tracing across logs
"""
from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any, Generic, Optional, TypeVar

from pydantic import BaseModel, Field

T = TypeVar("T")


# ── Enums ───────────────────────────────────────────────────────────────────

class DataStatus(str, Enum):
    """Freshness state of the returned payload."""
    FRESH = "fresh"           # data fetched within its TTL window
    STALE = "stale"           # data is older than TTL but served while refreshing
    PARTIAL = "partial"       # some symbols/fields missing (e.g. screener partial scan)
    UNAVAILABLE = "unavailable"  # no data at all (provider down, not cached)


class CachedLayer(str, Enum):
    """Which storage layer served the data."""
    REDIS = "redis"       # L1: hot in-memory cache
    DB = "db"             # L2: TimescaleDB / PostgreSQL
    PROVIDER = "provider" # L3: fetched live from external API
    NONE = "none"         # no data found anywhere


# ── Meta ────────────────────────────────────────────────────────────────────

class ResponseMeta(BaseModel):
    """Metadata attached to every API response."""

    request_id: str = Field(..., description="UUID for request tracing")
    data_status: DataStatus = Field(DataStatus.FRESH, description="Freshness of payload")
    as_of: Optional[datetime] = Field(None, description="Timestamp of newest data point")
    cached_layer: Optional[CachedLayer] = Field(None, description="Storage layer that served this data")
    next_refresh_in: Optional[int] = Field(
        None,
        ge=0,
        description="Hint: seconds until data will be re-fetched by background worker",
    )


# ── Envelope ─────────────────────────────────────────────────────────────────

class BaseResponse(BaseModel, Generic[T]):
    """
    Standard API envelope.

    Usage::

        return BaseResponse.ok(data=payload, request_id=req.state.request_id)
        return BaseResponse.stale(data=payload, request_id=..., as_of=ts)
        return BaseResponse.unavailable(request_id=...)
    """

    data: Optional[T] = None
    meta: ResponseMeta

    # ── Factories ────────────────────────────────────────────────────────────

    @classmethod
    def ok(
        cls,
        data: T,
        request_id: str,
        *,
        as_of: Optional[datetime] = None,
        cached_layer: Optional[CachedLayer] = None,
        next_refresh_in: Optional[int] = None,
    ) -> "BaseResponse[T]":
        """Fresh data, fully served."""
        return cls(
            data=data,
            meta=ResponseMeta(
                request_id=request_id,
                data_status=DataStatus.FRESH,
                as_of=as_of,
                cached_layer=cached_layer or CachedLayer.PROVIDER,
                next_refresh_in=next_refresh_in,
            ),
        )

    @classmethod
    def stale(
        cls,
        data: T,
        request_id: str,
        *,
        as_of: Optional[datetime] = None,
        cached_layer: Optional[CachedLayer] = None,
        next_refresh_in: Optional[int] = None,
    ) -> "BaseResponse[T]":
        """Stale-while-revalidate: served old data, refresh enqueued."""
        return cls(
            data=data,
            meta=ResponseMeta(
                request_id=request_id,
                data_status=DataStatus.STALE,
                as_of=as_of,
                cached_layer=cached_layer or CachedLayer.DB,
                next_refresh_in=next_refresh_in,
            ),
        )

    @classmethod
    def partial(
        cls,
        data: T,
        request_id: str,
        *,
        as_of: Optional[datetime] = None,
        cached_layer: Optional[CachedLayer] = None,
    ) -> "BaseResponse[T]":
        """Partial data (e.g. screener with some symbols missing)."""
        return cls(
            data=data,
            meta=ResponseMeta(
                request_id=request_id,
                data_status=DataStatus.PARTIAL,
                as_of=as_of,
                cached_layer=cached_layer,
            ),
        )

    @classmethod
    def unavailable(
        cls,
        request_id: str,
        *,
        as_of: Optional[datetime] = None,
    ) -> "BaseResponse[None]":
        """No data available anywhere (provider down + no cache)."""
        return cls(
            data=None,
            meta=ResponseMeta(
                request_id=request_id,
                data_status=DataStatus.UNAVAILABLE,
                as_of=as_of,
                cached_layer=CachedLayer.NONE,
            ),
        )
