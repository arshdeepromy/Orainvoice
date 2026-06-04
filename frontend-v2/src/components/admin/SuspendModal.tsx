import { useState, useEffect } from 'react'
import { Modal, Input, Button } from '@/components/ui'

export interface SuspendModalProps {
  open: boolean
  onClose: () => void
  onConfirm: (reason: string) => void
  saving: boolean
  orgName: string
}

export function SuspendModal({
  open,
  onClose,
  onConfirm,
  saving,
  orgName,
}: SuspendModalProps) {
  const [reason, setReason] = useState('')
  const [error, setError] = useState('')

  useEffect(() => {
    if (open) { setReason(''); setError('') }
  }, [open])

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault()
    if (!reason.trim()) { setError('A reason is required to suspend an organisation'); return }
    onConfirm(reason.trim())
  }

  return (
    <Modal open={open} onClose={onClose} title="Suspend organisation">
      <form onSubmit={handleSubmit} className="space-y-4">
        <p className="text-sm text-muted">
          You are about to suspend <span className="font-semibold">{orgName}</span>. All users will lose access immediately.
        </p>
        <Input
          label="Reason for suspension"
          value={reason}
          onChange={(e) => setReason(e.target.value)}
          error={error}
        />
        <div className="flex justify-end gap-3 pt-2">
          <Button type="button" variant="ghost" onClick={onClose}>Cancel</Button>
          <Button type="submit" variant="danger" loading={saving}>Suspend</Button>
        </div>
      </form>
    </Modal>
  )
}
