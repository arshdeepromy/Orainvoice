import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { AlertBanner, Button, FormField, Input, Modal, Select } from '@/components/ui'
import {
  AGREEMENT_TYPES,
  createEnvelope as defaultCreateEnvelope,
  placedFieldsToFieldIns,
  fieldDependenciesToDependencyIns,
} from '@/api/esign'
import type {
  AgreementType,
  EnvelopeCreate,
  EnvelopeOut,
  OriginatingEntityType,
  RecipientIn,
  SigningOrderMode,
  SigningRole,
} from '@/api/esign'
import SigningOrderControls, {
  reconcileSignerOrder,
  signingPositionByKey,
} from './SigningOrderControls'
import {
  FieldPlacementEditor,
  type FieldPlacementEditorRecipient,
} from './fieldplacement/FieldPlacementEditor'
import type { PlacedField } from './fieldplacement/hooks/useFieldSet'
import type { FieldDependency } from './lib/dependencyGraph'

/**
 * SendForSignatureModal — reusable "Send for signature" composer, now a
 * **two-step flow** (feature: esignature-field-placement, task 13.2; built on
 * esignature-integration task 17.1).
 *
 * Step 1 — Compose
 * ----------------
 * The existing surface-agnostic composer: pick / confirm a PDF, choose an
 * `agreement_type`, and add ≥1 recipient (name, email, `signing_role`). The
 * caller supplies the originating entity context as props so the resulting
 * envelope is pre-bound to that invoice / quote / staff member (R10.3 / R10.4
 * of esignature-integration). The primary action is now **Continue to field
 * placement**: it validates step 1 and, on success, advances to step 2.
 *
 * Step 2 — Place fields
 * ---------------------
 * Mounts {@link FieldPlacementEditor} with the selected PDF and the step-1
 * recipient list. The Org_Sender renders every page in-browser and places /
 * assigns / types / sizes the fields (R1, R2, R3, R4, R5). The **send happens
 * at the end of step 2** so the sender-defined Field_Set travels with it: the
 * editor's `onSend` maps the placed fields to the wire `FieldIn[]` via
 * {@link placedFieldsToFieldIns} and POSTs the existing multipart create
 * (`createEnvelope`) with `fields` attached (R8.1). The PDF is rendered only in
 * the browser and is never sent to Documenso before this confirm (R1.6); the
 * Documenso UI is never exposed to org users (R9.4).
 *
 * Lifecycle (R11)
 * ---------------
 * The editor owns the in-flight/abort/error orchestration around `onSend`:
 *   - Cancel discards the in-progress Field_Set and aborts any in-flight send
 *     (R11.2); here Cancel closes the whole Send_Flow.
 *   - Reopening the modal starts from step 1 with an empty Field_Set (R11.3):
 *     closing unmounts the editor and `resetForm` rewinds to step 1.
 *   - A failed send retains the Field_Set so the sender can correct and retry
 *     (R11.4) — the editor keeps its state and surfaces the humanized error.
 *
 * Safe consumption + testability:
 *   - controlled `open` / `onClose`,
 *   - the API call is injectable via `createEnvelopeFn` (defaults to the real
 *     client) so tests can drive happy / error paths without a network,
 *   - typed throughout (no `as any`), and the in-flight request is bound to an
 *     `AbortController` (owned by the editor) aborted on unmount / cancel.
 *
 * _Requirements: 9.4, 11.2, 11.3, 11.4 (and esignature-integration 3.6, 4.1,
 * 10.3, 10.4, 16.1)_
 */

export interface SendForSignatureModalProps {
  /** Controlled open state. */
  open: boolean
  /** Called when the user dismisses the modal (Cancel / × / after success). */
  onClose: () => void
  /** The originating entity the envelope is pre-bound to (R10.3 / R10.4). */
  originatingEntityType: OriginatingEntityType
  /** The originating entity id. */
  originatingEntityId: string
  /**
   * Called with the freshly-created envelope on a successful send, before the
   * modal closes — so the caller can refresh its surface / show a toast.
   */
  onSent?: (envelope: EnvelopeOut) => void
  /**
   * Edit-after-send (R13). When supplied, the modal opens in **edit mode** for
   * this envelope: step 2 mounts {@link FieldPlacementEditor} with the
   * `envelopeId` so it seeds from / submits to `…/fields`. Step 1 is reduced to
   * re-selecting the document to render for placement (recipients + fields come
   * from the live envelope). Omit for the normal create flow.
   */
  editEnvelopeId?: string
  /** Called after an edited Field_Set is saved (edit mode), before the modal closes. */
  onEdited?: () => void
  /**
   * Optionally constrain the agreement types offered. When omitted, a sensible
   * subset is derived from the entity type (staff → nda / employment /
   * contractor; invoice / quote → sales / purchase) but the picker always
   * falls back to all five types if the subset would be empty — kept flexible.
   */
  allowedAgreementTypes?: readonly AgreementType[]
  /** Injectable API call (defaults to the real esign client) — for testing. */
  createEnvelopeFn?: typeof defaultCreateEnvelope
}

/** Human-readable labels for each agreement type (stable UI rendering). */
const AGREEMENT_TYPE_LABELS: Record<AgreementType, string> = {
  sales_agreement: 'Sales agreement',
  purchase_agreement: 'Purchase agreement',
  nda: 'NDA',
  employment_agreement: 'Employment agreement',
  contractor_agreement: 'Contractor agreement',
}

/** Default agreement-type subset per originating entity (kept flexible). */
const DEFAULT_TYPES_BY_ENTITY: Record<OriginatingEntityType, readonly AgreementType[]> = {
  staff: ['nda', 'employment_agreement', 'contractor_agreement'],
  invoice: ['sales_agreement', 'purchase_agreement'],
  quote: ['sales_agreement', 'purchase_agreement'],
}

const SIGNING_ROLE_OPTIONS: { value: SigningRole; label: string }[] = [
  { value: 'signer', label: 'Signer' },
  { value: 'viewer', label: 'Viewer' },
]

/** Syntactic email check, mirroring the server-side atomic validation (R4.2). */
const EMAIL_RE = /^[^\s@]+@[^\s@]+\.[^\s@]+$/

/** The two steps of the send flow. */
type SendStep = 'compose' | 'place'

/** An editable recipient row with a stable key for React. */
interface RecipientRow {
  key: number
  name: string
  email: string
  signing_role: SigningRole
}

/** Per-recipient validation messages, keyed by the row's stable key. */
interface RecipientError {
  name?: string
  email?: string
}

let recipientKeySeq = 0
function newRecipientRow(): RecipientRow {
  recipientKeySeq += 1
  return { key: recipientKeySeq, name: '', email: '', signing_role: 'signer' }
}

export function SendForSignatureModal({
  open,
  onClose,
  originatingEntityType,
  originatingEntityId,
  onSent,
  editEnvelopeId,
  onEdited,
  allowedAgreementTypes,
  createEnvelopeFn = defaultCreateEnvelope,
}: SendForSignatureModalProps) {
  // ── Agreement-type options (pre-filtered, flexible fallback) ───────────
  const agreementOptions = useMemo(() => {
    const candidate =
      allowedAgreementTypes && allowedAgreementTypes.length > 0
        ? allowedAgreementTypes
        : DEFAULT_TYPES_BY_ENTITY[originatingEntityType] ?? AGREEMENT_TYPES
    const subset = candidate.length > 0 ? candidate : AGREEMENT_TYPES
    return subset.map((t) => ({ value: t, label: AGREEMENT_TYPE_LABELS[t] }))
  }, [allowedAgreementTypes, originatingEntityType])

  // ── Flow state ─────────────────────────────────────────────────────────
  const [step, setStep] = useState<SendStep>('compose')

  // ── Edit / void-and-recreate state (R13) ───────────────────────────────
  // `recreating` flips the modal out of edit mode into a fresh create send
  // pre-populated with a copy of the voided envelope's Field_Set (R13.5);
  // `recreateFields` carries that copy into the create-mode editor.
  const [recreating, setRecreating] = useState(false)
  const [recreateFields, setRecreateFields] = useState<PlacedField[] | null>(null)

  // The envelope being edited, unless a void-and-recreate has switched us to a
  // fresh create send.
  const activeEnvelopeId = recreating ? undefined : editEnvelopeId
  const isEdit = activeEnvelopeId != null && activeEnvelopeId !== ''

  // ── Form state ─────────────────────────────────────────────────────────
  const [file, setFile] = useState<File | null>(null)
  const [agreementType, setAgreementType] = useState<AgreementType | ''>('')
  const [recipients, setRecipients] = useState<RecipientRow[]>([newRecipientRow()])

  // ── Signing-order state (R15) ───────────────────────────────────────────
  // The chosen Signing_Order_Mode (defaults to `parallel`, R15.2) and the
  // ordered `signer`-role recipient keys (R15.3). `signerOrder` is kept
  // reconciled against the recipient list below so it always holds exactly the
  // current signers' keys, preserving order across edits.
  const [signingOrderMode, setSigningOrderMode] = useState<SigningOrderMode>('parallel')
  const [signerOrder, setSignerOrder] = useState<number[]>([])

  // ── Validation state ───────────────────────────────────────────────────
  const [fileError, setFileError] = useState<string | null>(null)
  const [agreementError, setAgreementError] = useState<string | null>(null)
  const [recipientErrors, setRecipientErrors] = useState<Record<number, RecipientError>>({})

  const fileInputRef = useRef<HTMLInputElement>(null)

  /** Reset everything to a clean slate (on open, and after a successful send). */
  const resetForm = useCallback(() => {
    setStep('compose')
    setFile(null)
    setAgreementType(agreementOptions.length === 1 ? agreementOptions[0].value : '')
    setRecipients([newRecipientRow()])
    setSigningOrderMode('parallel')
    setSignerOrder([])
    setFileError(null)
    setAgreementError(null)
    setRecipientErrors({})
    setRecreating(false)
    setRecreateFields(null)
    if (fileInputRef.current) fileInputRef.current.value = ''
  }, [agreementOptions])

  // Reset when the modal opens (R11.3 — reopening starts from an empty set).
  useEffect(() => {
    if (open) resetForm()
    // resetForm is stable for a given agreementOptions; entity changes re-open.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open])

  // ── File selection ──────────────────────────────────────────────────────
  const handleFileChange = useCallback((e: React.ChangeEvent<HTMLInputElement>) => {
    const picked = e.target.files?.[0] ?? null
    if (!picked) {
      setFile(null)
      return
    }
    const isPdf =
      picked.type === 'application/pdf' || picked.name.toLowerCase().endsWith('.pdf')
    if (!isPdf) {
      setFile(null)
      setFileError('Choose a PDF file.')
      if (fileInputRef.current) fileInputRef.current.value = ''
      return
    }
    if (picked.size === 0) {
      setFile(null)
      setFileError('The selected file is empty.')
      if (fileInputRef.current) fileInputRef.current.value = ''
      return
    }
    setFile(picked)
    setFileError(null)
  }, [])

  // ── Recipient row helpers ─────────────────────────────────────────────
  const updateRecipient = useCallback(
    (key: number, patch: Partial<Omit<RecipientRow, 'key'>>) => {
      setRecipients((prev) =>
        prev.map((r) => (r.key === key ? { ...r, ...patch } : r)),
      )
      setRecipientErrors((prev) => {
        if (!prev[key]) return prev
        const next = { ...prev }
        delete next[key]
        return next
      })
    },
    [],
  )

  const addRecipient = useCallback(() => {
    setRecipients((prev) => [...prev, newRecipientRow()])
  }, [])

  const removeRecipient = useCallback((key: number) => {
    setRecipients((prev) => (prev.length <= 1 ? prev : prev.filter((r) => r.key !== key)))
    setRecipientErrors((prev) => {
      if (!prev[key]) return prev
      const next = { ...prev }
      delete next[key]
      return next
    })
  }, [])

  /**
   * Validate the whole step-1 form. Populates the inline error state and
   * returns the normalised recipient payload when valid, else `null`.
   */
  const validate = useCallback((): RecipientIn[] | null => {
    let ok = true

    if (!file) {
      setFileError('Choose a PDF file to send.')
      ok = false
    }

    if (!agreementType) {
      setAgreementError('Select an agreement type.')
      ok = false
    }

    const rowErrors: Record<number, RecipientError> = {}
    for (const r of recipients) {
      const err: RecipientError = {}
      if (r.name.trim() === '') err.name = 'Enter a name.'
      if (r.email.trim() === '') {
        err.email = 'Enter an email address.'
      } else if (!EMAIL_RE.test(r.email.trim())) {
        err.email = 'Enter a valid email address.'
      }
      if (err.name || err.email) {
        rowErrors[r.key] = err
        ok = false
      }
    }
    setRecipientErrors(rowErrors)

    if (!ok || !file || !agreementType) return null

    return recipients.map((r) => ({
      name: r.name.trim(),
      email: r.email.trim(),
      signing_role: r.signing_role,
    }))
  }, [file, agreementType, recipients])

  // ── Step 1 → step 2 transition ──────────────────────────────────────────
  const handleContinue = useCallback(() => {
    if (isEdit) {
      // Edit mode: recipients + fields come from the live envelope; step 1 only
      // re-selects the document to render for placement.
      if (!file) {
        setFileError('Choose the PDF for this document to edit its fields.')
        return
      }
      setStep('place')
      return
    }
    const recipientPayload = validate()
    if (!recipientPayload) return
    setStep('place')
  }, [isEdit, file, validate])

  // ── Void & recreate (R13.5): void the envelope, then open a fresh create ──
  // send pre-populated with a copy of the read Field_Set + recipients. The
  // editor performs the void; the modal just rebuilds step 1 in create mode.
  const handleVoidAndRecreate = useCallback(
    (seed: { fields: PlacedField[]; recipients: FieldPlacementEditorRecipient[] }) => {
      // Allocate fresh recipient rows and remap each seeded field's recipientKey
      // from the (index-based) read key to its new row key, so the create-mode
      // editor's assignment stays consistent.
      const keyMap = new Map<number, number>()
      const rows: RecipientRow[] = seed.recipients.map((r) => {
        const row = newRecipientRow()
        keyMap.set(r.key, row.key)
        return {
          ...row,
          name: r.name ?? '',
          email: r.email ?? '',
          signing_role: r.signing_role,
        }
      })
      const remappedFields: PlacedField[] = seed.fields.map((f) => ({
        ...f,
        recipientKey: keyMap.get(f.recipientKey) ?? rows[0]?.key ?? f.recipientKey,
      }))

      setRecipients(rows.length > 0 ? rows : [newRecipientRow()])
      setRecreateFields(remappedFields)
      setRecreating(true)
      setFile(null)
      setAgreementType(agreementOptions.length === 1 ? agreementOptions[0].value : '')
      setFileError(null)
      setAgreementError(null)
      setRecipientErrors({})
      if (fileInputRef.current) fileInputRef.current.value = ''
      setStep('compose')
    },
    [agreementOptions],
  )

  // ── Edit success: close (the caller refreshes its own surface) ──────────
  const handleEdited = useCallback(() => {
    onEdited?.()
    onClose()
  }, [onEdited, onClose])

  // ── The recipient list handed to the editor (stable key drives colour) ──
  const editorRecipients = useMemo<FieldPlacementEditorRecipient[]>(
    () =>
      recipients.map((r) => ({
        key: r.key,
        name: r.name,
        email: r.email,
        signing_role: r.signing_role,
      })),
    [recipients],
  )

  // Keep the signer ordering reconciled with the recipient list (R15.3): adding
  // a signer appends it, removing one (or flipping it to viewer) drops it, and
  // existing positions are preserved. Viewers never enter the order (R15.6).
  useEffect(() => {
    setSignerOrder((prev) => {
      const next = reconcileSignerOrder(recipients, prev)
      const unchanged =
        next.length === prev.length && next.every((key, i) => key === prev[i])
      return unchanged ? prev : next
    })
  }, [recipients])

  // ── Advisory dependencies mirrored from the editor (R14) ────────────────
  // The editor owns the FieldDependency[]; we keep the latest copy in a ref so
  // the send callback can attach it to the create payload without re-creating
  // `handleSend` on every dependency edit. Edit-mode sends thread dependencies
  // through the editor's own `PUT …/fields`, so this only feeds create mode.
  const dependenciesRef = useRef<FieldDependency[]>([])
  const handleDependenciesChange = useCallback((deps: FieldDependency[]) => {
    dependenciesRef.current = deps
  }, [])

  // ── Send at the end of step 2: the Field_Set travels with the create ────
  const handleSend = useCallback(
    async (placedFields: PlacedField[], signal: AbortSignal): Promise<void> => {
      // Step 1 validated before advancing, so file + agreement type are set;
      // guard defensively rather than asserting non-null.
      if (!file || !agreementType) {
        throw new Error('Select a PDF and an agreement type before sending.')
      }

      // Resolve each field's recipientKey to its index in `recipients` (the
      // same order as the payload's recipients array).
      const recipientKeyOrder = recipients.map((r) => r.key)

      // Signing order (R15): in `sequential` mode attach each signer's distinct
      // 1-based position; viewers stay on the document with no position (R15.6).
      // In `parallel` mode no positions travel and the mode is sent as-is.
      const positions =
        signingOrderMode === 'sequential' ? signingPositionByKey(signerOrder) : null
      const recipientPayload: RecipientIn[] = recipients.map((r) => {
        const order = positions?.get(r.key)
        return {
          name: r.name.trim(),
          email: r.email.trim(),
          signing_role: r.signing_role,
          ...(order != null ? { order } : {}),
        }
      })

      const deps = dependenciesRef.current
      const payload: EnvelopeCreate = {
        agreement_type: agreementType,
        originating_entity_type: originatingEntityType,
        originating_entity_id: originatingEntityId,
        recipients: recipientPayload,
        signing_order_mode: signingOrderMode,
        fields: placedFieldsToFieldIns(placedFields, recipientKeyOrder),
        ...(deps.length > 0
          ? { dependencies: fieldDependenciesToDependencyIns(deps) }
          : {}),
      }

      const envelope = await createEnvelopeFn(file, payload, signal)
      if (signal.aborted) return
      onSent?.(envelope)
      onClose()
    },
    [
      file,
      agreementType,
      recipients,
      signingOrderMode,
      signerOrder,
      originatingEntityType,
      originatingEntityId,
      createEnvelopeFn,
      onSent,
      onClose,
    ],
  )

  const canContinue = isEdit
    ? file !== null
    : file !== null && agreementType !== '' && recipients.length > 0

  return (
    <Modal
      open={open}
      onClose={onClose}
      title={isEdit ? 'Edit fields' : 'Send for signature'}
      className={
        step === 'place'
          ? 'max-w-[1500px] w-[96vw] h-[90vh]'
          : 'max-w-xl'
      }
      bodyClassName={
        step === 'place' ? 'flex min-h-0 flex-1 flex-col overflow-hidden px-4 py-3' : undefined
      }
    >
      {step === 'compose' ? (
        <>
          <div className="flex flex-col gap-[15px]">
            {isEdit && (
              <AlertBanner variant="info">
                Editing the fields on a sent document. Re-select the document to render it, then
                adjust the placed fields and save your changes.
              </AlertBanner>
            )}
            {/* ── PDF picker ─────────────────────────────────────────────── */}
            <FormField label="Document (PDF)" required error={fileError ?? undefined}>
              {({ id, 'aria-invalid': ariaInvalid, 'aria-describedby': describedBy }) => (
                <div className="flex flex-col gap-2">
                  <div className="flex items-center gap-3">
                    <Button
                      variant="ghost"
                      size="sm"
                      onClick={() => fileInputRef.current?.click()}
                    >
                      {file ? 'Change file' : 'Choose PDF'}
                    </Button>
                    <span className="truncate text-[13px] text-muted" aria-live="polite">
                      {file ? file.name : 'No file selected'}
                    </span>
                  </div>
                  <input
                    ref={fileInputRef}
                    id={id}
                    type="file"
                    accept=".pdf,application/pdf"
                    onChange={handleFileChange}
                    className="sr-only"
                    aria-invalid={ariaInvalid}
                    aria-describedby={describedBy}
                    aria-label="Select a PDF document to send for signature"
                  />
                </div>
              )}
            </FormField>

            {/* ── Agreement type ─────────────────────────────────────────── */}
            {!isEdit && (
              <Select
                label="Agreement type"
                placeholder="Select an agreement type…"
                options={agreementOptions}
                value={agreementType}
                error={agreementError ?? undefined}
                onChange={(e) => {
                  setAgreementType(e.target.value as AgreementType)
                  setAgreementError(null)
                }}
              />
            )}

            {/* ── Recipients ─────────────────────────────────────────────── */}
            {!isEdit && (
              <div className="flex flex-col gap-3">
              <div className="flex items-center justify-between">
                <span className="text-[12.5px] font-medium text-text">
                  Recipients<span className="ml-1 text-danger" aria-hidden="true">*</span>
                </span>
                <Button variant="quiet" size="sm" onClick={addRecipient}>
                  + Add recipient
                </Button>
              </div>

              {recipients.map((r, idx) => {
                const err = recipientErrors[r.key]
                return (
                  <div
                    key={r.key}
                    className="flex flex-col gap-3 rounded-ctl border border-border bg-canvas p-3"
                  >
                    <div className="flex items-center justify-between">
                      <span className="text-[12px] font-medium text-muted">
                        Recipient {idx + 1}
                      </span>
                      {recipients.length > 1 && (
                        <button
                          type="button"
                          onClick={() => removeRecipient(r.key)}
                          className="rounded-ctl px-2 py-1 text-[12px] text-muted transition-colors hover:text-danger disabled:opacity-60"
                          aria-label={`Remove recipient ${idx + 1}`}
                        >
                          Remove
                        </button>
                      )}
                    </div>

                    <Input
                      label="Name"
                      value={r.name}
                      error={err?.name}
                      onChange={(e) => updateRecipient(r.key, { name: e.target.value })}
                      placeholder="Full name"
                    />
                    <Input
                      label="Email"
                      type="email"
                      value={r.email}
                      error={err?.email}
                      onChange={(e) => updateRecipient(r.key, { email: e.target.value })}
                      placeholder="name@example.com"
                    />
                    <Select
                      label="Role"
                      options={SIGNING_ROLE_OPTIONS}
                      value={r.signing_role}
                      onChange={(e) =>
                        updateRecipient(r.key, { signing_role: e.target.value as SigningRole })
                      }
                    />
                  </div>
                )
              })}
              </div>
            )}

            {/* ── Signing order (R15) ────────────────────────────────────── */}
            {!isEdit && (
              <SigningOrderControls
                recipients={editorRecipients}
                mode={signingOrderMode}
                onModeChange={setSigningOrderMode}
                signerOrder={signerOrder}
                onReorder={setSignerOrder}
              />
            )}
          </div>

          {/* ── Step 1 actions ─────────────────────────────────────────── */}
          <div className="mt-5 flex items-center justify-end gap-3 border-t border-border pt-4">
            <Button variant="ghost" onClick={onClose}>
              Cancel
            </Button>
            <Button onClick={handleContinue} disabled={!canContinue}>
              Continue to field placement
            </Button>
          </div>
        </>
      ) : (
        <div className="flex min-h-0 flex-1 flex-col gap-3">
          {/* ── Back to step 1 (edit document / recipients) ──────────────── */}
          <div className="flex shrink-0 items-center justify-between">
            <Button variant="quiet" size="sm" onClick={() => setStep('compose')}>
              ← Back to details
            </Button>
            <span className="truncate text-[12.5px] text-muted" aria-live="polite">
              {file?.name}
            </span>
          </div>

          {file ? (
            <FieldPlacementEditor
              className="min-h-0 flex-1"
              file={file}
              recipients={editorRecipients}
              envelopeId={activeEnvelopeId}
              initialFields={!isEdit ? recreateFields ?? undefined : undefined}
              onSend={handleSend}
              onCancel={onClose}
              onEdited={handleEdited}
              onVoidAndRecreate={handleVoidAndRecreate}
              onDependenciesChange={handleDependenciesChange}
            />
          ) : (
            <AlertBanner variant="error">
              No document selected. Go back and choose a PDF to place fields on.
            </AlertBanner>
          )}
        </div>
      )}
    </Modal>
  )
}

export default SendForSignatureModal
