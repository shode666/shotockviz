from datetime import date, datetime
from enum import Enum as PyEnum
from typing import TYPE_CHECKING
from sqlalchemy import String, Date, DateTime, Float, Boolean, Enum, ForeignKey, func
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
    # bd:shotockviz-o0b — INACTIVE removed for the identical reason,
    # flagged separately by 43x rather than folded into it. `status` and
    # `is_active` are two *different* concepts, not the same thing spelled
    # two ways, and INACTIVE was a redundant third spelling of one of
    # them:
    #   - `status` = lifecycle stage: has this alert ever fired?
    #     ACTIVE (default, armed, never fired) -> TRIGGERED (fired once;
    #     alert_checker.py sets it alongside is_active=False and never
    #     reads it back to "un-trigger"). No code path ever moved status
    #     to INACTIVE — grep -rn "AlertStatus\." backend/ finds only
    #     ACTIVE/TRIGGERED as values ever assigned.
    #   - `is_active` = user control: is this alert armed right now?
    #     Defaults True; PATCH /alerts/{id}/toggle
    #     (api/routes/alerts.py) flips it directly and is the ONLY way a
    #     user pairs it. alert_checker.py's selection query ANDs
    #     `status == ACTIVE AND is_active == True` — a triggered alert
    #     also has is_active=False (so it won't re-fire), but that's the
    #     checker enforcing "don't refire", not `is_active` becoming a
    #     status. A user-paused alert stays status=ACTIVE the whole time.
    # Frontend already gets this right (utils/alertStatus.ts checks
    # status == 'TRIGGERED' first, else falls through to is_active) — it
    # never read an INACTIVE status value off the wire because the
    # backend never sent one. Kept two fields rather than merging into
    # one: collapsing them would make "paused-but-already-fired" (a real,
    # reachable combination today) inexpressible without adding a new
    # status value, i.e. more surface for the exact bug this bead is
    # about. Documented as the real truth in REQUIREMENTS.md FR-ALERT-003.
    #
    # DB enum note (checked before removing, same finding as 43x): the
    # Postgres `alertstatus` type was never created by an Alembic
    # migration — the `alerts` table predates this project's Alembic
    # history entirely and is provisioned via `Base.metadata.create_all()`
    # (core/database.py, dev-only; main.py's `_sync_markettype_enum()`
    # only ADDs values, and does not even include `alertstatus` in its
    # enum_map). So wherever the Postgres type already exists, it keeps
    # the 'EXPIRED' and 'INACTIVE' labels forever — Postgres has no
    # `ALTER TYPE ... DROP VALUE` — but that is harmless: zero rows use
    # either (confirmed: `SELECT status, count(*) FROM alerts GROUP BY
    # status` — no query needed beyond the grep above showing nothing
    # ever assigns it) and nothing can write it once the Python member is
    # gone. No migration added for this.
    ACTIVE = "ACTIVE"
    TRIGGERED = "TRIGGERED"


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
    # bd:shotockviz-eb1 — the date `value` was last WRITTEN, i.e. the trading
    # units it is stated in. It exists because neither existing timestamp says
    # that and both fail in a different direction:
    #   created_at — too early. PUT /alerts/{id} can change `value`
    #     (api/routes/alerts.py:131-137) without touching created_at, so an
    #     already-post-split level would be rebased a second time.
    #   updated_at — too late. It has onupdate=now(), so PATCH /toggle (which
    #     does not touch `value` at all) moves it and would suppress a rebase
    #     the level still needs.
    # A price level is a standing instruction compared every 60 s against a live
    # quote that is always in CURRENT units, so it is rebased in place when a
    # split is recorded (workers/corporate_actions_fetcher.py::rebase_price_alerts)
    # — the opposite treatment from a transaction, which is a record of a past
    # event and is restated at read time instead (services/corporate_actions.py).
    # This column is the idempotency key for that rewrite: the rebase is guarded
    # by `value_as_of < ex_date`, so re-running the daily fetcher over the same
    # split table can never multiply a level twice.
    # NULL = units unknown -> never rebased (declines rather than guesses).
    value_as_of: Mapped[date | None] = mapped_column(Date, nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    status: Mapped[AlertStatus] = mapped_column(Enum(AlertStatus), default=AlertStatus.ACTIVE)
    channel: Mapped[AlertChannel] = mapped_column(Enum(AlertChannel), default=AlertChannel.TELEGRAM)
    triggered_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    user: Mapped["User"] = relationship(back_populates="alerts")
