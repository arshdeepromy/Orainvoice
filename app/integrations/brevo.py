"""Brevo / SendGrid / custom SMTP email client.

Provides a unified ``EmailClient`` that reads the platform-wide SMTP
configuration from the ``integration_configs`` table (name='smtp') and
dispatches emails via the configured provider.

Supported providers:
- **brevo**: Brevo transactional email API (v3)
- **sendgrid**: SendGrid v3 mail/send API
- **smtp**: Generic SMTP relay (STARTTLS)

Org-level emails use the global infrastructure but override the sender
name and reply-to with the organisation's configured values.

Requirements: 33.1, 33.2, 33.3
"""

from __future__ import annotations

import json
import logging
import smtplib
import ssl
from dataclasses import dataclass, field
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from typing import Any

import httpx

logger = logging.getLogger(__name__)


@dataclass
class SmtpConfig:
    """Platform-wide SMTP / email relay configuration."""

    provider: str = "smtp"  # brevo | sendgrid | smtp
    api_key: str = ""
    host: str = ""
    port: int = 587
    username: str = ""
    password: str = ""
    domain: str = ""
    from_email: str = ""
    from_name: str = ""
    reply_to: str = ""

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> SmtpConfig:
        return cls(
            provider=data.get("provider", "smtp"),
            api_key=data.get("api_key", ""),
            host=data.get("host", ""),
            port=int(data.get("port", 587)),
            username=data.get("username", ""),
            password=data.get("password", ""),
            domain=data.get("domain", ""),
            from_email=data.get("from_email", ""),
            from_name=data.get("from_name", ""),
            reply_to=data.get("reply_to", ""),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "provider": self.provider,
            "api_key": self.api_key,
            "host": self.host,
            "port": self.port,
            "username": self.username,
            "password": self.password,
            "domain": self.domain,
            "from_email": self.from_email,
            "from_name": self.from_name,
            "reply_to": self.reply_to,
        }


@dataclass
class EmailAttachment:
    """A file attachment for an email."""

    filename: str
    content: bytes
    mime_type: str = "application/pdf"


@dataclass
class EmailMessage:
    """A single outbound email."""

    to_email: str
    to_name: str = ""
    subject: str = ""
    html_body: str = ""
    text_body: str = ""
    from_name: str | None = None  # override global from_name
    reply_to: str | None = None   # override global reply-to
    attachments: list[EmailAttachment] = field(default_factory=list)


@dataclass
class SendResult:
    """Result of an email send attempt."""

    success: bool
    message_id: str | None = None
    error: str | None = None
    provider: str = ""


class EmailClient:
    """Unified email sending client.

    Reads config from an ``SmtpConfig`` instance and dispatches via the
    appropriate provider.
    """

    def __init__(self, config: SmtpConfig) -> None:
        self._config = config

    @property
    def config(self) -> SmtpConfig:
        return self._config

    async def send(self, message: EmailMessage) -> SendResult:
        """Send a single email using the configured provider."""
        provider = self._config.provider.lower()
        from_name = message.from_name or self._config.from_name
        reply_to = message.reply_to or self._config.reply_to

        if provider == "brevo":
            return await self._send_brevo(message, from_name, reply_to)
        elif provider == "sendgrid":
            return await self._send_sendgrid(message, from_name, reply_to)
        elif provider == "smtp":
            return await self._send_smtp(message, from_name, reply_to)
        else:
            return SendResult(
                success=False,
                error=f"Unknown provider: {provider}",
                provider=provider,
            )

    async def _send_brevo(
        self, msg: EmailMessage, from_name: str, reply_to: str
    ) -> SendResult:
        """Send via Brevo transactional email API v3."""
        payload: dict[str, Any] = {
            "sender": {
                "name": from_name,
                "email": self._config.from_email,
            },
            "to": [{"email": msg.to_email, "name": msg.to_name or msg.to_email}],
            "subject": msg.subject,
        }
        if msg.html_body:
            payload["htmlContent"] = msg.html_body
        if msg.text_body:
            payload["textContent"] = msg.text_body
        if reply_to:
            payload["replyTo"] = {"email": reply_to}
        if msg.attachments:
            import base64
            payload["attachment"] = [
                {
                    "name": att.filename,
                    "content": base64.b64encode(att.content).decode(),
                }
                for att in msg.attachments
            ]

        try:
            async with httpx.AsyncClient(timeout=30) as client:
                resp = await client.post(
                    "https://api.brevo.com/v3/smtp/email",
                    json=payload,
                    headers={
                        "api-key": self._config.api_key,
                        "Content-Type": "application/json",
                    },
                )
            if resp.status_code in (200, 201):
                data = resp.json()
                return SendResult(
                    success=True,
                    message_id=data.get("messageId"),
                    provider="brevo",
                )
            return SendResult(
                success=False,
                error=f"Brevo API error {resp.status_code}: {resp.text}",
                provider="brevo",
            )
        except Exception as exc:
            logger.exception("Brevo send failed")
            return SendResult(success=False, error=str(exc), provider="brevo")

    async def _send_sendgrid(
        self, msg: EmailMessage, from_name: str, reply_to: str
    ) -> SendResult:
        """Send via SendGrid v3 mail/send API."""
        payload: dict[str, Any] = {
            "personalizations": [
                {"to": [{"email": msg.to_email, "name": msg.to_name or msg.to_email}]}
            ],
            "from": {"email": self._config.from_email, "name": from_name},
            "subject": msg.subject,
            "content": [],
        }
        if msg.text_body:
            payload["content"].append({"type": "text/plain", "value": msg.text_body})
        if msg.html_body:
            payload["content"].append({"type": "text/html", "value": msg.html_body})
        if not payload["content"]:
            payload["content"].append({"type": "text/plain", "value": ""})
        if reply_to:
            payload["reply_to"] = {"email": reply_to}
        if msg.attachments:
            import base64
            payload["attachments"] = [
                {
                    "content": base64.b64encode(att.content).decode(),
                    "filename": att.filename,
                    "type": att.mime_type,
                    "disposition": "attachment",
                }
                for att in msg.attachments
            ]

        try:
            async with httpx.AsyncClient(timeout=30) as client:
                resp = await client.post(
                    "https://api.sendgrid.com/v3/mail/send",
                    json=payload,
                    headers={
                        "Authorization": f"Bearer {self._config.api_key}",
                        "Content-Type": "application/json",
                    },
                )
            if resp.status_code in (200, 202):
                msg_id = resp.headers.get("X-Message-Id")
                return SendResult(
                    success=True, message_id=msg_id, provider="sendgrid"
                )
            return SendResult(
                success=False,
                error=f"SendGrid API error {resp.status_code}: {resp.text}",
                provider="sendgrid",
            )
        except Exception as exc:
            logger.exception("SendGrid send failed")
            return SendResult(success=False, error=str(exc), provider="sendgrid")

    async def _send_smtp(
        self, msg: EmailMessage, from_name: str, reply_to: str
    ) -> SendResult:
        """Send via generic SMTP relay with STARTTLS."""
        mime = MIMEMultipart("alternative")
        mime["From"] = f"{from_name} <{self._config.from_email}>"
        mime["To"] = msg.to_email
        mime["Subject"] = msg.subject
        if reply_to:
            mime["Reply-To"] = reply_to

        if msg.text_body:
            mime.attach(MIMEText(msg.text_body, "plain"))
        if msg.html_body:
            mime.attach(MIMEText(msg.html_body, "html"))
        for att in msg.attachments:
            from email.mime.base import MIMEBase
            from email import encoders
            part = MIMEBase("application", "octet-stream")
            part.set_payload(att.content)
            encoders.encode_base64(part)
            part.add_header("Content-Disposition", f"attachment; filename={att.filename}")
            mime.attach(part)

        try:
            host = self._config.host
            port = self._config.port
            context = ssl.create_default_context()

            with smtplib.SMTP(host, port, timeout=30) as server:
                server.starttls(context=context)
                username = self._config.username or self._config.api_key
                password = self._config.password or self._config.api_key
                if username:
                    server.login(username, password)
                server.sendmail(
                    self._config.from_email, [msg.to_email], mime.as_string()
                )

            return SendResult(success=True, provider="smtp")
        except Exception as exc:
            logger.exception("SMTP send failed")
            return SendResult(success=False, error=str(exc), provider="smtp")


# ---------------------------------------------------------------------------
# Helper: load config from integration_configs table
# ---------------------------------------------------------------------------


async def load_smtp_config_from_db(db) -> SmtpConfig | None:
    """Load the SMTP integration config from the database.

    Returns None if no config is stored.
    """
    from sqlalchemy import select
    from app.modules.admin.models import IntegrationConfig
    from app.core.encryption import envelope_decrypt_str

    result = await db.execute(
        select(IntegrationConfig).where(IntegrationConfig.name == "smtp")
    )
    row = result.scalar_one_or_none()
    if row is None:
        return None

    try:
        decrypted = envelope_decrypt_str(row.config_encrypted)
        data = json.loads(decrypted)
        return SmtpConfig.from_dict(data)
    except Exception:
        logger.exception("Failed to decrypt SMTP config")
        return None


async def get_email_client(db) -> EmailClient | None:
    """Build an ``EmailClient`` from the stored SMTP config.

    Returns None if no config is stored.
    """
    config = await load_smtp_config_from_db(db)
    if config is None:
        return None
    return EmailClient(config)


async def send_org_email(
    db,
    *,
    to_email: str,
    to_name: str = "",
    subject: str,
    html_body: str = "",
    text_body: str = "",
    org_sender_name: str | None = None,
    org_reply_to: str | None = None,
    attachments: list[EmailAttachment] | None = None,
) -> SendResult:
    """Send an email using global infrastructure with org-level overrides.

    Org emails use the platform SMTP config but display the organisation's
    sender name and reply-to address (Requirement 33.3).
    """
    client = await get_email_client(db)
    if client is None:
        return SendResult(
            success=False,
            error="Email infrastructure not configured",
            provider="none",
        )

    message = EmailMessage(
        to_email=to_email,
        to_name=to_name,
        subject=subject,
        html_body=html_body,
        text_body=text_body,
        from_name=org_sender_name,
        reply_to=org_reply_to,
        attachments=attachments or [],
    )
    return await client.send(message)
