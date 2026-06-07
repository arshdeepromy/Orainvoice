/**
 * Send Email Modal — shared frontend contract.
 *
 * This module is the **single source of truth** for the Send Email composer
 * contract (R1.10). The mobile sheet (`mobile/src/components/email/SendEmailSheet.tsx`)
 * imports these types from here and SHALL NOT maintain a parallel definition.
 *
 * Every field name matches the Pydantic schemas in
 * `app/modules/email_compose/schemas.py` exactly (R1.9, R3.9, R11.10):
 * `SenderPreview`, `AttachmentSpec`, `BlocklistEntry`, `EmailPreviewResponse`,
 * and `OverrideSendBase`. Field renames or additions MUST be made on both sides
 * in the same change.
 */

// ---- Preview response (mirrors EmailPreviewResponse Pydantic schema) ----

export interface SenderPreview {
  from_email: string
  from_name: string
  reply_to: string | null
}

export interface AttachmentSpec {
  /** Stable id ('invoice_pdf') OR HMAC-signed token. */
  key: string
  label: string
  size_bytes: number
  default_attached: boolean
  required: boolean
}

export type BlocklistKind = 'soft' | 'hard'

export interface BlocklistEntry {
  email: string
  kind: BlocklistKind
  reason: string | null
  /** ISO 8601 timestamp of the bounce event. */
  bounced_at: string | null
}

export interface EmailPreviewResponse {
  subject: string
  body_html: string
  /** Inner editable body fragment (paragraphs + signature, no chrome/CTA) the editor binds to. */
  body_editable_html: string
  recipients: string[]
  cc: string[]
  bcc: string[]
  variable_context: Record<string, string>
  attachments: AttachmentSpec[]
  default_was_template: boolean
  sender_preview: SenderPreview
  blocklisted: BlocklistEntry[]
  /** Resolved locale (R3.10). */
  locale: string
  /** Server-side EMAIL_SIZE_LIMIT exposed to the modal (R3.9 / R7.3). */
  email_size_limit_bytes: number
  /** Total delivery time budget in seconds (R28.3). */
  total_budget_seconds: number
}

// ---- Override send payload (sent to the surface's endpoint) ----

export interface OverrideSendPayload {
  recipients?: string[]
  cc?: string[]
  bcc?: string[]
  subject?: string
  body_html?: string
  /** AttachmentSpec.key values for the checked attachments. */
  attachments?: string[]
  subject_was_edited?: boolean
  body_was_edited?: boolean
  override_blocklist?: boolean
}

// ---- Surface registry row ----

export type EntityType = 'invoice' | 'quote' | 'customer' | 'customer_vehicle'

export interface SurfaceConfig {
  templateType: string
  entityType: EntityType
  /** Build the override-send URL from the entity id (and log id for resend). */
  buildSendUrl: (entityId: string, opts?: { logId?: string }) => string
  method: 'POST' | 'PUT'
  /** v2 endpoints set this so apiClient uses the absolute path. */
  apiV2: boolean
  surfaceLabel: string
}

// ---- Modal props (R1.1 — exactly these, no surface-specific props) ----

export interface SendEmailModalProps {
  open: boolean
  onClose: () => void
  templateType: string
  entityType: EntityType
  entityId: string
  onSent: () => void
  surfaceLabel: string
  /** Resend surface only: notification-log row id, forwarded to buildSendUrl. */
  logId?: string
}
