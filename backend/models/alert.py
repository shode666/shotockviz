from datetime import datetime
from enum import Enum as PyEnum
from typing import TYPE_CHECKING
from sqlalchemy import String, DateTime, Float, Boolean, Enum, ForeignKey, func
from sqlalchemy.orm import Mapped, mapped_column, relationship
from core.database import Base

# bd:deps-2026-09 WP-B5 (03-stan-refactor-strategy.md §1.2 F821 finding) —
# forward-ref string "User" in `Mapped["User"]` below needs a real import
# path for both ruff (F821) and mypy to resolve it; TYPE_CHECKING avoids a
# circular import at runtime (models.user doesn't import models.alert).
if TYPE_CHECKING:
    from models.user import User


class AlertType(str, PyEnum):
    PRICE_ABOVE = "PRICE_ABOVE"
    PRICE_BELOW = "PRICE_BELOW"
    RSI_OVERBOUGHT = "RSI_OVERBOUGHT"
    RSI_OVERSOLD = "RSI_OVERSOLD"
    GOLDEN_CROSS = "GOLDEN_CROSS"
    DEATH_CROSS = "DEATH_CROSS"
    VOLUME_SPIKE = "VOLUME_SPIKE"


class AlertStatus(str, PyEnum):
    # bd:shotockviz-43x — EXPIRED removed: it was declared here and mapped
    # by the frontend (utils/alertStatus.ts) but no backend code path ever
    # assigned it (grep -rn EXPIRED backend/ returned only this enum
    # member itself). Striking per Oliver/Tara's call (LOW value, "resolve
    # by striking, not by implementing" — 10-tara-value.md) rather than
    # building an expiry rule that was never asked for.
    #
    # DB enum note (checked before removing): the Postgres `alertstatus`
    # type was never created by an Alembic migration — the `alerts` table
    # predates this project's Alembic history entirely and is provisioned
    # via `Base.metadata.create_all()` (core/database.py, dev-only;
    # main.py's `_sync_markettype_enum()` only ADDs values, and does not
    # even include `alertstatus` in its enum_map). So wherever the
    # Postgres type already exists, it keeps the 'EXPIRED' label forever —
    # Postgres has no `ALTER TYPE ... DROP VALUE` — but that is harmless:
    # zero rows use it (confirmed by grep above) and nothing can write it
    # once this Python member is gone. No migration added for this.
    ACTIVE = "ACTIVE"
    TRIGGERED = "TRIGGERED"
    INACTIVE = "INACTIVE"


class AlertChannel(str, PyEnum):
    TELEGRAM = "TELEGRAM"
    IN_APP = "IN_APP"
    EMAIL = "EMAIL"


class Alert(Base):
    __tablename__ = "alerts"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    symbol: Mapped[str] = mapped_column(String(20), index=True, nullable=False)
    alert_type: Mapped[AlertType] = mapped_column(Enum(AlertType), nullable=False)
    condition: Mapped[str] = mapped_column(String(100), nullable=False)
    value: Mapped[float | None] = mapped_column(Float, nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    status: Mapped[AlertStatus] = mapped_column(Enum(AlertStatus), default=AlertStatus.ACTIVE)
    channel: Mapped[AlertChannel] = mapped_column(Enum(AlertChannel), default=AlertChannel.TELEGRAM)
    triggered_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    user: Mapped["User"] = relationship(back_populates="alerts")
