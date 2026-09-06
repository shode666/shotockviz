"""add trigger_count to alerts — standing alerts + cooldown

bd:shotockviz-93h / bd:shotockviz-0ka — the user's decision (relayed by
Oliver): every alert is STANDING, with a cooldown, not one-shot. A one-shot
alert's `status=TRIGGERED` meant "spent" and nothing ever wrote it back to
ACTIVE (bd:shotockviz-0ka's finding) — the only recovery was
delete-and-recreate. Under "standing", `status` stops being a lifecycle gate
and becomes a sticky "has this ever fired" flag (see models/alert.py's
`AlertStatus` docstring); re-eligibility to fire again is governed instead by
`triggered_at` + `settings.alert_cooldown_minutes` (workers/alert_checker.py).

That single sticky flag can no longer tell an alert that just fired once
apart from one on its 40th fire this week — and the user explicitly asked to
be able to see that difference ("An alert that has fired three times this
week is different from one that has never fired"). Hence one new column:
`trigger_count`, incremented atomically in the same UPDATE that claims the
alert (`workers/alert_checker.py::claim_alert`), so it can never drift from
the actual number of times a notification was sent.

Additive only:
  - ADD COLUMN trigger_count INTEGER NOT NULL DEFAULT 0 — every existing row
    (including ones already TRIGGERED under the old one-shot semantics)
    starts at 0 by the column default, then is corrected below.
  - Backfill: rows already `status='TRIGGERED'` have, by definition, fired
    at least once — set trigger_count=1 for those (can't know the TRUE
    historical count for rows that predate this column; 1 is the
    unambiguous floor implied by status alone, never an overcount).
    `status='ACTIVE'` rows are correctly 0 and untouched.

NOT migrated here, deliberately: `is_active` on existing TRIGGERED rows.
Under the old design every fired alert has `is_active=False` — indistinguishable
in the DB from a row the user explicitly paused after it fired (same two
columns, same values, no way to tell intent apart). Flipping every existing
TRIGGERED+is_active=False row back to is_active=True as part of a migration
would silently re-arm alerts the user may have paused on purpose for a
different reason, which is a bigger unrequested behavior change than this
bead asks for. Existing fired alerts keep showing as paused
("หยุดชั่วคราว") until the user re-toggles them by hand; only alerts that
fire AFTER this deploy get the new "stays armed" behavior automatically.
Called out explicitly in the hand-off, not silently decided.

Revision ID: 20260906_0009
Revises: 20260906_0008
Create Date: 2026-09-06
"""
from typing import Union

from alembic import op
import sqlalchemy as sa

revision: str = "20260906_0009"
down_revision: Union[str, None] = "20260906_0008"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()

    # NO MAGIC / defensive existence check, same reasoning as 0006-0008:
    # `alerts` was never created by a migration in this project (it exists
    # via Base.metadata.create_all() in core/database.py — see the DB enum
    # note in models/alert.py), so an Alembic-only bootstrap can legitimately
    # reach this revision without the table.
    exists = bind.execute(
        sa.text("SELECT 1 FROM information_schema.tables WHERE table_name = 'alerts'")
    ).scalar()
    if not exists:
        print("[20260906_0009] alerts table not found — skipping")
        return

    already = bind.execute(
        sa.text(
            "SELECT 1 FROM information_schema.columns "
            "WHERE table_name = 'alerts' AND column_name = 'trigger_count'"
        )
    ).scalar()
    if already:
        print("[20260906_0009] alerts.trigger_count already present — skipping")
        return

    op.add_column(
        "alerts",
        sa.Column("trigger_count", sa.Integer(), nullable=False, server_default="0"),
    )

    # Conservative backfill — see module docstring. Only rows that are
    # DEFINITELY known to have fired at least once (status='TRIGGERED') get
    # bumped to 1; everything else stays at the column default of 0.
    result = bind.execute(
        sa.text(
            "UPDATE alerts SET trigger_count = 1 "
            "WHERE status = 'TRIGGERED' AND trigger_count = 0"
        )
    )
    print(
        f"[20260906_0009] added alerts.trigger_count; backfilled {result.rowcount} "
        "already-TRIGGERED row(s) to trigger_count=1 (floor implied by status, "
        "true historical count is unknowable for pre-existing rows)"
    )


def downgrade() -> None:
    bind = op.get_bind()
    exists = bind.execute(
        sa.text(
            "SELECT 1 FROM information_schema.columns "
            "WHERE table_name = 'alerts' AND column_name = 'trigger_count'"
        )
    ).scalar()
    if exists:
        op.drop_column("alerts", "trigger_count")
