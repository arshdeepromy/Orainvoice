"""Email compose Pydantic schemas — preview response + override send payloads.

These schemas are the backend half of the Send Email Modal contract. Field
names match ``frontend-v2/src/components/email/types.ts`` exactly (R1.9, R3.9,
R11.10) so the shared TypeScript contract and the Pydantic models stay aligned.

``EmailPreviewResponse`` declares **every** field returned by the preview
endpoint (per frontend-backend-contract-alignment Rule 8, undeclared fields are
silently dropped by Pydantic). Each per-surface override payload inherits from
``OverrideSendBase`` which sets ``extra="forbid"`` so unknown fields raise 422.

Design ref: "Backend Pydantic schemas — app/modules/email_compose/schemas.py".
Requirements: 3.2, 3.9, 11.10
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field


class SenderPreview(BaseModel):
    """System-resolved sender identity (read-only in the modal, R9)."""

    from_email: str
    from_name: str
    reply_to: str | None = None


class AttachmentSpec(BaseModel):
    """One available attachment for a surface (R7.2)."""

    key: str
    label: str
    size_bytes: int
    default_attached: bool
    required: bool


class BlocklistEntry(BaseModel):
    """A recipient present in the org's Bounce_Blocklist (R4.5, R4.6)."""

    email: str
    kind: str  # 'soft' | 'hard'
    reason: str | None = None
    bounced_at: str | None = None  # ISO 8601


class EmailPreviewResponse(BaseModel):
    """Default content returned by ``GET /api/v2/email-preview`` (R3.2, R3.9)."""

    subject: str
    body_html: str
    body_editable_html: str
    recipients: list[str]
    cc: list[str]
    bcc: list[str]
    variable_context: dict[str, str]
    attachments: list[AttachmentSpec]
    default_was_template: bool
    sender_preview: SenderPreview
    blocklisted: list[BlocklistEntry]
    locale: str
    email_size_limit_bytes: int
    total_budget_seconds: int


class OverrideSendBase(BaseModel):
    """Shared override payload for every send surface.

    ``extra="forbid"`` rejects unknown fields with a 422 (R11.10).
    """

    model_config = ConfigDict(extra="forbid")  # R11.10 — reject unknown fields

    recipients: list[str] | None = None
    cc: list[str] | None = None
    bcc: list[str] | None = None
    subject: str | None = Field(default=None, max_length=255)
    body_html: str | None = None
    attachments: list[str] | None = None
    subject_was_edited: bool = False
    body_was_edited: bool = False
    override_blocklist: bool = False


# Per-surface subclasses (one each) keep room for surface-specific fields and a
# precise OpenAPI contract while sharing the base shape (R1.5).
class InvoiceEmailOverrideRequest(OverrideSendBase):
    """Invoice-send override payload.

    Carries the legacy ``recipient_email`` scalar (pre-modal
    ``InvoiceEmailRequest``) so existing clients posting only that field keep
    working; the modal supersedes it via ``recipients`` (R8.1 backward-compat).
    """

    recipient_email: str | None = None


class PaymentLinkOverrideRequest(OverrideSendBase): ...


class ReceiptEmailOverrideRequest(OverrideSendBase): ...


class QuoteSendOverrideRequest(OverrideSendBase): ...


class StatementEmailOverrideRequest(OverrideSendBase): ...


class PortalLinkOverrideRequest(OverrideSendBase): ...


class ReminderResendOverrideRequest(OverrideSendBase): ...
