import { useState } from 'react'
import { Button } from '@/components/ui/Button'
import { Input } from '@/components/ui/Input'
import { useToast, ToastContainer } from '@/components/ui/Toast'
import apiClient from '@/api/client'

interface PasswordPolicy {
  min_length: number
  require_uppercase: boolean
  require_lowercase: boolean
  require_digit: boolean
  require_special: boolean
  expiry_days: number
  history_count: number
}

interface Props {
  policy: PasswordPolicy
  onSaved: (p: PasswordPolicy) => void
}

const TOGGLES: { key: keyof PasswordPolicy; label: string }[] = [
  { key: 'require_uppercase', label: 'Require uppercase letter' },
  { key: 'require_lowercase', label: 'Require lowercase letter' },
  { key: 'require_digit', label: 'Require digit (0-9)' },
  { key: 'require_special', label: 'Require special character (!@#$…)' },
]

export function PasswordPolicySection({ policy, onSaved }: Props) {
  const [form, setForm] = useState<PasswordPolicy>({
    min_length: policy?.min_length ?? 8,
    require_uppercase: policy?.require_uppercase ?? false,
    require_lowercase: policy?.require_lowercase ?? false,
    require_digit: policy?.require_digit ?? false,
    require_special: policy?.require_special ?? false,
    expiry_days: policy?.expiry_days ?? 0,
    history_count: policy?.history_count ?? 0,
  })
  const [saving, setSaving] = useState(false)
  const { toasts, addToast, dismissToast } = useToast()

  const setField = <K extends keyof PasswordPolicy>(key: K, value: PasswordPolicy[K]) =>
    setForm((prev) => ({ ...prev, [key]: value }))

  const save = async () => {
    if (form.min_length < 8 || form.min_length > 128) {
      addToast('error', 'Minimum length must be between 8 and 128')
      return
    }
    if (form.expiry_days < 0 || form.expiry_days > 365) {
      addToast('error', 'Expiry days must be between 0 and 365')
      return
    }
    if (form.history_count < 0 || form.history_count > 24) {
      addToast('error', 'History count must be between 0 and 24')
      return
    }
    setSaving(true)
    try {
      const res = await apiClient.put('/org/security-settings', { password_policy: form })
      const saved = res.data?.password_policy ?? form
      onSaved(saved)
      addToast('success', 'Password policy saved')
    } catch (err: unknown) {
      const detail = (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail
      addToast('error', detail ?? 'Failed to save password policy')
    } finally {
      setSaving(false)
    }
  }

  return (
    <div className="space-y-4 max-w-2xl">
      <ToastContainer toasts={toasts} onDismiss={dismissToast} />

      <div>
        <Input
          label="Minimum Password Length"
          type="number"
          min={8}
          max={128}
          value={String(form.min_length)}
          onChange={(e) => setField('min_length', parseInt(e.target.value) || 8)}
          helperText="PCI DSS 8.3.6: minimum 8 characters recommended"
        />
      </div>

      <fieldset className="space-y-2">
        <legend className="text-sm font-medium text-gray-700 mb-1">Complexity Requirements</legend>
        {TOGGLES.map(({ key, label }) => (
          <div key={key} className="flex items-center gap-3">
            <button
              type="button"
              role="switch"
              aria-checked={!!form[key]}
              onClick={() => setField(key, !form[key] as never)}
              className={`relative inline-flex h-6 w-11 items-center rounded-full transition-colors ${form[key] ? 'bg-blue-600' : 'bg-gray-300'}`}
            >
              <span className={`inline-block h-4 w-4 transform rounded-full bg-white transition-transform ${form[key] ? 'translate-x-6' : 'translate-x-1'}`} />
            </button>
            <span className="text-sm text-gray-700">{label}</span>
          </div>
        ))}
      </fieldset>

      <Input
        label="Password Expiry (days)"
        type="number"
        min={0}
        max={365}
        value={String(form.expiry_days)}
        onChange={(e) => setField('expiry_days', parseInt(e.target.value) || 0)}
        helperText="0 = no expiry. PCI DSS 8.3.9: max 90 days recommended."
      />

      <Input
        label="Password History Count"
        type="number"
        min={0}
        max={24}
        value={String(form.history_count)}
        onChange={(e) => setField('history_count', parseInt(e.target.value) || 0)}
        helperText="0 = no history check. Prevents reuse of the last N passwords."
      />

      <Button onClick={save} loading={saving}>Save Password Policy</Button>
    </div>
  )
}
