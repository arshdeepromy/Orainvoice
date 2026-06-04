/**
 * TakeOverDialog — Task 26 port of frontend/src/pages/jobs/TakeOverDialog.tsx.
 *
 * Modal for reassigning a job card to the current user. ALL logic copied
 * VERBATIM: requires a takeover note, calls PUT /job-cards/:id/assign with
 * { new_assignee_id, takeover_note }, toasts on success/error, blocks close
 * while submitting. Presentation remapped onto the design tokens (FR-2b): the
 * shared Modal primitive + token textarea, `secondary`→`ghost`.
 *
 * Requirements: 8.7, 8.8
 */

import React, { useState } from 'react'
import apiClient from '@/api/client'
import { Button, Modal, useToast } from '@/components/ui'
import { useAuth } from '@/contexts/AuthContext'

/* ------------------------------------------------------------------ */
/*  Types                                                              */
/* ------------------------------------------------------------------ */

export interface TakeOverDialogProps {
  jobCardId: string
  isOpen: boolean
  onClose: () => void
  onSuccess: () => void
}

/* ------------------------------------------------------------------ */
/*  Component                                                          */
/* ------------------------------------------------------------------ */

export default function TakeOverDialog({
  jobCardId,
  isOpen,
  onClose,
  onSuccess,
}: TakeOverDialogProps) {
  const { user } = useAuth()
  const { addToast } = useToast()
  const [note, setNote] = useState('')
  const [submitting, setSubmitting] = useState(false)

  const canSubmit = note.trim().length > 0

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault()
    if (!canSubmit || !user) return

    setSubmitting(true)
    try {
      await apiClient.put(`/job-cards/${jobCardId}/assign`, {
        new_assignee_id: user.id,
        takeover_note: note.trim(),
      })
      addToast('success', 'Job reassigned to you.')
      setNote('')
      onClose()
      onSuccess()
    } catch (err: unknown) {
      const detail =
        (err as { response?: { data?: { detail?: string } } })?.response?.data
          ?.detail
      addToast('error', detail ?? 'Failed to take over job.')
    } finally {
      setSubmitting(false)
    }
  }

  const handleClose = () => {
    if (!submitting) {
      setNote('')
      onClose()
    }
  }

  return (
    <Modal open={isOpen} onClose={handleClose} title="Take Over Job">
      <form onSubmit={handleSubmit} className="space-y-4">
        <div className="flex flex-col gap-[7px]">
          <label htmlFor="takeover-note" className="text-[12.5px] font-medium text-text">
            Reason for takeover <span className="text-danger">*</span>
          </label>
          <textarea
            id="takeover-note"
            className="block w-full rounded-ctl border border-border bg-card px-[13px] py-2 text-[13.5px] text-text transition-[border-color,box-shadow] duration-150 placeholder:text-muted-2 focus:border-accent focus:outline-none focus:shadow-[0_0_0_3px_var(--accent-soft)]"
            rows={3}
            required
            placeholder="Explain why you are taking over this job…"
            value={note}
            onChange={(e) => setNote(e.target.value)}
            disabled={submitting}
            data-testid="takeover-note"
          />
        </div>

        <div className="flex justify-end gap-3 border-t border-border pt-4">
          <Button
            type="button"
            variant="ghost"
            onClick={handleClose}
            disabled={submitting}
          >
            Cancel
          </Button>
          <Button type="submit" disabled={!canSubmit || submitting}>
            {submitting ? 'Reassigning…' : 'Take Over'}
          </Button>
        </div>
      </form>
    </Modal>
  )
}
