/**
 * Modal for adding an internal note to a claim.
 *
 * Requirements: 7.5
 */

import { useState } from 'react'
import { Modal, Button } from '../ui'

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
      <div className="space-y-4">
        <div>
          <label htmlFor="claim-note" className="block text-sm font-medium text-gray-700 mb-1">
            Note
          </label>
          <textarea
            id="claim-note"
            value={notes}
            onChange={e => setNotes(e.target.value)}
            rows={4}
            placeholder="Enter internal note…"
            className="w-full rounded-md border border-gray-300 px-3 py-2 text-sm focus:border-blue-400 focus:ring-1 focus:ring-blue-400 outline-none resize-y"
            autoFocus
          />
        </div>
        <div className="flex justify-end gap-2 pt-2">
          <Button variant="secondary" size="sm" onClick={handleClose} disabled={loading}>
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
