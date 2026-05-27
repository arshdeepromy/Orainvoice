"""Brevo ``delivered`` event sets ``notification_log.delivered_at``.

Phase 8c task 9.15 of the email-provider-unification spec. Verifies:

- The Brevo webhook handler accepts a ``delivered`` event for a known
  ``provider_message_id`` and issues an UPDATE to set
  ``notification_log.delivered_at = now()``.
- A ``delivered`` event for an unknown id logs an info-level warning
  but does not error — the response is still 200.
- The handler ignores ``delivered`` events for the bounce-side fan-out
  path (no ``flag_bounce`` calls).

Validates: Requirements 11.3, 11.4
"""

from __future__ import annotations

import json
import logging
import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# Import models so SQLAlchemy can resolve relationships at import time.
import app.modules.admin.models  # noqa: F401
import app.modules.inventory.models  # noqa: F401
from app.modules.auth.models import User  # noqa: F401

from app.core.webhook_security import sign_webhook_payload


def _fake_request(body: bytes, headers: dict):
    r = AsyncMock()
    r.body = AsyncMock(return_value=body)
    r.json = AsyncMock(return_value=json.loads(body))
    r.headers = headers
    r.state = MagicMock()
    r.client = MagicMock()
    r.client.host = "127.0.0.1"
    return r


def _empty_provider_lookup():
    """Result for the candidate-secret SELECT — zero providers."""
    scalars = MagicMock()
    scalars.all = MagicMock(return_value=[])
    result = MagicMock()
    result.scalars = MagicMock(return_value=scalars)
    return result


def _update_result(rowcount: int):
    r = MagicMock()
    r.rowcount = rowcount
    return r


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_brevo_delivered_event_sets_delivered_at_when_id_known() -> None:
    """A ``delivered`` event for a known provider_message_id triggers
    an UPDATE on ``notification_log``.

    Validates: Requirement 11.3
    """
    from app.modules.notifications.router import brevo_bounce_webhook

    secret = "shared-secret"
    body = json.dumps(
        {"event": "delivered", "email": "good@example.com", "message-id": "msg-known"}
    ).encode()
    sig = sign_webhook_payload(body, secret)

    db = AsyncMock()
    db.flush = AsyncMock()
    # Two execute calls expected:
    #   1. provider-secret lookup (no rows; env fallback admits the sig)
    #   2. UPDATE notification_log SET delivered_at = now() WHERE
    #      provider_message_id = msg-known (rowcount=1, known id)
    db.execute = AsyncMock(
        side_effect=[_empty_provider_lookup(), _update_result(1)]
    )

    with patch("app.modules.notifications.router.app_settings") as ms, patch(
        "app.modules.notifications.router.flag_bounce", new=AsyncMock()
    ) as flag_mock:
        ms.brevo_webhook_secret = secret
        resp = await brevo_bounce_webhook(
            request=_fake_request(body, {"X-Brevo-Signature": sig}),
            db=db,
        )

    assert resp.status_code == 200
    body_json = json.loads(resp.body)
    assert body_json["delivered_processed"] == 1
    assert body_json["emails_processed"] == 0
    # Bounce-side fan-out never runs for a delivered event.
    flag_mock.assert_not_awaited()
    # The UPDATE must have been issued (second execute call).
    assert db.execute.await_count == 2


@pytest.mark.asyncio
async def test_brevo_delivered_event_unknown_id_logs_warning_no_error(
    caplog,
) -> None:
    """A ``delivered`` event for an unknown id logs at info level and
    returns 200 — losing track of one log row is not worth a 500.

    Validates: Requirement 11.4
    """
    from app.modules.notifications.router import brevo_bounce_webhook

    secret = "shared-secret"
    body = json.dumps(
        {
            "event": "delivered",
            "email": "good@example.com",
            "message-id": "msg-unknown",
        }
    ).encode()
    sig = sign_webhook_payload(body, secret)

    db = AsyncMock()
    db.flush = AsyncMock()
    # Provider lookup empty + UPDATE returns rowcount=0 (no matching log row).
    db.execute = AsyncMock(
        side_effect=[_empty_provider_lookup(), _update_result(0)]
    )

    with patch("app.modules.notifications.router.app_settings") as ms, patch(
        "app.modules.notifications.router.flag_bounce", new=AsyncMock()
    ):
        ms.brevo_webhook_secret = secret
        with caplog.at_level(
            logging.INFO, logger="app.modules.notifications.router"
        ):
            resp = await brevo_bounce_webhook(
                request=_fake_request(body, {"X-Brevo-Signature": sig}),
                db=db,
            )

    assert resp.status_code == 200
    body_json = json.loads(resp.body)
    # No log row was matched, so delivered_processed stays 0.
    assert body_json["delivered_processed"] == 0
    # The handler should have logged the unknown-id warning at info.
    assert any(
        "delivered event for unknown" in rec.getMessage().lower()
        for rec in caplog.records
    )


@pytest.mark.asyncio
async def test_brevo_batch_with_mixed_events_handles_each_kind() -> None:
    """A batch containing one bounce + one delivered event triggers
    one ``flag_bounce`` call AND one delivered UPDATE.

    Validates: Requirements 11.2, 11.3
    """
    from app.modules.notifications.router import brevo_bounce_webhook

    secret = "shared-secret"
    body = json.dumps(
        {
            "events": [
                {
                    "event": "hard_bounce",
                    "email": "bad@example.com",
                    "message-id": "msg-bounce",
                    "reason": "550 No such user",
                },
                {
                    "event": "delivered",
                    "email": "ok@example.com",
                    "message-id": "msg-delivered",
                },
            ]
        }
    ).encode()
    sig = sign_webhook_payload(body, secret)

    db = AsyncMock()
    db.flush = AsyncMock()
    # Provider lookup + delivered UPDATE.
    db.execute = AsyncMock(
        side_effect=[_empty_provider_lookup(), _update_result(1)]
    )

    with patch("app.modules.notifications.router.app_settings") as ms, patch(
        "app.modules.notifications.router.flag_bounce", new=AsyncMock()
    ) as flag_mock:
        ms.brevo_webhook_secret = secret
        resp = await brevo_bounce_webhook(
            request=_fake_request(body, {"X-Brevo-Signature": sig}),
            db=db,
        )

    assert resp.status_code == 200
    body_json = json.loads(resp.body)
    assert body_json["emails_processed"] == 1
    assert body_json["delivered_processed"] == 1
    flag_mock.assert_awaited_once()
    # flag_bounce was called with the right kind/recipient.
    call_kwargs = flag_mock.await_args.kwargs
    assert call_kwargs["recipient"] == "bad@example.com"
    assert call_kwargs["kind"] == "hard_bounce"
    assert call_kwargs["reason"] == "550 No such user"
    assert call_kwargs["provider_message_id"] == "msg-bounce"
