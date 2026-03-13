"""Provider-agnostic SMS types.

Shared dataclasses used by all SMS provider clients (Connexus, etc.)
and the notification task layer. Extracted from the original Twilio
client to decouple business logic from any single provider.

Requirements: 1.2
"""

from __future__ import annotations

from dataclasses import dataclass, field

SMS_CHAR_LIMIT = 160


@dataclass
class SmsMessage:
    """A single outbound SMS."""

    to_number: str
    body: str
    from_number: str | None = None


@dataclass
class SmsSendResult:
    """Result of an SMS send attempt."""

    success: bool
    message_sid: str | None = None
    error: str | None = None
    metadata: dict | None = None  # parts_count, route, etc.
