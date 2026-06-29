/**
 * Typed API client for the E-Signature (Agreements) module
 * (feature: esignature-integration).
 *
 * Covers the organisation-user envelope surface mounted under
 * `/api/v2/esign` in `app/modules/esignatures/router.py`:
 *
 *   - POST   /api/v2/esign/envelopes                       create + send (multipart)
 *   - GET    /api/v2/esign/envelopes (optional ?status=)   dashboard list
 *   - GET    /api/v2/esign/envelopes/{id}                  envelope detail
 *   - POST   /api/v2/esign/envelopes/{id}/void             void a non-terminal envelope
 *   - GET    /api/v2/esign/envelopes/{id}/signed-document  download the signed PDF (blob)
 *
 * Mirrors the Pydantic schemas in `app/modules/esignatures/schemas.py`
 * (`RecipientIn`, `EnvelopeCreate`, `RecipientOut`, `EnvelopeOut`,
 * `EnvelopeListResponse`, `EsignError`) and the agreement / status / role
 * enums defined there.
 *
 * Conventions (per `.kiro/steering/safe-api-consumption.md`, the project
 * rules, and the `api/staff.ts` / `api/payrollTax.ts` / `api/ppsr.ts`
 * conventions):
 *
 *   - v2 endpoints use absolute `/api/v2/...` paths (the axios client in
 *     `client.ts` strips the `/api/v1` baseURL when the URL starts with
 *     `/api/`).
 *   - All array responses are wrapped objects (`{ items, total }`) — never
 *     bare arrays.
 *   - Every call accepts an optional `AbortSignal` forwarded via `{ signal }`.
 *   - Typed generics on every `apiClient.*` call — never `as any`.
 *   - Read sites use `?.` / `?? []` / `?? 0` so a partial / blank response can
 *     never crash a consumer.
 *   - Binary downloads return a `Blob` (matching `api/ppsr.ts` `exportPdf` and
 *     `api/payslips.ts` `downloadPayslipPdf`); the DOM object-URL + anchor
 *     dance stays in the calling page.
 *
 * _Requirements: 16.1 (and the frontend safe-consumption rules)_
 */

import apiClient from './client'

// ===========================================================================
// Enums — mirror the Literal types in app/modules/esignatures/schemas.py
// ===========================================================================

/** The five agreement categories the module supports (R3.6). */
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
 * The backend persists and sends to Documenso in UPPERCASE (`SIGNER` /
 * `VIEWER`) — the request body carries the lowercase form.
 */
export type SigningRole = 'signer' | 'viewer'

/**
 * Envelope lifecycle status. `completed`, `declined`, and `voided` are
 * terminal. (`draft` is modelled for completeness; the create flow starts an
 * envelope at `sent`.)
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
 * The six sender-placeable field types (R2.1), accepted by the API in
 * **lowercase**. The backend maps each to its UPPERCASE Documenso type
 * (`SIGNATURE` / `INITIALS` / `NAME` / `DATE` / `EMAIL` / `TEXT`) in
 * `field_mapping.map_field_type`. Mirrors the `FieldType` Literal in
 * `app/modules/esignatures/schemas.py`.
 */
export type FieldType = 'signature' | 'initials' | 'name' | 'date' | 'email' | 'text'

/** Ordered list of field types for stable UI rendering (palette order). */
export const FIELD_TYPES: readonly FieldType[] = [
  'signature',
  'initials',
  'name',
  'date',
  'email',
  'text',
]

/**
 * Signing-order mode (R15). `parallel` (the existing default behaviour) lets
 * every signer sign at once; `sequential` invites each signer only after the
 * previous one in the order has signed. The backend maps each to Documenso's
 * `PARALLEL` / `SEQUENTIAL` distribution mode (R15.4, R15.5). Mirrors the
 * `SigningOrderMode` Literal in `app/modules/esignatures/schemas.py`.
 */
export type SigningOrderMode = 'parallel' | 'sequential'

/** Ordered list of signing-order modes for stable UI rendering (toggle order). */
export const SIGNING_ORDER_MODES: readonly SigningOrderMode[] = ['parallel', 'sequential']

/**
 * The supported conditional-field trigger conditions (R14.3). `is_checked` /
 * `is_not_checked` apply to checkbox-style triggers; `equals` / `not_equals`
 * (using the optional `value`) and `is_filled` / `is_empty` apply to
 * value-bearing triggers. Mirrors the `DependencyCondition` Literal in
 * `app/modules/esignatures/schemas.py`.
 */
export type DependencyCondition =
  | 'is_checked'
  | 'is_not_checked'
  | 'equals'
  | 'not_equals'
  | 'is_filled'
  | 'is_empty'

/**
 * The effect a {@link DependencyIn} has on its dependent field (R14.1).
 * Enforcement is **advisory** today (Documenso has no cross-field conditional
 * primitive), so a `require`-effect advisory dependency degrades the dependent
 * field to optional at signing time (R14.8). Mirrors the `DependencyEffect`
 * Literal in `app/modules/esignatures/schemas.py`.
 */
export type DependencyEffect = 'show' | 'require'

// ===========================================================================
// Request types — mirror RecipientIn / EnvelopeCreate
// ===========================================================================

/**
 * A recipient supplied when creating a send. `signing_role` defaults to
 * `signer` server-side when omitted. Mirrors `RecipientIn`.
 */
export interface RecipientIn {
  name: string
  /** Syntactically validated server-side before sending to Documenso (R4.2). */
  email: string
  signing_role?: SigningRole
  /**
   * Optional 1-based signing-order position (R15.3, R15.6). Used only when the
   * send's `signing_order_mode` is `sequential`; viewers carry no position but
   * remain on the document. Additive — omitted for parallel sends. Mirrors
   * `RecipientIn.order`.
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
 * Mirrors the Pydantic `FieldIn` in `app/modules/esignatures/schemas.py`
 * (type, page, recipient_index, position_x, position_y, width, height,
 * required, label?, placeholder?). The Pydantic constraints there are a
 * first-pass guard; the authoritative cross-field rules live in the server's
 * `validate_field_set`, which re-validates the whole set before any Documenso
 * call (R6.6).
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
   * (`dependent_client_id` / `trigger_client_id`, R14). Additive and optional:
   * sends without dependencies never need it. Mirrors `FieldIn.client_id`.
   */
  client_id?: string
}

/**
 * A conditional-field dependency carried alongside the Field_Set (R14). Records
 * that the `dependent_client_id` field's visibility/required state is governed
 * by the value of the `trigger_client_id` field (R14.1). Enforcement is
 * **advisory** today — Documenso has no cross-field conditional primitive — so
 * the dependency is stored for the sender's reference and a `require` effect
 * degrades the dependent field to optional at signing (R14.8). The
 * authoritative acyclicity / self-loop rules live in the pure dependency-graph
 * validator (R14.2, R14.4). Mirrors `DependencyIn`.
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
   * the existing single-signature auto-placement path unchanged (R8.3
   * fallback); when non-empty these fields are re-validated server-side and
   * created on the Documenso document via `field/create-many` before
   * distribute (R8.1).
   */
  fields?: FieldIn[]
  /**
   * Signing-order mode (R15.2). Defaults to `parallel` server-side so existing
   * callers are unaffected; `sequential` uses each recipient's `order`
   * position. Additive and backward-compatible. Mirrors
   * `EnvelopeCreate.signing_order_mode`.
   */
  signing_order_mode?: SigningOrderMode
  /**
   * Advisory conditional-field dependencies over the Field_Set (R14). Additive
   * and optional; re-checked for cycles/self-loops server-side before send.
   * Mirrors `EnvelopeCreate.dependencies`.
   */
  dependencies?: DependencyIn[]
}

/**
 * Body for `PUT /api/v2/esign/envelopes/{id}/fields` (edit-after-send, R13).
 * Unlike {@link EnvelopeCreate} the Field_Set is **required** (≥1 field) here:
 * an edit always replaces the whole set, and the server re-validates it with
 * the same rules as an initial send before atomically replacing the Documenso
 * fields (R13.3). `dependencies` is optional and re-checked for
 * cycles/self-loops. Mirrors `FieldSetReplace`.
 */
export interface FieldSetReplace {
  fields: FieldIn[]
  dependencies?: DependencyIn[]
}

/**
 * A single field stored on a Field_Template (R17.1). Carries
 * geometry/type/required/label/placeholder plus a `template_role` — an abstract
 * recipient slot (e.g. `signer 1`) rather than a specific person, so applying
 * the template maps each role to one of the current send's recipients without
 * ever storing a name or email. Mirrors `TemplateFieldIn`.
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
 * Org-scoped and durable; stores roles, never specific recipients. `roles` is
 * the set of distinct Template_Recipient_Role slots the template's fields refer
 * to, used at apply time to drive role→recipient mapping (R17.5, R17.6).
 * Mirrors `FieldTemplateCreate`.
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
 * Structurally satisfied by the editor's `PlacedField`
 * (`components/esign/fieldplacement/hooks/useFieldSet.ts`) so the modal can pass
 * its Field_Set straight in without an adapter, while keeping the API layer
 * free of a dependency on the component tree.
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
   * so a {@link DependencyIn} can reference this field by
   * `dependent_client_id` / `trigger_client_id` (R14). Structurally satisfied by
   * the editor's `PlacedField.clientId`; optional so dependency-free callers are
   * unaffected.
   */
  clientId?: string
}

/**
 * Map the editor's placed fields onto the wire `FieldIn[]`, resolving each
 * field's `recipientKey` to its recipient's **array index** in the send.
 *
 * `recipientKeyOrder` MUST be the stable keys of the send's recipients **in the
 * exact same order** they appear in the `EnvelopeCreate.recipients` array, so a
 * field's resolved `recipient_index` lines up with the recipient the backend
 * reconciles by email. The editor's client-side validation keeps send disabled
 * until every field references an existing recipient (R6.4), so a field whose
 * key is absent from the order is a programming error and throws rather than
 * silently misassigning.
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
    // Thread the stable per-field client id so advisory dependencies resolve to
    // this field on the wire (`dependent_client_id` / `trigger_client_id`, R14).
    if (field.clientId !== undefined) out.client_id = field.clientId
    return out
  })
}

/**
 * The minimal field-dependency shape this module needs to build a
 * {@link DependencyIn}. Structurally satisfied by the editor's `FieldDependency`
 * (`components/esign/lib/dependencyGraph.ts`) so the editor / modal can pass its
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
 * `trigger_client_id`, R14). The `value` operand is carried only when present
 * (the boolean/presence conditions don't use it). Acyclicity / self-loop rules
 * are enforced upstream by the pure dependency-graph core and re-checked
 * server-side (R14.2, R14.4); this is a pure shape mapping.
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
 * `EnvelopeOut`. `signed_document_url` is populated only when a signed
 * document has been stored (R11.5); it is an opaque, org-checked link served
 * by `GET /api/v2/esign/envelopes/{id}/signed-document`, never the bytes.
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
 * Humanized error shape (R16). `message` is always present; `code` is an
 * optional secondary machine-readable code. Mirrors `EsignError`.
 */
export interface EsignError {
  message: string
  code: string | null
}

/**
 * Result of listing envelopes. Always `{ items, total }`; `error` is present
 * only on the fail-closed filter path (HTTP 200 with empty items and a
 * humanized `filter_unavailable` error, R11.6).
 */
export interface EnvelopeListResult {
  items: EnvelopeOut[]
  total: number
  /** Set only when a requested `?status=` filter could not be applied. */
  error: EsignError | null
}

/**
 * A field read back from the Documenso document (edit-after-send, R13). Mirrors
 * {@link FieldIn} / `FieldOut` so the editor can be seeded from the live field
 * set via `GET …/fields` and re-submitted through {@link FieldSetReplace}.
 * Coordinates are normalized percent, origin top-left.
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
 * editor with the envelope's current Field_Set, its recipients (so fields can
 * be re-assigned), and the `editable` flag computed by the pure
 * `editable_state` gate (`status == 'sent'` AND no recipient has signed). When
 * `editable` is false the editor surfaces the Non_Editable_State banner and
 * offers Void_And_Recreate (R13.4). Mirrors `EnvelopeFieldsOut`.
 */
export interface EnvelopeFieldsOut {
  fields: FieldOut[]
  recipients: RecipientOut[]
  editable: boolean
}

/**
 * A persisted, org-scoped Field_Template (R17). Mirrors `FieldTemplateOut`.
 */
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
 * the backend `UploadFile` + `Form(...)` signature).
 *
 * Returns the freshly-created envelope (status `sent`); a freshly-sent
 * envelope never carries a `signed_document_url`.
 *
 * Errors surface as the standard humanized `{ message, code }` body:
 *   - 422 validation (non-PDF / no recipients / bad email),
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
      // Let the browser set the multipart boundary; override the client's
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
 * List the calling organisation's envelopes, newest-updated first (R11.4).
 * Always returns `{ items, total, error }`.
 *
 * Fail-closed filter (R11.6): when a requested `status` filter cannot be
 * applied the backend still responds HTTP 200 with **empty** items and a
 * humanized `filter_unavailable` error in the body — so the UI must show no
 * envelopes plus the error rather than an unfiltered list. That `error` is
 * surfaced here on `result.error`.
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
 * Return one envelope's detail: per-recipient signing status and, when a
 * signed document is stored, its org-checked `signed_document_url`. A missing
 * or cross-org envelope yields a humanized 404 (R13.4, R13.5).
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
 * status to `voided` (R7). A terminal envelope yields a humanized 409 and no
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
 * ready for browser download via an object URL (matching `api/ppsr.ts`
 * `exportPdf` and `api/payslips.ts` `downloadPayslipPdf`); the calling page
 * owns the `URL.createObjectURL` + anchor click.
 *
 * A 404 is returned when the envelope is missing / cross-org, or when no
 * signed document has been stored yet.
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
 * Read an envelope's current Field_Set, its recipients, and the pure
 * `editable` gate (`status == 'sent'` AND nobody has signed) so the editor can
 * be seeded for an in-place edit (R13.1). When `editable` is false the editor
 * surfaces the Non_Editable_State banner and offers Void_And_Recreate (R13.4).
 * A missing / cross-org envelope yields a humanized 404.
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
 * re-checks the Editable_State gate, re-validates the set with the same rules
 * as an initial send, then atomically replaces the Documenso fields (R13.3).
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
//
// Defined here ahead of the backend endpoints (added in task 21.1) so the
// editor's template picker can type its calls now. All four are org-scoped
// under RLS and guarded by the module gate + `require_esign_sender` (R17.3,
// R17.4, R17.7).
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
