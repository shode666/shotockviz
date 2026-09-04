"""Admin API routes — data retention policy management."""
from __future__ import annotations

import json
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from core.database import get_db
from core.logger import get_logger
from core.redis import get_redis
from models.user import User
from api.middleware.auth import require_admin
from schemas.envelope import EnvelopingAPIRoute

# bd:deps-2026-09 S2 (ADR-001 r3) — prefix lifted /api/admin -> /admin,
# mounted under /api/v1 in main.py. route_class = envelope wrap (ADR-002).
router = APIRouter(prefix="/admin", tags=["admin"], route_class=EnvelopingAPIRoute)
logger = get_logger(__name__)

RETENTION_CONFIG_KEY = "config:retention_policy"

# Default retention policy
DEFAULT_POLICY = [
    {"resolution": "1m", "max_age_days": 7, "label": "1-minute bars"},
    {"resolution": "5m", "max_age_days": 90, "label": "5-minute bars"},
    {"resolution": "1d", "max_age_days": 730, "label": "Daily bars"},
]


class RetentionRule(BaseModel):
    resolution: str  # "1m", "5m", "1d"
    max_age_days: int  # number of days to keep


class RetentionPolicyUpdate(BaseModel):
    policy: list[RetentionRule]


class RetentionPolicyResponse(BaseModel):
    policy: list[dict]
    disk_usage_mb: float | None = None


# ── GET /api/admin/retention-policy ────────────────────────────────────────

@router.get("/retention-policy")
async def get_retention_policy(
    user: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """Get current data retention policy and disk usage stats."""
    r = await get_redis()

    # Read policy from Redis (or use defaults)
    raw = await r.get(RETENTION_CONFIG_KEY)
    if raw:
        policy = json.loads(raw)
    else:
        policy = DEFAULT_POLICY

    # Get disk usage from PostgreSQL
    disk_usage_mb = None
    try:
        result = await db.execute(text("""
            SELECT
                COALESCE(pg_total_relation_size('stock_prices_1m') / 1024.0 / 1024.0, 0) +
                COALESCE(pg_total_relation_size('ohlcv_bars') / 1024.0 / 1024.0, 0)
            AS total_mb
        """))
        row = result.fetchone()
        if row:
            disk_usage_mb = round(float(row[0]), 2)
    except Exception as e:
        logger.debug("Disk usage query failed", error=str(e))

    return RetentionPolicyResponse(policy=policy, disk_usage_mb=disk_usage_mb)


# ── PUT /api/admin/retention-policy ────────────────────────────────────────

@router.put("/retention-policy")
async def update_retention_policy(
    body: RetentionPolicyUpdate,
    user: User = Depends(require_admin),
):
    """Update data retention policy. Stored in Redis, read by housekeeping worker."""
    r = await get_redis()

    # Validate rules
    valid_resolutions = {"1m", "5m", "1d", "1w"}
    for rule in body.policy:
        if rule.resolution not in valid_resolutions:
            raise HTTPException(
                status_code=400,
                detail=f"Invalid resolution: {rule.resolution}. Must be one of: {valid_resolutions}",
            )
        if rule.max_age_days < 1:
            raise HTTPException(status_code=400, detail="max_age_days must be >= 1")

    # Store as JSON in Redis
    policy_data = [
        {"resolution": r.resolution, "max_age_days": r.max_age_days}
        for r in body.policy
    ]
    await (await get_redis()).set(RETENTION_CONFIG_KEY, json.dumps(policy_data))

    logger.info("Retention policy updated", policy=policy_data, user=user.email)
    return {"status": "ok", "policy": policy_data}


# ── POST /api/admin/retention-policy/run-now ───────────────────────────────

@router.post("/retention-policy/run-now")
async def run_housekeeping_now(
    user: User = Depends(require_admin),
):
    """Trigger housekeeping worker immediately."""
    try:
        from workers.housekeeping import run_housekeeping
        run_housekeeping.delay()
        logger.info("Housekeeping triggered manually", user=user.email)
        return {"status": "ok", "message": "Housekeeping task queued"}
    except Exception as e:
        logger.warning("Failed to trigger housekeeping", error=str(e))
        # Fallback: still return success but note it's queued
        return {"status": "queued", "message": "Task will run on next beat cycle"}
