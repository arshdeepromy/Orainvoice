"""Unit tests for the ``all_email_providers_auth_failed`` in-app alert.

Covers task 4.8 of the email-provider-unification spec: when
:func:`app.integrations.email_sender.send_email` walks the entire
active-provider chain and every attempt returns ``FailureKind.SOFT_AUTH``
(typically a 401 from the provider's REST API), the helper
:func:`_maybe_fire_all_auth_fail_alert` must:

1. Fire one ``create_in_app_notification`` call on the **first** such
   send;
2. Skip the call on a **second** send within the
   ``ALL_AUTH_FAIL_DEDUP_SECONDS`` (24 hour) window;
3. **Not** fire when one of the providers in the chain succeeds —
   ``send_email`` short-circuits on success and never reaches the
   "every attempt was SOFT_AUTH" branch.

Test strategy: drive ``send_email`` end-to-end with three Brevo REST
providers (all consume an ``api_key`` and therefore route through
:func:`_dispatch_brevo_rest`), patching ``httpx.AsyncClient`` with a
fake whose ``post`` returns 401 for the first two providers and either
401 (chain-fails case) or 202 (one-succeeds case) for the third.
``envelope_decrypt_str`` is patched to return a valid JSON credentials
blob so the dispatcher's decryption gate passes. The Redis sentinel is
mocked with the same in-process fake used by
``tests/test_email_no_providers_alert.py`` for the no-providers alert.

Validates: Requirements 10.2, 10.4, 21.9
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
    EmailMessage,
    FailureKind,
    SendResult,
    send_email,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


class _FakeRedis:
    """In-process Redis fake covering the SETNX+TTL contract.

    Mirrors the helper in ``tests/test_email_no_providers_alert.py`` —
    re-implemented locally so each test file is self-contained.
    """

    def __init__(self) -> None:
        self._keys: dict[str, str] = {}
        self._ttls: dict[str, int | None] = {}

    async def set(
        self,
        key: str,
        value: str,
        *,
        nx: bool = False,
        ex: int | None = None,
    ) -> bool | None:
        if nx and key in self._keys:
            return None
        self._keys[key] = value
        self._ttls[key] = ex
        return True


def _make_provider(provider_key: str, priority: int) -> MagicMock:
    """Mock an active ``EmailProvider`` row.

    Configured for the Brevo REST dispatch path: ``credentials_set`` is
    True and ``provider_key="brevo"`` (combined with the patched
    ``envelope_decrypt_str`` returning ``{"api_key": ...}``) means
    :func:`dispatch_one_provider` routes to :func:`_dispatch_brevo_rest`.
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


def _make_message() -> EmailMessage:
    return EmailMessage(
        to_email="user@example.com",
        to_name="User",
        subject="Subject",
        html_body="<p>Body</p>",
        text_body="Body",
        org_id=uuid.uuid4(),
    )


class _FakeResp:
    """Minimal ``httpx.Response`` stand-in for ``_dispatch_brevo_rest``.

    The dispatcher reads ``status_code``, ``text``, ``headers``, and
    calls ``json()``. A bare ``MagicMock`` would work but a hand-rolled
    class makes the stub's surface obvious.
    """

    def __init__(
        self,
        *,
        status_code: int,
        body: dict | None = None,
        text: str = "",
    ) -> None:
        self.status_code = status_code
        self._body = body
        self.text = text
        self.headers = {"content-type": "application/json"}

    def json(self) -> dict:
        if self._body is None:
            raise ValueError("no body")
        return self._body


def _make_fake_client(responses: list[_FakeResp]):
    """Build a fake ``httpx.AsyncClient`` whose ``post`` returns each
    response in ``responses`` in order.

    ``call_count`` on the returned class lets the test assert exactly
    how many provider attempts hit the network.
    """

    class _FakeClient:
        call_count = 0

        def __init__(self, *args, **kwargs) -> None:
            self._args = args
            self._kwargs = kwargs

        async def __aenter__(self) -> "_FakeClient":
            return self

        async def __aexit__(self, *a) -> None:
            return None

        async def post(self, url, json=None, headers=None):
            idx = type(self).call_count
            type(self).call_count += 1
            if idx >= len(responses):
                # Defensive: the test should never request more
                # responses than it queued.
                raise AssertionError(
                    f"FakeClient: post() called {idx + 1} times but "
                    f"only {len(responses)} responses were queued"
                )
            return responses[idx]

    return _FakeClient


# ---------------------------------------------------------------------------
# Test cases
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_first_send_with_all_soft_auth_fires_alert() -> None:
    """3-provider chain all returning 401 fires the alert exactly once.

    Every provider attempt classifies as ``FailureKind.SOFT_AUTH`` so
    the loop reaches its end with three failures, none of which were
    short-circuiting (HARD_*). The chain-exhaustion branch then fires
    :func:`_maybe_fire_all_auth_fail_alert`, which (Redis sentinel was
    empty) calls ``create_in_app_notification`` once with the
    all-auth-fail kwargs.

    Validates: Requirements 10.2, 21.9
    """
    providers = [
        _make_provider("brevo", priority=1),
        _make_provider("brevo", priority=2),
        _make_provider("brevo", priority=3),
    ]
    fake_client_cls = _make_fake_client(
        [
            _FakeResp(status_code=401, text="Unauthorized"),
            _FakeResp(status_code=401, text="Unauthorized"),
            _FakeResp(status_code=401, text="Unauthorized"),
        ]
    )
    fake_redis = _FakeRedis()
    create_notif_stub = AsyncMock(return_value=None)
    db = AsyncMock()

    with patch(
        "app.integrations.email_sender._load_active_providers",
        new=AsyncMock(return_value=providers),
    ), patch(
        "app.integrations.email_sender._check_bounce_blocklist",
        new=AsyncMock(return_value=(False, None)),
    ), patch(
        "app.integrations.email_sender.envelope_decrypt_str",
        return_value='{"api_key": "xkeysib-test"}',
    ), patch(
        "app.integrations.email_sender.httpx.AsyncClient", fake_client_cls,
    ), patch(
        "app.core.redis.redis_pool", fake_redis,
    ), patch(
        "app.modules.in_app_notifications.service.create_in_app_notification",
        new=create_notif_stub,
    ):
        result = await send_email(db, _make_message())

    # Aggregate result: total failure with three SOFT_AUTH attempts.
    assert isinstance(result, SendResult)
    assert result.success is False
    assert len(result.attempts) == 3
    assert all(
        a.failure_kind == FailureKind.SOFT_AUTH for a in result.attempts
    )

    # Every provider was attempted (no short-circuit).
    assert fake_client_cls.call_count == 3

    # Notification fired exactly once with the documented kwargs.
    assert create_notif_stub.await_count == 1
    _, kwargs = create_notif_stub.call_args
    assert kwargs["category"] == "email_failure"
    assert kwargs["severity"] == "error"
    assert kwargs["title"] == "All email providers failed authentication"
    assert "credentials" in kwargs["body"].lower()
    assert kwargs["link_url"] == "/admin/email-providers"
    assert kwargs["audience_roles"] == ["global_admin"]

    # Redis sentinel claimed under the right key.
    assert "email_all_auth_fail_alert" in fake_redis._keys


@pytest.mark.asyncio
async def test_subsequent_send_within_dedup_window_does_not_fire() -> None:
    """Second all-SOFT_AUTH send within 24h is suppressed.

    The fake Redis already holds the all-auth-fail sentinel from the
    first chain-exhaustion, so the second send's
    :func:`_alert_dedup_should_fire` returns ``False`` and the
    notification call is skipped — only the first send fires the alert.

    Validates: Requirements 10.4, 21.9
    """
    providers = [
        _make_provider("brevo", priority=1),
        _make_provider("brevo", priority=2),
        _make_provider("brevo", priority=3),
    ]
    # Six 401s — three per send, two sends.
    fake_client_cls = _make_fake_client(
        [_FakeResp(status_code=401, text="Unauthorized") for _ in range(6)]
    )
    fake_redis = _FakeRedis()
    create_notif_stub = AsyncMock(return_value=None)
    db = AsyncMock()

    with patch(
        "app.integrations.email_sender._load_active_providers",
        new=AsyncMock(return_value=providers),
    ), patch(
        "app.integrations.email_sender._check_bounce_blocklist",
        new=AsyncMock(return_value=(False, None)),
    ), patch(
        "app.integrations.email_sender.envelope_decrypt_str",
        return_value='{"api_key": "xkeysib-test"}',
    ), patch(
        "app.integrations.email_sender.httpx.AsyncClient", fake_client_cls,
    ), patch(
        "app.core.redis.redis_pool", fake_redis,
    ), patch(
        "app.modules.in_app_notifications.service.create_in_app_notification",
        new=create_notif_stub,
    ):
        result1 = await send_email(db, _make_message())
        result2 = await send_email(db, _make_message())

    # Both sends fail (chain exhausted both times).
    assert result1.success is False
    assert result2.success is False
    assert len(result1.attempts) == 3
    assert len(result2.attempts) == 3

    # All six provider attempts hit the wire — dedup only suppresses
    # the in-app notification, not the underlying send retries.
    assert fake_client_cls.call_count == 6

    # Only the first chain-exhaustion fired the alert.
    assert create_notif_stub.await_count == 1


@pytest.mark.asyncio
async def test_one_provider_succeeds_does_not_fire() -> None:
    """Successful send anywhere in the chain skips the alert entirely.

    First two providers return 401 (SOFT_AUTH), third returns 202 with
    a valid Brevo ``messageId``. ``send_email`` short-circuits on the
    third attempt's success and returns ``SendResult.success=True``,
    never reaching the chain-exhaustion / all-auth-fail branch — so the
    alert is not fired and the Redis sentinel stays unset.

    Validates: Requirements 10.2 (negative), 21.9
    """
    providers = [
        _make_provider("brevo", priority=1),
        _make_provider("brevo", priority=2),
        _make_provider("brevo", priority=3),
    ]
    fake_client_cls = _make_fake_client(
        [
            _FakeResp(status_code=401, text="Unauthorized"),
            _FakeResp(status_code=401, text="Unauthorized"),
            _FakeResp(
                status_code=201,
                body={"messageId": "<msg-success@brevo>"},
            ),
        ]
    )
    fake_redis = _FakeRedis()
    create_notif_stub = AsyncMock(return_value=None)
    db = AsyncMock()

    with patch(
        "app.integrations.email_sender._load_active_providers",
        new=AsyncMock(return_value=providers),
    ), patch(
        "app.integrations.email_sender._check_bounce_blocklist",
        new=AsyncMock(return_value=(False, None)),
    ), patch(
        "app.integrations.email_sender.envelope_decrypt_str",
        return_value='{"api_key": "xkeysib-test"}',
    ), patch(
        "app.integrations.email_sender.httpx.AsyncClient", fake_client_cls,
    ), patch(
        "app.core.redis.redis_pool", fake_redis,
    ), patch(
        "app.modules.in_app_notifications.service.create_in_app_notification",
        new=create_notif_stub,
    ):
        result = await send_email(db, _make_message())

    # Aggregate result: success on the third provider.
    assert result.success is True
    assert result.message_id == "<msg-success@brevo>"
    assert len(result.attempts) == 3
    assert result.attempts[0].failure_kind == FailureKind.SOFT_AUTH
    assert result.attempts[1].failure_kind == FailureKind.SOFT_AUTH
    assert result.attempts[2].success is True

    # Three provider attempts — dispatcher never short-circuited.
    assert fake_client_cls.call_count == 3

    # Alert NOT fired: the chain wasn't exhausted, so the
    # all-auth-fail branch never ran.
    assert create_notif_stub.await_count == 0
    assert "email_all_auth_fail_alert" not in fake_redis._keys
