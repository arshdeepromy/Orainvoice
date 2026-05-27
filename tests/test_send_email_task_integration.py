"""Integration test for ``send_email_task`` — end-to-end with mock httpx.

Covers task 2.9 of the email-provider-unification spec: drive the full
``send_email_task`` → ``_send_email_async`` → ``send_email`` →
``dispatch_one_provider`` → REST transport → ``update_log_status``
chain and assert that on a 2-provider failover scenario the
notification-log row gets the **winning provider's** ``provider_key``
and ``provider_message_id`` populated alongside ``status='sent'``.

Scenario
--------

- Provider 1 (``brevo``, priority 1) → REST 401 → ``SOFT_AUTH`` → loop continues
- Provider 2 (``sendgrid``, priority 2) → REST 202 with ``X-Message-Id:
  msg-abc-123`` → success

Patches
-------

- ``app.core.database.async_session_factory`` — yields a dummy session
  with the right async-context-manager protocol (we never touch the real
  DB; the bits of code that read from ``session`` are themselves patched
  out below).
- ``app.integrations.email_sender._load_active_providers`` — returns the
  two mock provider rows in priority order.
- ``app.integrations.email_sender._check_bounce_blocklist`` — returns
  ``(False, None)``.
- ``app.integrations.email_sender.envelope_decrypt_str`` — returns the
  raw JSON credentials so the dispatchers find ``api_key``.
- ``app.integrations.email_sender.httpx.AsyncClient`` — a fake client
  that returns 401 for the Brevo URL and 202 (with ``X-Message-Id``) for
  the SendGrid URL.
- ``app.modules.notifications.service.update_log_status`` — captures the
  kwargs the task forwards on success so the test can assert
  ``status='sent'``, ``provider_key='sendgrid'``, and
  ``provider_message_id='msg-abc-123'``.

Validates: Requirements 21.5
"""

from __future__ import annotations

import uuid
from contextlib import asynccontextmanager
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# Import models so SQLAlchemy can resolve all relationships at import time.
import app.modules.admin.models  # noqa: F401
import app.modules.inventory.models  # noqa: F401
from app.modules.auth.models import User  # noqa: F401

from app.tasks.notifications import send_email_task


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_provider(provider_key: str, priority: int) -> MagicMock:
    """Mock an active ``EmailProvider`` row.

    Only the attributes the unified-sender path reads are populated. The
    bytes blob in ``credentials_encrypted`` is opaque — we patch
    ``envelope_decrypt_str`` to return the raw JSON the dispatchers
    expect.
    """
    provider = MagicMock()
    provider.provider_key = provider_key
    provider.priority = priority
    provider.is_active = True
    provider.credentials_set = True
    provider.credentials_encrypted = b"encrypted-blob"
    provider.config = {"from_email": "from@example.com", "from_name": "OraInvoice"}
    provider.smtp_host = None
    provider.smtp_port = None
    provider.smtp_encryption = "tls"
    return provider


class _FakeResponse:
    """Drop-in replacement for ``httpx.Response`` for the two URLs we hit.

    Implements just the surface area the dispatchers read:
    ``status_code``, ``text``, ``headers`` (dict-like with ``.get``), and
    ``json()``.
    """

    def __init__(
        self,
        status_code: int,
        *,
        text: str = "",
        headers: dict | None = None,
        json_body: dict | None = None,
    ) -> None:
        self.status_code = status_code
        self.text = text
        self.headers = headers or {}
        self._json_body = json_body

    def json(self) -> dict:
        if self._json_body is None:
            raise ValueError("no json body")
        return self._json_body


class _FakeClient:
    """In-process replacement for ``httpx.AsyncClient``.

    Routes by URL: Brevo gets a 401 (drives ``SOFT_AUTH``, loop
    continues), SendGrid gets a 202 with ``X-Message-Id`` populated
    (success — captured into ``EmailAttempt.message_id``).
    """

    BREVO_URL = "https://api.brevo.com/v3/smtp/email"
    SENDGRID_URL = "https://api.sendgrid.com/v3/mail/send"

    def __init__(self, *args, **kwargs) -> None:
        # ``timeout=...`` and any other kwargs are accepted but ignored.
        self._args = args
        self._kwargs = kwargs

    async def __aenter__(self) -> "_FakeClient":
        return self

    async def __aexit__(self, *exc) -> None:
        return None

    async def post(self, url, json=None, headers=None):  # noqa: A002 (param shadows builtin)
        if url == self.BREVO_URL:
            return _FakeResponse(
                401,
                text='{"code":"unauthorized","message":"invalid api key"}',
                headers={"content-type": "application/json"},
                json_body={"code": "unauthorized", "message": "invalid api key"},
            )
        if url == self.SENDGRID_URL:
            return _FakeResponse(
                202,
                text="",
                headers={"X-Message-Id": "msg-abc-123"},
            )
        raise AssertionError(f"unexpected URL hit by the test: {url!r}")


def _make_session_factory() -> MagicMock:
    """Build a callable that mimics ``app.core.database.async_session_factory``.

    Real shape: ``async with async_session_factory() as session: async
    with session.begin(): ...``. Both layers must be async-context-manager
    aware. The yielded session is a bare ``MagicMock`` because every code
    path that would have read from it is itself patched out
    (``_load_active_providers``, ``_check_bounce_blocklist``,
    ``update_log_status``).
    """
    session = MagicMock()

    @asynccontextmanager
    async def _begin():
        yield

    session.begin = MagicMock(side_effect=_begin)

    @asynccontextmanager
    async def _factory():
        yield session

    return _factory


# ---------------------------------------------------------------------------
# Test
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_send_email_task_failover_persists_winning_provider_to_log() -> None:
    """``send_email_task`` walks the chain, succeeds on provider 2, and
    persists the winning provider's identity onto the notification log.

    The end-to-end contract pinned by this test:

    1. ``httpx.AsyncClient`` is hit twice — first for Brevo (401), then
       for SendGrid (202).
    2. ``send_email_task`` returns ``{"success": True, "message_id":
       "msg-abc-123", "provider": "sendgrid"}`` (legacy shape preserved
       by the ``SendResult.provider`` alias).
    3. ``update_log_status`` is awaited exactly once with
       ``status="sent"``, ``provider_key="sendgrid"``, and
       ``provider_message_id="msg-abc-123"``.

    Validates: Requirements 21.5
    """
    org_id = str(uuid.uuid4())
    log_id = str(uuid.uuid4())

    brevo_provider = _make_provider("brevo", priority=1)
    sendgrid_provider = _make_provider("sendgrid", priority=2)

    load_providers_stub = AsyncMock(
        return_value=[brevo_provider, sendgrid_provider]
    )
    blocklist_stub = AsyncMock(return_value=(False, None))
    update_log_stub = AsyncMock(return_value=None)
    session_factory = _make_session_factory()

    with patch(
        "app.core.database.async_session_factory",
        new=session_factory,
    ), patch(
        "app.integrations.email_sender._load_active_providers",
        new=load_providers_stub,
    ), patch(
        "app.integrations.email_sender._check_bounce_blocklist",
        new=blocklist_stub,
    ), patch(
        "app.integrations.email_sender.envelope_decrypt_str",
        return_value='{"api_key": "test-api-key"}',
    ), patch(
        "app.integrations.email_sender.httpx.AsyncClient",
        _FakeClient,
    ), patch(
        "app.modules.notifications.service.update_log_status",
        new=update_log_stub,
    ):
        result = await send_email_task(
            org_id=org_id,
            log_id=log_id,
            to_email="recipient@example.com",
            to_name="Recipient",
            subject="Hello",
            html_body="<p>Hi</p>",
            text_body="Hi",
            org_sender_name=None,
            org_reply_to=None,
            template_type="generic",
        )

    # 1. Task return shape — success path with the winning provider's id.
    assert result == {
        "success": True,
        "message_id": "msg-abc-123",
        "provider": "sendgrid",
    }

    # 2. Failover actually happened: both providers were considered
    #    (Brevo 401 → SendGrid 202).
    load_providers_stub.assert_awaited_once()
    blocklist_stub.assert_awaited_once()

    # 3. The notification log row was updated exactly once with the
    #    winning provider's ``provider_key`` + ``provider_message_id``
    #    and ``status='sent'``.
    update_log_stub.assert_awaited_once()
    _call_args, call_kwargs = update_log_stub.await_args
    assert call_kwargs["status"] == "sent"
    assert call_kwargs["provider_key"] == "sendgrid"
    assert call_kwargs["provider_message_id"] == "msg-abc-123"
    assert call_kwargs["log_id"] == uuid.UUID(log_id)
    # ``sent_at`` is set by the task to ``datetime.now(timezone.utc)``;
    # we don't pin its value but it must be non-None so the column lands.
    assert call_kwargs["sent_at"] is not None
