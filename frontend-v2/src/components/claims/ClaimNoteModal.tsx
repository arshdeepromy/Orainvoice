/**
 * Modal for adding an internal note to a claim.
 *
 * Requirements: 7.5
 */

import { useState } from 'react'
import { Modal, Button } from '@/components/ui'

interface ClaimNoteModalProps {
  open: boolean
  onClose: () => void
  onSubmit: (notes: string) => void
  loading?: boolean
}

export function ClaimNoteModal({ open, onClose, onSubmit, loading = false }: ClaimNoteModalProps) {
  const [notes, setNotes] = useState('')

  const canSubmit = notes.trim().length > 0

  const handleSubmit = () => {
    if (!canSubmit) return
    onSubmit(notes.trim())
  }

  const handleClose = () => {
    setNotes('')
    onClose()
  }

  return (
    <Modal open={open} onClose={handleClose} title="Add Internal Note">
      <div className="space-y-4" data-testid="note-modal">
        <div>
          <label htmlFor="claim-note" className="mb-1 block text-sm font-medium text-text">
            Note
          </label>
          <textarea
            id="claim-note"
            value={notes}
            onChange={e => setNotes(e.target.value)}
            rows={4}
            placeholder="Enter internal note…"
            className="w-full resize-y rounded-ctl border border-border bg-card px-3 py-2 text-sm text-text outline-none focus:border-accent focus:ring-1 focus:ring-accent"
            autoFocus
          />
        </div>
        <div className="flex justify-end gap-2 pt-2">
          <Button variant="ghost" size="sm" onClick={handleClose} disabled={loading}>
            Cancel
          </Button>
          <Button size="sm" onClick={handleSubmit} disabled={!canSubmit} loading={loading}>
            Add Note
          </Button>
        </div>
      </div>
    </Modal>
  )
}
