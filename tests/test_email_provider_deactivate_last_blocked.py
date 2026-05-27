"""Unit tests for ``deactivate_email_provider`` — last-active 409 guard.

Covers task 5.5 of the email-provider-unification spec: when there is
exactly one active provider, deactivating it must raise
``HTTPException(409)`` with the exact admin-facing copy from Phase 5
(commit 4971047, Req 9.4) and must NOT flip the row.

The protection matters because outbound mail goes dark the moment the
Active_Provider_Set is empty — the unified sender returns
``success=False, attempts=[]`` and every email type (invoices, password
reset, MFA OTP) silently fails. The 409 + lock-the-set pattern is the
backstop that turns "one careless click" into "the API said no, try
again".

Validates: Requirement 9.4
"""

from __future__ import annotations

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


# Exact admin-facing copy from Req 9.4 (mirrored in service.py L168-172).
# Pinned as a top-level constant so a typo in either place is caught
# the first time someone "rewords for clarity" without checking the
# requirement.
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

    Includes every attribute ``_provider_to_dict`` reads — including
    ``created_at`` / ``updated_at`` — because the deactivate path
    serialises the row on its idempotent fall-through branch.
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
    """Result whose ``scalars().all()`` returns the locked active set.

    Mirrors the shape produced by the
    ``select(EmailProvider).where(is_active.is_(True)).with_for_update()``
    query in ``deactivate_email_provider``.
    """
    scalars_proxy = MagicMock()
    scalars_proxy.all = MagicMock(return_value=active)
    result = MagicMock()
    result.scalars = MagicMock(return_value=scalars_proxy)
    return result


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_deactivating_only_active_provider_raises_409() -> None:
    """Single active provider → deactivate raises ``HTTPException(409)``.

    The exception's ``detail`` must match Req 9.4's exact copy character
    for character. The admin UI keys its error banner off this string,
    so even a stray whitespace edit would break the user-facing
    message without breaking any other test.

    Validates: Requirement 9.4
    """
    only_active = _make_provider("brevo", priority=1, is_active=True)

    db = AsyncMock()
    # Locked active set lookup → returns the single active row.
    db.execute = AsyncMock(
        return_value=_make_active_set_result([only_active])
    )
    db.flush = AsyncMock()
    db.refresh = AsyncMock()

    with patch.object(
        ep_service,
        "write_audit_log",
        new=AsyncMock(),
    ) as audit_mock:
        with pytest.raises(HTTPException) as exc_info:
            await ep_service.deactivate_email_provider(
                db, provider_key="brevo"
            )

    # HTTP status pinned at 409 (Req 9.4).
    assert exc_info.value.status_code == 409
    # Exact admin-facing copy — pin character-for-character so a
    # typo "fix" doesn't drift away from the requirement.
    assert exc_info.value.detail == EXPECTED_409_DETAIL

    # Row was not flipped — admin can retry after activating another
    # provider without the system being in a half-broken state.
    assert only_active.is_active is True

    # No audit-log entry for the failed call (audit log is for
    # successful flips only).
    audit_mock.assert_not_awaited()

    # No flush either — nothing should have been written.
    db.flush.assert_not_awaited()


@pytest.mark.asyncio
async def test_deactivate_last_active_uses_locking_select() -> None:
    """The active-set lookup must request ``SELECT ... FOR UPDATE``.

    The 409 guard alone isn't safe under concurrent calls — two admin
    tabs each clicking Deactivate in the same second would both pass
    the "≥1 must remain" check and both commit, taking the platform
    dark. The fix (per design Concurrency > Activate / Deactivate) is
    a row-level lock on every row in the Active_Provider_Set.

    This test peeks at the SQL statement the service hands to
    ``db.execute`` and asserts ``with_for_update()`` is set on the
    SELECT. We inspect the AST flag directly rather than compiling to
    a SQL string so this test does not depend on the full SQLAlchemy
    registry being configured at import time. The concurrent test
    (5.6) exercises the runtime contract; this one pins the lock at
    the call site so a "let's optimise this query" refactor can't
    quietly drop it.

    Validates: Requirement 9.4 (lock-acquisition prerequisite)
    """
    only_active = _make_provider("brevo", priority=1, is_active=True)

    db = AsyncMock()
    captured_stmt = {}

    async def _capture(stmt):
        captured_stmt["stmt"] = stmt
        return _make_active_set_result([only_active])

    db.execute = AsyncMock(side_effect=_capture)
    db.flush = AsyncMock()
    db.refresh = AsyncMock()

    with patch.object(ep_service, "write_audit_log", new=AsyncMock()):
        with pytest.raises(HTTPException):
            await ep_service.deactivate_email_provider(
                db, provider_key="brevo"
            )

    stmt = captured_stmt["stmt"]
    # ``with_for_update()`` sets ``_for_update_arg`` on the SELECT to a
    # truthy ``ForUpdateArg`` instance; ``None`` means a plain SELECT.
    # We inspect that attribute directly so the assertion stays valid
    # even if the test is run with an incomplete ORM registry (the
    # mapper config isn't required to read this flag).
    for_update_arg = getattr(stmt, "_for_update_arg", None)
    assert for_update_arg is not None, (
        "deactivate_email_provider must call SELECT ... FOR UPDATE on "
        "the active-set query — without it, concurrent deactivate "
        "calls can both pass the '≥1 must remain' guard."
    )


@pytest.mark.asyncio
async def test_deactivate_succeeds_when_other_active_providers_remain() -> None:
    """Sanity check: with two active providers, deactivating one works.

    This is the negative-space test for the 409 guard — without it the
    suite couldn't tell whether the 409 fires because the guard is
    correct or because the function always raises 409. Two providers
    active, deactivate one, the surviving provider is the only thing
    keeping the active set non-empty so the call is allowed.

    Validates: Requirement 9.4 (negative case)
    """
    target = _make_provider("brevo", priority=1, is_active=True)
    survivor = _make_provider("sendgrid", priority=2, is_active=True)

    db = AsyncMock()
    db.execute = AsyncMock(
        return_value=_make_active_set_result([target, survivor])
    )
    db.flush = AsyncMock()
    db.refresh = AsyncMock()

    with patch.object(
        ep_service,
        "write_audit_log",
        new=AsyncMock(),
    ) as audit_mock:
        result = await ep_service.deactivate_email_provider(
            db, provider_key="brevo"
        )

    # Target was flipped, survivor untouched.
    assert target.is_active is False
    assert survivor.is_active is True
    assert result is not None
    assert result["provider_key"] == "brevo"
    assert result["is_active"] is False

    # Audit log written exactly once on the successful flip.
    audit_mock.assert_awaited_once()
    assert (
        audit_mock.await_args.kwargs["action"]
        == "admin.email_provider_deactivated"
    )
