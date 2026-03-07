"""Twilio SMS client.

Provides a unified ``SmsClient`` that reads the platform-wide Twilio
configuration from the ``integration_configs`` table (name='twilio') and
dispatches SMS messages via the Twilio REST API.

Org-level SMS uses the global Twilio infrastructure but can override the
sender name/number with the organisation's configured values.

Requirements: 36.1, 36.2, 36.3, 36.4, 36.5, 36.6
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from typing import Any

import httpx

logger = logging.getLogger(__name__)


SMS_CHAR_LIMIT = 160


@dataclass
class TwilioConfig:
    """Platform-wide Twilio SMS configuration."""

    account_sid: str = ""
    auth_token: str = ""
    sender_number: str = ""

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> TwilioConfig:
        return cls(
            account_sid=data.get("account_sid", ""),
            auth_token=data.get("auth_token", ""),
            sender_number=data.get("sender_number", ""),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "account_sid": self.account_sid,
            "auth_token": self.auth_token,
            "sender_number": self.sender_number,
        }


@dataclass
class SmsMessage:
    """A single outbound SMS."""

    to_number: str
    body: str
    from_number: str | None = None  # override global sender


@dataclass
class SmsSendResult:
    """Result of an SMS send attempt."""

    success: bool
    message_sid: str | None = None
    error: str | None = None


class SmsClient:
    """Twilio SMS sending client.

    Uses the Twilio REST API to send messages.
    """

    def __init__(self, config: TwilioConfig) -> None:
        self._config = config

    @property
    def config(self) -> TwilioConfig:
        return self._config

    async def send(self, message: SmsMessage) -> SmsSendResult:
        """Send a single SMS via Twilio REST API."""
        from_number = message.from_number or self._config.sender_number
        if not from_number:
            return SmsSendResult(
                success=False, error="No sender number configured"
            )

        url = (
            f"https://api.twilio.com/2010-04-01/Accounts/"
            f"{self._config.account_sid}/Messages.json"
        )
        payload = {
            "To": message.to_number,
            "From": from_number,
            "Body": message.body,
        }

        try:
            async with httpx.AsyncClient(timeout=30) as client:
                resp = await client.post(
                    url,
                    data=payload,
                    auth=(self._config.account_sid, self._config.auth_token),
                )
            if resp.status_code in (200, 201):
                data = resp.json()
                return SmsSendResult(
                    success=True,
                    message_sid=data.get("sid"),
                )
            return SmsSendResult(
                success=False,
                error=f"Twilio API error {resp.status_code}: {resp.text}",
            )
        except Exception as exc:
            logger.exception("Twilio SMS send failed")
            return SmsSendResult(success=False, error=str(exc))


# ---------------------------------------------------------------------------
# Helper: load config from integration_configs table
# ---------------------------------------------------------------------------


async def load_twilio_config_from_db(db) -> TwilioConfig | None:
    """Load the Twilio integration config from the database.

    Returns None if no config is stored.
    """
    from sqlalchemy import select
    from app.modules.admin.models import IntegrationConfig
    from app.core.encryption import envelope_decrypt_str

    result = await db.execute(
        select(IntegrationConfig).where(IntegrationConfig.name == "twilio")
    )
    row = result.scalar_one_or_none()
    if row is None:
        return None

    try:
        decrypted = envelope_decrypt_str(row.config_encrypted)
        data = json.loads(decrypted)
        return TwilioConfig.from_dict(data)
    except Exception:
        logger.exception("Failed to decrypt Twilio config")
        return None


async def get_sms_client(db) -> SmsClient | None:
    """Build an ``SmsClient`` from the stored Twilio config.

    Returns None if no config is stored.
    """
    config = await load_twilio_config_from_db(db)
    if config is None:
        return None
    return SmsClient(config)


async def send_org_sms(
    db,
    *,
    to_number: str,
    body: str,
    org_sender_number: str | None = None,
) -> SmsSendResult:
    """Send an SMS using global Twilio infrastructure with org-level overrides.

    Org SMS uses the platform Twilio config but can override the sender
    number with the organisation's configured value (Requirement 36.3).
    """
    client = await get_sms_client(db)
    if client is None:
        return SmsSendResult(
            success=False,
            error="Twilio SMS infrastructure not configured",
        )

    message = SmsMessage(
        to_number=to_number,
        body=body,
        from_number=org_sender_number,
    )
    return await client.send(message)
