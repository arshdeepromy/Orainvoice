/**
 * EsignSendScreen — the mobile "Send for signature" flow (R16).
 *
 * A two-step flow, mirroring the frontend-v2 `SendForSignatureModal`:
 *   - **Step 1 (compose):** select a PDF, choose the Agreement_Type, attach the
 *     originating entity, and add recipients (name + email + signing role).
 *   - **Step 2 (place):** the {@link MobileFieldPlacementEditor}, where the
 *     sender renders the PDF and places/assigns/configures fields, then confirms
 *     the send.
 *
 * The whole screen is gated by the `esignatures` ModuleGate and the org-sender
 * roles (R16.1): the field-placement send already enforces the module gate +
 * RBAC server-side, and this matches it client-side so the entry is hidden when
 * the module is off or the user isn't a sender.
 *
 * Safe consumption + AbortController throughout (R16.8): the create request is
 * bound to an AbortController that is aborted on unmount / cancel; the typed
 * `createEnvelope` client uses `?.` / `?? []` internally. A failed send retains
 * the in-progress Field_Set in the editor for correction and retry (R11.4).
 *
 * _Requirements: 16.1, 16.4, 16.5, 16.6, 16.7, 16.8, 16.9_
 */

import { useCallback, useEffect, useRef, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { ModuleGate } from '@/components/common/ModuleGate'
import { MobileButton, MobileInput, MobileSelect } from '@/components/ui'
import {
  AGREEMENT_TYPES,
  createEnvelope,
  placedFieldsToFieldIns,
  type AgreementType,
  type EnvelopeCreate,
  type OriginatingEntityType,
  type SigningRole,
} from '@/api/esign'
import type { PlacedField } from '@/lib/esign'
import MobileFieldPlacementEditor, { type EditorRecipient } from './MobileFieldPlacementEditor'

/** Org-sender roles permitted to send for signature (R16.1, mirrors RBAC). */
const ESIGN_SENDER_ROLES = ['org_admin', 'branch_admin', 'location_manager'] as const

/** Human labels for the agreement types. */
const AGREEMENT_TYPE_LABELS: Record<AgreementType, string> = {
  sales_agreement: 'Sales agreement',
  purchase_agreement: 'Purchase agreement',
  nda: 'NDA',
  employment_agreement: 'Employment agreement',
  contractor_agreement: 'Contractor agreement',
}

/** The originating-entity types the backend accepts. */
const ORIGINATING_ENTITY_TYPES: readonly OriginatingEntityType[] = ['invoice', 'quote', 'staff']
const ORIGINATING_ENTITY_LABELS: Record<OriginatingEntityType, string> = {
  invoice: 'Invoice',
  quote: 'Quote',
  staff: 'Staff member',
}

/** A recipient row in the step-1 composer. */
type RecipientRow = EditorRecipient

/** Loose error-message extraction from a humanized `{ message, code }` body. */
function extractErrorMessage(err: unknown): string {
  const data = (err as { response?: { data?: { message?: string } } })?.response?.data
  return data?.message ?? 'Couldn’t send the document for signature. Please try again.'
}

let recipientKeyCounter = 1
function nextRecipientKey(): number {
  recipientKeyCounter += 1
  return recipientKeyCounter
}

export default function EsignSendScreen() {
  const navigate = useNavigate()

  const [step, setStep] = useState<'compose' | 'place'>('compose')

  // Step 1 state
  const [file, setFile] = useState<File | null>(null)
  const [agreementType, setAgreementType] = useState<AgreementType>('sales_agreement')
  const [originatingType, setOriginatingType] = useState<OriginatingEntityType>('invoice')
  const [originatingId, setOriginatingId] = useState('')
  const [recipients, setRecipients] = useState<RecipientRow[]>([
    { key: 1, name: '', email: '', signing_role: 'signer' },
  ])
  const [composeError, setComposeError] = useState<string | null>(null)

  // Send state
  const [isSending, setIsSending] = useState(false)
  const [sendError, setSendError] = useState<string | null>(null)
  const [sent, setSent] = useState(false)
  const abortRef = useRef<AbortController | null>(null)

  // Abort any in-flight send on unmount (R16.8 / R11.2).
  useEffect(() => {
    return () => abortRef.current?.abort()
  }, [])

  const updateRecipient = useCallback(
    (key: number, patch: Partial<RecipientRow>) => {
      setRecipients((prev) => prev.map((r) => (r.key === key ? { ...r, ...patch } : r)))
    },
    [],
  )

  const addRecipient = useCallback(() => {
    setRecipients((prev) => [
      ...prev,
      { key: nextRecipientKey(), name: '', email: '', signing_role: 'signer' },
    ])
  }, [])

  const removeRecipient = useCallback((key: number) => {
    setRecipients((prev) => (prev.length <= 1 ? prev : prev.filter((r) => r.key !== key)))
  }, [])

  const handleFileChange = useCallback((e: React.ChangeEvent<HTMLInputElement>) => {
    const picked = e.target.files?.[0] ?? null
    setFile(picked)
    setComposeError(null)
  }, [])

  const validateCompose = useCallback((): boolean => {
    if (!file) {
      setComposeError('Select a PDF to send.')
      return false
    }
    if (!originatingId.trim()) {
      setComposeError('Enter the reference for the record this document is attached to.')
      return false
    }
    const cleaned = recipients.filter((r) => r.name.trim() && r.email.trim())
    if (cleaned.length === 0) {
      setComposeError('Add at least one recipient with a name and email.')
      return false
    }
    const emailLike = /\S+@\S+\.\S+/
    if (cleaned.some((r) => !emailLike.test(r.email.trim()))) {
      setComposeError('Check that every recipient email is valid.')
      return false
    }
    setComposeError(null)
    return true
  }, [file, originatingId, recipients])

  const goToPlace = useCallback(() => {
    if (!validateCompose()) return
    setSendError(null)
    setStep('place')
  }, [validateCompose])

  // The recipients passed to the editor: only the completed rows.
  const editorRecipients: EditorRecipient[] = recipients
    .filter((r) => r.name.trim() && r.email.trim())
    .map((r) => ({
      key: r.key,
      name: r.name.trim(),
      email: r.email.trim(),
      signing_role: r.signing_role,
    }))

  const handleSend = useCallback(
    async (fields: PlacedField[]) => {
      if (!file) return

      // Abort any prior in-flight send and start a fresh controller (R16.8).
      abortRef.current?.abort()
      const controller = new AbortController()
      abortRef.current = controller

      setIsSending(true)
      setSendError(null)

      const recipientKeyOrder = editorRecipients.map((r) => r.key)
      const payload: EnvelopeCreate = {
        agreement_type: agreementType,
        originating_entity_type: originatingType,
        originating_entity_id: originatingId.trim(),
        recipients: editorRecipients.map((r) => ({
          name: r.name,
          email: r.email,
          signing_role: r.signing_role,
        })),
        fields: placedFieldsToFieldIns(fields, recipientKeyOrder),
      }

      try {
        await createEnvelope(file, payload, controller.signal)
        if (controller.signal.aborted) return
        setSent(true)
      } catch (err) {
        if (controller.signal.aborted) return
        // Retain the Field_Set in the editor for correction + retry (R11.4).
        setSendError(extractErrorMessage(err))
      } finally {
        if (!controller.signal.aborted) setIsSending(false)
      }
    },
    [file, agreementType, originatingType, originatingId, editorRecipients],
  )

  const handleCancel = useCallback(() => {
    abortRef.current?.abort()
    navigate(-1)
  }, [navigate])

  // ---- Success state ------------------------------------------------------
  if (sent) {
    return (
      <ModuleGate moduleSlug="esignatures" roles={[...ESIGN_SENDER_ROLES]}>
        <div className="flex flex-col items-center gap-4 p-6 text-center">
          <div className="flex h-14 w-14 items-center justify-center rounded-full bg-green-100 text-green-600 dark:bg-green-900/40 dark:text-green-400">
            <svg
              className="h-7 w-7"
              viewBox="0 0 24 24"
              fill="none"
              stroke="currentColor"
              strokeWidth="2"
              strokeLinecap="round"
              strokeLinejoin="round"
              aria-hidden="true"
            >
              <path d="M20 6 9 17l-5-5" />
            </svg>
          </div>
          <h1 className="text-xl font-semibold text-gray-900 dark:text-gray-100">
            Sent for signature
          </h1>
          <p className="text-sm text-gray-500 dark:text-gray-400">
            The document has been sent to your recipients.
          </p>
          <MobileButton variant="primary" fullWidth onClick={() => navigate(-1)}>
            Done
          </MobileButton>
        </div>
      </ModuleGate>
    )
  }

  // ---- Step 2: editor -----------------------------------------------------
  if (step === 'place' && file) {
    return (
      <ModuleGate moduleSlug="esignatures" roles={[...ESIGN_SENDER_ROLES]}>
        <MobileFieldPlacementEditor
          file={file}
          recipients={editorRecipients}
          onSend={handleSend}
          onBack={() => setStep('compose')}
          isSending={isSending}
          sendError={sendError}
        />
      </ModuleGate>
    )
  }

  // ---- Step 1: composer ---------------------------------------------------
  return (
    <ModuleGate moduleSlug="esignatures" roles={[...ESIGN_SENDER_ROLES]}>
      <div className="flex flex-col gap-4 p-4">
        <button
          type="button"
          onClick={handleCancel}
          className="flex min-h-[44px] items-center gap-1 self-start text-blue-600 dark:text-blue-400"
          aria-label="Cancel"
        >
          <svg
            className="h-5 w-5"
            viewBox="0 0 24 24"
            fill="none"
            stroke="currentColor"
            strokeWidth="2"
            strokeLinecap="round"
            strokeLinejoin="round"
            aria-hidden="true"
          >
            <path d="m15 18-6-6 6-6" />
          </svg>
          Cancel
        </button>

        <h1 className="text-xl font-semibold text-gray-900 dark:text-gray-100">
          Send for signature
        </h1>

        {/* PDF select */}
        <div className="flex flex-col gap-1">
          <span className="text-sm font-medium text-gray-700 dark:text-gray-300">Document</span>
          <label className="flex min-h-[44px] cursor-pointer items-center justify-center rounded-lg border border-dashed border-gray-300 bg-gray-50 px-3 py-2 text-sm text-gray-600 dark:border-gray-600 dark:bg-gray-800 dark:text-gray-300">
            <input
              type="file"
              accept="application/pdf"
              className="hidden"
              onChange={handleFileChange}
            />
            {file ? file.name : 'Choose a PDF'}
          </label>
        </div>

        {/* Agreement type */}
        <MobileSelect
          label="Agreement type"
          value={agreementType}
          onChange={(e) => setAgreementType(e.target.value as AgreementType)}
          options={AGREEMENT_TYPES.map((t) => ({
            value: t,
            label: AGREEMENT_TYPE_LABELS[t],
          }))}
        />

        {/* Originating entity */}
        <MobileSelect
          label="Attach to"
          value={originatingType}
          onChange={(e) => setOriginatingType(e.target.value as OriginatingEntityType)}
          options={ORIGINATING_ENTITY_TYPES.map((t) => ({
            value: t,
            label: ORIGINATING_ENTITY_LABELS[t],
          }))}
        />
        <MobileInput
          label="Record reference"
          value={originatingId}
          onChange={(e) => setOriginatingId(e.target.value)}
          placeholder="ID of the invoice / quote / staff record"
          helperText="The record this signed document belongs to."
        />

        {/* Recipients */}
        <div className="flex flex-col gap-3">
          <div className="flex items-center justify-between">
            <span className="text-sm font-medium text-gray-700 dark:text-gray-300">
              Recipients
            </span>
            <MobileButton variant="ghost" size="sm" onClick={addRecipient}>
              Add
            </MobileButton>
          </div>

          {recipients.map((r, i) => (
            <div
              key={r.key}
              className="flex flex-col gap-2 rounded-lg border border-gray-200 p-3 dark:border-gray-700"
            >
              <div className="flex items-center justify-between">
                <span className="text-xs font-medium text-gray-500 dark:text-gray-400">
                  Recipient {i + 1}
                </span>
                {recipients.length > 1 && (
                  <button
                    type="button"
                    onClick={() => removeRecipient(r.key)}
                    className="flex min-h-[44px] min-w-[44px] items-center justify-center text-sm text-red-600 dark:text-red-400"
                    aria-label={`Remove recipient ${i + 1}`}
                  >
                    Remove
                  </button>
                )}
              </div>
              <MobileInput
                label="Name"
                value={r.name}
                onChange={(e) => updateRecipient(r.key, { name: e.target.value })}
                placeholder="Full name"
              />
              <MobileInput
                label="Email"
                type="email"
                value={r.email}
                onChange={(e) => updateRecipient(r.key, { email: e.target.value })}
                placeholder="name@example.com"
              />
              <MobileSelect
                label="Role"
                value={r.signing_role}
                onChange={(e) =>
                  updateRecipient(r.key, { signing_role: e.target.value as SigningRole })
                }
                options={[
                  { value: 'signer', label: 'Signer' },
                  { value: 'viewer', label: 'Viewer' },
                ]}
              />
            </div>
          ))}
        </div>

        {composeError && (
          <p className="text-sm text-red-600 dark:text-red-400" role="alert">
            {composeError}
          </p>
        )}

        <MobileButton variant="primary" fullWidth onClick={goToPlace}>
          Next: place fields
        </MobileButton>
      </div>
    </ModuleGate>
  )
}
