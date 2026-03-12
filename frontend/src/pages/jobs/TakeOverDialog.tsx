/**
 * TakeOverDialog — modal for reassigning a job card to the current user.
 *
 * Requires a takeover note explaining why the job is being reassigned.
 * Calls PUT /api/v1/job-cards/{id}/assign with { new_assignee_id, takeover_note }.
 *
 * Requirements: 8.7, 8.8
 */

import React, { useState } from 'react'
import apiClient from '../../api/client'
import { Button, Modal, useToast } from '../../components/ui'
import { useAuth } from '../../contexts/AuthContext'

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
        <div>
          <label
            htmlFor="takeover-note"
            className="block text-sm font-medium text-gray-700"
          >
            Reason for takeover <span className="text-red-500">*</span>
          </label>
          <textarea
            id="takeover-note"
            className="mt-1 block w-full rounded-md border border-gray-300 px-3 py-2 text-sm shadow-sm focus:border-blue-500 focus:outline-none focus:ring-1 focus:ring-blue-500"
            rows={3}
            required
            placeholder="Explain why you are taking over this job…"
            value={note}
            onChange={(e) => setNote(e.target.value)}
            disabled={submitting}
            data-testid="takeover-note"
          />
        </div>

        <div className="flex justify-end gap-3 border-t border-gray-200 pt-4">
          <Button
            type="button"
            variant="secondary"
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
