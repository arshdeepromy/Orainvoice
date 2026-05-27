"""Tests for bounce webhook endpoints — Phase 8c contract.

Original Req 2.20 tests were updated for the Phase 8c rewrite of the
Brevo / SendGrid bounce webhook handlers. Three contract changes:

1. Signature mismatch now returns HTTP **403** (not 401) — matches the
   per-provider secret iteration introduced in tasks 9.6 / 9.7.
2. The handler accepts any active provider's
   ``<kind>_webhook_secret`` from ``email_providers.config`` first,
   falling back to ``app_settings.<kind>_webhook_secret`` for one
   release per Req 25.5.
3. The bounce side-effect is now driven by
   :func:`flag_bounce` (notification_log flip + bounced_addresses
   upsert + in-app notification + customer flag), not a direct call
   to ``flag_bounced_email_on_customer``.

Validates: Requirements 2.20, 11.2, 11.3, 13.1, 13.2, 13.3, 25.5
"""
from __future__ import annotations

import json
import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.core.webhook_security import sign_webhook_payload, verify_webhook_signature
from app.modules.notifications.schemas import (
    BrevoBounceEvent,
    BrevoBounceWebhookRequest,
    SendGridBounceEvent,
)


BREVO_BOUNCE = {"hard_bounce", "soft_bounce", "blocked", "invalid_email"}
SENDGRID_BOUNCE = {"bounce", "dropped", "deferred"}


# ---------------------------------------------------------------------------
# Schema-level tests (unchanged from pre-Phase-8c — schemas weren't touched)
# ---------------------------------------------------------------------------


class TestSchemas:
    def test_brevo_event(self):
        e = BrevoBounceEvent(event="hard_bounce", email="u@e.com")
        assert e.event == "hard_bounce"

    def test_brevo_batch(self):
        p = BrevoBounceWebhookRequest(
            events=[BrevoBounceEvent(event="hard_bounce", email="a@e.com")]
        )
        assert len(p.events) == 1

    def test_sendgrid_event(self):
        e = SendGridBounceEvent(event="bounce", email="u@e.com")
        assert e.event == "bounce"


class TestSignature:
    def test_valid(self):
        p = b'{"event":"hard_bounce"}'
        assert verify_webhook_signature(p, sign_webhook_payload(p, "s"), "s")

    def test_invalid(self):
        assert not verify_webhook_signature(b'{}', "bad", "s")


class TestFiltering:
    def test_brevo_batch(self):
        p = BrevoBounceWebhookRequest(
            events=[
                BrevoBounceEvent(event="hard_bounce", email="a@e.com"),
                BrevoBounceEvent(event="delivered", email="b@e.com"),
            ]
        )
        assert [
            e.email for e in p.events if e.event in BREVO_BOUNCE
        ] == ["a@e.com"]

    def test_sendgrid(self):
        raw = [
            {"event": "bounce", "email": "a@e.com"},
            {"event": "delivered", "email": "b@e.com"},
        ]
        assert [
            r["email"] for r in raw if r["event"] in SENDGRID_BOUNCE
        ] == ["a@e.com"]


class TestFlagBounced:
    @pytest.mark.asyncio
    async def test_flags_customer(self):
        from app.modules.notifications.service import flag_bounced_email_on_customer

        db = AsyncMock()
        db.flush = AsyncMock()
        r = MagicMock()
        r.rowcount = 1
        db.execute = AsyncMock(return_value=r)
        assert (
            await flag_bounced_email_on_customer(
                db, org_id=uuid.uuid4(), email_address="b@e.com"
            )
            == 1
        )

    @pytest.mark.asyncio
    async def test_no_match(self):
        from app.modules.notifications.service import flag_bounced_email_on_customer

        db = AsyncMock()
        db.flush = AsyncMock()
        r = MagicMock()
        r.rowcount = 0
        db.execute = AsyncMock(return_value=r)
        assert (
            await flag_bounced_email_on_customer(
                db, org_id=uuid.uuid4(), email_address="x@e.com"
            )
            == 0
        )


# ---------------------------------------------------------------------------
# Endpoint-level tests — Phase 8c contract
# ---------------------------------------------------------------------------


def _req(body, headers):
    """Mock ``Request`` with a pre-set raw body, headers, and client.host."""
    r = AsyncMock()
    r.body = AsyncMock(return_value=body)
    r.json = AsyncMock(return_value=json.loads(body))
    r.headers = headers
    r.state = MagicMock()
    r.client = MagicMock()
    r.client.host = "127.0.0.1"
    return r


class TestBrevoEndpoint:
    """Phase 8c: signature verification accepts the env-var fallback or
    any active Brevo provider's ``brevo_webhook_secret``; mismatch
    returns HTTP 403; bounce side-effect runs through ``flag_bounce``.
    """

    @pytest.mark.asyncio
    async def test_valid_env_fallback_sig(self):
        from app.modules.notifications.router import brevo_bounce_webhook

        secret = "s"
        body = json.dumps(
            {"event": "hard_bounce", "email": "b@e.com"}
        ).encode()
        sig = sign_webhook_payload(body, secret)
        db = AsyncMock()
        db.flush = AsyncMock()
        # No active providers → candidate list is just the env fallback.
        scalars = MagicMock()
        scalars.all = MagicMock(return_value=[])
        provider_lookup = MagicMock()
        provider_lookup.scalars = MagicMock(return_value=scalars)
        db.execute = AsyncMock(return_value=provider_lookup)
        with patch("app.modules.notifications.router.app_settings") as ms, patch(
            "app.modules.notifications.router.flag_bounce", new=AsyncMock()
        ) as flag_mock:
            ms.brevo_webhook_secret = secret
            resp = await brevo_bounce_webhook(
                request=_req(body, {"X-Brevo-Signature": sig}), db=db
            )
        assert resp.status_code == 200
        body_json = json.loads(resp.body)
        assert body_json["emails_processed"] == 1
        flag_mock.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_invalid_sig_403(self):
        from app.modules.notifications.router import brevo_bounce_webhook

        body = json.dumps(
            {"event": "hard_bounce", "email": "b@e.com"}
        ).encode()
        db = AsyncMock()
        scalars = MagicMock()
        scalars.all = MagicMock(return_value=[])
        provider_lookup = MagicMock()
        provider_lookup.scalars = MagicMock(return_value=scalars)
        db.execute = AsyncMock(return_value=provider_lookup)
        with patch("app.modules.notifications.router.app_settings") as ms:
            ms.brevo_webhook_secret = "s"
            resp = await brevo_bounce_webhook(
                request=_req(body, {"X-Brevo-Signature": "bad"}), db=db
            )
        assert resp.status_code == 403

    @pytest.mark.asyncio
    async def test_empty_secret_403(self):
        from app.modules.notifications.router import brevo_bounce_webhook

        body = json.dumps(
            {"event": "hard_bounce", "email": "b@e.com"}
        ).encode()
        db = AsyncMock()
        scalars = MagicMock()
        scalars.all = MagicMock(return_value=[])
        provider_lookup = MagicMock()
        provider_lookup.scalars = MagicMock(return_value=scalars)
        db.execute = AsyncMock(return_value=provider_lookup)
        with patch("app.modules.notifications.router.app_settings") as ms:
            ms.brevo_webhook_secret = ""
            resp = await brevo_bounce_webhook(
                request=_req(body, {"X-Brevo-Signature": "x"}), db=db
            )
        assert resp.status_code == 403

    @pytest.mark.asyncio
    async def test_non_bounce_ignored(self):
        from app.modules.notifications.router import brevo_bounce_webhook

        secret = "s"
        body = json.dumps(
            {"event": "spam_complaint", "email": "ok@e.com"}
        ).encode()
        sig = sign_webhook_payload(body, secret)
        db = AsyncMock()
        db.flush = AsyncMock()
        scalars = MagicMock()
        scalars.all = MagicMock(return_value=[])
        provider_lookup = MagicMock()
        provider_lookup.scalars = MagicMock(return_value=scalars)
        db.execute = AsyncMock(return_value=provider_lookup)
        with patch("app.modules.notifications.router.app_settings") as ms, patch(
            "app.modules.notifications.router.flag_bounce", new=AsyncMock()
        ) as flag_mock:
            ms.brevo_webhook_secret = secret
            resp = await brevo_bounce_webhook(
                request=_req(body, {"X-Brevo-Signature": sig}), db=db
            )
        assert json.loads(resp.body)["emails_processed"] == 0
        flag_mock.assert_not_awaited()


class TestSendGridEndpoint:
    """Phase 8c: same per-provider-or-env contract as Brevo."""

    @pytest.mark.asyncio
    async def test_valid_env_fallback_sig(self):
        from app.modules.notifications.router import sendgrid_bounce_webhook

        secret = "s"
        body = json.dumps(
            [{"event": "bounce", "email": "b@e.com"}]
        ).encode()
        sig = sign_webhook_payload(body, secret)
        db = AsyncMock()
        db.flush = AsyncMock()
        scalars = MagicMock()
        scalars.all = MagicMock(return_value=[])
        provider_lookup = MagicMock()
        provider_lookup.scalars = MagicMock(return_value=scalars)
        db.execute = AsyncMock(return_value=provider_lookup)
        with patch("app.modules.notifications.router.app_settings") as ms, patch(
            "app.modules.notifications.router.flag_bounce", new=AsyncMock()
        ) as flag_mock:
            ms.sendgrid_webhook_secret = secret
            resp = await sendgrid_bounce_webhook(
                request=_req(
                    body,
                    {"X-Twilio-Email-Event-Webhook-Signature": sig},
                ),
                db=db,
            )
        assert resp.status_code == 200
        flag_mock.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_invalid_sig_403(self):
        from app.modules.notifications.router import sendgrid_bounce_webhook

        body = json.dumps(
            [{"event": "bounce", "email": "b@e.com"}]
        ).encode()
        db = AsyncMock()
        scalars = MagicMock()
        scalars.all = MagicMock(return_value=[])
        provider_lookup = MagicMock()
        provider_lookup.scalars = MagicMock(return_value=scalars)
        db.execute = AsyncMock(return_value=provider_lookup)
        with patch("app.modules.notifications.router.app_settings") as ms:
            ms.sendgrid_webhook_secret = "s"
            resp = await sendgrid_bounce_webhook(
                request=_req(
                    body,
                    {"X-Twilio-Email-Event-Webhook-Signature": "bad"},
                ),
                db=db,
            )
        assert resp.status_code == 403

    @pytest.mark.asyncio
    async def test_filters_bounces(self):
        from app.modules.notifications.router import sendgrid_bounce_webhook

        secret = "s"
        body = json.dumps(
            [
                {"event": "bounce", "email": "a@e.com"},
                {"event": "delivered", "email": "b@e.com"},
                {"event": "dropped", "email": "c@e.com"},
            ]
        ).encode()
        sig = sign_webhook_payload(body, secret)
        db = AsyncMock()
        db.flush = AsyncMock()
        # Two execute calls expected: provider lookup (empty) and the
        # delivered-event update.
        scalars = MagicMock()
        scalars.all = MagicMock(return_value=[])
        provider_lookup = MagicMock()
        provider_lookup.scalars = MagicMock(return_value=scalars)
        delivered_update = MagicMock()
        delivered_update.rowcount = 0
        db.execute = AsyncMock(side_effect=[provider_lookup, delivered_update])
        with patch("app.modules.notifications.router.app_settings") as ms, patch(
            "app.modules.notifications.router.flag_bounce", new=AsyncMock()
        ) as flag_mock:
            ms.sendgrid_webhook_secret = secret
            resp = await sendgrid_bounce_webhook(
                request=_req(
                    body,
                    {"X-Twilio-Email-Event-Webhook-Signature": sig},
                ),
                db=db,
            )
        assert json.loads(resp.body)["emails_processed"] == 2
        # bounce + dropped → two flag_bounce calls
        assert flag_mock.await_count == 2


class TestRouteRegistration:
    def _routes(self):
        from app.modules.notifications.router import router

        return [(r.path, r.methods) for r in router.routes if hasattr(r, "path")]

    def test_brevo_route(self):
        assert "/webhooks/brevo-bounce" in [p for p, _ in self._routes()]

    def test_sendgrid_route(self):
        assert "/webhooks/sendgrid-bounce" in [p for p, _ in self._routes()]


class TestWebhooksAreRegisteredAsPublicPaths:
    """The bounce webhooks must skip JWT auth — Brevo and SendGrid sign
    payloads with a per-provider secret stored in
    ``email_providers.config``, and the handlers verify that signature
    before processing. JWT auth would just block legitimate webhook
    deliveries with a 401 before the handler ever ran.

    Pinned here as a regression guard so a future refactor of
    ``PUBLIC_PATHS`` can't accidentally re-introduce the auth gap.

    Validates: Requirements 13.1, 13.2 (signature-verified webhooks
    must be reachable from the provider's webhook delivery worker)
    """

    def test_brevo_v1_webhook_is_public(self):
        from app.middleware.auth import PUBLIC_PATHS

        assert "/api/v1/notifications/webhooks/brevo-bounce" in PUBLIC_PATHS

    def test_sendgrid_v1_webhook_is_public(self):
        from app.middleware.auth import PUBLIC_PATHS

        assert "/api/v1/notifications/webhooks/sendgrid-bounce" in PUBLIC_PATHS

    def test_brevo_v2_webhook_is_public(self):
        from app.middleware.auth import PUBLIC_PATHS

        assert "/api/v2/notifications/webhooks/brevo-bounce" in PUBLIC_PATHS

    def test_sendgrid_v2_webhook_is_public(self):
        from app.middleware.auth import PUBLIC_PATHS

        assert "/api/v2/notifications/webhooks/sendgrid-bounce" in PUBLIC_PATHS

    def test_is_public_helper_returns_true_for_webhook_paths(self):
        """Spot-check the ``_is_public`` helper since that's what the
        ASGI middleware actually calls — set membership alone isn't
        sufficient if the helper logic ever changes shape.
        """
        from app.middleware.auth import _is_public

        assert _is_public("/api/v1/notifications/webhooks/brevo-bounce")
        assert _is_public("/api/v1/notifications/webhooks/sendgrid-bounce")
        assert _is_public("/api/v2/notifications/webhooks/brevo-bounce")
        assert _is_public("/api/v2/notifications/webhooks/sendgrid-bounce")
