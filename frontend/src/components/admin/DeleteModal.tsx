import { useState, useEffect } from 'react'
import { Modal } from '@/components/ui/Modal'
import { Input } from '@/components/ui/Input'
import { Button } from '@/components/ui/Button'
import { AlertBanner } from '@/components/ui/AlertBanner'

export interface DeleteModalProps {
  open: boolean
  onClose: () => void
  onConfirm: (reason: string) => void
  saving: boolean
  orgName: string
}

export function DeleteModal({
  open,
  onClose,
  onConfirm,
  saving,
  orgName,
}: DeleteModalProps) {
  const [step, setStep] = useState<1 | 2>(1)
  const [reason, setReason] = useState('')
  const [confirmText, setConfirmText] = useState('')
  const [error, setError] = useState('')

  useEffect(() => {
    if (open) { setStep(1); setReason(''); setConfirmText(''); setError('') }
  }, [open])

  const handleStep1 = (e: React.FormEvent) => {
    e.preventDefault()
    if (!reason.trim()) { setError('A reason is required to delete an organisation'); return }
    setError('')
    setStep(2)
  }

  const handleStep2 = (e: React.FormEvent) => {
    e.preventDefault()
    if (confirmText !== orgName) { setError(`Please type "${orgName}" to confirm`); return }
    onConfirm(reason.trim())
  }

  return (
    <Modal open={open} onClose={onClose} title="Soft delete organisation">
      {step === 1 ? (
        <form onSubmit={handleStep1} className="space-y-4">
          <AlertBanner variant="warning" title="Soft delete (data retained)">
            Soft deleting <span className="font-semibold">{orgName}</span> will mark it as deleted but keep all data in the database. The organisation can potentially be recovered.
          </AlertBanner>
          <Input
            label="Reason for deletion"
            value={reason}
            onChange={(e) => setReason(e.target.value)}
            error={error}
          />
          <div className="flex justify-end gap-3 pt-2">
            <Button type="button" variant="secondary" onClick={onClose}>Cancel</Button>
            <Button type="submit" variant="danger">Continue</Button>
          </div>
        </form>
      ) : (
        <form onSubmit={handleStep2} className="space-y-4">
          <p className="text-sm text-gray-600">
            To confirm soft deletion, type the organisation name: <span className="font-semibold">{orgName}</span>
          </p>
          <Input
            label="Confirm organisation name"
            value={confirmText}
            onChange={(e) => setConfirmText(e.target.value)}
            error={error}
          />
          <div className="flex justify-end gap-3 pt-2">
            <Button type="button" variant="secondary" onClick={() => setStep(1)}>Back</Button>
            <Button type="submit" variant="danger" loading={saving}>Soft delete</Button>
          </div>
        </form>
      )}
    </Modal>
  )
}
