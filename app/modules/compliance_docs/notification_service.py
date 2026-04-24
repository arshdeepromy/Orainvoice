"""Compliance document expiry notification service.

Sends email notifications when compliance documents are approaching or
have reached their expiry date. Supports three thresholds: 30-day,
7-day, and day-of. Uses a deduplication log to prevent duplicate sends.

**Validates: Requirements 7.1, 7.2, 7.3, 7.4, 7.5, 7.6, 13.2**
"""

from __future__ import annotations

import logging
import uuid
from datetime import date, timedelta

from sqlalchemy import and_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.compliance_docs.models import (
    ComplianceDocument,
    ComplianceNotificationLog,
)

logger = logging.getLogger(__name__)

# Threshold label mapping: threshold_days -> log label
THRESHOLD_LABELS: dict[int, str] = {
    30: "30_day",
    7: "7_day",
    0: "day_of",
}

DEFAULT_DASHBOARD_URL = "/compliance"


class ComplianceNotificationService:
    """Service for sending compliance document expiry email notifications."""

    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def send_expiry_notifications(
        self,
        threshold_days: int,
        dashboard_url: str = DEFAULT_DASHBOARD_URL,
    ) -> dict:
        """Send expiry notifications for documents at the exact threshold.

        For threshold_days=30 and threshold_days=7, queries documents where
        expiry_date == today + threshold_days. For threshold_days=0 (day_of),
        queries documents where expiry_date == today.

        Each document's notification is wrapped in its own try/except for
        isolation — one failure does not block others.

        Returns a summary dict with counts of sent, skipped, and errored.

        **Validates: Requirements 7.1, 7.2, 7.3, 7.5, 7.6**
        """
        threshold_label = THRESHOLD_LABELS.get(threshold_days)
        if threshold_label is None:
            logger.warning(
                "Unknown threshold_days=%d — skipping", threshold_days,
            )
            return {"sent": 0, "skipped": 0, "errors": 0}

        today = date.today()
        if threshold_days > 0:
            target_date = today + timedelta(days=threshold_days)
        else:
            target_date = today

        # Query documents expiring at the exact threshold date
        stmt = select(ComplianceDocument).where(
            and_(
                ComplianceDocument.expiry_date == target_date,
                ComplianceDocument.expiry_date.isnot(None),
            )
        )
        result = await self.db.execute(stmt)
        documents = list(result.scalars().all())

        sent = 0
        skipped = 0
        errors = 0

        for doc in documents:
            try:
                # Check deduplication log
                already_notified = await self.check_already_notified(
                    doc.id, threshold_label,
                )
                if already_notified:
                    skipped += 1
                    continue

                # Find org admin email to send to
                recipient = await self._get_org_admin_email(doc.org_id)
                if recipient is None:
                    logger.warning(
                        "No active org admin with email for org %s — "
                        "skipping compliance expiry notification for doc %s",
                        doc.org_id,
                        doc.id,
                    )
                    skipped += 1
                    continue

                # Build email content
                subject, html_body, text_body = self._build_expiry_email(
                    doc, threshold_label, dashboard_url,
                )

                # Log email to notification_log and dispatch
                await self._dispatch_email(
                    doc=doc,
                    recipient=recipient,
                    subject=subject,
                    html_body=html_body,
                    text_body=text_body,
                    threshold_label=threshold_label,
                )

                # Record in compliance dedup log — only on success
                await self.log_notification(
                    doc.id, doc.org_id, threshold_label,
                )
                sent += 1

            except Exception:
                logger.exception(
                    "Failed to send %s expiry notification for doc_id=%s org_id=%s",
                    threshold_label,
                    doc.id,
                    doc.org_id,
                )
                errors += 1

        return {"sent": sent, "skipped": skipped, "errors": errors}

    async def check_already_notified(
        self,
        doc_id: uuid.UUID,
        threshold: str,
    ) -> bool:
        """Check if a notification has already been sent for this doc+threshold.

        Returns True if a matching entry exists in compliance_notification_log.

        **Validates: Requirements 7.5, 13.2**
        """
        stmt = select(ComplianceNotificationLog.id).where(
            and_(
                ComplianceNotificationLog.document_id == doc_id,
                ComplianceNotificationLog.threshold == threshold,
            )
        ).limit(1)
        result = await self.db.execute(stmt)
        return result.scalar_one_or_none() is not None

    async def log_notification(
        self,
        doc_id: uuid.UUID,
        org_id: uuid.UUID,
        threshold: str,
    ) -> None:
        """Insert a record into compliance_notification_log.

        This is only called after a successful email dispatch so that
        failed notifications can be retried on the next scheduled run.

        **Validates: Requirements 13.2**
        """
        entry = ComplianceNotificationLog(
            document_id=doc_id,
            org_id=org_id,
            threshold=threshold,
        )
        self.db.add(entry)
        await self.db.flush()

    @staticmethod
    def _build_expiry_email(
        doc: ComplianceDocument,
        threshold: str,
        dashboard_url: str,
    ) -> tuple[str, str, str]:
        """Build the subject, HTML body, and text body for an expiry email.

        The email includes the document type, file name, expiry date, and
        a link to the compliance dashboard.

        **Validates: Requirements 7.4**
        """
        expiry_str = doc.expiry_date.strftime("%d/%m/%Y") if doc.expiry_date else "N/A"
        doc_type = doc.document_type or "Compliance Document"
        file_name = doc.file_name or "Unknown"

        if threshold == "30_day":
            urgency = "expires in 30 days"
        elif threshold == "7_day":
            urgency = "expires in 7 days"
        else:
            urgency = "expires today"

        subject = f"Compliance Document {urgency}: {doc_type}"

        html_body = (
            f"<p>Your compliance document <strong>{doc_type}</strong> "
            f"({file_name}) {urgency}.</p>"
            f"<p><strong>Expiry Date:</strong> {expiry_str}</p>"
            f'<p>Please <a href="{dashboard_url}">review your compliance documents</a> '
            f"and take action to renew before expiry.</p>"
        )

        text_body = (
            f"Your compliance document {doc_type} ({file_name}) {urgency}. "
            f"Expiry Date: {expiry_str}. "
            f"Please visit {dashboard_url} to review your compliance documents "
            f"and take action to renew before expiry."
        )

        return subject, html_body, text_body

    async def _get_org_admin_email(self, org_id: uuid.UUID) -> str | None:
        """Find the first active org_admin's email for the given org."""
        from app.modules.auth.models import User

        stmt = (
            select(User.email)
            .where(
                and_(
                    User.org_id == org_id,
                    User.role == "org_admin",
                    User.is_active.is_(True),
                )
            )
            .limit(1)
        )
        result = await self.db.execute(stmt)
        return result.scalar_one_or_none()

    async def _dispatch_email(
        self,
        doc: ComplianceDocument,
        recipient: str,
        subject: str,
        html_body: str,
        text_body: str,
        threshold_label: str,
    ) -> None:
        """Log the email to notification_log and dispatch via send_email_task.

        Follows the same pattern as check_card_expiry_task: log first,
        then send.
        """
        from app.modules.notifications.service import log_email_sent
        from app.tasks.notifications import send_email_task

        log_entry = await log_email_sent(
            self.db,
            org_id=doc.org_id,
            recipient=recipient,
            template_type=f"compliance_expiry_{threshold_label}",
            subject=subject,
            status="queued",
            channel="email",
        )

        result = await send_email_task(
            org_id=str(doc.org_id),
            log_id=log_entry["id"],
            to_email=recipient,
            to_name="",
            subject=subject,
            html_body=html_body,
            text_body=text_body,
            template_type=f"compliance_expiry_{threshold_label}",
        )

        if not result.get("success"):
            error_msg = result.get("error", "Unknown email send error")
            logger.error(
                "Email dispatch failed for compliance doc_id=%s org_id=%s "
                "threshold=%s: %s",
                doc.id,
                doc.org_id,
                threshold_label,
                error_msg,
            )
            # Raise to prevent logging the notification as sent,
            # allowing retry on the next scheduled run.
            raise RuntimeError(
                f"Email dispatch failed for doc {doc.id}: {error_msg}"
            )
