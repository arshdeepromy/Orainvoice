"""Removed in Phase 9 of the email-provider-unification spec.

The legacy ``EmailClient`` / ``SmtpConfig`` / ``send_org_email`` /
``get_email_client`` / ``load_smtp_config_from_db`` shims that this
module used to host were retired in Phase 9 (task 10.2 / Requirement
23.2). All outbound email now goes through
:mod:`app.integrations.email_sender` (``send_email``) which reads the
``email_providers`` table for priority-ordered failover, error
classification, and bounce correlation.

This module is intentionally empty: it is kept only so that any
straggler ``unittest.mock.patch("app.integrations.brevo.<name>",
create=True)`` calls sitting in stale test fixtures still resolve to
an importable parent module instead of crashing with
``ModuleNotFoundError`` at decoration time. Once those fixtures have
been cleaned up, the file can be deleted outright.

If you are looking for the new symbols, import them from
``app.integrations.email_sender`` directly:

    from app.integrations.email_sender import (
        EmailAttachment,
        EmailMessage,
        SendResult,
        send_email,
    )
"""

from __future__ import annotations
