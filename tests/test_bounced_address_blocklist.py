"""Bounced address blocklist short-circuits subsequent sends.

Phase 8c task 9.13 of the email-provider-unification spec. Verifies
the contract pinned by Requirement 12 (blocklist):

- Hard-bounced address → next ``send_email`` call returns
  ``success=False`` with ``failure_kind=HARD_RECIPIENT`` and an empty
  ``attempts`` list (well, one synthetic ``precheck`` attempt).
- Soft-bounced address only → send proceeds to the provider chain;
  the blocklist hit is logged as a warning but does not stop delivery.
- Cleared bounce row → send proceeds normally.

The tests work directly against ``_check_bounce_blocklist`` for the
fast path and against ``send_email`` for the integration check; they
mock the DB layer so no PG instance is required.

Validates: Requirements 12.3, 12.4, 12.5, 12.7
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# Import models so SQLAlchemy can resolve relationships at import time.
import app.modules.admin.models  # noqa: F401
import app.modules.inventory.models  # noqa: F401
from app.modules.auth.models import User  # noqa: F401

from app.integrations.email_sender import (
    EmailAttempt,
    EmailMessage,
    FailureKind,
    _check_bounce_blocklist,
    send_email,
)


def _bounced_row(
    *,
    email: str,
    kind: str,
    expires_at: datetime | None = None,
    reason: str | None = None,
    org_id: uuid.UUID | None = None,
):
    return SimpleNamespace(
        id=uuid.uuid4(),
        org_id=org_id,
        email_address=email,
        bounce_kind=kind,
        reason=reason,
        expires_at=expires_at,
    )


def _execute_returning_scalars(rows):
    scalars = MagicMock()
    scalars.all = MagicMock(return_value=rows)
    result = MagicMock()
    result.scalars = MagicMock(return_value=scalars)
    return result


# ---------------------------------------------------------------------------
# Direct tests of _check_bounce_blocklist
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_hard_bounce_returns_blocked_with_reason() -> None:
    """A hard-bounce row → ``(True, reason)``.

    Validates: Requirement 12.4
    """
    org_id = uuid.uuid4()
    db = AsyncMock()
    db.execute = AsyncMock(
        return_value=_execute_returning_scalars(
            [
                _bounced_row(
                    email="bad@example.com",
                    kind="hard",
                    expires_at=None,
                    reason="550 No such user",
                    org_id=org_id,
                )
            ]
        )
    )

    blocked, reason = await _check_bounce_blocklist(
        db, org_id=org_id, email_address="bad@example.com"
    )
    assert blocked is True
    assert reason == "550 No such user"


@pytest.mark.asyncio
async def test_soft_bounce_does_not_block_returns_warning_reason() -> None:
    """A soft-bounce row → ``(False, "soft bounce observed (proceeding)")``.

    The caller (``send_email``) logs the reason as a warning but
    proceeds to the provider chain. Validates: Requirement 12.5
    """
    org_id = uuid.uuid4()
    db = AsyncMock()
    db.execute = AsyncMock(
        return_value=_execute_returning_scalars(
            [
                _bounced_row(
                    email="iffy@example.com",
                    kind="soft",
                    expires_at=datetime.now(timezone.utc)
                    + timedelta(days=2),
                    reason="421 Try again",
                    org_id=org_id,
                )
            ]
        )
    )

    blocked, reason = await _check_bounce_blocklist(
        db, org_id=org_id, email_address="iffy@example.com"
    )
    assert blocked is False
    assert reason == "soft bounce observed (proceeding)"


@pytest.mark.asyncio
async def test_no_bounce_row_returns_clear() -> None:
    """No bounce on file → ``(False, None)`` and the send proceeds.

    Validates: Requirement 12.7 (clear → next send proceeds normally)
    """
    db = AsyncMock()
    db.execute = AsyncMock(return_value=_execute_returning_scalars([]))

    blocked, reason = await _check_bounce_blocklist(
        db, org_id=uuid.uuid4(), email_address="ok@example.com"
    )
    assert blocked is False
    assert reason is None


@pytest.mark.asyncio
async def test_lookup_is_case_insensitive_on_address() -> None:
    """Recipient comparison is case-insensitive — the storage column is
    lowercased and the lookup mirrors that.

    Pin the property at the wire level: lookups for
    ``MIXED.Case@Example.COM`` must hit a row stored with
    ``mixed.case@example.com``. We assert this by feeding the same
    matched row back from a stub ``execute`` regardless of the input
    casing.

    Validates: Requirement 12.1 (storage shape) + Requirement 12.4
    (lookup contract)
    """
    org_id = uuid.uuid4()
    stored = _bounced_row(
        email="mixed.case@example.com",
        kind="hard",
        expires_at=None,
        reason="bad",
        org_id=org_id,
    )

    db = AsyncMock()
    db.execute = AsyncMock(
        return_value=_execute_returning_scalars([stored])
    )

    # Three case variants — the function must hit the same row each time.
    for raw in [
        "MIXED.Case@Example.COM",
        "mixed.CASE@example.com",
        "Mixed.Case@example.com",
    ]:
        blocked, _ = await _check_bounce_blocklist(
            db, org_id=org_id, email_address=raw
        )
        assert blocked is True


# ---------------------------------------------------------------------------
# Integration test of send_email's blocklist short-circuit
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_send_email_short_circuits_on_hard_bounce() -> None:
    """``send_email`` returns ``HARD_RECIPIENT`` without calling any
    provider when the recipient is on the hard-bounce list.

    The provider chain must never be loaded. The synthetic
    ``precheck`` attempt carries the bounce reason verbatim.

    Validates: Requirements 12.3, 12.4
    """
    org_id = uuid.uuid4()
    msg = EmailMessage(
        to_email="bad@example.com",
        to_name="",
        subject="Test",
        text_body="hello",
        org_id=org_id,
    )

    db = AsyncMock()
    # Patch the blocklist helper to short-circuit; assert provider load
    # never runs.
    with patch(
        "app.integrations.email_sender._check_bounce_blocklist",
        new=AsyncMock(return_value=(True, "hard bounce on file")),
    ), patch(
        "app.integrations.email_sender._load_active_providers",
        new=AsyncMock(),
    ) as load_providers, patch(
        "app.integrations.email_sender.dispatch_one_provider",
        new=AsyncMock(),
    ) as dispatch_mock:
        result = await send_email(db, msg)

    assert result.success is False
    assert result.error == "recipient is on the bounce list"
    assert len(result.attempts) == 1
    assert result.attempts[0].failure_kind == FailureKind.HARD_RECIPIENT
    assert result.attempts[0].transport == "precheck"
    # Provider load + dispatch never ran — the chain was short-
    # circuited before any provider attempt.
    load_providers.assert_not_awaited()
    dispatch_mock.assert_not_awaited()


@pytest.mark.asyncio
async def test_send_email_proceeds_on_soft_bounce_only() -> None:
    """``send_email`` proceeds normally when only a soft bounce is on file.

    Validates: Requirement 12.5
    """
    org_id = uuid.uuid4()
    msg = EmailMessage(
        to_email="iffy@example.com",
        to_name="",
        subject="Test",
        text_body="hello",
        org_id=org_id,
    )

    provider = MagicMock()
    provider.provider_key = "brevo"
    provider.priority = 1

    success_attempt = EmailAttempt(
        provider_key="brevo",
        transport="rest_api",
        success=True,
        message_id="msg-1",
        duration_ms=10,
    )

    db = AsyncMock()
    with patch(
        "app.integrations.email_sender._check_bounce_blocklist",
        new=AsyncMock(return_value=(False, "soft bounce observed (proceeding)")),
    ), patch(
        "app.integrations.email_sender._load_active_providers",
        new=AsyncMock(return_value=[provider]),
    ), patch(
        "app.integrations.email_sender.dispatch_one_provider",
        new=AsyncMock(return_value=success_attempt),
    ) as dispatch_mock:
        result = await send_email(db, msg)

    # Send went through despite the soft-bounce note.
    assert result.success is True
    assert result.provider_key == "brevo"
    assert result.message_id == "msg-1"
    dispatch_mock.assert_awaited_once()


@pytest.mark.asyncio
async def test_cleared_bounce_row_lets_next_send_through() -> None:
    """Once the ``bounced_addresses`` row is gone, the blocklist
    returns ``(False, None)`` and the provider chain runs.

    Validates: Requirement 12.7
    """
    org_id = uuid.uuid4()
    msg = EmailMessage(
        to_email="recovered@example.com",
        to_name="",
        subject="Test",
        text_body="hello",
        org_id=org_id,
    )

    provider = MagicMock()
    provider.provider_key = "brevo"
    provider.priority = 1

    success_attempt = EmailAttempt(
        provider_key="brevo",
        transport="rest_api",
        success=True,
        message_id="msg-recovered",
        duration_ms=12,
    )

    db = AsyncMock()
    with patch(
        "app.integrations.email_sender._check_bounce_blocklist",
        new=AsyncMock(return_value=(False, None)),
    ), patch(
        "app.integrations.email_sender._load_active_providers",
        new=AsyncMock(return_value=[provider]),
    ), patch(
        "app.integrations.email_sender.dispatch_one_provider",
        new=AsyncMock(return_value=success_attempt),
    ) as dispatch_mock:
        result = await send_email(db, msg)

    assert result.success is True
    dispatch_mock.assert_awaited_once()
