"""Tests for bounce webhook endpoints.
Validates: Requirements 2.20
"""
from __future__ import annotations
import json
import uuid
from unittest.mock import AsyncMock, MagicMock, patch
import pytest
from app.core.webhook_security import sign_webhook_payload, verify_webhook_signature
from app.modules.notifications.schemas import (
    BrevoBounceEvent, BrevoBounceWebhookRequest, SendGridBounceEvent,
)

BREVO_BOUNCE = {"hard_bounce", "soft_bounce", "blocked", "invalid_email"}
SENDGRID_BOUNCE = {"bounce", "dropped", "deferred"}


class TestSchemas:
    def test_brevo_event(self):
        e = BrevoBounceEvent(event="hard_bounce", email="u@e.com")
        assert e.event == "hard_bounce"

    def test_brevo_batch(self):
        p = BrevoBounceWebhookRequest(events=[BrevoBounceEvent(event="hard_bounce", email="a@e.com")])
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
        p = BrevoBounceWebhookRequest(events=[
            BrevoBounceEvent(event="hard_bounce", email="a@e.com"),
            BrevoBounceEvent(event="delivered", email="b@e.com"),
        ])
        assert [e.email for e in p.events if e.event in BREVO_BOUNCE] == ["a@e.com"]

    def test_sendgrid(self):
        raw = [{"event": "bounce", "email": "a@e.com"}, {"event": "delivered", "email": "b@e.com"}]
        assert [r["email"] for r in raw if r["event"] in SENDGRID_BOUNCE] == ["a@e.com"]


class TestFlagBounced:
    @pytest.mark.asyncio
    async def test_flags_customer(self):
        from app.modules.notifications.service import flag_bounced_email_on_customer
        db = AsyncMock()
        db.flush = AsyncMock()
        r = MagicMock()
        r.rowcount = 1
        db.execute = AsyncMock(return_value=r)
        assert await flag_bounced_email_on_customer(db, org_id=uuid.uuid4(), email_address="b@e.com") == 1

    @pytest.mark.asyncio
    async def test_no_match(self):
        from app.modules.notifications.service import flag_bounced_email_on_customer
        db = AsyncMock()
        db.flush = AsyncMock()
        r = MagicMock()
        r.rowcount = 0
        db.execute = AsyncMock(return_value=r)
        assert await flag_bounced_email_on_customer(db, org_id=uuid.uuid4(), email_address="x@e.com") == 0


def _req(body, headers):
    r = AsyncMock()
    r.body = AsyncMock(return_value=body)
    r.json = AsyncMock(return_value=json.loads(body))
    r.headers = headers
    r.state = MagicMock()
    r.client = MagicMock()
    r.client.host = "127.0.0.1"
    return r


def _db_bounce(org_ids):
    db = AsyncMock()
    db.flush = AsyncMock()
    sel = MagicMock()
    sel.scalars.return_value.all.return_value = org_ids
    upd = MagicMock()
    upd.rowcount = 1
    db.execute = AsyncMock(side_effect=[sel, upd] * 10)
    return db


class TestBrevoEndpoint:
    @pytest.mark.asyncio
    async def test_valid_sig(self):
        from app.modules.notifications.router import brevo_bounce_webhook
        secret = "s"
        body = json.dumps({"event": "hard_bounce", "email": "b@e.com"}).encode()
        sig = sign_webhook_payload(body, secret)
        db = _db_bounce([uuid.uuid4()])
        with patch("app.modules.notifications.router.app_settings") as ms:
            ms.brevo_webhook_secret = secret
            resp = await brevo_bounce_webhook(request=_req(body, {"X-Brevo-Signature": sig}), db=db)
        assert resp.status_code == 200
        assert json.loads(resp.body)["emails_processed"] == 1

    @pytest.mark.asyncio
    async def test_invalid_sig_401(self):
        from app.modules.notifications.router import brevo_bounce_webhook
        body = json.dumps({"event": "hard_bounce", "email": "b@e.com"}).encode()
        with patch("app.modules.notifications.router.app_settings") as ms:
            ms.brevo_webhook_secret = "s"
            resp = await brevo_bounce_webhook(request=_req(body, {"X-Brevo-Signature": "bad"}), db=AsyncMock())
        assert resp.status_code == 401

    @pytest.mark.asyncio
    async def test_empty_secret_401(self):
        from app.modules.notifications.router import brevo_bounce_webhook
        body = json.dumps({"event": "hard_bounce", "email": "b@e.com"}).encode()
        with patch("app.modules.notifications.router.app_settings") as ms:
            ms.brevo_webhook_secret = ""
            resp = await brevo_bounce_webhook(request=_req(body, {"X-Brevo-Signature": "x"}), db=AsyncMock())
        assert resp.status_code == 401

    @pytest.mark.asyncio
    async def test_non_bounce_ignored(self):
        from app.modules.notifications.router import brevo_bounce_webhook
        secret = "s"
        body = json.dumps({"event": "delivered", "email": "ok@e.com"}).encode()
        sig = sign_webhook_payload(body, secret)
        db = AsyncMock()
        db.flush = AsyncMock()
        with patch("app.modules.notifications.router.app_settings") as ms:
            ms.brevo_webhook_secret = secret
            resp = await brevo_bounce_webhook(request=_req(body, {"X-Brevo-Signature": sig}), db=db)
        assert json.loads(resp.body)["emails_processed"] == 0


class TestSendGridEndpoint:
    @pytest.mark.asyncio
    async def test_valid_sig(self):
        from app.modules.notifications.router import sendgrid_bounce_webhook
        secret = "s"
        body = json.dumps([{"event": "bounce", "email": "b@e.com"}]).encode()
        sig = sign_webhook_payload(body, secret)
        db = _db_bounce([uuid.uuid4()])
        with patch("app.modules.notifications.router.app_settings") as ms:
            ms.sendgrid_webhook_secret = secret
            resp = await sendgrid_bounce_webhook(request=_req(body, {"X-Twilio-Email-Event-Webhook-Signature": sig}), db=db)
        assert resp.status_code == 200

    @pytest.mark.asyncio
    async def test_invalid_sig_401(self):
        from app.modules.notifications.router import sendgrid_bounce_webhook
        body = json.dumps([{"event": "bounce", "email": "b@e.com"}]).encode()
        with patch("app.modules.notifications.router.app_settings") as ms:
            ms.sendgrid_webhook_secret = "s"
            resp = await sendgrid_bounce_webhook(request=_req(body, {"X-Twilio-Email-Event-Webhook-Signature": "bad"}), db=AsyncMock())
        assert resp.status_code == 401

    @pytest.mark.asyncio
    async def test_filters_bounces(self):
        from app.modules.notifications.router import sendgrid_bounce_webhook
        secret = "s"
        body = json.dumps([
            {"event": "bounce", "email": "a@e.com"},
            {"event": "delivered", "email": "b@e.com"},
            {"event": "dropped", "email": "c@e.com"},
        ]).encode()
        sig = sign_webhook_payload(body, secret)
        db = _db_bounce([uuid.uuid4()])
        with patch("app.modules.notifications.router.app_settings") as ms:
            ms.sendgrid_webhook_secret = secret
            resp = await sendgrid_bounce_webhook(request=_req(body, {"X-Twilio-Email-Event-Webhook-Signature": sig}), db=db)
        assert json.loads(resp.body)["emails_processed"] == 2


class TestRouteRegistration:
    def _routes(self):
        from app.modules.notifications.router import router
        return [(r.path, r.methods) for r in router.routes if hasattr(r, "path")]

    def test_brevo_route(self):
        assert "/webhooks/brevo-bounce" in [p for p, _ in self._routes()]

    def test_sendgrid_route(self):
        assert "/webhooks/sendgrid-bounce" in [p for p, _ in self._routes()]
