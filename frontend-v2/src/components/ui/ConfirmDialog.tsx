import { Modal } from './Modal'
import Button from './Button'

/**
 * ConfirmDialog — Task 73 base component, pulled forward for Task 28
 * (BookingListPanel). Port of frontend/src/components/ui/ConfirmDialog.tsx:
 * a small confirm/cancel dialog built on the shared Modal + Button primitives.
 * Logic copied VERBATIM; `secondary`→`ghost` and message text remapped to the
 * design tokens.
 */

interface ConfirmDialogProps {
  open: boolean
  title: string
  message: string
  confirmLabel?: string
  cancelLabel?: string
  variant?: 'danger' | 'primary'
  loading?: boolean
  onConfirm: () => void
  onCancel: () => void
}

export function ConfirmDialog({
  open,
  title,
  message,
  confirmLabel = 'Confirm',
  cancelLabel = 'Cancel',
  variant = 'primary',
  loading = false,
  onConfirm,
  onCancel,
}: ConfirmDialogProps) {
  return (
    <Modal open={open} onClose={onCancel} title={title} className="max-w-md">
      <div className="space-y-4">
        <p className="text-[13.5px] text-muted">{message}</p>
        <div className="flex justify-end gap-3">
          <Button variant="ghost" size="sm" onClick={onCancel} disabled={loading}>
            {cancelLabel}
          </Button>
          <Button variant={variant} size="sm" onClick={onConfirm} loading={loading} disabled={loading}>
            {confirmLabel}
          </Button>
        </div>
      </div>
    </Modal>
  )
}

export default ConfirmDialog
