/**
 * AwaitingPartsNoteModal — required-note prompt when moving a job card
 * into the "Awaiting parts" column on the Job Cards Kanban.
 *
 * The backend (`update_job_card`) rejects the transition without a
 * non-empty note, so this modal blocks Save until the user types one.
 */

import { useEffect, useRef, useState } from 'react'
import { Modal } from '@/components/ui'

interface AwaitingPartsNoteModalProps {
  open: boolean
  jobCardLabel: string
  onClose: () => void
  onConfirm: (note: string) => Promise<void> | void
}

export default function AwaitingPartsNoteModal({
  open,
  jobCardLabel,
  onClose,
  onConfirm,
}: AwaitingPartsNoteModalProps) {
  const [note, setNote] = useState('')
  const [submitting, setSubmitting] = useState(false)
  const [error, setError] = useState('')
  const submittingRef = useRef(false)

  useEffect(() => {
    if (open) {
      setNote('')
      setError('')
      setSubmitting(false)
      submittingRef.current = false
    }
  }, [open])

  const handleSave = async () => {
    if (submittingRef.current) return
    const trimmed = note.trim()
    if (!trimmed) {
      setError('Please describe the parts being ordered or the reason for the wait.')
      return
    }
    submittingRef.current = true
    setSubmitting(true)
    setError('')
    try {
      await onConfirm(trimmed)
      onClose()
    } catch (err: unknown) {
      const detail =
        (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail ??
        'Failed to update job card.'
      setError(detail)
    } finally {
      submittingRef.current = false
      setSubmitting(false)
    }
  }

  const handleCancel = () => {
    if (submittingRef.current) return
    onClose()
  }

  return (
    <Modal open={open} onClose={handleCancel} title="Move to Awaiting parts">
      <div className="space-y-3">
        <p className="text-sm text-muted">
          Add a note for <span className="font-medium text-text">{jobCardLabel}</span>.
          This will be appended to the job card's notes with a timestamp.
        </p>
        <div>
          <label htmlFor="awaiting-parts-note" className="mb-1 block text-xs text-muted">
            Note <span className="text-danger">*</span>
          </label>
          <textarea
            id="awaiting-parts-note"
            value={note}
            onChange={(e) => setNote(e.target.value)}
            placeholder="e.g. Ordered front brake pads — ETA Wed"
            rows={4}
            className="block w-full rounded-ctl border border-border bg-card px-3 py-2 text-sm text-text focus:border-accent focus:outline-none focus:shadow-[0_0_0_3px_var(--accent-soft)]"
            autoFocus
          />
        </div>
        {error && (
          <p role="alert" className="text-xs text-danger">
            {error}
          </p>
        )}
      </div>

      <div className="mt-5 flex justify-end gap-2">
        <button
          type="button"
          onClick={handleCancel}
          disabled={submitting}
          className="rounded-ctl border border-border bg-card px-3 py-1.5 text-xs font-medium text-text hover:bg-canvas disabled:opacity-50"
        >
          Cancel
        </button>
        <button
          type="button"
          onClick={handleSave}
          disabled={submitting}
          className="rounded-ctl bg-warn px-3 py-1.5 text-xs font-medium text-white hover:brightness-95 disabled:opacity-50"
        >
          {submitting ? 'Saving…' : 'Move to Awaiting parts'}
        </button>
      </div>
    </Modal>
  )
}
