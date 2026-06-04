import { useState } from 'react'
import { Button, useToast, ToastContainer } from '@/components/ui'
import apiClient from '@/api/client'

interface MfaPolicy {
  mode: 'optional' | 'mandatory_all' | 'mandatory_admins_only'
  excluded_user_ids: string[]
}

interface Props {
  policy: MfaPolicy
  onSaved: (p: MfaPolicy) => void
}

const MODE_OPTIONS: { value: MfaPolicy['mode']; label: string; desc: string; tip: string }[] = [
  { value: 'optional', label: 'Optional', desc: 'Users may configure MFA but it is not required.', tip: '' },
  { value: 'mandatory_all', label: 'Mandatory — All Users', desc: 'Every user must set up MFA before accessing the app.', tip: 'PCI DSS 8.4.2 recommends MFA for all access to cardholder data.' },
  { value: 'mandatory_admins_only', label: 'Mandatory — Admins Only', desc: 'Only org_admin and branch_admin users must set up MFA.', tip: 'PCI DSS 8.4.1 requires MFA for administrative access.' },
]

export function MfaEnforcementSection({ policy, onSaved }: Props) {
  const [mode, setMode] = useState<MfaPolicy['mode']>(policy?.mode ?? 'optional')
  const [excludedIds, setExcludedIds] = useState<string[]>(policy?.excluded_user_ids ?? [])
  const [newExclusion, setNewExclusion] = useState('')
  const [saving, setSaving] = useState(false)
  const { toasts, addToast, dismissToast } = useToast()

  const addExclusion = () => {
    const id = newExclusion.trim()
    if (!id) return
    if (excludedIds.includes(id)) {
      addToast('warning', 'User already in exclusion list')
      return
    }
    setExcludedIds((prev) => [...prev, id])
    setNewExclusion('')
  }

  const removeExclusion = (id: string) => {
    setExcludedIds((prev) => prev.filter((x) => x !== id))
  }

  const save = async () => {
    setSaving(true)
    try {
      const payload: MfaPolicy = { mode, excluded_user_ids: excludedIds }
      const res = await apiClient.put('/org/security-settings', { mfa_policy: payload })
      const saved = res.data?.mfa_policy ?? payload
      onSaved(saved)
      addToast('success', 'MFA policy saved')
    } catch (err: unknown) {
      const detail = (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail
      addToast('error', detail ?? 'Failed to save MFA policy')
    } finally {
      setSaving(false)
    }
  }

  return (
    <div className="space-y-4 max-w-2xl">
      <ToastContainer toasts={toasts} onDismiss={dismissToast} />

      <fieldset>
        <legend className="text-sm font-medium text-text mb-2">MFA Enforcement Mode</legend>
        <div className="space-y-2">
          {MODE_OPTIONS.map((opt) => (
            <label key={opt.value} className={`flex items-start gap-3 rounded-card border p-3 cursor-pointer transition-colors ${mode === opt.value ? 'border-accent bg-accent-soft' : 'border-border hover:border-border-strong'}`}>
              <input
                type="radio"
                name="mfa-mode"
                value={opt.value}
                checked={mode === opt.value}
                onChange={() => setMode(opt.value)}
                className="mt-0.5"
              />
              <div>
                <span className="text-sm font-medium text-text">{opt.label}</span>
                <p className="text-xs text-muted-2 mt-0.5">{opt.desc}</p>
                {opt.tip && <p className="text-xs text-accent mt-0.5" title={opt.tip}>ℹ {opt.tip}</p>}
              </div>
            </label>
          ))}
        </div>
      </fieldset>

      {mode !== 'optional' && (
        <div>
          <label className="text-sm font-medium text-text">User Exclusions</label>
          <p className="text-xs text-muted-2 mb-2">Users in this list will be exempt from MFA enforcement.</p>
          <div className="flex gap-2 mb-2">
            <input
              type="text"
              value={newExclusion}
              onChange={(e) => setNewExclusion(e.target.value)}
              placeholder="User ID to exclude"
              className="flex-1 rounded-ctl border border-border bg-card px-3 py-2 text-sm text-text focus:border-accent focus:outline-none focus:shadow-[0_0_0_3px_var(--accent-soft)]"
              onKeyDown={(e) => { if (e.key === 'Enter') { e.preventDefault(); addExclusion() } }}
            />
            <Button size="sm" variant="ghost" onClick={addExclusion}>Add</Button>
          </div>
          {(excludedIds ?? []).length > 0 && (
            <ul className="space-y-1">
              {(excludedIds ?? []).map((id) => (
                <li key={id} className="flex items-center justify-between rounded bg-canvas px-3 py-1.5 text-sm">
                  <span className="mono text-xs text-muted truncate">{id}</span>
                  <button onClick={() => removeExclusion(id)} className="text-danger hover:brightness-90 text-xs ml-2" aria-label={`Remove ${id}`}>✕</button>
                </li>
              ))}
            </ul>
          )}
        </div>
      )}

      <Button onClick={save} loading={saving}>Save MFA Policy</Button>
    </div>
  )
}
