/**
 * FieldPlacementEditor — the orchestrator for the in-app field-placement editor
 * (feature: esignature-field-placement, task 6.4).
 *
 * Composes the already-built pieces into the working editor surface:
 *
 *   - {@link usePdfDocument} + {@link PdfPageCanvas} — render every page of the
 *     selected PDF in the browser (R1.1, R1.2); a per-page loading indicator
 *     shows while a page rasterises (R1.3) and a render failure surfaces the
 *     `render_failed` banner and blocks the send (R1.4);
 *   - {@link FieldPalette} — the six field-type sources, as drag-to-add /
 *     tap-to-arm controls (R2.1);
 *   - {@link RecipientLegend} — the recipient colour key + active-recipient
 *     picker that decides which recipient a newly placed field is assigned to
 *     (R4.2, R4.4);
 *   - {@link FieldOverlay} — one draggable / resizable box per placed field,
 *     drawn in its recipient's colour (R3.2, R3.3, R4.4);
 *   - {@link FieldInspector} — the per-field property editor (recipient,
 *     required, text meta, delete; R4.3, R5.1, R5.2, R3.4);
 *   - {@link useFieldSet} — the pure Field_Set reducer holding all placement
 *     state, retained across in-editor page navigation (R11.1).
 *
 * Placement (R3.1)
 * ----------------
 * A field is placed two ways, both routed through the same `placeFieldAt`:
 *   - **drag-to-add** — the palette writes the chosen type onto the drag payload
 *     under {@link FIELD_TYPE_DRAG_MIME}; the per-page drop layer reads it and
 *     adds a field at the drop point;
 *   - **tap-to-arm** — tapping a palette control arms a type; the next tap on an
 *     empty area of a page places a field of the armed type there.
 * Both convert the drop/tap point from overlay CSS px → normalized via
 * {@link overlayToNormalized} against that page's dims; the reducer then clamps
 * the new field in-bounds and to ≥ min-size (R3.5, R3.6).
 *
 * Send control (R6.4 / R6.5)
 * --------------------------
 * The send control is enabled iff the client {@link validateFieldSet} passes,
 * no page failed to render (R1.4), the document is loaded, and no send is in
 * flight. It is disabled the instant the Field_Set becomes invalid and
 * re-enabled when every failure is corrected.
 *
 * Lifecycle (R11.2 / R11.4)
 * -------------------------
 * Cancel dispatches `reset` (discarding the in-progress Field_Set) and aborts
 * any in-flight send. A failed send keeps the Field_Set intact so the sender
 * can correct and retry. The actual network send is delegated to the `onSend`
 * prop (wired by `SendForSignatureModal` in task 13.2); this component owns the
 * abort/in-flight/error orchestration around it.
 *
 * The editor is self-contained: it accepts the selected PDF `file` and the
 * Send_Flow `recipients`, owns the selection / active-recipient / armed-type
 * state, and exposes the resulting Field_Set + validity to its parent through
 * `onFieldsChange` / `onValidityChange`.
 *
 * Edit-after-send (R13, task 16.7)
 * --------------------------------
 * When an optional `envelopeId` is supplied the editor opens in **edit mode**:
 * on mount it seeds the Field_Set from `GET /api/v2/esign/envelopes/{id}/fields`
 * (via {@link getEnvelopeFields}) — mapping each `FieldOut` to a `PlacedField`,
 * resolving `recipient_index` to a recipient through the fetched recipient
 * list, with fresh client ids — and derives its recipient list from that same
 * response (R13.1). The send control then submits the edited set via
 * `PUT …/fields` ({@link replaceEnvelopeFields}) instead of the create endpoint
 * (R13.3). When the GET (or a racing PUT) reports the envelope is **not
 * editable** (`editable === false` / a `not_editable` response), the editor
 * shows the Non_Editable_State banner explaining signing has begun / the
 * document is finished and offers **Void & recreate** — which voids the
 * envelope ({@link voidEnvelope}) and hands a copy of the read Field_Set back to
 * the parent so a fresh send can be pre-populated (R13.4, R13.5). All
 * consumption stays typed + AbortController-bound (R9.5). When no `envelopeId`
 * is supplied the create (send) flow is unchanged.
 *
 * _Requirements: 1.4, 3.1, 6.4, 6.5, 11.1, 11.2, 11.4, 13.1, 13.3, 13.4, 13.5_
 */

import {
  useCallback,
  useEffect,
  useLayoutEffect,
  useMemo,
  useRef,
  useState,
  type DragEvent,
  type MouseEvent,
} from 'react'
import { AlertBanner, Button } from '@/components/ui'
import {
  getEnvelopeFields as defaultGetEnvelopeFields,
  replaceEnvelopeFields as defaultReplaceEnvelopeFields,
  voidEnvelope as defaultVoidEnvelope,
  placedFieldsToFieldIns,
  fieldDependenciesToDependencyIns,
} from '@/api/esign'
import type {
  AgreementType,
  FieldOut,
  FieldSetReplace,
  RecipientOut,
  SigningRole,
} from '@/api/esign'

import usePdfDocument from './hooks/usePdfDocument'
import { useFieldSet, FIELD_TYPES, type FieldType, type PlacedField } from './hooks/useFieldSet'
import PdfPageCanvas from './PdfPageCanvas'
import FieldOverlay from './FieldOverlay'
import FieldPalette, { FIELD_TYPE_DRAG_MIME } from './FieldPalette'
import RecipientLegend, { type LegendRecipient } from './RecipientLegend'
import FieldInspector, { type InspectorRecipient } from './FieldInspector'
import DependencyInspector from './DependencyInspector'
import TemplateControls from './TemplateControls'
import type { FieldDependency } from '../lib/dependencyGraph'
import {
  overlayToNormalized,
  type OverlayRect,
  type PageDims,
} from './lib/coordinateMapping'
import { validateFieldSet, type FieldValidationRecipient } from './lib/fieldValidation'

/**
 * A recipient as the editor needs it: the SendForSignatureModal recipient row
 * shape (a stable `key`, name/email, and signing role). A field's
 * `recipientKey` references `key` (R4.1); a recipient's colour is derived from
 * its **index** in this list (R4.4), so the order matters and must be stable.
 */
export interface FieldPlacementEditorRecipient {
  /** Stable key referenced by a placed field's `recipientKey` (R4.1). */
  key: number
  /** Display name; falls back to email then a generic label. */
  name?: string
  /** Email; used as a name fallback. */
  email?: string
  /** Signer recipients require ≥1 signature field; viewers are exempt (R4.6). */
  signing_role: SigningRole
}

export interface FieldPlacementEditorProps {
  /** The PDF the Org_Sender selected in step 1 of the Send_Flow. */
  file: File | null
  /** The Send_Flow recipient list, in order (drives colours + assignment). */
  recipients: readonly FieldPlacementEditorRecipient[]
  /**
   * Optional agreement-type of the current send (R17.2). Stored on a template
   * saved from the editor; purely advisory metadata, so it is fine to omit.
   */
  agreementType?: AgreementType
  /**
   * Optional create-mode seed: pre-populate the Field_Set when the editor opens
   * in create mode (used by Void & recreate to carry a copy of a voided
   * envelope's fields into a fresh send, R13.5). Seeded once on mount; ignored
   * in edit mode (which seeds from `GET …/fields` instead). Each field's
   * `recipientKey` must reference a recipient in `recipients`.
   */
  initialFields?: readonly PlacedField[]
  /**
   * Edit-after-send (R13). When supplied, the editor opens in **edit mode**:
   * it seeds the Field_Set + recipients from `GET …/fields`, submits via
   * `PUT …/fields`, and (when the envelope is no longer editable) surfaces the
   * Non_Editable_State banner + Void & recreate. Omit for the create flow.
   */
  envelopeId?: string
  /**
   * Perform the actual send with the placed Field_Set. The editor owns the
   * abort/in-flight/error orchestration; the parent (SendForSignatureModal,
   * task 13.2) maps the Field_Set to the wire payload and calls the API. A
   * rejection (other than an abort) is surfaced inline and the Field_Set is
   * retained for retry (R11.4). On success the parent typically closes.
   *
   * Used only in **create mode**; edit mode submits via `PUT …/fields`.
   */
  onSend?: (fields: PlacedField[], signal: AbortSignal) => Promise<void>
  /** Called after the editor discards its Field_Set and aborts any send (R11.2). */
  onCancel?: () => void
  /** Notified whenever the Field_Set's client-side validity changes (R6.4/R6.5). */
  onValidityChange?: (valid: boolean) => void
  /** Notified whenever the placed Field_Set changes (so the parent can mirror it). */
  onFieldsChange?: (fields: PlacedField[]) => void
  /**
   * Notified whenever the advisory dependency set changes (R14). The parent
   * (SendForSignatureModal) mirrors it and attaches it to the create payload as
   * `dependencies[]` in create mode; in edit mode the editor threads it onto the
   * `PUT …/fields` body itself.
   */
  onDependenciesChange?: (dependencies: FieldDependency[]) => void
  /**
   * Edit mode only: called after an edited Field_Set is successfully replaced
   * via `PUT …/fields` (R13.3), with the field set read back from Documenso.
   */
  onEdited?: (fields: FieldOut[]) => void
  /**
   * Edit mode only: called after the envelope is voided through Void & recreate
   * (R13.5), with a copy of the read Field_Set and its recipients so the parent
   * can open a fresh send pre-populated with them before confirmation.
   */
  onVoidAndRecreate?: (seed: {
    fields: PlacedField[]
    recipients: FieldPlacementEditorRecipient[]
  }) => void
  /** Injectable `GET …/fields` (defaults to the real client) — for testing. */
  getEnvelopeFieldsFn?: typeof defaultGetEnvelopeFields
  /** Injectable `PUT …/fields` (defaults to the real client) — for testing. */
  replaceEnvelopeFieldsFn?: typeof defaultReplaceEnvelopeFields
  /** Injectable void call (defaults to the real client) — for testing. */
  voidEnvelopeFn?: typeof defaultVoidEnvelope
  /** Extra classes for the container. */
  className?: string
}

/** Default size of a newly-dropped field, in overlay CSS px (reducer clamps it). */
const DEFAULT_FIELD_WIDTH_PX = 140
const DEFAULT_FIELD_HEIGHT_PX = 44

/** The supported field types as a fast membership set (guards drag payloads). */
const FIELD_TYPE_SET: ReadonlySet<string> = new Set(FIELD_TYPES)

function isFieldType(value: string): value is FieldType {
  return FIELD_TYPE_SET.has(value)
}

/** Best-effort display name: name → email → "Recipient N". */
function recipientDisplayName(recipient: FieldPlacementEditorRecipient, index: number): string {
  if (recipient.name && recipient.name.trim()) return recipient.name.trim()
  if (recipient.email && recipient.email.trim()) return recipient.email.trim()
  return `Recipient ${index + 1}`
}

/** True when the thrown value is an aborted-request signal (ignore it). */
function isAbortError(err: unknown): boolean {
  const name = (err as { name?: string })?.name
  const code = (err as { code?: string })?.code
  return name === 'AbortError' || name === 'CanceledError' || code === 'ERR_CANCELED'
}

/**
 * Coerce a thrown value into a humanized, leak-free message (R12). The send
 * endpoint returns `{ message, code }` (optionally under FastAPI's `detail`);
 * raw DB / exception text is never leaked server-side, so the fallback is safe.
 */
function extractSendMessage(err: unknown): string {
  const data = (err as { response?: { data?: unknown } })?.response?.data
  if (data && typeof data === 'object') {
    const obj = data as Record<string, unknown>
    if (typeof obj.message === 'string' && obj.message.trim()) return obj.message
    const detail = obj.detail
    if (detail && typeof detail === 'object') {
      const d = detail as Record<string, unknown>
      if (typeof d.message === 'string' && d.message.trim()) return d.message
    }
    if (typeof detail === 'string' && detail.trim()) return detail
  }
  return 'Something went wrong sending this document for signature. Please try again.'
}

/**
 * Extract the optional machine-readable `code` from a thrown error's
 * `{ message, code }` body (optionally under FastAPI's `detail`). Used to spot
 * a racing `not_editable` response on a `PUT …/fields` edit (R13.4).
 */
function extractErrorCode(err: unknown): string | null {
  const data = (err as { response?: { data?: unknown } })?.response?.data
  if (data && typeof data === 'object') {
    const obj = data as Record<string, unknown>
    if (typeof obj.code === 'string' && obj.code) return obj.code
    const detail = obj.detail
    if (detail && typeof detail === 'object') {
      const d = detail as Record<string, unknown>
      if (typeof d.code === 'string' && d.code) return d.code
    }
  }
  return null
}

/**
 * Map a persisted recipient's stored UPPERCASE Documenso role (`SIGNER` /
 * `VIEWER`) back to the lowercase {@link SigningRole} the editor works in.
 * Anything that isn't a viewer is treated as a signer (the send-blocking
 * "≥1 signature per signer" rule errs safe).
 */
function toSigningRole(stored: string | null | undefined): SigningRole {
  return (stored ?? '').toUpperCase() === 'VIEWER' ? 'viewer' : 'signer'
}

/**
 * Map the recipients read back from an envelope into the editor's recipient
 * shape, keying each by its **array index** so a `FieldOut.recipient_index`
 * resolves straight to a `recipientKey` (R13.1).
 */
function editRecipientsFrom(
  recipients: readonly RecipientOut[],
): FieldPlacementEditorRecipient[] {
  return recipients.map((r, index) => ({
    key: index,
    name: r.name,
    email: r.email,
    signing_role: toSigningRole(r.signing_role),
  }))
}

export function FieldPlacementEditor({
  file,
  recipients,
  agreementType,
  initialFields,
  envelopeId,
  onSend,
  onCancel,
  onValidityChange,
  onFieldsChange,
  onDependenciesChange,
  onEdited,
  onVoidAndRecreate,
  getEnvelopeFieldsFn = defaultGetEnvelopeFields,
  replaceEnvelopeFieldsFn = defaultReplaceEnvelopeFields,
  voidEnvelopeFn = defaultVoidEnvelope,
  className,
}: FieldPlacementEditorProps) {
  const isEditMode = envelopeId != null && envelopeId !== ''
  // ── Available width → responsive render scale ──────────────────────────
  const pageColumnRef = useRef<HTMLDivElement | null>(null)
  const [availableWidth, setAvailableWidth] = useState<number | undefined>(undefined)

  useLayoutEffect(() => {
    const el = pageColumnRef.current
    if (!el) return
    const measure = () => setAvailableWidth(el.clientWidth)
    measure()
    if (typeof ResizeObserver === 'undefined') return
    const ro = new ResizeObserver(() => measure())
    ro.observe(el)
    return () => ro.disconnect()
  }, [])

  // ── Document + Field_Set ───────────────────────────────────────────────
  const { pdf, pages, loading, error, hasRenderError, setPageStatus } = usePdfDocument(file, {
    availableWidth,
  })
  const {
    fields,
    addField,
    moveField,
    resizeField,
    assignField,
    setRequired,
    setTextMeta,
    deleteField,
    removeRecipient,
    seedFields,
    reset,
  } = useFieldSet()

  // ── Editor-owned interaction state ─────────────────────────────────────
  const [armedType, setArmedType] = useState<FieldType | null>(null)
  const [activeRecipientKey, setActiveRecipientKey] = useState<number | null>(null)
  const [selectedClientId, setSelectedClientId] = useState<string | null>(null)
  const [sending, setSending] = useState(false)
  const [sendError, setSendError] = useState<string | null>(null)

  // ── Advisory conditional-field dependencies (R14) ───────────────────────
  // The editor holds the FieldDependency[]; DependencyInspector adds (already
  // self-loop/cycle-checked via the pure `addDependency` against this set) and
  // removes by index. The set is threaded onto the wire as `dependencies[]`
  // (create payload / `PUT …/fields`) and mirrored to the parent for create
  // mode via `onDependenciesChange`. Enforcement is advisory (R14.7).
  const [dependencies, setDependencies] = useState<FieldDependency[]>([])

  // ── Edit-after-send state (R13) ────────────────────────────────────────
  // In edit mode the editor seeds itself + its recipient list from the
  // envelope's current Documenso fields; `editable === false` flips it into the
  // Non_Editable_State (banner + Void & recreate).
  const [editRecipients, setEditRecipients] = useState<FieldPlacementEditorRecipient[]>([])
  const [editable, setEditable] = useState(true)
  const [editLoading, setEditLoading] = useState(isEditMode)
  const [editLoadError, setEditLoadError] = useState<string | null>(null)
  const [voiding, setVoiding] = useState(false)

  const abortRef = useRef<AbortController | null>(null)

  // The recipient list the editor actually works against: the fetched list in
  // edit mode, the prop list in create mode.
  const effectiveRecipients = isEditMode ? editRecipients : recipients

  // ── Recipient lookups (index drives colour; key is the field reference) ─
  const recipientIndexByKey = useMemo(() => {
    const map = new Map<number, number>()
    effectiveRecipients.forEach((r, index) => map.set(r.key, index))
    return map
  }, [effectiveRecipients])

  const legendRecipients = useMemo<LegendRecipient[]>(
    () =>
      effectiveRecipients.map((r) => ({
        key: r.key,
        name: r.name,
        email: r.email,
        signing_role: r.signing_role,
      })),
    [effectiveRecipients],
  )

  const inspectorRecipients = useMemo<InspectorRecipient[]>(
    () =>
      effectiveRecipients.map((r, index) => ({ key: r.key, name: recipientDisplayName(r, index) })),
    [effectiveRecipients],
  )

  const validationRecipients = useMemo<FieldValidationRecipient[]>(
    () =>
      effectiveRecipients.map((r) => ({
        key: r.key,
        signing_role: r.signing_role,
        name: r.name,
        email: r.email,
      })),
    [effectiveRecipients],
  )

  // ── Keep the active recipient valid (default to first; follow removals) ──
  useEffect(() => {
    const keys = effectiveRecipients.map((r) => r.key)
    if (activeRecipientKey == null || !keys.includes(activeRecipientKey)) {
      setActiveRecipientKey(keys[0] ?? null)
    }
  }, [effectiveRecipients, activeRecipientKey])

  // ── Cascade-delete a recipient's fields when it leaves the Send_Flow (R4.5) ─
  const prevRecipientKeysRef = useRef<number[]>(effectiveRecipients.map((r) => r.key))
  useEffect(() => {
    const currentKeys = effectiveRecipients.map((r) => r.key)
    const removed = prevRecipientKeysRef.current.filter((k) => !currentKeys.includes(k))
    for (const key of removed) removeRecipient(key)
    prevRecipientKeysRef.current = currentKeys
  }, [effectiveRecipients, removeRecipient])

  // ── Client-side validation drives the send control (R6.4 / R6.5) ────────
  const validation = useMemo(
    () => validateFieldSet(fields, validationRecipients),
    [fields, validationRecipients],
  )

  // Surface validity + the Field_Set to the parent.
  useEffect(() => {
    onValidityChange?.(validation.ok)
  }, [validation.ok, onValidityChange])

  useEffect(() => {
    onFieldsChange?.(fields)
  }, [fields, onFieldsChange])

  // ── Keep dependencies consistent with the live Field_Set (R14) ──────────
  // A dependency references fields by their stable client id; if a field is
  // deleted (or cascade-removed with its recipient) any dependency that points
  // at it is dropped so no dangling reference is ever sent to the server.
  useEffect(() => {
    setDependencies((prev) => {
      const liveIds = new Set(fields.map((f) => f.clientId))
      const pruned = prev.filter(
        (dep) => liveIds.has(dep.dependentClientId) && liveIds.has(dep.triggerClientId),
      )
      return pruned.length === prev.length ? prev : pruned
    })
  }, [fields])

  // Mirror the advisory dependency set to the parent (create-mode payload, R14).
  useEffect(() => {
    onDependenciesChange?.(dependencies)
  }, [dependencies, onDependenciesChange])

  // ── Dependency add/remove (DependencyInspector already self-loop/cycle-checks) ─
  const handleAddDependency = useCallback((dependency: FieldDependency) => {
    setDependencies((prev) => [...prev, dependency])
  }, [])

  const handleRemoveDependency = useCallback((index: number) => {
    setDependencies((prev) => prev.filter((_, i) => i !== index))
  }, [])

  // ── Apply a saved template into the editor (R17.5) ──────────────────────
  // Replace the whole Field_Set with the template's role-mapped placed fields.
  // Fresh client ids are assigned by the reducer (we strip the applier's ids),
  // dependencies/selection are cleared, and the applied set then flows through
  // the same `validateFieldSet` as any hand-placed set before send (R17.8).
  const handleApplyTemplate = useCallback(
    (applied: PlacedField[]) => {
      seedFields(applied.map(({ clientId: _clientId, ...rest }) => rest))
      setDependencies([])
      setSelectedClientId(null)
      setArmedType(null)
    },
    [seedFields],
  )

  // Abort any in-flight send on unmount (R11.2).
  useEffect(() => () => abortRef.current?.abort(), [])

  // ── Edit mode: seed the Field_Set + recipients from the live envelope (R13.1) ─
  useEffect(() => {
    if (!isEditMode || !envelopeId) return
    const controller = new AbortController()
    setEditLoading(true)
    setEditLoadError(null)
    getEnvelopeFieldsFn(envelopeId, controller.signal)
      .then((res) => {
        if (controller.signal.aborted) return
        const recs = editRecipientsFrom(res.recipients)
        setEditRecipients(recs)
        setEditable(res.editable)
        // Map each read FieldOut → a PlacedField input (fresh client ids are
        // generated by seedFields). `recipient_index` resolves to a recipientKey
        // (== array index); an out-of-range index falls back to the first.
        seedFields(
          res.fields.map((f) => ({
            type: f.type,
            page: f.page,
            rect: {
              positionX: f.position_x,
              positionY: f.position_y,
              width: f.width,
              height: f.height,
            },
            recipientKey:
              f.recipient_index >= 0 && f.recipient_index < recs.length
                ? recs[f.recipient_index].key
                : (recs[0]?.key ?? 0),
            required: f.required,
            label: f.label,
            placeholder: f.placeholder,
          })),
        )
        setEditLoading(false)
      })
      .catch((err: unknown) => {
        if (controller.signal.aborted || isAbortError(err)) return
        setEditLoadError(extractSendMessage(err))
        setEditLoading(false)
      })
    return () => controller.abort()
  }, [isEditMode, envelopeId, getEnvelopeFieldsFn, seedFields])

  // ── Create mode: optional one-time seed (Void & recreate carry-over, R13.5) ─
  const seededFromInitialRef = useRef(false)
  useEffect(() => {
    if (isEditMode || seededFromInitialRef.current) return
    if (initialFields && initialFields.length > 0) {
      seededFromInitialRef.current = true
      // Strip the incoming client ids so the reducer assigns fresh ones.
      seedFields(initialFields.map(({ clientId: _clientId, ...rest }) => rest))
    }
  }, [isEditMode, initialFields, seedFields])

  // The Non_Editable_State is active once an edit-mode load reports the envelope
  // can no longer be edited (signing begun / terminal) — or a racing PUT does.
  const notEditable = isEditMode && !editable

  const selectedField = useMemo(
    () => fields.find((f) => f.clientId === selectedClientId) ?? null,
    [fields, selectedClientId],
  )

  const editingDisabled = !pdf || hasRenderError || notEditable || editLoading

  // ── Palette arming (tap-to-arm; tapping the armed type disarms it) ───────
  const handleArm = useCallback((type: FieldType) => {
    setArmedType((prev) => (prev === type ? null : type))
  }, [])

  // ── Place a field at an overlay point on a page (drag drop OR armed tap) ─
  const placeFieldAt = useCallback(
    (type: FieldType, page: number, dims: PageDims, clientX: number, clientY: number, layer: HTMLElement) => {
      if (activeRecipientKey == null) return
      const bounds = layer.getBoundingClientRect()
      // Centre the new field on the drop/tap point; the reducer clamps it.
      const overlay: OverlayRect = {
        xPx: clientX - bounds.left - DEFAULT_FIELD_WIDTH_PX / 2,
        yPx: clientY - bounds.top - DEFAULT_FIELD_HEIGHT_PX / 2,
        wPx: DEFAULT_FIELD_WIDTH_PX,
        hPx: DEFAULT_FIELD_HEIGHT_PX,
      }
      const rect = overlayToNormalized(overlay, dims)
      const clientId = addField({ type, page, rect, recipientKey: activeRecipientKey, dims })
      setSelectedClientId(clientId)
    },
    [activeRecipientKey, addField],
  )

  const handleDrop = useCallback(
    (e: DragEvent<HTMLDivElement>, page: number, dims: PageDims) => {
      const raw = e.dataTransfer.getData(FIELD_TYPE_DRAG_MIME)
      if (!raw || !isFieldType(raw)) return
      e.preventDefault()
      placeFieldAt(raw, page, dims, e.clientX, e.clientY, e.currentTarget)
    },
    [placeFieldAt],
  )

  const handleDragOver = useCallback((e: DragEvent<HTMLDivElement>) => {
    // Allow the drop and show the copy cursor (R3.1).
    if (e.dataTransfer.types.includes(FIELD_TYPE_DRAG_MIME)) {
      e.preventDefault()
      e.dataTransfer.dropEffect = 'copy'
    }
  }, [])

  const handleLayerClick = useCallback(
    (e: MouseEvent<HTMLDivElement>, page: number, dims: PageDims) => {
      // Only react to clicks on the empty page area, never on a child field box.
      if (e.target !== e.currentTarget) return
      if (armedType) {
        placeFieldAt(armedType, page, dims, e.clientX, e.clientY, e.currentTarget)
      } else {
        setSelectedClientId(null)
      }
    },
    [armedType, placeFieldAt],
  )

  // ── Send / cancel orchestration (R11.2 / R11.4) ─────────────────────────
  const canSend =
    !!pdf && !hasRenderError && !loading && !sending && !voiding && validation.ok && !notEditable

  const handleSend = useCallback(async () => {
    if (sending || !canSend) return
    // Create mode needs an `onSend` delegate; edit mode submits via PUT itself.
    if (!isEditMode && !onSend) return
    setSendError(null)

    abortRef.current?.abort()
    const controller = new AbortController()
    abortRef.current = controller

    setSending(true)
    try {
      if (isEditMode && envelopeId) {
        // Edit mode: replace the whole Field_Set via PUT …/fields (R13.3).
        const recipientKeyOrder = effectiveRecipients.map((r) => r.key)
        const body: FieldSetReplace = {
          fields: placedFieldsToFieldIns(fields, recipientKeyOrder),
          ...(dependencies.length > 0
            ? { dependencies: fieldDependenciesToDependencyIns(dependencies) }
            : {}),
        }
        const result = await replaceEnvelopeFieldsFn(envelopeId, body, controller.signal)
        if (controller.signal.aborted) return
        onEdited?.(result)
      } else if (onSend) {
        await onSend(fields, controller.signal)
      }
      // Success: leave the parent to close / advance. The Field_Set is not
      // reset here so a parent that keeps the editor mounted still has it.
    } catch (err: unknown) {
      if (controller.signal.aborted || isAbortError(err)) return
      // A racing edit can come back `not_editable` (someone signed meanwhile):
      // flip into the Non_Editable_State so the banner + Void & recreate show
      // (R13.4). Otherwise surface the humanized error and retain the set (R11.4).
      if (isEditMode && extractErrorCode(err) === 'not_editable') {
        setEditable(false)
      }
      setSendError(extractSendMessage(err))
    } finally {
      if (!controller.signal.aborted) setSending(false)
    }
  }, [
    onSend,
    sending,
    canSend,
    fields,
    dependencies,
    isEditMode,
    envelopeId,
    effectiveRecipients,
    replaceEnvelopeFieldsFn,
    onEdited,
  ])

  // ── Void & recreate (R13.5) — the Non_Editable_State escape hatch ───────
  const handleVoidAndRecreate = useCallback(async () => {
    if (!isEditMode || !envelopeId || voiding) return
    setSendError(null)

    abortRef.current?.abort()
    const controller = new AbortController()
    abortRef.current = controller

    setVoiding(true)
    try {
      await voidEnvelopeFn(envelopeId, controller.signal)
      if (controller.signal.aborted) return
      // Hand the parent a copy of the read Field_Set + recipients so it can open
      // a fresh send pre-populated with them for editing before confirmation.
      onVoidAndRecreate?.({
        fields: fields.map((f) => ({ ...f })),
        recipients: effectiveRecipients.map((r) => ({ ...r })),
      })
    } catch (err: unknown) {
      if (controller.signal.aborted || isAbortError(err)) return
      setSendError(extractSendMessage(err))
    } finally {
      if (!controller.signal.aborted) setVoiding(false)
    }
  }, [isEditMode, envelopeId, voiding, voidEnvelopeFn, onVoidAndRecreate, fields, effectiveRecipients])

  const handleCancel = useCallback(() => {
    // Abort any in-flight send and discard the in-progress Field_Set (R11.2).
    abortRef.current?.abort()
    reset()
    setDependencies([])
    setSelectedClientId(null)
    setArmedType(null)
    setSendError(null)
    setSending(false)
    onCancel?.()
  }, [reset, onCancel])

  // ── Field-set issue list for the inline guidance panel ──────────────────
  const issueMessages = useMemo(
    () => Array.from(new Set(validation.issues.map((i) => i.message))),
    [validation.issues],
  )

  return (
    <div
      className={['flex flex-col gap-3', className].filter(Boolean).join(' ')}
      data-testid="field-placement-editor"
    >
      {/* ── Render failure blocks the send (R1.4) ───────────────────────── */}
      {hasRenderError && (
        <AlertBanner variant="error">
          <span data-testid="render-failed">
            This document couldn’t be displayed for field placement. Choose a different PDF and try
            again.
          </span>
        </AlertBanner>
      )}

      {/* ── Non_Editable_State: signing begun / finished (R13.4 / R13.5) ── */}
      {notEditable && (
        <AlertBanner variant="warning">
          <div className="flex flex-col gap-2">
            <span data-testid="non-editable-banner">
              This document can no longer be edited because signing has begun or the document is
              finished. To change the fields, void it and send a new copy.
            </span>
            <div>
              <Button
                size="sm"
                variant="ghost"
                onClick={() => void handleVoidAndRecreate()}
                loading={voiding}
                data-testid="void-and-recreate"
              >
                Void &amp; recreate
              </Button>
            </div>
          </div>
        </AlertBanner>
      )}

      {/* ── Edit-mode load failure ──────────────────────────────────────── */}
      {editLoadError && !notEditable && (
        <AlertBanner variant="error" onDismiss={() => setEditLoadError(null)}>
          <span data-testid="edit-load-error">{editLoadError}</span>
        </AlertBanner>
      )}

      {/* ── Send failure (retained Field_Set, R11.4) ────────────────────── */}
      {sendError && (
        <AlertBanner variant="error" onDismiss={() => setSendError(null)}>
          <span data-testid="send-error">{sendError}</span>
        </AlertBanner>
      )}

      {/* ── Advisory conditional-rules notice — visible whenever any
              dependency exists, regardless of the current selection (R14.7). ── */}
      {dependencies.length > 0 && (
        <AlertBanner variant="warning">
          <span data-testid="dependency-advisory-banner">
            Conditional rules are recorded with this document but are{' '}
            <strong>not enforced</strong> during signing — every field is shown to the recipient,
            and a “require” rule is treated as optional.
          </span>
        </AlertBanner>
      )}

      <div className="flex flex-col gap-4 lg:flex-row">
        {/* ── Left rail: palette + recipient legend ─────────────────────── */}
        <aside className="flex shrink-0 flex-col gap-5 lg:w-56">
          <FieldPalette armedType={armedType} onArm={handleArm} disabled={editingDisabled} />
          <RecipientLegend
            recipients={legendRecipients}
            activeRecipientKey={activeRecipientKey}
            onSelectRecipient={setActiveRecipientKey}
            disabled={editingDisabled}
          />
          {/* Saved field templates: save the current set (roles, never people)
              and apply a template by mapping its roles to recipients (R17). */}
          <TemplateControls
            fields={fields}
            recipients={effectiveRecipients}
            agreementType={agreementType}
            disabled={editingDisabled}
            onApply={handleApplyTemplate}
          />
        </aside>

        {/* ── Centre: the rendered page list with field overlays ────────── */}
        <div
          ref={pageColumnRef}
          className="flex min-w-0 flex-1 flex-col items-center gap-4 overflow-auto rounded-ctl bg-canvas-2 p-4"
          data-testid="page-column"
        >
          {(loading || editLoading) && (
            <div
              role="status"
              aria-live="polite"
              data-testid="doc-loading"
              className="py-10 text-[13px] text-muted"
            >
              {editLoading ? 'Loading fields…' : 'Loading document…'}
            </div>
          )}

          {error && !loading && (
            <p className="py-10 text-[13px] text-muted" data-testid="doc-error">
              The document couldn’t be displayed.
            </p>
          )}

          {pdf &&
            pages.map((page) => {
              const dims: PageDims = { cssWidth: page.cssWidth, cssHeight: page.cssHeight }
              const pageFields = fields.filter((f) => f.page === page.pageNumber)
              return (
                <PdfPageCanvas
                  key={page.pageNumber}
                  pdf={pdf}
                  page={page}
                  setPageStatus={setPageStatus}
                >
                  {/* Per-page overlay/drop layer: accepts palette drops + armed
                      taps and hosts this page's field boxes (R3.1). */}
                  <div
                    className="absolute inset-0"
                    data-testid={`drop-layer-${page.pageNumber}`}
                    onDragOver={handleDragOver}
                    onDrop={(e) => handleDrop(e, page.pageNumber, dims)}
                    onClick={(e) => handleLayerClick(e, page.pageNumber, dims)}
                    style={{ cursor: armedType ? 'copy' : 'default' }}
                  >
                    {pageFields.map((field) => {
                      const index = recipientIndexByKey.get(field.recipientKey) ?? 0
                      const recipient = effectiveRecipients[index]
                      return (
                        <FieldOverlay
                          key={field.clientId}
                          field={field}
                          dims={dims}
                          selected={field.clientId === selectedClientId}
                          recipient={{
                            index,
                            name: recipient?.name,
                            email: recipient?.email,
                          }}
                          onSelect={() => setSelectedClientId(field.clientId)}
                          onMove={(rect) => moveField(field.clientId, rect, dims)}
                          onResize={(rect) => resizeField(field.clientId, rect, dims)}
                          onDelete={() => {
                            deleteField(field.clientId)
                            setSelectedClientId((cur) => (cur === field.clientId ? null : cur))
                          }}
                        />
                      )
                    })}
                  </div>
                </PdfPageCanvas>
              )
            })}
        </div>

        {/* ── Right rail: the selected-field inspector + conditional rules ── */}
        <aside className="flex shrink-0 flex-col gap-4 lg:w-64">
          <FieldInspector
            field={selectedField}
            recipients={inspectorRecipients}
            onAssign={assignField}
            onSetRequired={setRequired}
            onSetTextMeta={setTextMeta}
            onDelete={(clientId) => {
              deleteField(clientId)
              setSelectedClientId((cur) => (cur === clientId ? null : cur))
            }}
          />
          {/* Advisory conditional / dependent fields (R14.1, R14.7). */}
          <DependencyInspector
            field={selectedField}
            fields={fields}
            dependencies={dependencies}
            onAddDependency={handleAddDependency}
            onRemoveDependency={handleRemoveDependency}
          />
        </aside>
      </div>

      {/* ── Validation guidance + send/cancel actions ───────────────────── */}
      {!validation.ok && issueMessages.length > 0 && !hasRenderError && !notEditable && (
        <div
          className="rounded-ctl border border-border bg-card p-3"
          data-testid="validation-issues"
        >
          <p className="mb-1 text-[12.5px] font-medium text-text">
            Finish these before sending:
          </p>
          <ul className="list-disc pl-5 text-[12.5px] text-muted">
            {issueMessages.map((message, i) => (
              <li key={i}>{message}</li>
            ))}
          </ul>
        </div>
      )}

      <div className="flex items-center justify-end gap-3 border-t border-border pt-4">
        <Button variant="ghost" onClick={handleCancel} disabled={sending}>
          Cancel
        </Button>
        <Button
          onClick={() => void handleSend()}
          loading={sending}
          disabled={!canSend}
          data-testid="send-for-signature"
        >
          {isEditMode ? 'Save changes' : 'Send for signature'}
        </Button>
      </div>
    </div>
  )
}

export default FieldPlacementEditor
