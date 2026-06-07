/**
 * Send Email — shared contract re-export (mobile).
 *
 * The single source of truth for the Send Email composer contract lives in the
 * web module (`frontend-v2/src/components/email/types.ts`, R1.10 / R12.1). The
 * mobile sheet MUST NOT maintain a parallel definition; it re-exports the web
 * types verbatim through the `@email-contract` path alias (configured in
 * mobile/tsconfig.json + vite.config.ts + vitest.config.ts).
 */
export type {
  SenderPreview,
  AttachmentSpec,
  BlocklistKind,
  BlocklistEntry,
  EmailPreviewResponse,
  OverrideSendPayload,
  EntityType,
  SurfaceConfig,
  SendEmailModalProps,
} from '@email-contract/types'
