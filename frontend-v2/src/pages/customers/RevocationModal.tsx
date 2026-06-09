/**
 * RevocationModal (F6) — confirm a manual revocation of reminder consent for a
 * single (category, channel) entry.
 *
 * Required obtained_method select + required reason note. On Confirm it POSTs
 * /customers/{id}/reminders/revoke and calls onRevoked; on Cancel it closes
 * without writing.
 *
 * Requirements: 3.1, 3.2, 3.3, 3.4.
 */

import { useState } from 'react'
import apiClient from '@/api/client'
import { Button, Modal, Select, Input } from '@/components/ui'
import type {
  ReminderCategory,
  ReminderChannel,
  RemindersRevokeRequest,
} from '@/api/customers'

const OBTAINED_METHODS: { value: RemindersRevokeRequest['obtained_method']; label: string }[] = [
  { value: 'phone', label: 'Phone' },
  { value: 'in_person', label: 'In person' },
  { value: 'email_reply', label: 'Email reply' },
  { value: 'other', label: 'Other' },
]

const CATEGORY_LABEL: Record<ReminderCategory, string> = {
  service_due: 'Service due',
  wof_expiry: 'WOF expiry',
  cof_expiry: 'COF expiry',
  registration_expiry: 'Registration expiry',
}

export interface RevocationModalProps {
  open: boolean
  customerId: string
  category: ReminderCategory
  channel: ReminderChannel
  onRevoked: () => void
  onCancel: () => void
}

export function RevocationModal({
  open,
  customerId,
  category,
  channel,
  onRevoked,
  onCancel,
}: RevocationModalProps) {
  const [obtainedMethod, setObtainedMethod] =
    useState<RemindersRevokeRequest['obtained_method'] | ''>('')
  const [reasonNote, setReasonNote] = useState('')
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState('')

  const canConfirm = obtainedMethod !== '' && reasonNote.trim().length > 0

  async function handleConfirm() {
    if (!canConfirm) return
    setSaving(true)
    setError('')
    try {
      const body: RemindersRevokeRequest = {
        obtained_method: obtainedMethod as RemindersRevokeRequest['obtained_method'],
        channel,
        categories_affected: [category],
        reason_note: reasonNote.trim(),
      }
      await apiClient.post<Record<string, unknown>>(
        `/customers/${customerId}/reminders/revoke`,
        body,
      )
      onRevoked()
    } catch {
      setError('Failed to record revocation. Please try again.')
    } finally {
      setSaving(false)
    }
  }

  return (
    <Modal open={open} onClose={onCancel} title="Revoke reminder consent">
      <div className="space-y-4">
        <p className="text-[13px] text-muted">
          Revoke consent for{' '}
          <span className="font-medium text-text">{CATEGORY_LABEL[category]}</span> ·{' '}
          <span className="font-medium text-text">{channel.toUpperCase()}</span>. This
          disables the reminder and is recorded with a full audit trail.
        </p>

        <Select
          label="How was the revocation obtained?"
          options={[{ value: '', label: 'Select…' }, ...OBTAINED_METHODS]}
          value={obtainedMethod}
          onChange={(e) =>
            setObtainedMethod(e.target.value as RemindersRevokeRequest['obtained_method'])
          }
        />

        <Input
          label="Reason"
          value={reasonNote}
          onChange={(e) => setReasonNote(e.target.value)}
          placeholder="Why is consent being revoked?"
        />

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
            variant="danger"
            onClick={handleConfirm}
            disabled={!canConfirm || saving}
            loading={saving}
          >
            Revoke consent
          </Button>
        </div>
      </div>
    </Modal>
  )
}

export default RevocationModal
