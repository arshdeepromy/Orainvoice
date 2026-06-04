import { useState } from 'react'
import { Button, Input, useToast, ToastContainer } from '@/components/ui'
import apiClient from '@/api/client'

interface SessionPolicy {
  access_token_expire_minutes: number
  refresh_token_expire_days: number
  max_sessions_per_user: number
  excluded_user_ids: string[]
  excluded_roles: string[]
}

interface Props {
  policy: SessionPolicy
  onSaved: (p: SessionPolicy) => void
}

const AVAILABLE_ROLES = ['org_admin', 'branch_admin', 'location_manager', 'salesperson', 'staff_member', 'kiosk']

export function SessionPolicySection({ policy, onSaved }: Props) {
  const [form, setForm] = useState<SessionPolicy>({
    access_token_expire_minutes: policy?.access_token_expire_minutes ?? 30,
    refresh_token_expire_days: policy?.refresh_token_expire_days ?? 7,
    max_sessions_per_user: policy?.max_sessions_per_user ?? 5,
    excluded_user_ids: policy?.excluded_user_ids ?? [],
    excluded_roles: policy?.excluded_roles ?? [],
  })
  const [newExclusion, setNewExclusion] = useState('')
  const [saving, setSaving] = useState(false)
  const { toasts, addToast, dismissToast } = useToast()

  const setField = <K extends keyof SessionPolicy>(key: K, value: SessionPolicy[K]) =>
    setForm((prev) => ({ ...prev, [key]: value }))

  const addUserExclusion = () => {
    const id = newExclusion.trim()
    if (!id) return
    if ((form.excluded_user_ids ?? []).includes(id)) {
      addToast('warning', 'User already excluded')
      return
    }
    setField('excluded_user_ids', [...(form.excluded_user_ids ?? []), id])
    setNewExclusion('')
  }

  const removeUserExclusion = (id: string) => {
    setField('excluded_user_ids', (form.excluded_user_ids ?? []).filter((x) => x !== id))
  }

  const toggleRoleExclusion = (role: string) => {
    const current = form.excluded_roles ?? []
    if (current.includes(role)) {
      setField('excluded_roles', current.filter((r) => r !== role))
    } else {
      setField('excluded_roles', [...current, role])
    }
  }

  const save = async () => {
    if (form.access_token_expire_minutes < 5 || form.access_token_expire_minutes > 120) {
      addToast('error', 'Access token lifetime must be between 5 and 120 minutes')
      return
    }
    if (form.refresh_token_expire_days < 1 || form.refresh_token_expire_days > 90) {
      addToast('error', 'Refresh token lifetime must be between 1 and 90 days')
      return
    }
    if (form.max_sessions_per_user < 1 || form.max_sessions_per_user > 10) {
      addToast('error', 'Max sessions must be between 1 and 10')
      return
    }
    setSaving(true)
    try {
      const res = await apiClient.put('/org/security-settings', { session_policy: form })
      const saved = res.data?.session_policy ?? form
      onSaved(saved)
      addToast('success', 'Session policy saved')
    } catch (err: unknown) {
      const detail = (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail
      addToast('error', detail ?? 'Failed to save session policy')
    } finally {
      setSaving(false)
    }
  }

  return (
    <div className="space-y-4 max-w-2xl">
      <ToastContainer toasts={toasts} onDismiss={dismissToast} />

      <Input
        label="Access Token Lifetime (minutes)"
        type="number"
        min={5}
        max={120}
        value={String(form.access_token_expire_minutes)}
        onChange={(e) => setField('access_token_expire_minutes', parseInt(e.target.value) || 30)}
        helperText="PCI DSS 8.2.8: max 120 minutes (15 min idle recommended)."
      />

      <Input
        label="Refresh Token Lifetime (days)"
        type="number"
        min={1}
        max={90}
        value={String(form.refresh_token_expire_days)}
        onChange={(e) => setField('refresh_token_expire_days', parseInt(e.target.value) || 7)}
        helperText="How long a user stays logged in without re-authenticating."
      />

      <Input
        label="Max Concurrent Sessions Per User"
        type="number"
        min={1}
        max={10}
        value={String(form.max_sessions_per_user)}
        onChange={(e) => setField('max_sessions_per_user', parseInt(e.target.value) || 5)}
        helperText="Oldest sessions are revoked when the limit is exceeded."
      />

      {/* Role Exclusions */}
      <div>
        <p className="text-sm font-medium text-text mb-1">Role Exclusions</p>
        <p className="text-xs text-muted-2 mb-2">Excluded roles use global default session settings instead of org policy.</p>
        <div className="flex flex-wrap gap-2">
          {AVAILABLE_ROLES.map((role) => (
            <label key={role} className="flex items-center gap-1.5 cursor-pointer">
              <input
                type="checkbox"
                checked={(form.excluded_roles ?? []).includes(role)}
                onChange={() => toggleRoleExclusion(role)}
                className="rounded"
              />
              <span className="text-sm text-muted">{role}</span>
            </label>
          ))}
        </div>
      </div>

      {/* User Exclusions */}
      <div>
        <p className="text-sm font-medium text-text mb-1">User Exclusions</p>
        <p className="text-xs text-muted-2 mb-2">Excluded users use global default session settings.</p>
        <div className="flex gap-2 mb-2">
          <input
            type="text"
            value={newExclusion}
            onChange={(e) => setNewExclusion(e.target.value)}
            placeholder="User ID to exclude"
            className="flex-1 rounded-ctl border border-border bg-card px-3 py-2 text-sm text-text focus:border-accent focus:outline-none focus:shadow-[0_0_0_3px_var(--accent-soft)]"
            onKeyDown={(e) => { if (e.key === 'Enter') { e.preventDefault(); addUserExclusion() } }}
          />
          <Button size="sm" variant="ghost" onClick={addUserExclusion}>Add</Button>
        </div>
        {(form.excluded_user_ids ?? []).length > 0 && (
          <ul className="space-y-1">
            {(form.excluded_user_ids ?? []).map((id) => (
              <li key={id} className="flex items-center justify-between rounded bg-canvas px-3 py-1.5 text-sm">
                <span className="mono text-xs text-muted truncate">{id}</span>
                <button onClick={() => removeUserExclusion(id)} className="text-danger hover:brightness-90 text-xs ml-2" aria-label={`Remove ${id}`}>✕</button>
              </li>
            ))}
          </ul>
        )}
      </div>

      <Button onClick={save} loading={saving}>Save Session Policy</Button>
    </div>
  )
}
