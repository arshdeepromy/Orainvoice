"""Job cards: add awaiting_parts status.

Adds ``awaiting_parts`` to the ``job_cards.status`` CHECK constraint so the
Job Cards Kanban (frontend-v2 ``JobCardList`` Board view) can move a card
into a "waiting on parts" column. The status is a real DB-level state, not
a flag — transition rules are enforced in
``app.modules.job_cards.service.VALID_TRANSITIONS``:

  * in_progress → awaiting_parts
  * awaiting_parts → in_progress  (parts arrived, resume work)
  * awaiting_parts → completed    (parts arrived + work finished)

The application layer also requires non-empty ``notes`` whenever a card
moves *into* ``awaiting_parts`` (validated in
``update_job_card``). The note is appended to the existing
``job_cards.notes`` column with a timestamp prefix — no schema change for
notes is required.

Idempotent + reversible:
  * ``DROP CONSTRAINT IF EXISTS`` then re-create the CHECK with the new
    enum value list.
  * ``downgrade()`` recreates the original 4-status CHECK after refusing
    to downgrade if any rows are in the new state (data-safety guard —
    we don't silently change live rows).

Revision ID: 0213
Revises: 0212
Create Date: 2026-06-05
"""

from __future__ import annotations

import logging

from alembic import op


revision: str = "0213"
down_revision: str = "0212"
branch_labels: tuple[str, ...] | None = None
depends_on: tuple[str, ...] | None = None


logger = logging.getLogger("alembic.runtime.migration")


_OLD_VALUES = "'open','in_progress','completed','invoiced'"
_NEW_VALUES = "'open','in_progress','awaiting_parts','completed','invoiced'"


def upgrade() -> None:
    op.execute("ALTER TABLE job_cards DROP CONSTRAINT IF EXISTS ck_job_cards_status")
    op.execute(
        f"ALTER TABLE job_cards ADD CONSTRAINT ck_job_cards_status "
        f"CHECK (status IN ({_NEW_VALUES}))"
    )
    logger.info("[0213] job_cards.status CHECK now includes awaiting_parts")


def downgrade() -> None:
    # Refuse to downgrade if any row is in the new state — silently
    # changing live rows would be unsafe.
    from sqlalchemy import text as _text

    bind = op.get_bind()
    in_use = bind.execute(
        _text("SELECT COUNT(*) FROM job_cards WHERE status = 'awaiting_parts'")
    ).scalar()
    if in_use:
        raise RuntimeError(
            f"Refusing to downgrade: {in_use} job card(s) are in "
            f"'awaiting_parts'. Move them to another status first."
        )
    op.execute("ALTER TABLE job_cards DROP CONSTRAINT IF EXISTS ck_job_cards_status")
    op.execute(
        f"ALTER TABLE job_cards ADD CONSTRAINT ck_job_cards_status "
        f"CHECK (status IN ({_OLD_VALUES}))"
    )
    logger.info("[0213-DOWN] job_cards.status CHECK reverted to 4 values")
