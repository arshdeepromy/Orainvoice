"""Unit tests for :mod:`app.integrations.sms_sender`.

Covers task C4 from ``.kiro/specs/staff-management-p1``:

1. **Happy path** — active provider configured, ``ConnexusSmsClient.send``
   returns success → :class:`SmsSendResult` carries ``ok=True`` with the
   provider message id and provider key, and no DLQ row is stored.
2. **Provider raises** — the Connexus client's ``send`` blows up
   (network/auth/etc) → :class:`SmsSendResult` carries ``ok=False``
   with ``reason='provider_error'`` and the DLQ row is written when
   ``dlq_task_name`` was supplied.
3. **No active provider** — the lookup returns no row → result has
   ``reason='no_active_provider'`` and no DLQ row is written (because
   nothing to retry against).
4. **Provider rejects (structured failure)** — ``client.send`` returns
   ``SmsSendResult(success=False, error='401: nope')`` → result is
   ``reason='provider_error'`` and the DLQ row captures the structured
   error.
5. **Missing credentials** — provider row exists but
   ``credentials_encrypted`` is ``None`` → result is
   ``reason='missing_credentials'`` and the DLQ row is stored when
   requested.

The tests stub ``db.execute`` with an ``AsyncMock`` so no PostgreSQL is
required, and patch :class:`ConnexusSmsClient` + :class:`DeadLetterService`
to focus the assertions on the orchestrator's branching logic.

**Validates: Requirement R9 prerequisite — Staff Phase 1 task C4.**
"""

from __future__ import annotations

import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.integrations.sms_sender import SmsSendResult, send_sms
from app.integrations.sms_types import SmsSendResult as ConnexusSendResult


# ---------------------------------------------------------------------------
# Test helpers
# ---------------------------------------------------------------------------


_VALID_CREDS_PLAINTEXT = (
    '{"client_id":"abc","client_secret":"shh","sender_id":"OraInvoice"}'
)


def _make_provider(
    *,
    provider_key: str = "connexus",
    is_active: bool = True,
    credentials_encrypted: bytes | None = b"\x00" * 16 + b"sentinel-creds",
):
    """Build a duck-typed stand-in for ``SmsVerificationProvider``.

    Using ``SimpleNamespace`` (rather than instantiating the real ORM
    class) keeps the test independent of the broader SQLAlchemy mapper
    configuration. ``send_sms`` only reads attributes off the row, so a
    plain object is sufficient and won't drag the full registry into
    the test session.
    """
    return SimpleNamespace(
        id=uuid.uuid4(),
        provider_key=provider_key,
        display_name=provider_key,
        is_active=is_active,
        is_default=True,
        priority=0,
        credentials_encrypted=credentials_encrypted,
        credentials_set=credentials_encrypted is not None,
        config={},
    )


def _make_db(provider) -> AsyncMock:
    """Build an ``AsyncMock`` DB session whose first execute() returns the provider."""
    db = AsyncMock()

    async def fake_execute(stmt):  # noqa: ARG001 - stmt inspection unnecessary
        result = MagicMock()
        scalars = MagicMock()
        scalars.first.return_value = provider
        result.scalars.return_value = scalars
        return result

    db.execute = fake_execute
    return db


class _StubConnexusClient:
    """Lightweight stand-in for :class:`ConnexusSmsClient`."""

    def __init__(self, *, send_result=None, send_exc: Exception | None = None):
        self._send_result = send_result
        self._send_exc = send_exc
        self.sent_messages: list = []
        self.closed = False

    async def send(self, message):
        self.sent_messages.append(message)
        if self._send_exc is not None:
            raise self._send_exc
        return self._send_result

    async def close(self):
        self.closed = True


# ---------------------------------------------------------------------------
# Happy path
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_happy_path_returns_ok_with_message_id():
    """Active provider + successful send → ``ok=True`` with message id."""
    provider = _make_provider()
    db = _make_db(provider)

    stub = _StubConnexusClient(
        send_result=ConnexusSendResult(success=True, message_sid="ws-123"),
    )

    with (
        patch(
            "app.integrations.sms_sender.envelope_decrypt_str",
            return_value=_VALID_CREDS_PLAINTEXT,
        ),
        patch(
            "app.integrations.sms_sender.ConnexusSmsClient",
            return_value=stub,
        ),
        patch(
            "app.core.dead_letter.DeadLetterService.store_failed_task",
            new=AsyncMock(),
        ) as mock_dlq,
    ):
        result = await send_sms(
            db,
            to_phone="+64211234567",
            body="Hello",
            dlq_task_name="roster_sms",
        )

    assert isinstance(result, SmsSendResult)
    assert result.ok is True
    assert result.message_id == "ws-123"
    assert result.provider_key == "connexus"
    assert result.reason is None
    assert stub.closed is True
    assert len(stub.sent_messages) == 1
    assert stub.sent_messages[0].to_number == "+64211234567"
    assert stub.sent_messages[0].body == "Hello"
    mock_dlq.assert_not_called()


# ---------------------------------------------------------------------------
# Provider down — exception path with DLQ
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_provider_exception_writes_dlq_when_requested():
    """``client.send`` raising an exception triggers DLQ + ``provider_error``."""
    provider = _make_provider()
    db = _make_db(provider)
    org_id = uuid.uuid4()

    stub = _StubConnexusClient(send_exc=RuntimeError("boom"))

    with (
        patch(
            "app.integrations.sms_sender.envelope_decrypt_str",
            return_value=_VALID_CREDS_PLAINTEXT,
        ),
        patch(
            "app.integrations.sms_sender.ConnexusSmsClient",
            return_value=stub,
        ),
        patch(
            "app.core.dead_letter.DeadLetterService.store_failed_task",
            new=AsyncMock(),
        ) as mock_dlq,
    ):
        result = await send_sms(
            db,
            to_phone="+64211234567",
            body="Hello",
            dlq_task_name="roster_sms",
            dlq_task_args={"staff_id": "abc-123"},
            org_id=org_id,
        )

    assert result.ok is False
    assert result.provider_key == "connexus"
    assert result.reason == "provider_error"
    assert stub.closed is True
    mock_dlq.assert_called_once()
    kwargs = mock_dlq.call_args.kwargs
    assert kwargs["task_name"] == "roster_sms"
    assert kwargs["task_args"]["to_phone"] == "+64211234567"
    assert kwargs["task_args"]["body"] == "Hello"
    assert kwargs["task_args"]["staff_id"] == "abc-123"
    assert "boom" in kwargs["error_message"]
    assert kwargs["org_id"] == org_id


@pytest.mark.asyncio
async def test_provider_exception_no_dlq_when_not_requested():
    """Without ``dlq_task_name`` we still return ``ok=False`` but skip the DLQ insert."""
    provider = _make_provider()
    db = _make_db(provider)

    stub = _StubConnexusClient(send_exc=RuntimeError("boom"))

    with (
        patch(
            "app.integrations.sms_sender.envelope_decrypt_str",
            return_value=_VALID_CREDS_PLAINTEXT,
        ),
        patch(
            "app.integrations.sms_sender.ConnexusSmsClient",
            return_value=stub,
        ),
        patch(
            "app.core.dead_letter.DeadLetterService.store_failed_task",
            new=AsyncMock(),
        ) as mock_dlq,
    ):
        result = await send_sms(db, to_phone="+64211234567", body="Hello")

    assert result.ok is False
    assert result.reason == "provider_error"
    mock_dlq.assert_not_called()


# ---------------------------------------------------------------------------
# Provider rejects (structured failure)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_provider_rejection_returns_provider_error():
    """``client.send`` returning ``success=False`` → ``provider_error``."""
    provider = _make_provider()
    db = _make_db(provider)

    stub = _StubConnexusClient(
        send_result=ConnexusSendResult(success=False, error="401: bad creds"),
    )

    with (
        patch(
            "app.integrations.sms_sender.envelope_decrypt_str",
            return_value=_VALID_CREDS_PLAINTEXT,
        ),
        patch(
            "app.integrations.sms_sender.ConnexusSmsClient",
            return_value=stub,
        ),
        patch(
            "app.core.dead_letter.DeadLetterService.store_failed_task",
            new=AsyncMock(),
        ) as mock_dlq,
    ):
        result = await send_sms(
            db,
            to_phone="+64211234567",
            body="Hello",
            dlq_task_name="roster_sms",
        )

    assert result.ok is False
    assert result.provider_key == "connexus"
    assert result.reason == "provider_error"
    mock_dlq.assert_called_once()
    assert "401: bad creds" in mock_dlq.call_args.kwargs["error_message"]


# ---------------------------------------------------------------------------
# No active provider
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_no_active_provider_returns_no_active_provider_reason():
    """When the loader returns ``None`` there is nothing to send; no DLQ."""
    db = _make_db(None)

    with patch(
        "app.core.dead_letter.DeadLetterService.store_failed_task",
        new=AsyncMock(),
    ) as mock_dlq:
        result = await send_sms(
            db,
            to_phone="+64211234567",
            body="Hello",
            dlq_task_name="roster_sms",
        )

    assert result.ok is False
    assert result.provider_key is None
    assert result.reason == "no_active_provider"
    # No provider means no point queuing for retry — the platform is
    # misconfigured and replay would just re-fail.
    mock_dlq.assert_not_called()


# ---------------------------------------------------------------------------
# Missing credentials
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_missing_credentials_returns_missing_credentials_reason():
    """Provider row with ``credentials_encrypted=None`` → soft failure."""
    provider = _make_provider(credentials_encrypted=None)
    db = _make_db(provider)

    with patch(
        "app.core.dead_letter.DeadLetterService.store_failed_task",
        new=AsyncMock(),
    ) as mock_dlq:
        result = await send_sms(
            db,
            to_phone="+64211234567",
            body="Hello",
            dlq_task_name="roster_sms",
        )

    assert result.ok is False
    assert result.provider_key == "connexus"
    assert result.reason == "missing_credentials"
    mock_dlq.assert_called_once()
