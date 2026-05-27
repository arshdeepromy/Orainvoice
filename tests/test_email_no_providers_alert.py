"""Unit tests for the ``no_active_email_providers`` in-app alert.

Covers task 4.7 of the email-provider-unification spec: when
:func:`app.integrations.email_sender.send_email` is called and the
``Active_Provider_Set`` is empty, the helper
:func:`_maybe_fire_no_providers_alert` must:

1. Fire one ``create_in_app_notification`` call on the **first** invocation;
2. Skip the call on a **second** invocation that lands inside the
   ``NO_PROVIDERS_DEDUP_SECONDS`` (1 hour) window — the Redis SETNX
   sentinel returns falsy because the key is still set;
3. Fire again on a **third** invocation after the dedup TTL has expired
   (simulated by clearing the fake-Redis key).

We mock :class:`redis.asyncio.Redis` with a tiny in-process fake whose
``set(key, value, nx=True, ex=...)`` method mirrors the real SETNX
contract: returns ``True`` the first time and ``None`` on subsequent
calls within the window. The test directly clears the fake's storage
between calls 2 and 3 to model the natural TTL expiry that would
otherwise require ``time.sleep`` on a real Redis instance.

``_load_active_providers`` is patched to return ``[]`` so the loop
short-circuits to the alert. ``_check_bounce_blocklist`` is patched to
return ``(False, None)`` because the bounce-blocklist check happens
before the provider-set load. ``create_in_app_notification`` is
imported inside ``_maybe_fire_no_providers_alert`` from
``app.modules.in_app_notifications.service`` — patching at that module
intercepts every call.

Validates: Requirements 10.1, 10.3, 21.9
"""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

# Import models so SQLAlchemy can resolve all relationships at import time.
import app.modules.admin.models  # noqa: F401
import app.modules.inventory.models  # noqa: F401
from app.modules.auth.models import User  # noqa: F401

from app.integrations.email_sender import (
    EmailMessage,
    SendResult,
    send_email,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


class _FakeRedis:
    """Tiny in-process Redis fake covering the SETNX+TTL contract.

    Only ``set(key, value, nx=True, ex=ttl)`` is implemented because
    that's the entire surface :func:`_alert_dedup_should_fire` uses.

    - Returns ``True`` when the key didn't already exist (the caller
      claims the dedup window).
    - Returns ``None`` when ``nx=True`` and the key is already present
      (mirrors real Redis SETNX semantics — the dedup check fires
      ``False`` and the alert is skipped).

    TTL is recorded but not enforced — tests that exercise expiry
    manually clear ``self._keys`` to simulate the TTL elapsing.
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


def _empty_message() -> EmailMessage:
    """Build a minimal valid ``EmailMessage`` — content is irrelevant
    here because the loop never reaches a dispatcher."""
    return EmailMessage(
        to_email="user@example.com",
        to_name="User",
        subject="Subject",
        html_body="<p>Body</p>",
        text_body="Body",
    )


# ---------------------------------------------------------------------------
# Test cases
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_first_call_fires_in_app_notification() -> None:
    """First ``send_email`` with no active providers fires the alert.

    The SETNX call returns truthy because the dedup key has never been
    set, so ``_maybe_fire_no_providers_alert`` proceeds to call
    ``create_in_app_notification`` exactly once with the documented
    kwargs (category, severity, title, body, link_url, audience_roles).

    Validates: Requirements 10.1, 21.9
    """
    fake_redis = _FakeRedis()
    create_notif_stub = AsyncMock(return_value=None)
    db = AsyncMock()

    with patch(
        "app.integrations.email_sender._load_active_providers",
        new=AsyncMock(return_value=[]),
    ), patch(
        "app.integrations.email_sender._check_bounce_blocklist",
        new=AsyncMock(return_value=(False, None)),
    ), patch(
        "app.core.redis.redis_pool", fake_redis,
    ), patch(
        "app.modules.in_app_notifications.service.create_in_app_notification",
        new=create_notif_stub,
    ):
        result = await send_email(db, _empty_message())

    # Aggregate result reflects the no-providers short-circuit.
    assert isinstance(result, SendResult)
    assert result.success is False
    assert result.attempts == []
    assert result.error == "No active email providers configured"

    # Notification fired exactly once with the spec's kwargs.
    assert create_notif_stub.await_count == 1
    _, kwargs = create_notif_stub.call_args
    assert kwargs["category"] == "email_failure"
    assert kwargs["severity"] == "error"
    assert kwargs["title"] == "No email providers configured"
    assert "Outbound email is currently disabled" in kwargs["body"]
    assert kwargs["link_url"] == "/admin/email-providers"
    assert kwargs["audience_roles"] == ["global_admin"]

    # Redis sentinel is in place after the first fire.
    assert "email_no_providers_alert" in fake_redis._keys


@pytest.mark.asyncio
async def test_second_call_within_dedup_window_does_not_fire() -> None:
    """Second invocation inside the 1-hour window is suppressed.

    The fake Redis already holds the sentinel key from the first call,
    so its ``set(..., nx=True)`` returns ``None`` and
    :func:`_alert_dedup_should_fire` returns ``False``. The alert path
    therefore exits early — no ``create_in_app_notification`` call
    happens for the second send.

    Validates: Requirements 10.3, 21.9
    """
    fake_redis = _FakeRedis()
    create_notif_stub = AsyncMock(return_value=None)
    db = AsyncMock()

    load_stub = AsyncMock(return_value=[])
    blocklist_stub = AsyncMock(return_value=(False, None))

    with patch(
        "app.integrations.email_sender._load_active_providers",
        new=load_stub,
    ), patch(
        "app.integrations.email_sender._check_bounce_blocklist",
        new=blocklist_stub,
    ), patch(
        "app.core.redis.redis_pool", fake_redis,
    ), patch(
        "app.modules.in_app_notifications.service.create_in_app_notification",
        new=create_notif_stub,
    ):
        await send_email(db, _empty_message())  # call 1 → fires
        await send_email(db, _empty_message())  # call 2 → deduped

    # Only the first call fires the alert.
    assert create_notif_stub.await_count == 1

    # Both invocations still ran the failover loop (and both returned
    # the same no-providers failure shape).
    assert load_stub.await_count == 2


@pytest.mark.asyncio
async def test_after_ttl_expiry_third_call_fires_again() -> None:
    """After the dedup TTL elapses, the alert fires once more.

    We simulate TTL expiry by manually deleting the fake-Redis key
    between calls 2 and 3 — equivalent to Redis evicting the entry
    after ``NO_PROVIDERS_DEDUP_SECONDS``. The third invocation finds
    the key absent, claims it via SETNX, and fires the notification.

    Total: notifications fire on calls 1 and 3 (2 fires), suppressed on
    call 2 (1 dedup hit).

    Validates: Requirements 10.3, 21.9
    """
    fake_redis = _FakeRedis()
    create_notif_stub = AsyncMock(return_value=None)
    db = AsyncMock()

    with patch(
        "app.integrations.email_sender._load_active_providers",
        new=AsyncMock(return_value=[]),
    ), patch(
        "app.integrations.email_sender._check_bounce_blocklist",
        new=AsyncMock(return_value=(False, None)),
    ), patch(
        "app.core.redis.redis_pool", fake_redis,
    ), patch(
        "app.modules.in_app_notifications.service.create_in_app_notification",
        new=create_notif_stub,
    ):
        await send_email(db, _empty_message())  # call 1 → fires
        await send_email(db, _empty_message())  # call 2 → deduped

        # Simulate the 1-hour TTL elapsing.
        fake_redis._keys.pop("email_no_providers_alert", None)
        fake_redis._ttls.pop("email_no_providers_alert", None)

        await send_email(db, _empty_message())  # call 3 → fires again

    # Two fires (calls 1 and 3), one suppression (call 2).
    assert create_notif_stub.await_count == 2

    # Sentinel re-claimed by call 3.
    assert "email_no_providers_alert" in fake_redis._keys
