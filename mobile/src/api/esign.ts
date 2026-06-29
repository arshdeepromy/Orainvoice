/**
 * Typed API client for the E-Signature (Agreements) module — **mobile**
 * (feature: esignature-field-placement, R16).
 *
 * This is the mobile-app twin of `frontend-v2/src/api/esign.ts`. It speaks the
 * **identical** backend contract against the organisation-user envelope surface
 * mounted under `/api/v2/esign` in `app/modules/esignatures/router.py`, so a
 * mobile send is indistinguishable from a web send on the wire (R16.7):
 *
 *   - POST   /api/v2/esign/envelopes                       create + send (multipart)
 *   - GET    /api/v2/esign/envelopes (optional ?status=)   dashboard list
 *   - GET    /api/v2/esign/envelopes/{id}                  envelope detail
 *   - POST   /api/v2/esign/envelopes/{id}/void             void a non-terminal envelope
 *   - GET    /api/v2/esign/envelopes/{id}/signed-document  download the signed PDF (blob)
 *   - GET    /api/v2/esign/envelopes/{id}/fields           read the live Field_Set (R13)
 *   - PUT    /api/v2/esign/envelopes/{id}/fields           replace the Field_Set (R13)
 *   - GET    /api/v2/esign/field-templates                 list templates (R17)
 *   - POST   /api/v2/esign/field-templates                 save a template (R17)
 *   - GET    /api/v2/esign/field-templates/{id}            fetch one template (R17)
 *   - DELETE /api/v2/esign/field-templates/{id}            delete a template (R17)
 *
 * Conventions (per `.kiro/steering/mobile-app.md`,
 * `.kiro/steering/safe-api-consumption.md`, and R16.8):
 *
 *   - v2 endpoints use **absolute** `/api/v2/...` paths. The mobile axios client
 *     in `client.ts` strips its `/api/v1` baseURL for any URL starting with
 *     `/api/`, so these resolve correctly on both native and web builds.
 *   - All array responses are wrapped objects (`{ items, total }`) — never bare
 *     arrays.
 *   - Every call accepts an optional `AbortSignal` forwarded via `{ signal }`,
 *     so the caller can bind the in-flight request to an AbortController that is
 *     aborted on unmount / cancel (R16.8).
 *   - Typed generics on every `apiClient.*` call — never `as any`.
 *   - Read sites use `?.` / `?? []` / `?? 0` so a partial / blank response can
 *     never crash a consumer.
 *   - Binary downloads return a `Blob`; the share / object-URL handling stays in
 *     the calling screen.
 *
 * The mobile pure core (`@/lib/esign`, from task 23.1) is the single source of
 * truth for `FieldType` / `FIELD_TYPES` / `PlacedField` / `NormalizedRect` and
 * the dependency condition/effect enums, so this module reuses them rather than
 * redefining them.
 *
 * _Requirements: 16.7, 16.8_
 */

import apiClient from '@/api/client'
import {
  FIELD_TYPES,
  type FieldType,
  type PlacedField,
  type DependencyCondition,
  type DependencyEffect,
} from '@/lib/esign'

// Re-export the field-type contract so editor screens (task 24.2) can import it
// from the API module without reaching into the pure core directly.
export { FIELD_TYPES, type FieldType, type DependencyCondition, type DependencyEffect }

// ===========================================================================
// Enums — mirror the Literal types in app/modules/esignatures/schemas.py
// ===========================================================================

/** The five agreement categories the module supports. */
export type AgreementType =
  | 'sales_agreement'
  | 'purchase_agreement'
  | 'nda'
  | 'employment_agreement'
  | 'contractor_agreement'

/** Ordered list of agreement types for stable UI rendering (e.g. a select). */
export const AGREEMENT_TYPES: readonly AgreementType[] = [
  'sales_agreement',
  'purchase_agreement',
  'nda',
  'employment_agreement',
  'contractor_agreement',
]

/** The OraInvoice record an envelope is attached to. */
export type OriginatingEntityType = 'invoice' | 'quote' | 'staff'

/**
 * Signing role accepted by the API in **lowercase** (`signer` / `viewer`).
 * The backend persists and sends to Documenso in UPPERCASE; the request body
 * carries the lowercase form.
 */
export type SigningRole = 'signer' | 'viewer'

/**
 * Envelope lifecycle status. `completed`, `declined`, and `voided` are
 * terminal.
 */
export type EnvelopeStatus =
  | 'draft'
  | 'sent'
  | 'viewed'
  | 'partially_signed'
  | 'completed'
  | 'declined'
  | 'voided'
  | 'error'

/** Statuses an org user can filter the dashboard by. */
export const ENVELOPE_STATUSES: readonly EnvelopeStatus[] = [
  'draft',
  'sent',
  'viewed',
  'partially_signed',
  'completed',
  'declined',
  'voided',
  'error',
]

/**
 * Signing-order mode (R15). `parallel` lets every signer sign at once;
 * `sequential` invites each signer only after the previous one in the order has
 * signed. The backend maps each to Documenso's `PARALLEL` / `SEQUENTIAL`
 * distribution mode.
 */
export type SigningOrderMode = 'parallel' | 'sequential'

/** Ordered list of signing-order modes for stable UI rendering (toggle order). */
export const SIGNING_ORDER_MODES: readonly SigningOrderMode[] = ['parallel', 'sequential']

// ===========================================================================
// Request types — mirror RecipientIn / EnvelopeCreate
// ===========================================================================

/**
 * A recipient supplied when creating a send. `signing_role` defaults to
 * `signer` server-side when omitted. Mirrors `RecipientIn`.
 */
export interface RecipientIn {
  name: string
  /** Syntactically validated server-side before sending to Documenso. */
  email: string
  signing_role?: SigningRole
  /**
   * Optional 1-based signing-order position (R15). Used only when the send's
   * `signing_order_mode` is `sequential`; viewers carry no position but remain
   * on the document. Additive — omitted for parallel sends.
   */
  order?: number
}

/**
 * A single sender-placed field carried on a field-placement send. Coordinates
 * are **normalized percent** (0–100) with the origin at the page's top-left,
 * independent of the on-screen render scale (R7.2). `recipient_index` is the
 * field's recipient's **position in the `recipients` array** of the same
 * `EnvelopeCreate` body — produce it from the editor's `PlacedField.recipientKey`
 * with {@link placedFieldsToFieldIns} at submit time.
 *
 * Mirrors the Pydantic `FieldIn` in `app/modules/esignatures/schemas.py`.
 */
export interface FieldIn {
  /** One of the six supported types (R2.1). */
  type: FieldType
  /** 1-based page number the field sits on. */
  page: number
  /** Index into the send's `recipients` array this field is assigned to. */
  recipient_index: number
  /** Normalized percent (0–100), origin top-left. */
  position_x: number
  position_y: number
  /** Normalized percent (0–100), strictly positive. */
  width: number
  height: number
  /** Per-field required flag (R5.1). */
  required: boolean
  /** Label for `text` fields only (R5.2). */
  label?: string
  /** Placeholder for `text` fields only (R5.2). */
  placeholder?: string
  /**
   * Stable per-field key used to reference this field from a {@link DependencyIn}
   * (`dependent_client_id` / `trigger_client_id`, R14). Additive and optional.
   */
  client_id?: string
}

/**
 * A conditional-field dependency carried alongside the Field_Set (R14).
 * Enforcement is **advisory** today (Documenso has no cross-field conditional
 * primitive), so a `require` effect degrades the dependent field to optional at
 * signing. Mirrors `DependencyIn`.
 */
export interface DependencyIn {
  /** The field governed by the rule (a `FieldIn.client_id`). */
  dependent_client_id: string
  /** The field whose value is observed (≠ dependent, R14.2). */
  trigger_client_id: string
  /** The trigger condition (R14.3). */
  condition: DependencyCondition
  /** Comparison value for `equals` / `not_equals`. */
  value?: string
  /** The effect on the dependent field (R14.1) — show / require. */
  effect: DependencyEffect
}

/**
 * The JSON body half of the multipart create request (the PDF is the other
 * half). Serialised to a string and sent in the `payload` form field.
 * Mirrors `EnvelopeCreate`.
 */
export interface EnvelopeCreate {
  agreement_type: AgreementType
  originating_entity_type: OriginatingEntityType
  originating_entity_id: string
  /** At least one recipient is required (R3.3). */
  recipients: RecipientIn[]
  /**
   * The sender-defined Field_Set placed in the editor (R2.1, R5.1, R5.2).
   * **Additive and backward-compatible**: when omitted / empty the backend runs
   * the existing single-signature auto-placement path unchanged; when non-empty
   * these fields are re-validated server-side and created via `field/create-many`
   * before distribute (R8.1).
   */
  fields?: FieldIn[]
  /**
   * Signing-order mode (R15.2). Defaults to `parallel` server-side so existing
   * callers are unaffected; `sequential` uses each recipient's `order` position.
   */
  signing_order_mode?: SigningOrderMode
  /**
   * Advisory conditional-field dependencies over the Field_Set (R14). Additive
   * and optional; re-checked for cycles/self-loops server-side before send.
   */
  dependencies?: DependencyIn[]
}

/**
 * Body for `PUT /api/v2/esign/envelopes/{id}/fields` (edit-after-send, R13).
 * The Field_Set is **required** (≥1 field): an edit always replaces the whole
 * set, and the server re-validates it with the same rules as an initial send
 * before atomically replacing the Documenso fields (R13.3). Mirrors
 * `FieldSetReplace`.
 */
export interface FieldSetReplace {
  fields: FieldIn[]
  dependencies?: DependencyIn[]
}

/**
 * A single field stored on a Field_Template (R17.1). Carries
 * geometry/type/required/label/placeholder plus a `template_role` — an abstract
 * recipient slot (e.g. `signer 1`) rather than a specific person. Mirrors
 * `TemplateFieldIn`.
 */
export interface TemplateFieldIn {
  type: FieldType
  /** 1-based page number the field sits on. */
  page: number
  /** Normalized percent (0–100), origin top-left. */
  position_x: number
  position_y: number
  /** Normalized percent (0–100), strictly positive. */
  width: number
  height: number
  required: boolean
  label?: string
  placeholder?: string
  /** Abstract recipient slot, never a person (R17.1). */
  template_role: string
}

/**
 * Payload to save the current Field_Set as a reusable template (R17.1–R17.3).
 * Org-scoped and durable; stores roles, never specific recipients. Mirrors
 * `FieldTemplateCreate`.
 */
export interface FieldTemplateCreate {
  name: string
  /** Optional agreement-type association (R17.2). */
  agreement_type?: AgreementType
  fields: TemplateFieldIn[]
  roles: string[]
}

// ---------------------------------------------------------------------------
// Field_Set mapping — turn the editor's placed fields (which reference a
// recipient by a stable client key) into the wire `FieldIn[]` (which references
// a recipient by its index in the send's `recipients` array).
// ---------------------------------------------------------------------------

/**
 * The minimal placed-field shape this module needs to build a {@link FieldIn}.
 * Structurally satisfied by the mobile pure core's `PlacedField`
 * (`@/lib/esign`) so the editor can pass its Field_Set straight in without an
 * adapter, while keeping the API layer free of a dependency on the editor's
 * component tree.
 */
export interface PlacedFieldLike {
  type: FieldType
  page: number
  rect: { positionX: number; positionY: number; width: number; height: number }
  /** References a recipient row by its stable client key (R4.1). */
  recipientKey: number
  required: boolean
  label?: string
  placeholder?: string
  /**
   * Stable per-field client id, threaded onto the wire as {@link FieldIn.client_id}
   * so a {@link DependencyIn} can reference this field. Structurally satisfied by
   * the core's `PlacedField.clientId`; optional so dependency-free callers are
   * unaffected.
   */
  clientId?: string
}

// Compile-time guarantee that the pure-core `PlacedField` satisfies the shape
// `placedFieldsToFieldIns` accepts, so the editor (task 24.2) can pass its
// Field_Set straight in. Erased at build time — purely a type assertion.
type _PlacedFieldSatisfiesLike = PlacedField extends PlacedFieldLike ? true : never
const _placedFieldShapeCheck: _PlacedFieldSatisfiesLike = true
void _placedFieldShapeCheck

/**
 * Map the editor's placed fields onto the wire `FieldIn[]`, resolving each
 * field's `recipientKey` to its recipient's **array index** in the send.
 *
 * `recipientKeyOrder` MUST be the stable keys of the send's recipients **in the
 * exact same order** they appear in the `EnvelopeCreate.recipients` array, so a
 * field's resolved `recipient_index` lines up with the recipient the backend
 * reconciles by email. The editor's client-side validation keeps send disabled
 * until every field references an existing recipient, so a field whose key is
 * absent from the order is a programming error and throws rather than silently
 * misassigning.
 */
export function placedFieldsToFieldIns(
  placedFields: readonly PlacedFieldLike[],
  recipientKeyOrder: readonly number[],
): FieldIn[] {
  const indexByKey = new Map<number, number>()
  recipientKeyOrder.forEach((key, index) => {
    if (!indexByKey.has(key)) indexByKey.set(key, index)
  })

  return placedFields.map((field) => {
    const recipientIndex = indexByKey.get(field.recipientKey)
    if (recipientIndex === undefined) {
      throw new Error(
        `Placed field references recipient key ${field.recipientKey}, ` +
          'which is not in the send\u2019s recipient list.',
      )
    }
    const out: FieldIn = {
      type: field.type,
      page: field.page,
      recipient_index: recipientIndex,
      position_x: field.rect.positionX,
      position_y: field.rect.positionY,
      width: field.rect.width,
      height: field.rect.height,
      required: field.required,
    }
    if (field.label !== undefined) out.label = field.label
    if (field.placeholder !== undefined) out.placeholder = field.placeholder
    if (field.clientId !== undefined) out.client_id = field.clientId
    return out
  })
}

/**
 * The minimal field-dependency shape this module needs to build a
 * {@link DependencyIn}. Structurally satisfied by the pure core's
 * `FieldDependency` (`@/lib/esign`) so the editor / modal can pass its
 * dependency set straight in without an adapter.
 */
export interface PlacedDependencyLike {
  dependentClientId: string
  triggerClientId: string
  condition: DependencyCondition
  effect: DependencyEffect
  value?: string
}

/**
 * Map the editor's {@link PlacedDependencyLike} dependency set onto the wire
 * `DependencyIn[]` (camelCase client ids → `dependent_client_id` /
 * `trigger_client_id`, R14). The `value` operand is carried only when present.
 * Acyclicity / self-loop rules are enforced upstream by the pure
 * dependency-graph core and re-checked server-side; this is a pure shape mapping.
 */
export function fieldDependenciesToDependencyIns(
  dependencies: readonly PlacedDependencyLike[],
): DependencyIn[] {
  return dependencies.map((dep) => {
    const out: DependencyIn = {
      dependent_client_id: dep.dependentClientId,
      trigger_client_id: dep.triggerClientId,
      condition: dep.condition,
      effect: dep.effect,
    }
    if (dep.value !== undefined) out.value = dep.value
    return out
  })
}

// ===========================================================================
// Response types — mirror RecipientOut / EnvelopeOut / EnvelopeListResponse /
// EsignError
// ===========================================================================

/**
 * A persisted recipient with its per-recipient signing status. `signing_role`
 * is returned as the stored UPPERCASE Documenso role. Mirrors `RecipientOut`.
 */
export interface RecipientOut {
  id: string
  name: string
  email: string
  /** Stored UPPERCASE Documenso role (`SIGNER` / `VIEWER`). */
  signing_role: string
  /** Per-recipient signing status (e.g. `pending`, `signed`). */
  recipient_status: string
}

/**
 * A single envelope with its recipients and current status. Mirrors
 * `EnvelopeOut`. `signed_document_url` is populated only when a signed document
 * has been stored; it is an opaque, org-checked link, never the bytes.
 */
export interface EnvelopeOut {
  id: string
  agreement_type: string
  originating_entity_type: string
  originating_entity_id: string
  status: string
  recipients: RecipientOut[]
  /** Present only when a signed document is stored, else null. */
  signed_document_url: string | null
  created_at: string
  updated_at: string
}

/**
 * Humanized error shape. `message` is always present; `code` is an optional
 * secondary machine-readable code. Mirrors `EsignError`.
 */
export interface EsignError {
  message: string
  code: string | null
}

/**
 * Result of listing envelopes. Always `{ items, total }`; `error` is present
 * only on the fail-closed filter path (HTTP 200 with empty items and a
 * humanized `filter_unavailable` error).
 */
export interface EnvelopeListResult {
  items: EnvelopeOut[]
  total: number
  /** Set only when a requested `?status=` filter could not be applied. */
  error: EsignError | null
}

/**
 * A field read back from the Documenso document (edit-after-send, R13). Mirrors
 * {@link FieldIn} / `FieldOut`. Coordinates are normalized percent, origin
 * top-left.
 */
export interface FieldOut {
  type: FieldType
  page: number
  recipient_index: number
  position_x: number
  position_y: number
  width: number
  height: number
  required: boolean
  label?: string
  placeholder?: string
  client_id?: string
}

/**
 * Response for `GET /api/v2/esign/envelopes/{id}/fields` (R13.1). Seeds the
 * editor with the envelope's current Field_Set, its recipients, and the
 * `editable` flag (`status == 'sent'` AND no recipient has signed). Mirrors
 * `EnvelopeFieldsOut`.
 */
export interface EnvelopeFieldsOut {
  fields: FieldOut[]
  recipients: RecipientOut[]
  editable: boolean
}

/** A persisted, org-scoped Field_Template (R17). Mirrors `FieldTemplateOut`. */
export interface FieldTemplateOut {
  id: string
  name: string
  /** Optional agreement-type association (R17.2), else null. */
  agreement_type: string | null
  fields: TemplateFieldIn[]
  roles: string[]
  created_at: string
  updated_at: string
}

/**
 * Result of listing field templates. Always `{ items, total }`. Mirrors
 * `FieldTemplateListResponse`.
 */
export interface FieldTemplateListResult {
  items: FieldTemplateOut[]
  total: number
}

// ---------------------------------------------------------------------------
// Wire types — what the backend actually serialises.
// ---------------------------------------------------------------------------

interface RecipientOutWire {
  id?: string | null
  name?: string | null
  email?: string | null
  signing_role?: string | null
  recipient_status?: string | null
}

interface EnvelopeOutWire {
  id?: string | null
  agreement_type?: string | null
  originating_entity_type?: string | null
  originating_entity_id?: string | null
  status?: string | null
  recipients?: RecipientOutWire[] | null
  signed_document_url?: string | null
  created_at?: string | null
  updated_at?: string | null
}

interface EnvelopeListWire {
  items?: EnvelopeOutWire[] | null
  total?: number | string | null
  /** Present only on the fail-closed filter path (HTTP 200). */
  error?: { message?: string | null; code?: string | null } | null
}

interface FieldOutWire {
  type?: string | null
  page?: number | string | null
  recipient_index?: number | string | null
  position_x?: number | string | null
  position_y?: number | string | null
  width?: number | string | null
  height?: number | string | null
  required?: boolean | null
  label?: string | null
  placeholder?: string | null
  client_id?: string | null
}

interface EnvelopeFieldsWire {
  fields?: FieldOutWire[] | null
  recipients?: RecipientOutWire[] | null
  editable?: boolean | null
}

interface TemplateFieldWire {
  type?: string | null
  page?: number | string | null
  position_x?: number | string | null
  position_y?: number | string | null
  width?: number | string | null
  height?: number | string | null
  required?: boolean | null
  label?: string | null
  placeholder?: string | null
  template_role?: string | null
}

interface FieldTemplateOutWire {
  id?: string | null
  name?: string | null
  agreement_type?: string | null
  fields?: TemplateFieldWire[] | null
  roles?: (string | null)[] | null
  created_at?: string | null
  updated_at?: string | null
}

interface FieldTemplateListWire {
  items?: FieldTemplateOutWire[] | null
  total?: number | string | null
}

// ===========================================================================
// Normalisers — coerce a partial/blank wire payload into a fully-populated,
// crash-proof shape so callers never see `undefined`.
// ===========================================================================

function toNumber(value: unknown, fallback = 0): number {
  const n = Number(value)
  return Number.isFinite(n) ? n : fallback
}

function normaliseRecipient(wire: RecipientOutWire | null | undefined): RecipientOut {
  return {
    id: wire?.id ?? '',
    name: wire?.name ?? '',
    email: wire?.email ?? '',
    signing_role: wire?.signing_role ?? '',
    recipient_status: wire?.recipient_status ?? '',
  }
}

function normaliseEnvelope(wire: EnvelopeOutWire | null | undefined): EnvelopeOut {
  return {
    id: wire?.id ?? '',
    agreement_type: wire?.agreement_type ?? '',
    originating_entity_type: wire?.originating_entity_type ?? '',
    originating_entity_id: wire?.originating_entity_id ?? '',
    status: wire?.status ?? '',
    recipients: (wire?.recipients ?? []).map(normaliseRecipient),
    signed_document_url: wire?.signed_document_url ?? null,
    created_at: wire?.created_at ?? '',
    updated_at: wire?.updated_at ?? '',
  }
}

function normaliseError(
  wire: { message?: string | null; code?: string | null } | null | undefined,
): EsignError | null {
  if (!wire) return null
  return {
    message: wire.message ?? 'Something went wrong handling your request.',
    code: wire.code ?? null,
  }
}

/**
 * Coerce a wire `type` string into a known {@link FieldType}. The backend only
 * ever returns one of the six supported types; an unexpected/blank value falls
 * back to `text` so a partial payload can never produce an `undefined` type.
 */
function toFieldType(value: unknown): FieldType {
  return (FIELD_TYPES as readonly string[]).includes(value as string)
    ? (value as FieldType)
    : 'text'
}

function normaliseField(wire: FieldOutWire | null | undefined): FieldOut {
  const out: FieldOut = {
    type: toFieldType(wire?.type),
    page: toNumber(wire?.page, 1),
    recipient_index: toNumber(wire?.recipient_index, 0),
    position_x: toNumber(wire?.position_x, 0),
    position_y: toNumber(wire?.position_y, 0),
    width: toNumber(wire?.width, 0),
    height: toNumber(wire?.height, 0),
    required: wire?.required ?? true,
  }
  if (wire?.label != null) out.label = wire.label
  if (wire?.placeholder != null) out.placeholder = wire.placeholder
  if (wire?.client_id != null) out.client_id = wire.client_id
  return out
}

function normaliseEnvelopeFields(
  wire: EnvelopeFieldsWire | null | undefined,
): EnvelopeFieldsOut {
  return {
    fields: (wire?.fields ?? []).map(normaliseField),
    recipients: (wire?.recipients ?? []).map(normaliseRecipient),
    editable: wire?.editable ?? false,
  }
}

function normaliseTemplateField(wire: TemplateFieldWire | null | undefined): TemplateFieldIn {
  const out: TemplateFieldIn = {
    type: toFieldType(wire?.type),
    page: toNumber(wire?.page, 1),
    position_x: toNumber(wire?.position_x, 0),
    position_y: toNumber(wire?.position_y, 0),
    width: toNumber(wire?.width, 0),
    height: toNumber(wire?.height, 0),
    required: wire?.required ?? true,
    template_role: wire?.template_role ?? '',
  }
  if (wire?.label != null) out.label = wire.label
  if (wire?.placeholder != null) out.placeholder = wire.placeholder
  return out
}

function normaliseTemplate(wire: FieldTemplateOutWire | null | undefined): FieldTemplateOut {
  return {
    id: wire?.id ?? '',
    name: wire?.name ?? '',
    agreement_type: wire?.agreement_type ?? null,
    fields: (wire?.fields ?? []).map(normaliseTemplateField),
    roles: (wire?.roles ?? []).filter((r): r is string => typeof r === 'string'),
    created_at: wire?.created_at ?? '',
    updated_at: wire?.updated_at ?? '',
  }
}

// ===========================================================================
// Endpoints
// ===========================================================================

/**
 * POST /api/v2/esign/envelopes
 *
 * Create a Documenso document from the supplied PDF and send it for signature.
 * The request is multipart: the PDF goes in the `file` part and the
 * `EnvelopeCreate` JSON is serialised into the `payload` form field (matching
 * the backend `UploadFile` + `Form(...)` signature). This is the **identical**
 * contract the `frontend-v2/` editor uses (R16.7).
 *
 * Returns the freshly-created envelope (status `sent`); a freshly-sent envelope
 * never carries a `signed_document_url`.
 *
 * Errors surface as the standard humanized `{ message, code }` body:
 *   - 422 validation (non-PDF / no recipients / bad email / invalid Field_Set),
 *   - 502 Documenso API failure (envelope recorded with `error` status),
 *   - 503 the org's Documenso connection is not configured / verified.
 */
export async function createEnvelope(
  file: File | Blob,
  payload: EnvelopeCreate,
  signal?: AbortSignal,
): Promise<EnvelopeOut> {
  const form = new FormData()
  form.append('file', file)
  form.append('payload', JSON.stringify(payload))

  const res = await apiClient.post<EnvelopeOutWire>(
    '/api/v2/esign/envelopes',
    form,
    {
      // Let the platform set the multipart boundary; override the client's
      // default application/json content type for this request only.
      headers: { 'Content-Type': 'multipart/form-data' },
      signal,
    },
  )
  return normaliseEnvelope(res.data)
}

/**
 * GET /api/v2/esign/envelopes (optional ?status=)
 *
 * List the calling organisation's envelopes, newest-updated first. Always
 * returns `{ items, total, error }`.
 *
 * Fail-closed filter: when a requested `status` filter cannot be applied the
 * backend still responds HTTP 200 with **empty** items and a humanized
 * `filter_unavailable` error in the body, surfaced here on `result.error`.
 */
export async function listEnvelopes(
  status?: EnvelopeStatus | null,
  signal?: AbortSignal,
): Promise<EnvelopeListResult> {
  const res = await apiClient.get<EnvelopeListWire>('/api/v2/esign/envelopes', {
    params: status ? { status } : undefined,
    signal,
  })
  const data = res.data
  return {
    items: (data?.items ?? []).map(normaliseEnvelope),
    total: toNumber(data?.total, 0),
    error: normaliseError(data?.error),
  }
}

/**
 * GET /api/v2/esign/envelopes/{id}
 *
 * Return one envelope's detail: per-recipient signing status and, when a signed
 * document is stored, its org-checked `signed_document_url`. A missing or
 * cross-org envelope yields a humanized 404.
 */
export async function getEnvelope(
  envelopeId: string,
  signal?: AbortSignal,
): Promise<EnvelopeOut> {
  const res = await apiClient.get<EnvelopeOutWire>(
    `/api/v2/esign/envelopes/${envelopeId}`,
    { signal },
  )
  return normaliseEnvelope(res.data)
}

/**
 * POST /api/v2/esign/envelopes/{id}/void
 *
 * Void a non-terminal envelope, cancelling it in Documenso and setting its
 * status to `voided`. A terminal envelope yields a humanized 409 and no
 * Documenso call; a cross-org / missing envelope yields a 404. Requires the
 * `org_admin` / `branch_admin` / `location_manager` role (else 403).
 */
export async function voidEnvelope(
  envelopeId: string,
  signal?: AbortSignal,
): Promise<EnvelopeOut> {
  const res = await apiClient.post<EnvelopeOutWire>(
    `/api/v2/esign/envelopes/${envelopeId}/void`,
    {},
    { signal },
  )
  return normaliseEnvelope(res.data)
}

/**
 * GET /api/v2/esign/envelopes/{id}/signed-document
 *
 * Download the stored signed PDF (binary `application/pdf`) for an envelope,
 * served from the encrypted uploads pipeline and org-checked. Returns a `Blob`
 * ready for the calling screen to share / save.
 *
 * A 404 is returned when the envelope is missing / cross-org, or when no signed
 * document has been stored yet.
 */
export async function downloadSignedDocument(
  envelopeId: string,
  signal?: AbortSignal,
): Promise<Blob> {
  const res = await apiClient.get<Blob>(
    `/api/v2/esign/envelopes/${envelopeId}/signed-document`,
    { responseType: 'blob', signal },
  )
  return res.data
}

// ===========================================================================
// Edit-after-send endpoints (R13)
// ===========================================================================

/**
 * GET /api/v2/esign/envelopes/{id}/fields
 *
 * Read an envelope's current Field_Set, its recipients, and the pure `editable`
 * gate (`status == 'sent'` AND nobody has signed) so the mobile editor can be
 * seeded for an in-place edit (R13.1). A missing / cross-org envelope yields a
 * humanized 404.
 */
export async function getEnvelopeFields(
  envelopeId: string,
  signal?: AbortSignal,
): Promise<EnvelopeFieldsOut> {
  const res = await apiClient.get<EnvelopeFieldsWire>(
    `/api/v2/esign/envelopes/${envelopeId}/fields`,
    { signal },
  )
  return normaliseEnvelopeFields(res.data)
}

/**
 * PUT /api/v2/esign/envelopes/{id}/fields
 *
 * Replace an editable envelope's whole Field_Set in place (R13). The server
 * re-checks the Editable_State gate, re-validates the set with the same rules as
 * an initial send, then atomically replaces the Documenso fields (R13.3).
 * Returns the new field set read back from Documenso.
 *
 * Errors surface as the standard humanized `{ message, code }` body:
 *   - 422 `not_editable` (signing begun / terminal) — no Documenso mutation,
 *   - 422 validation (same rules as send),
 *   - 502 Documenso failure — the prior field set is left intact (R13.8).
 */
export async function replaceEnvelopeFields(
  envelopeId: string,
  body: FieldSetReplace,
  signal?: AbortSignal,
): Promise<FieldOut[]> {
  const res = await apiClient.put<{ fields?: FieldOutWire[] | null }>(
    `/api/v2/esign/envelopes/${envelopeId}/fields`,
    body,
    { signal },
  )
  return (res.data?.fields ?? []).map(normaliseField)
}

// ===========================================================================
// Field-template endpoints (R17)
// ===========================================================================

/**
 * GET /api/v2/esign/field-templates
 *
 * List the calling organisation's saved field templates. Always returns
 * `{ items, total }` (R17).
 */
export async function listFieldTemplates(
  signal?: AbortSignal,
): Promise<FieldTemplateListResult> {
  const res = await apiClient.get<FieldTemplateListWire>(
    '/api/v2/esign/field-templates',
    { signal },
  )
  const data = res.data
  return {
    items: (data?.items ?? []).map(normaliseTemplate),
    total: toNumber(data?.total, 0),
  }
}

/**
 * POST /api/v2/esign/field-templates
 *
 * Save the current Field_Set as a reusable, org-scoped template (R17.1–R17.3).
 * Stores Template_Recipient_Role slots, never specific recipients. Returns the
 * persisted template.
 */
export async function createFieldTemplate(
  payload: FieldTemplateCreate,
  signal?: AbortSignal,
): Promise<FieldTemplateOut> {
  const res = await apiClient.post<FieldTemplateOutWire>(
    '/api/v2/esign/field-templates',
    payload,
    { signal },
  )
  return normaliseTemplate(res.data)
}

/**
 * GET /api/v2/esign/field-templates/{id}
 *
 * Fetch a single template (to apply). A missing / cross-org template yields a
 * humanized 404.
 */
export async function getFieldTemplate(
  templateId: string,
  signal?: AbortSignal,
): Promise<FieldTemplateOut> {
  const res = await apiClient.get<FieldTemplateOutWire>(
    `/api/v2/esign/field-templates/${templateId}`,
    { signal },
  )
  return normaliseTemplate(res.data)
}

/**
 * DELETE /api/v2/esign/field-templates/{id}
 *
 * Delete an org-scoped template (HTTP 204). A missing / cross-org template
 * yields a humanized 404.
 */
export async function deleteFieldTemplate(
  templateId: string,
  signal?: AbortSignal,
): Promise<void> {
  await apiClient.delete<void>(`/api/v2/esign/field-templates/${templateId}`, {
    signal,
  })
}
