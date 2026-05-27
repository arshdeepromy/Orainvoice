"""Unit tests for ``send_email`` — 3-provider failover chain.

Covers task 1.11 of the email-provider-unification spec: drive the
public ``send_email`` loop with three active ``EmailProvider`` rows
where:

- Provider 1 returns a Brevo REST 401 → ``FailureKind.SOFT_AUTH``
- Provider 2 raises an httpx connection error → ``FailureKind.SOFT_PROVIDER``
- Provider 3 returns SendGrid REST 202 → success

Both soft failures must let the loop continue, and the third provider's
successful attempt must populate the aggregate ``SendResult``. The test
asserts on the loop's contract (which transports were attempted, in what
order, with which classifications) rather than on the underlying
HTTP/SMTP machinery — the per-transport classification rules are
exercised in ``tests/test_email_sender_error_classification.py``
(task 1.14) and the dispatch matrix is pinned by
``tests/test_email_sender_dispatch.py`` (task 1.10).

We patch ``dispatch_one_provider`` directly with an ``AsyncMock`` whose
``side_effect`` is the three canned ``EmailAttempt``s. This isolates the
test to the loop's contract: "given dispatch_one_provider returned X,
what does send_email do?". ``_load_active_providers`` and
``_check_bounce_blocklist`` are also patched so no DB session is needed.

Validates: Requirements 2.1, 2.2, 21.1
"""

from __future__ import annotations

import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# Import models so SQLAlchemy can resolve all relationships at import time.
import app.modules.admin.models  # noqa: F401
import app.modules.inventory.models  # noqa: F401
from app.modules.auth.models import User  # noqa: F401

from app.integrations.email_sender import (
    EmailAttempt,
    EmailMessage,
    FailureKind,
    SendResult,
    send_email,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_provider(provider_key: str, priority: int) -> MagicMock:
    """Mock an active ``EmailProvider`` row.

    Only the attributes the unified-sender loop reads are populated.
    Credentials decryption is bypassed by patching
    ``dispatch_one_provider`` directly, so the encrypted blob never has
    to round-trip through ``envelope_decrypt_str``.
    """
    provider = MagicMock()
    provider.provider_key = provider_key
    provider.priority = priority
    provider.is_active = True
    provider.credentials_set = True
    provider.credentials_encrypted = b"x"
    provider.config = {"from_email": "from@example.com"}
    provider.smtp_host = None
    provider.smtp_port = None
    provider.smtp_encryption = "tls"
    return provider


# ---------------------------------------------------------------------------
# 3-provider failover chain
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_send_email_failover_chain_succeeds_on_third_provider() -> None:
    """``send_email`` walks the chain and succeeds on the third provider.

    Scenario (per task 1.11):

    - Provider 1 (brevo, priority 1) → 401 → ``SOFT_AUTH``
    - Provider 2 (brevo, priority 2) → connection error → ``SOFT_PROVIDER``
    - Provider 3 (sendgrid, priority 3) → 202 → success

    The loop must continue through both soft failures, succeed on the
    third attempt, and populate the aggregate ``SendResult`` with the
    third provider's identity (key, transport, message_id). All three
    attempts must show up in ``result.attempts`` in priority order with
    their original classifications intact, and ``dispatch_one_provider``
    must be awaited exactly three times (no extra calls after success).

    Validates: Requirements 2.1, 2.2, 21.1
    """
    provider1 = _make_provider("brevo", priority=1)
    provider2 = _make_provider("brevo", priority=2)
    provider3 = _make_provider("sendgrid", priority=3)

    # Canned attempts the patched dispatch_one_provider returns in order.
    attempt1 = EmailAttempt(
        provider_key="brevo",
        transport="rest_api",
        success=False,
        error="brevo REST 401: ",
        failure_kind=FailureKind.SOFT_AUTH,
        duration_ms=12,
    )
    attempt2 = EmailAttempt(
        provider_key="brevo",
        transport="rest_api",
        success=False,
        error="ConnectError: network down",
        failure_kind=FailureKind.SOFT_PROVIDER,
        duration_ms=15,
    )
    attempt3 = EmailAttempt(
        provider_key="sendgrid",
        transport="rest_api",
        success=True,
        error=None,
        failure_kind=None,
        duration_ms=42,
        message_id="<abc-123@sendgrid>",
    )

    dispatch_stub = AsyncMock(side_effect=[attempt1, attempt2, attempt3])
    load_providers_stub = AsyncMock(
        return_value=[provider1, provider2, provider3]
    )
    blocklist_stub = AsyncMock(return_value=(False, None))

    db = AsyncMock()
    message = EmailMessage(
        to_email="to@example.com",
        to_name="Recipient",
        subject="Subject",
        html_body="<p>Hi</p>",
        text_body="Hi",
        org_id=uuid.uuid4(),
    )

    with patch(
        "app.integrations.email_sender.dispatch_one_provider",
        new=dispatch_stub,
    ), patch(
        "app.integrations.email_sender._load_active_providers",
        new=load_providers_stub,
    ), patch(
        "app.integrations.email_sender._check_bounce_blocklist",
        new=blocklist_stub,
    ):
        result = await send_email(db, message)

    # Aggregate result reflects the third (winning) provider.
    assert isinstance(result, SendResult)
    assert result.success is True
    assert result.provider_key == provider3.provider_key
    assert result.transport == "rest_api"
    assert result.message_id == "<abc-123@sendgrid>"

    # All three attempts present in priority order with original
    # classifications intact (the loop must not mutate them).
    assert len(result.attempts) == 3

    assert result.attempts[0] is attempt1
    assert result.attempts[0].success is False
    assert result.attempts[0].failure_kind == FailureKind.SOFT_AUTH

    assert result.attempts[1] is attempt2
    assert result.attempts[1].success is False
    assert result.attempts[1].failure_kind == FailureKind.SOFT_PROVIDER

    assert result.attempts[2] is attempt3
    assert result.attempts[2].success is True
    assert result.attempts[2].failure_kind is None

    # Exactly three dispatches — the loop stopped after the success
    # rather than continuing on to a phantom fourth attempt.
    assert dispatch_stub.await_count == 3
