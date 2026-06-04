/**
 * LeaveOverlapConfirmationModal — confirmation prompt shown before
 * submitting a paint that overlaps approved leave
 * (Workstream B / task B9, R3.6).
 *
 * Logic copied verbatim from
 * frontend/src/pages/staff-schedule/components/LeaveOverlapConfirmationModal.tsx;
 * presentation remapped onto the design-system tokens.
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
      <div className="space-y-4 text-sm text-text">
        <p>
          {cellCount} of the painted cells overlap with approved leave.
          Continue?
        </p>
        <div className="flex justify-end gap-2 pt-2">
          <button
            type="button"
            onClick={onClose}
            className="rounded-ctl border border-border bg-card px-4 py-2 text-sm font-medium text-text hover:bg-canvas hover:border-border-strong focus:outline-none focus-visible:ring-2 focus-visible:ring-accent"
          >
            Cancel
          </button>
          <button
            type="button"
            onClick={onConfirm}
            className="rounded-ctl bg-warn px-4 py-2 text-sm font-medium text-white hover:brightness-95 focus:outline-none focus-visible:ring-2 focus-visible:ring-warn"
          >
            Continue anyway
          </button>
        </div>
      </div>
    </Modal>
  )
}
