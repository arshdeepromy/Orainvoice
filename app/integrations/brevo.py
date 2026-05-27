"""Legacy email integration module — DEPRECATED.

# DEPRECATED — Phase 9 deletes this. See email-provider-unification spec.

This module used to host the hand-rolled ``EmailClient`` / ``SmtpConfig``
implementation that read SMTP credentials from the
``integration_configs`` table. Phase 1 of the
email-provider-unification spec moved the real implementation to
``app.integrations.email_sender`` (driven by the ``email_providers``
table with priority-ordered failover, error classification, and bounce
correlation).

This file now contains only thin shims kept for one release so existing
imports of ``EmailMessage``, ``EmailAttachment``, ``SendResult``,
``send_org_email``, ``EmailClient``, ``SmtpConfig``,
``get_email_client`` and ``load_smtp_config_from_db`` still resolve
during Phase 2 cutover. Phase 9 (task 10.2) deletes the file outright.

Each shim either re-exports the new symbol or delegates to the
unified sender. None of the shims re-implement the old SMTP path;
the only outbound code path is ``app.integrations.email_sender.send_email``.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

# DEPRECATED — Phase 9 deletes this. See email-provider-unification spec.
from app.integrations.email_sender import (  # noqa: F401  (re-exports)
    EmailAttachment,
    EmailMessage,
    SendResult,
    send_email,
)

logger = logging.getLogger(__name__)


# DEPRECATED — Phase 9 deletes this. See email-provider-unification spec.
@dataclass
class SmtpConfig:
    """Legacy platform-wide SMTP / email relay configuration.

    Retained as a thin compat dataclass so existing imports in
    ``tests/test_email_infrastructure.py`` (and the admin-service
    legacy-test path that still asks for ``client.config.provider`` /
    ``client.config.domain``) continue to resolve. The fields here have
    no effect on the actual outbound email path — that goes through
    ``app.integrations.email_sender.send_email`` which reads from the
    ``email_providers`` table.
    """

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


# DEPRECATED — Phase 9 deletes this. See email-provider-unification spec.
class EmailClient:
    """Legacy unified email sending client.

    The original implementation dispatched to Brevo / SendGrid / SMTP
    using a single ``SmtpConfig``. Phase 1 of email-provider-unification
    replaced it with the multi-provider, failover-aware ``send_email``
    in ``app.integrations.email_sender``. This shim is retained for one
    release so existing ``EmailClient(config)`` constructor calls keep
    importing cleanly. ``.send`` is a no-op that returns a clear failure
    so any forgotten caller surfaces immediately rather than silently
    succeeding.
    """

    def __init__(self, config: SmtpConfig) -> None:
        self._config = config

    @property
    def config(self) -> SmtpConfig:
        return self._config

    async def send(self, message: EmailMessage) -> SendResult:
        """Deprecated send. Use ``app.integrations.email_sender.send_email``.

        Returns a failed ``SendResult`` so any remaining caller fails
        fast instead of silently appearing to succeed.
        """
        del message  # legacy stub — message is intentionally ignored
        logger.warning(
            "EmailClient.send is deprecated; use "
            "app.integrations.email_sender.send_email instead"
        )
        return SendResult(
            success=False,
            error=(
                "EmailClient is deprecated; use "
                "app.integrations.email_sender.send_email"
            ),
            provider_key=self._config.provider or None,
            transport=None,
        )


# DEPRECATED — Phase 9 deletes this. See email-provider-unification spec.
async def load_smtp_config_from_db(db: Any) -> SmtpConfig | None:
    """Legacy ``integration_configs`` SMTP loader.

    The new send path reads from the ``email_providers`` table directly
    (see ``app.integrations.email_sender``). The legacy admin endpoint
    backed by this function returns HTTP 410 Gone in Phase 7. Until then
    this shim returns ``None`` so any caller falls through to its
    "config not found" branch.
    """
    del db
    logger.warning(
        "load_smtp_config_from_db is deprecated; "
        "the email_providers table is now the source of truth"
    )
    return None


# DEPRECATED — Phase 9 deletes this. See email-provider-unification spec.
async def get_email_client(db: Any) -> EmailClient | None:
    """Legacy ``EmailClient`` builder.

    Phase 2 rewrote ``_send_email_async`` to call
    ``app.integrations.email_sender.send_email`` directly. The only
    remaining in-tree caller is the legacy
    ``app.modules.admin.service.send_test_email`` admin endpoint, which
    Phase 7 retires (HTTP 410 Gone). Returning ``None`` here makes that
    endpoint cleanly report "SMTP configuration not found" until the
    Phase 7 cut-over.
    """
    del db
    logger.warning(
        "get_email_client is deprecated; use "
        "app.integrations.email_sender.send_email instead"
    )
    return None


# DEPRECATED — Phase 9 deletes this. See email-provider-unification spec.
async def send_org_email(
    db: Any,
    *,
    to_email: str,
    to_name: str = "",
    subject: str,
    html_body: str = "",
    text_body: str = "",
    org_sender_name: str | None = None,
    org_reply_to: str | None = None,
    attachments: list[EmailAttachment] | None = None,
    **_: Any,
) -> SendResult:
    """Legacy org-email entry point — delegates to the unified sender.

    Translates the call to the new ``send_email`` API in
    ``app.integrations.email_sender``. The returned ``SendResult`` carries
    ``provider_key``; the old ``provider: str`` shape is preserved by the
    ``SendResult.provider`` ``@property`` defined in ``email_sender.py``.

    Extra kwargs are accepted (``**_``) so any forgotten caller passing
    legacy-only arguments doesn't crash on TypeError.
    """
    message = EmailMessage(
        to_email=to_email,
        to_name=to_name,
        subject=subject,
        html_body=html_body,
        text_body=text_body,
        attachments=attachments or [],
    )
    return await send_email(
        db,
        message,
        org_sender_name=org_sender_name,
        org_reply_to=org_reply_to,
    )
