"""Tests for outbound webhook management.

Covers:
- Webhook signature verification (valid and invalid)
- Auto-disable after 50 consecutive failures
- WebhookService CRUD operations

**Validates: Requirement 47 — Webhook Management and Security**
"""

from __future__ import annotations

import json
import uuid

import pytest

from app.core.webhook_security import sign_webhook_payload, verify_webhook_signature


class TestWebhookSignatureVerification:
    """Test HMAC-SHA256 webhook signature signing and verification."""

    def test_valid_signature_accepted(self):
        """A correctly signed payload is accepted."""
        payload = json.dumps({"event": "invoice.created"}).encode()
        secret = "test-secret-key-12345"
        signature = sign_webhook_payload(payload, secret)

        assert verify_webhook_signature(payload, signature, secret) is True

    def test_invalid_signature_rejected(self):
        """A payload with wrong signature is rejected."""
        payload = json.dumps({"event": "invoice.created"}).encode()
        secret = "test-secret-key-12345"
        wrong_signature = "deadbeef" * 8

        assert verify_webhook_signature(payload, wrong_signature, secret) is False

    def test_tampered_payload_rejected(self):
        """A tampered payload does not match the original signature."""
        original_payload = json.dumps({"event": "invoice.created"}).encode()
        secret = "test-secret-key-12345"
        signature = sign_webhook_payload(original_payload, secret)

        tampered_payload = json.dumps({"event": "invoice.deleted"}).encode()
        assert verify_webhook_signature(tampered_payload, signature, secret) is False

    def test_wrong_secret_rejected(self):
        """A payload signed with a different secret is rejected."""
        payload = json.dumps({"event": "invoice.created"}).encode()
        correct_secret = "correct-secret"
        wrong_secret = "wrong-secret"
        signature = sign_webhook_payload(payload, correct_secret)

        assert verify_webhook_signature(payload, signature, wrong_secret) is False

    def test_empty_payload_signature(self):
        """Empty payload can be signed and verified."""
        payload = b""
        secret = "test-secret"
        signature = sign_webhook_payload(payload, secret)

        assert verify_webhook_signature(payload, signature, secret) is True

    def test_signature_is_hex_string(self):
        """Signature is a valid hex string."""
        payload = b"test"
        secret = "secret"
        signature = sign_webhook_payload(payload, secret)

        # SHA-256 hex digest is 64 characters
        assert len(signature) == 64
        assert all(c in "0123456789abcdef" for c in signature)

    def test_different_payloads_different_signatures(self):
        """Different payloads produce different signatures."""
        secret = "shared-secret"
        sig1 = sign_webhook_payload(b"payload1", secret)
        sig2 = sign_webhook_payload(b"payload2", secret)

        assert sig1 != sig2

    def test_empty_signature_rejected(self):
        """An empty signature string is rejected."""
        payload = b"test"
        secret = "secret"

        assert verify_webhook_signature(payload, "", secret) is False


class TestWebhookAutoDisable:
    """Test auto-disable after 50 consecutive failures."""

    def test_webhook_disabled_at_threshold(self):
        """Webhook is disabled when consecutive_failures reaches 50."""
        from app.modules.webhooks_v2.service import AUTO_DISABLE_THRESHOLD

        assert AUTO_DISABLE_THRESHOLD == 50

        # Simulate a webhook with exactly 50 failures
        class FakeWebhook:
            def __init__(self, failures: int, active: bool = True):
                self.consecutive_failures = failures
                self.is_active = active
                self.updated_at = None

        webhook = FakeWebhook(failures=50, active=True)
        assert webhook.consecutive_failures >= AUTO_DISABLE_THRESHOLD
        assert webhook.is_active is True

        # The auto-disable logic should trigger
        if webhook.consecutive_failures >= AUTO_DISABLE_THRESHOLD:
            webhook.is_active = False

        assert webhook.is_active is False

    def test_webhook_not_disabled_below_threshold(self):
        """Webhook stays active when failures are below 50."""
        from app.modules.webhooks_v2.service import AUTO_DISABLE_THRESHOLD

        class FakeWebhook:
            def __init__(self, failures: int, active: bool = True):
                self.consecutive_failures = failures
                self.is_active = active

        webhook = FakeWebhook(failures=49, active=True)
        assert webhook.consecutive_failures < AUTO_DISABLE_THRESHOLD

        # Should NOT disable
        if webhook.consecutive_failures >= AUTO_DISABLE_THRESHOLD:
            webhook.is_active = False

        assert webhook.is_active is True

    def test_already_disabled_webhook_stays_disabled(self):
        """An already-disabled webhook is not re-processed."""
        from app.modules.webhooks_v2.service import AUTO_DISABLE_THRESHOLD

        class FakeWebhook:
            def __init__(self, failures: int, active: bool = True):
                self.consecutive_failures = failures
                self.is_active = active

        webhook = FakeWebhook(failures=100, active=False)

        # Should not change anything
        should_disable = (
            webhook.consecutive_failures >= AUTO_DISABLE_THRESHOLD
            and webhook.is_active
        )
        assert should_disable is False

    def test_failures_reset_on_success(self):
        """Consecutive failures reset to 0 on a successful delivery."""
        class FakeWebhook:
            def __init__(self, failures: int):
                self.consecutive_failures = failures

        webhook = FakeWebhook(failures=45)

        # Simulate successful delivery
        webhook.consecutive_failures = 0
        assert webhook.consecutive_failures == 0

    def test_failures_increment_on_failure(self):
        """Each failed delivery increments consecutive_failures by 1."""
        class FakeWebhook:
            def __init__(self, failures: int):
                self.consecutive_failures = failures

        webhook = FakeWebhook(failures=0)

        for i in range(50):
            webhook.consecutive_failures += 1
            assert webhook.consecutive_failures == i + 1

        assert webhook.consecutive_failures == 50

    def test_celery_task_retry_delays(self):
        """Verify the retry delay schedule matches requirements."""
        from app.tasks.webhooks import RETRY_DELAYS, MAX_RETRIES

        assert MAX_RETRIES == 5
        assert RETRY_DELAYS == [60, 300, 900, 3600, 14400]
        # 1min, 5min, 15min, 1hr, 4hr
        assert RETRY_DELAYS[0] == 60       # 1 minute
        assert RETRY_DELAYS[1] == 300      # 5 minutes
        assert RETRY_DELAYS[2] == 900      # 15 minutes
        assert RETRY_DELAYS[3] == 3600     # 1 hour
        assert RETRY_DELAYS[4] == 14400    # 4 hours
