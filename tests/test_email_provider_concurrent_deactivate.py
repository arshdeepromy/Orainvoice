"""Unit tests for ``deactivate_email_provider`` — concurrent race safety.

Covers task 5.6 of the email-provider-unification spec: two admin tabs
each click Deactivate on the last two active providers in the same
second. Without locking, both reads pass the "≥1 must remain" guard,
both writes commit, and outbound mail goes dark for every email type.
The Phase 5 fix (commit 4971047) acquires
``SELECT ... FOR UPDATE`` over the Active_Provider_Set so concurrent
calls serialise on PG row locks.

This module simulates the PG row-lock semantics with an
``asyncio.Lock`` and two ``AsyncMock`` sessions that share a single
mutable provider list. The lock is acquired inside the mocked
``db.execute`` (mirroring the moment ``SELECT ... FOR UPDATE`` would
take the row lock in PG) and released in the caller's ``finally``
clause (mirroring the moment the transaction would commit and release
the row lock).

The contract being pinned:

  - exactly one of the two coroutines returns 200 (success);
  - the other returns ``HTTPException(409)`` with the Phase 5 detail copy;
  - the surviving provider's ``is_active`` is still ``True`` at the end
    so outbound mail keeps working.

Validates: Requirements 9.5, 21.7
"""

from __future__ import annotations

import asyncio
import uuid
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import HTTPException

# Import models so SQLAlchemy can resolve all relationships at import time.
import app.modules.admin.models  # noqa: F401
from app.modules.auth.models import User  # noqa: F401
import app.modules.inventory.models  # noqa: F401

from app.modules.email_providers import service as ep_service


# Pinned to match the constant in test_email_provider_deactivate_last_blocked.py
# so a typo in the service drift is caught by both files.
EXPECTED_409_DETAIL = (
    "Activate another provider before deactivating this one — "
    "at least one active email provider is required for "
    "outbound mail."
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_provider(
    provider_key: str,
    *,
    priority: int = 1,
    is_active: bool = True,
) -> MagicMock:
    """Mock an active ``EmailProvider`` row.

    Includes every attribute ``_provider_to_dict`` reads so the
    serialiser doesn't blow up when the success branch returns the
    post-flip dict.
    """
    provider = MagicMock()
    provider.id = uuid.uuid4()
    provider.provider_key = provider_key
    provider.display_name = provider_key.title()
    provider.description = None
    provider.smtp_host = None
    provider.smtp_port = None
    provider.smtp_encryption = "tls"
    provider.priority = priority
    provider.is_active = is_active
    provider.credentials_encrypted = b"x"
    provider.credentials_set = True
    provider.config = {"from_email": "from@example.com"}
    provider.setup_guide = None
    provider.created_at = datetime.now(timezone.utc)
    provider.updated_at = datetime.now(timezone.utc)
    return provider


def _make_active_set_result(active: list[MagicMock]) -> MagicMock:
    """Result whose ``scalars().all()`` returns the locked active set."""
    scalars_proxy = MagicMock()
    scalars_proxy.all = MagicMock(return_value=active)
    result = MagicMock()
    result.scalars = MagicMock(return_value=scalars_proxy)
    return result


def _build_locking_db(
    all_providers: list[MagicMock],
    row_lock: asyncio.Lock,
) -> AsyncMock:
    """Build an AsyncMock session that simulates row-locked active-set reads.

    The mocked ``db.execute`` acquires ``row_lock`` and snapshots the
    *current* active subset of ``all_providers`` into the returned
    result. The caller is responsible for releasing the lock after the
    deactivate function returns (mirroring transaction commit). That
    sequencing is what reproduces the PG row-lock contract: while one
    coroutine holds the lock, the other's ``execute`` blocks on the
    lock; after the holder commits and releases, the waiter wakes up,
    re-reads the active set, and sees the post-flip state.

    ``db.flush``/``db.refresh`` are no-op AsyncMocks because the
    deactivate path's only writes go through the in-memory provider
    mocks (``target.is_active = False`` happens before flush).
    """
    db = AsyncMock()

    async def _execute_with_row_lock(_stmt):
        # Acquire the shared lock before "running the query". This is
        # the moment ``SELECT ... FOR UPDATE`` would take the PG row
        # lock; concurrent callers wait here.
        await row_lock.acquire()
        active_now = [p for p in all_providers if p.is_active]
        return _make_active_set_result(active_now)

    db.execute = AsyncMock(side_effect=_execute_with_row_lock)
    db.flush = AsyncMock()
    db.refresh = AsyncMock()
    return db


async def _call_deactivate_then_release_lock(
    db: AsyncMock,
    provider_key: str,
    row_lock: asyncio.Lock,
):
    """Run ``deactivate_email_provider`` and release the row lock at end.

    The lock is released in a ``finally`` block so it drops on both the
    success path (after ``write_audit_log`` returns) and the 409 path
    (after ``HTTPException`` raises). This mimics the real
    transaction-commit boundary: PG releases ``FOR UPDATE`` row locks
    when the transaction ends, regardless of whether the work
    succeeded or raised.

    The function returns the deactivate result for the success path,
    and re-raises the ``HTTPException`` for the 409 path —
    ``asyncio.gather(..., return_exceptions=True)`` will collect either
    shape.
    """
    try:
        return await ep_service.deactivate_email_provider(
            db, provider_key=provider_key
        )
    finally:
        if row_lock.locked():
            row_lock.release()


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_concurrent_deactivate_serialises_to_one_success_one_409() -> None:
    """Two concurrent deactivate calls on the last two active providers.

    Scenario:
      - Provider A (brevo, priority 1) — active
      - Provider B (sendgrid, priority 2) — active
      - Coroutine 1 calls deactivate("brevo")
      - Coroutine 2 calls deactivate("sendgrid")
      - Both fire under ``asyncio.gather`` so they truly race

    Expected outcome (Req 9.5):
      - Whichever coroutine wins the row-lock race succeeds (returns a
        dict with ``is_active=False`` for its target);
      - The losing coroutine raises ``HTTPException(409)`` with the
        Phase 5 admin-facing copy because it sees the now-singleton
        active set and would otherwise leave outbound email dark;
      - Exactly one provider remains active at the end of the race —
        the lock-loser's target.

    The "which side wins" is not pinned by this test — it depends on
    the asyncio scheduler and Lock implementation. We only assert the
    *aggregate* invariants: one success, one 409, exactly one survivor.

    Validates: Requirements 9.5
    """
    provider_a = _make_provider("brevo", priority=1, is_active=True)
    provider_b = _make_provider("sendgrid", priority=2, is_active=True)
    all_providers = [provider_a, provider_b]

    # Shared row lock simulating SELECT ... FOR UPDATE serialisation.
    row_lock = asyncio.Lock()

    # Each coroutine gets its own session — production runs each
    # request in a separate ``AsyncSession`` from the connection pool.
    db1 = _build_locking_db(all_providers, row_lock)
    db2 = _build_locking_db(all_providers, row_lock)

    with patch.object(ep_service, "write_audit_log", new=AsyncMock()):
        results = await asyncio.gather(
            _call_deactivate_then_release_lock(db1, "brevo", row_lock),
            _call_deactivate_then_release_lock(db2, "sendgrid", row_lock),
            return_exceptions=True,
        )

    # Partition the gathered results into successes and 409s.
    successes = [r for r in results if isinstance(r, dict)]
    failures_409 = [
        r
        for r in results
        if isinstance(r, HTTPException) and r.status_code == 409
    ]
    other = [
        r
        for r in results
        if not isinstance(r, dict)
        and not (isinstance(r, HTTPException) and r.status_code == 409)
    ]

    assert other == [], (
        "Unexpected error from concurrent deactivate "
        f"(should be exactly one success + one 409): {other!r}"
    )
    assert len(successes) == 1, (
        f"Expected exactly one success, got {len(successes)}: {results!r}"
    )
    assert len(failures_409) == 1, (
        f"Expected exactly one 409, got {len(failures_409)}: {results!r}"
    )

    # The 409 carries the Phase 5 admin-facing copy verbatim.
    assert failures_409[0].detail == EXPECTED_409_DETAIL

    # Exactly one provider ends up active — the loser's target. The
    # winner's target was successfully flipped; the loser's target
    # survived because the 409 short-circuited before any write.
    final_active = [p for p in all_providers if p.is_active]
    assert len(final_active) == 1, (
        "Concurrent deactivate must leave exactly one active provider; "
        f"got {[p.provider_key for p in final_active]!r}"
    )

    # The success result targeted the now-inactive provider.
    deactivated_key = successes[0]["provider_key"]
    assert deactivated_key in {"brevo", "sendgrid"}
    survivor_key = (
        "sendgrid" if deactivated_key == "brevo" else "brevo"
    )
    assert final_active[0].provider_key == survivor_key
    assert successes[0]["is_active"] is False
