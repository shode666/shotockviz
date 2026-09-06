from datetime import date, datetime
from enum import Enum as PyEnum
from typing import TYPE_CHECKING
from sqlalchemy import String, Date, DateTime, Float, Boolean, Integer, Enum, ForeignKey, func
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
    #
    # bd:shotockviz-93h / bd:shotockviz-0ka (2026-09-06) — MEANING CHANGED.
    # The paragraph above described the one-shot design: TRIGGERED meant
    # "spent", set alongside is_active=False so the checker's
    # `status==ACTIVE AND is_active==True` selection query would never
    # pick the row up again, and nothing ever wrote status back to ACTIVE
    # (bd:shotockviz-0ka's finding) — the only recovery was
    # delete-and-recreate.
    #
    # The user's decision (relayed by Oliver, not re-opened here): every
    # alert is STANDING, with a cooldown, rather than a per-alert
    # once/standing/cooldown picker at creation time — that picker was
    # offered and explicitly rejected as a setting nobody wants to make on
    # every alert (same shape objection as the one that killed a
    # per-alert lifetime field). So there is nothing to "re-arm": nothing
    # disarms in the first place.
    #
    # That retires TRIGGERED-as-lifecycle-exit. Per Oliver's framing this
    # is one of "the field changes meaning" or "it stops being a
    # lifecycle marker and becomes 'last fired'" — this project takes the
    # latter, cheaper option, because it needs zero new enum members (see
    # the struck-EXPIRED/INACTIVE history above — this bead exists
    # partly to NOT repeat that shape of defect):
    #   ACTIVE     = has never fired.
    #   TRIGGERED  = has fired at least once, ever — a STICKY historical
    #     flag, not a gate. `alert_checker.claim_alert()` still sets it
    #     (idempotently — it may already be TRIGGERED) alongside
    #     `triggered_at` and `trigger_count += 1`; it does NOT set
    #     `is_active=False` any more, and no code path ever moves it back
    #     to ACTIVE (a status file rewind would itself misrepresent
    #     "has this ever fired" history, which is the whole point of
    #     keeping the field).
    # `status` and `is_active` stay two different concepts, per
    # `bd:shotockviz-o0b`'s original separation, unchanged by this bead:
    #   - `is_active` is STILL the only user arm/pause control, written
    #     only by `PATCH /alerts/{id}/toggle`. The checker's eligibility
    #     query is now `is_active==True AND (never fired OR cooldown
    #     elapsed)` — `status` no longer appears in that WHERE clause at
    #     all, because it no longer says anything about whether the row
    #     is checkable, only about its fire history.
    #   - Re-eligibility to fire again is governed by `triggered_at` +
    #     `settings.alert_cooldown_minutes` (see workers/alert_checker.py
    #     module docstring for the cooldown-length reasoning), NOT by
    #     `status`. A fresh TRIGGERED alert and one that fired 40 times
    #     this week look identical in `status` (both "TRIGGERED") —
    #     `trigger_count` (below) is what tells them apart for display.
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
    # bd:shotockviz-93h/0ka — total number of times this alert has ever fired.
    # Exists because a standing alert's `status` is now sticky (see AlertStatus
    # docstring above): "TRIGGERED" alone cannot distinguish an alert that just
    # fired once from one on its 40th fire this week, and the UI needs to
    # ("An alert that has fired three times this week is different from one
    # that has never fired" — Oliver's brief). Incremented in the same atomic
    # UPDATE that claims the alert (workers/alert_checker.py::claim_alert), so
    # it can never drift from `triggered_at`/the actual number of Telegram
    # sends. Additive, NOT NULL DEFAULT 0 — migration 20260906_0009.
    trigger_count: Mapped[int] = mapped_column(Integer, default=0, server_default="0", nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    user: Mapped["User"] = relationship(back_populates="alerts")
