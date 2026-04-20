import { useState, useEffect } from 'react'
import { Modal } from '@/components/ui/Modal'
import { Select } from '@/components/ui/Select'
import { Button } from '@/components/ui/Button'

export interface Plan {
  id: string
  name: string
  [key: string]: unknown
}

export interface MovePlanModalProps {
  open: boolean
  onClose: () => void
  onConfirm: (planId: string) => void
  saving: boolean
  orgName: string
  currentPlanId: string
  plans: Plan[]
}

export function MovePlanModal({
  open,
  onClose,
  onConfirm,
  saving,
  orgName,
  currentPlanId,
  plans,
}: MovePlanModalProps) {
  const [planId, setPlanId] = useState('')
  const [error, setError] = useState('')

  useEffect(() => {
    if (open) { setPlanId(''); setError('') }
  }, [open])

  const availablePlans = (plans ?? []).filter((p) => p.id !== currentPlanId)

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault()
    if (!planId) { setError('Please select a new plan'); return }
    onConfirm(planId)
  }

  return (
    <Modal open={open} onClose={onClose} title="Move to different plan">
      <form onSubmit={handleSubmit} className="space-y-4">
        <p className="text-sm text-gray-600">
          Change the subscription plan for <span className="font-semibold">{orgName}</span>.
        </p>
        <Select
          label="New plan"
          options={availablePlans.map((p) => ({ value: p.id, label: p.name }))}
          value={planId}
          onChange={(e) => setPlanId(e.target.value)}
          placeholder="Select a plan"
          error={error}
        />
        <div className="flex justify-end gap-3 pt-2">
          <Button type="button" variant="secondary" onClick={onClose}>Cancel</Button>
          <Button type="submit" loading={saving}>Move plan</Button>
        </div>
      </form>
    </Modal>
  )
}
