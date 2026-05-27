"""Unit tests for ``send_email`` per-attempt timeout and total budget.

Covers task 1.15 of the email-provider-unification spec:

- Per-attempt timeout: an ``httpx.TimeoutException`` raised inside a
  REST dispatcher must be classified ``FailureKind.SOFT_PROVIDER`` so
  the failover loop continues to the next provider. We do NOT need to
  test that ``httpx`` itself respects the timeout — that's its own
  test surface. Instead we patch ``httpx.AsyncClient`` so its ``.post``
  raises ``httpx.TimeoutException`` and assert on the attempt the
  dispatcher returns.

- Total budget: a 3-provider chain where each ``dispatch_one_provider``
  call sleeps long enough that the total budget is exhausted before the
  third dispatch starts. We patch ``EMAIL_TOTAL_BUDGET_SECONDS`` to a
  small float (0.1s) so the test runs in well under a second, and use
  short ``asyncio.sleep`` durations to drive real elapsed time. The
  outer-loop gate in :func:`send_email` checks the budget at the top of
  each iteration and, when exceeded, appends an attempt with
  ``failure_kind=BUDGET_EXCEEDED`` instead of dispatching.

Validates: Requirements 5.7, 5.8, 21.3
"""

from __future__ import annotations

import asyncio
import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

# Import models so SQLAlchemy can resolve all relationships at import time.
import app.modules.admin.models  # noqa: F401
import app.modules.inventory.models  # noqa: F401
from app.modules.auth.models import User  # noqa: F401

from app.integrations import email_sender
from app.integrations.email_sender import (
    EmailAttempt,
    EmailMessage,
    FailureKind,
    SendResult,
    _dispatch_brevo_rest,
    send_email,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_provider(provider_key: str, priority: int) -> MagicMock:
    """Mock an active ``EmailProvider`` row used by ``send_email``."""
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


def _make_message() -> EmailMessage:
    return EmailMessage(
        to_email="to@example.com",
        to_name="Recipient",
        subject="Subject line",
        html_body="<p>Hello</p>",
        text_body="Hello",
        org_id=uuid.uuid4(),
    )


# ---------------------------------------------------------------------------
# Test 1 — per-attempt timeout classification
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_per_attempt_httpx_timeout_classified_soft_provider() -> None:
    """``httpx.TimeoutException`` from a REST dispatcher → ``SOFT_PROVIDER``.

    The Brevo REST dispatcher wraps its ``client.post(...)`` in a broad
    ``try/except`` and routes the exception through
    ``_classify_brevo_rest_error(None, exc)`` which delegates to
    ``_classify_network_exc`` for ``httpx.TimeoutException``. The
    failure must surface as ``FailureKind.SOFT_PROVIDER`` so the
    failover loop continues to the next provider rather than
    short-circuiting on what is, from the chain's perspective, a
    transient per-provider hiccup.

    We patch ``httpx.AsyncClient`` with a fake whose ``.post`` raises
    immediately so the test runs at memory speed — there is no point
    actually waiting 15 seconds to confirm httpx's timeout machinery
    works (that's httpx's own test suite).

    Validates: Requirements 5.7, 21.3
    """

    class _FakeClient:
        """Replacement for ``httpx.AsyncClient`` — ``post`` raises a timeout."""

        def __init__(self, *args, **kwargs) -> None:
            # Accept and ignore ``timeout=...`` and any other kwargs.
            pass

        async def __aenter__(self) -> "_FakeClient":
            return self

        async def __aexit__(self, *exc_info) -> None:
            return None

        async def post(self, url, json=None, headers=None):
            raise httpx.TimeoutException("read timed out")

    provider = _make_provider("brevo", priority=1)
    message = _make_message()

    with patch(
        "app.integrations.email_sender.envelope_decrypt_str",
        return_value='{"api_key": "x"}',
    ), patch(
        "app.integrations.email_sender.httpx.AsyncClient",
        _FakeClient,
    ):
        attempt = await _dispatch_brevo_rest(
            provider,
            message,
            from_name="Test",
            from_email="from@example.com",
            reply_to=None,
            timeout_seconds=1,
        )

    assert isinstance(attempt, EmailAttempt)
    assert attempt.success is False
    assert attempt.failure_kind == FailureKind.SOFT_PROVIDER
    # Error string surfaces the exception message so logs are useful.
    assert attempt.error is not None
    assert "timed out" in attempt.error.lower()


# ---------------------------------------------------------------------------
# Test 2 — total budget enforced across a 3-provider chain
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_total_budget_exhausted_marks_last_attempt_budget_exceeded() -> None:
    """3-provider chain where the total budget runs out mid-loop.

    With the budget patched to 0.1s and each dispatch awaiting an
    ``asyncio.sleep(0.06)`` the call timeline is:

    - iter 1: elapsed=~0.0   → under budget → dispatch sleeps 0.06s →
      ``SOFT_PROVIDER`` returned by the stub.
    - iter 2: elapsed=~0.06  → under budget → dispatch sleeps 0.06s →
      ``SOFT_PROVIDER`` returned by the stub. After this, elapsed is
      ~0.12s and exceeds the 0.1s budget.
    - iter 3: elapsed=~0.12  → ABOVE budget → outer-loop gate appends an
      ``EmailAttempt(failure_kind=BUDGET_EXCEEDED)`` and breaks. The
      dispatch stub is NOT called for this provider.

    The assertions stay loose around exact attempt count to absorb CI
    timing variance: at minimum the last attempt's ``failure_kind`` must
    be ``BUDGET_EXCEEDED``, the result must be a failure, and the
    ``dispatch_one_provider`` stub must have been awaited fewer than 3
    times (it never gets to provider 3).

    Validates: Requirements 5.7, 5.8, 21.3
    """
    provider1 = _make_provider("brevo", priority=1)
    provider2 = _make_provider("brevo", priority=2)
    provider3 = _make_provider("sendgrid", priority=3)

    async def _slow_soft_provider(
        db,
        provider,
        message,
        *,
        org_sender_name=None,
        org_reply_to=None,
        timeout_seconds=15,
    ) -> EmailAttempt:
        # Sleep long enough that two iterations push elapsed past the
        # patched 0.1s total budget. Returning SOFT_PROVIDER keeps the
        # loop iterating instead of short-circuiting on a hard failure.
        await asyncio.sleep(0.06)
        return EmailAttempt(
            provider_key=provider.provider_key,
            transport="rest_api",
            success=False,
            error="simulated slow provider",
            failure_kind=FailureKind.SOFT_PROVIDER,
            duration_ms=60,
        )

    dispatch_stub = AsyncMock(side_effect=_slow_soft_provider)
    load_providers_stub = AsyncMock(
        return_value=[provider1, provider2, provider3]
    )
    blocklist_stub = AsyncMock(return_value=(False, None))

    db = AsyncMock()
    message = _make_message()

    with patch.object(
        email_sender, "EMAIL_TOTAL_BUDGET_SECONDS", 0.1
    ), patch(
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

    assert isinstance(result, SendResult)
    assert result.success is False
    # At least one attempt and at most one per provider in the chain.
    assert 1 <= len(result.attempts) <= 3
    # The chain must have stopped before reaching the third provider's
    # dispatch — once the budget is blown the outer gate appends
    # BUDGET_EXCEEDED and breaks instead of awaiting the dispatcher.
    assert dispatch_stub.await_count < 3
    # And the chain MUST end with a BUDGET_EXCEEDED attempt — that's
    # the contract that signals "time budget hit" to upstream callers.
    assert result.attempts[-1].failure_kind == FailureKind.BUDGET_EXCEEDED
    assert any(
        a.failure_kind == FailureKind.BUDGET_EXCEEDED for a in result.attempts
    )
