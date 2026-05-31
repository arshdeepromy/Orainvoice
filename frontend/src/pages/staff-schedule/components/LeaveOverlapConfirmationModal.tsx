/**
 * LeaveOverlapConfirmationModal — confirmation prompt shown before
 * submitting a paint that overlaps approved leave
 * (Workstream B / task B9, R3.6).
 */

import { Modal } from '@/components/ui/Modal'

export interface LeaveOverlapConfirmationModalProps {
  open: boolean
  cellCount: number
  onConfirm: () => void
  onClose: () => void
}

export default function LeaveOverlapConfirmationModal({
  open,
  cellCount,
  onConfirm,
  onClose,
}: LeaveOverlapConfirmationModalProps) {
  return (
    <Modal
      open={open}
      onClose={onClose}
      title="Overlap with approved leave"
      className="max-w-md"
    >
      <div className="space-y-4 text-sm text-gray-700">
        <p>
          {cellCount} of the painted cells overlap with approved leave.
          Continue?
        </p>
        <div className="flex justify-end gap-2 pt-2">
          <button
            type="button"
            onClick={onClose}
            className="rounded border border-gray-300 px-4 py-2 text-sm font-medium text-gray-700 hover:bg-gray-50 focus:outline-none focus:ring-2 focus:ring-blue-500"
          >
            Cancel
          </button>
          <button
            type="button"
            onClick={onConfirm}
            className="rounded bg-amber-600 px-4 py-2 text-sm font-medium text-white hover:bg-amber-700 focus:outline-none focus:ring-2 focus:ring-amber-500"
          >
            Continue anyway
          </button>
        </div>
      </div>
    </Modal>
  )
}
