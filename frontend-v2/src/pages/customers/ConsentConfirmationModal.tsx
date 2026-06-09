/**
 * ConsentConfirmationModal (F4) — staff confirm a manually-obtained consent
 * before enabling reminder (category, channel) pairs that aren't yet covered.
 *
 * Renders the consent text + version (from GET /customers/consent-text), the
 * still-missing pairs, a required obtained_method select, and a note textarea
 * that becomes required when obtained_method === 'other'. On Confirm it builds
 * a RemindersConsentRecord and PUTs /customers/{id}/reminders with the config
 * + consent_record; on Cancel it closes without writing.
 *
 * Requirements: 2.4, 2.5, 2.6, 2.7, 6.4.
 */

import { useEffect, useState } from 'react'
import apiClient from '@/api/client'
import { Button, Modal, Select, Input } from '@/components/ui'
import {
  fetchConsentText,
  type MissingConsentPair,
  type ReminderCategory,
  type ReminderChannel,
  type RemindersConsentEntry,
  type RemindersConsentRecord,
} from '@/api/customers'

export type ObtainedMethod =
  | 'verbal_in_person'
  | 'phone'
  | 'email_reply'
  | 'written_form'
  | 'other'

const OBTAINED_METHODS: { value: ObtainedMethod; label: string }[] = [
  { value: 'verbal_in_person', label: 'Verbal — in person' },
  { value: 'phone', label: 'Phone' },
  { value: 'email_reply', label: 'Email reply' },
  { value: 'written_form', label: 'Written form' },
  { value: 'other', label: 'Other' },
]

const CATEGORY_LABEL: Record<ReminderCategory, string> = {
  service_due: 'Service due',
  wof_expiry: 'WOF expiry',
  cof_expiry: 'COF expiry',
  registration_expiry: 'Registration expiry',
}

export interface ConsentConfirmationModalProps {
  open: boolean
  customerId: string
  missing: MissingConsentPair[]
  /** The full reminder config dict (per-category) to persist alongside consent. */
  config: Record<string, { enabled: boolean; days_before: number; channel: ReminderChannel }>
  onConfirmed: () => void
  onCancel: () => void
}

export function ConsentConfirmationModal({
  open,
  customerId,
  missing,
  config,
  onConfirmed,
  onCancel,
}: ConsentConfirmationModalProps) {
  const [consentText, setConsentText] = useState('')
  const [consentTextVersion, setConsentTextVersion] = useState('')
  const [obtainedMethod, setObtainedMethod] = useState<ObtainedMethod | ''>('')
  const [manualNote, setManualNote] = useState('')
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState('')

  useEffect(() => {
    if (!open) return
    const controller = new AbortController()
    fetchConsentText(controller.signal)
      .then((ct) => {
        setConsentText(ct.text)
        setConsentTextVersion(ct.version)
      })
      .catch(() => setError('Could not load consent text.'))
    return () => controller.abort()
  }, [open])

  const noteRequired = obtainedMethod === 'other'
  const canConfirm =
    obtainedMethod !== '' &&
    (!noteRequired || manualNote.trim().length > 0) &&
    consentTextVersion.length > 0

  async function handleConfirm() {
    // `canConfirm` already guarantees obtainedMethod is non-empty (TS narrows
    // it to ObtainedMethod here via the aliased-condition analysis).
    if (!canConfirm) return
    setSaving(true)
    setError('')
    try {
      const entries: RemindersConsentEntry[] = (missing ?? []).map((p) => ({
        vehicle_id: null,
        category: p.category,
        channel: p.channel,
      }))
      const record: RemindersConsentRecord = {
        given_at: new Date().toISOString(),
        source: `manually_recorded_by_staff:${obtainedMethod}`,
        entries,
        consent_text_version: consentTextVersion,
        manual_note: noteRequired ? manualNote.trim() : null,
      }
      const { ...configOnly } = config
      await apiClient.put<Record<string, unknown>>(
        `/customers/${customerId}/reminders`,
        { ...configOnly, consent_record: record },
      )
      onConfirmed()
    } catch {
      setError('Failed to save consent. Please try again.')
    } finally {
      setSaving(false)
    }
  }

  return (
    <Modal open={open} onClose={onCancel} title="Confirm reminder consent">
      <div className="space-y-4">
        <p className="text-[13px] text-muted">
          Enabling these reminders requires the customer's consent. Confirm you
          have obtained it for the following:
        </p>

        <ul className="space-y-1" aria-label="Pairs requiring consent">
          {(missing ?? []).map((p) => (
            <li
              key={`${p.category}:${p.channel}`}
              className="rounded-ctl bg-canvas px-3 py-2 text-[13px] text-text"
            >
              {CATEGORY_LABEL[p.category]} · {p.channel.toUpperCase()}
            </li>
          ))}
        </ul>

        {consentText && (
          <div className="rounded-card border border-border p-3">
            <p className="text-[13px] text-text">{consentText}</p>
            <p className="mono mt-2 text-[11px] text-muted-2">
              Consent version {consentTextVersion}
            </p>
          </div>
        )}

        <Select
          label="How was consent obtained?"
          options={[
            { value: '', label: 'Select…' },
            ...OBTAINED_METHODS,
          ]}
          value={obtainedMethod}
          onChange={(e) => setObtainedMethod(e.target.value as ObtainedMethod)}
        />

        {noteRequired && (
          <Input
            label="Note (required for “Other”)"
            value={manualNote}
            onChange={(e) => setManualNote(e.target.value)}
            placeholder="Describe how consent was obtained"
          />
        )}

        {error && (
          <p className="text-[13px] text-danger" role="alert">
            {error}
          </p>
        )}

        <div className="flex justify-end gap-2">
          <Button variant="ghost" size="sm" onClick={onCancel} disabled={saving}>
            Cancel
          </Button>
          <Button
            size="sm"
            onClick={handleConfirm}
            disabled={!canConfirm || saving}
            loading={saving}
          >
            Confirm consent &amp; save
          </Button>
        </div>
      </div>
    </Modal>
  )
}

export default ConsentConfirmationModal
