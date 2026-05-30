import { useState } from 'react'
import { Modal } from '../ui/Modal'
import { Button } from '../ui/Button'

interface CancelQuoteModalProps {
  isOpen: boolean
  onClose: () => void
  onConfirm: (reason: string) => Promise<void>
  loading: boolean
}

/**
 * Confirmation modal for cancelling a quote.
 * Requires a non-whitespace reason before the confirm button is enabled.
 */
export default function CancelQuoteModal({ isOpen, onClose, onConfirm, loading }: CancelQuoteModalProps) {
  const [reason, setReason] = useState('')

  const isReasonValid = reason.trim().length > 0

  const handleConfirm = async () => {
    if (!isReasonValid) return
    await onConfirm(reason.trim())
    setReason('')
  }

  const handleClose = () => {
    if (loading) return
    setReason('')
    onClose()
  }

  return (
    <Modal open={isOpen} onClose={handleClose} title="Cancel Quote">
      <div className="space-y-4">
        {/* Warning message */}
        <div className="rounded-md border border-amber-200 bg-amber-50 px-4 py-3">
          <p className="text-sm text-amber-800">
            Cancelling this quote will retain its number but mark it as withdrawn. This cannot be undone.
          </p>
        </div>

        {/* Reason textarea */}
        <div>
          <label htmlFor="cancel-reason" className="block text-sm font-medium text-gray-700 mb-1">
            Reason for cancellation
          </label>
          <textarea
            id="cancel-reason"
            value={reason}
            onChange={(e) => setReason(e.target.value)}
            placeholder="Enter the reason for cancelling this quote…"
            rows={3}
            className="w-full rounded-md border border-gray-300 px-3 py-2 text-sm text-gray-900 placeholder-gray-400
              focus:border-blue-500 focus:outline-none focus:ring-1 focus:ring-blue-500
              disabled:bg-gray-50 disabled:text-gray-500"
            disabled={loading}
          />
        </div>

        {/* Action buttons */}
        <div className="flex justify-end gap-3 pt-2">
          <Button
            variant="secondary"
            onClick={handleClose}
            disabled={loading}
          >
            Go Back
          </Button>
          <Button
            variant="danger"
            onClick={handleConfirm}
            disabled={!isReasonValid || loading}
            loading={loading}
          >
            Cancel Quote
          </Button>
        </div>
      </div>
    </Modal>
  )
}
