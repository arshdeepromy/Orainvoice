import { useState } from 'react'
import { Button } from '@/components/ui/Button'
import { Input } from '@/components/ui/Input'
import { useToast, ToastContainer } from '@/components/ui/Toast'
import apiClient from '@/api/client'

interface LockoutPolicy {
  temp_lock_threshold: number
  temp_lock_minutes: number
  permanent_lock_threshold: number
}

interface Props {
  policy: LockoutPolicy
  onSaved: (p: LockoutPolicy) => void
}

export function LockoutPolicySection({ policy, onSaved }: Props) {
  const [form, setForm] = useState<LockoutPolicy>({
    temp_lock_threshold: policy?.temp_lock_threshold ?? 5,
    temp_lock_minutes: policy?.temp_lock_minutes ?? 15,
    permanent_lock_threshold: policy?.permanent_lock_threshold ?? 10,
  })
  const [saving, setSaving] = useState(false)
  const [validationError, setValidationError] = useState('')
  const { toasts, addToast, dismissToast } = useToast()

  const setField = <K extends keyof LockoutPolicy>(key: K, value: number) => {
    const next = { ...form, [key]: value }
    setForm(next)
    if (next.permanent_lock_threshold <= next.temp_lock_threshold) {
      setValidationError('Permanent lock threshold must be greater than temporary lock threshold')
    } else {
      setValidationError('')
    }
  }

  const save = async () => {
    if (form.permanent_lock_threshold <= form.temp_lock_threshold) {
      setValidationError('Permanent lock threshold must be greater than temporary lock threshold')
      return
    }
    if (form.temp_lock_threshold < 3 || form.temp_lock_threshold > 10) {
      addToast('error', 'Temporary lock threshold must be between 3 and 10')
      return
    }
    if (form.temp_lock_minutes < 5 || form.temp_lock_minutes > 60) {
      addToast('error', 'Temporary lock duration must be between 5 and 60 minutes')
      return
    }
    if (form.permanent_lock_threshold < 5 || form.permanent_lock_threshold > 20) {
      addToast('error', 'Permanent lock threshold must be between 5 and 20')
      return
    }
    setSaving(true)
    try {
      const res = await apiClient.put('/org/security-settings', { lockout_policy: form })
      const saved = res.data?.lockout_policy ?? form
      onSaved(saved)
      addToast('success', 'Lockout policy saved')
    } catch (err: unknown) {
      const detail = (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail
      addToast('error', detail ?? 'Failed to save lockout policy')
    } finally {
      setSaving(false)
    }
  }

  return (
    <div className="space-y-4 max-w-2xl">
      <ToastContainer toasts={toasts} onDismiss={dismissToast} />

      <Input
        label="Temporary Lock — Failed Attempts"
        type="number"
        min={3}
        max={10}
        value={String(form.temp_lock_threshold)}
        onChange={(e) => setField('temp_lock_threshold', parseInt(e.target.value) || 5)}
        helperText="PCI DSS 8.3.4: lock after no more than 10 failed attempts."
      />

      <Input
        label="Temporary Lock Duration (minutes)"
        type="number"
        min={5}
        max={60}
        value={String(form.temp_lock_minutes)}
        onChange={(e) => setField('temp_lock_minutes', parseInt(e.target.value) || 15)}
        helperText="PCI DSS 8.3.4: minimum 30 minutes recommended."
      />

      <Input
        label="Permanent Lock — Failed Attempts"
        type="number"
        min={5}
        max={20}
        value={String(form.permanent_lock_threshold)}
        onChange={(e) => setField('permanent_lock_threshold', parseInt(e.target.value) || 10)}
        helperText="Account is deactivated after this many total failed attempts."
        error={validationError || undefined}
      />

      <Button onClick={save} loading={saving} disabled={!!validationError}>Save Lockout Policy</Button>
    </div>
  )
}
