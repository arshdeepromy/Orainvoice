/**
 * Workshop Admin — Fleet portal security policy editor.
 * Allows org admins to configure password policy, session policy, and MFA requirements.
 *
 * Implements: B2B Fleet Portal — Requirement 21.2.
 */
import { useEffect, useState } from 'react'
import type { FormEvent } from 'react'

import apiClient from '../../api/client'

interface SecurityPolicy {
  password_min_length: number
  password_require_uppercase: boolean
  password_require_number: boolean
  password_require_special: boolean
  password_history_count: number
  password_max_age_days: number
  lockout_threshold: number
  lockout_duration_minutes: number
  session_idle_timeout_minutes: number
  session_max_concurrent: number
  mfa_mode: 'optional' | 'encouraged' | 'required'
}

const DEFAULT_POLICY: SecurityPolicy = {
  password_min_length: 8,
  password_require_uppercase: false,
  password_require_number: false,
  password_require_special: false,
  password_history_count: 3,
  password_max_age_days: 0,
  lockout_threshold: 5,
  lockout_duration_minutes: 15,
  session_idle_timeout_minutes: 240,
  session_max_concurrent: 5,
  mfa_mode: 'optional',
}

export default function SecuritySettings() {
  const [policy, setPolicy] = useState<SecurityPolicy>(DEFAULT_POLICY)
  const [loading, setLoading] = useState(true)
  const [saving, setSaving] = useState(false)
  const [msg, setMsg] = useState<{ type: 'ok' | 'err'; text: string } | null>(null)

  useEffect(() => {
    const controller = new AbortController()
    apiClient.get<SecurityPolicy>('/api/v2/fleet-portal/admin/security-policy', { signal: controller.signal })
      .then(res => setPolicy({ ...DEFAULT_POLICY, ...(res.data ?? {}) }))
      .catch(() => {})
      .finally(() => setLoading(false))
    return () => controller.abort()
  }, [])

  const handleSave = async (e: FormEvent) => {
    e.preventDefault()
    setSaving(true)
    setMsg(null)
    try {
      await apiClient.put('/api/v2/fleet-portal/admin/security-policy', policy)
      setMsg({ type: 'ok', text: 'Security policy saved.' })
    } catch (err: unknown) {
      setMsg({ type: 'err', text: (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail ?? 'Failed to save.' })
    } finally { setSaving(false) }
  }

  if (loading) return <div className="p-4 text-sm text-gray-500">Loading…</div>

  return (
    <div className="space-y-6 max-w-2xl">
      <h1 className="text-xl font-semibold">Fleet Portal Security Policy</h1>
      <p className="text-sm text-gray-500">Configure password rules, session limits, and MFA requirements for fleet portal users.</p>

      {msg && <div className={`rounded border p-3 text-sm ${msg.type === 'ok' ? 'border-green-200 bg-green-50 text-green-800' : 'border-red-200 bg-red-50 text-red-800'}`}>{msg.text}</div>}

      <form onSubmit={handleSave} className="space-y-6">
        {/* Password Policy */}
        <section className="rounded-lg border border-gray-200 bg-white p-4 dark:border-gray-800 dark:bg-gray-950">
          <h2 className="text-sm font-medium mb-3">Password Policy</h2>
          <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
            <div>
              <label className="block text-xs text-gray-500 mb-1">Minimum Length</label>
              <input type="number" min={8} max={128} value={policy.password_min_length}
                onChange={e => setPolicy({ ...policy, password_min_length: parseInt(e.target.value) || 8 })}
                className="w-full rounded border border-gray-300 px-2 py-1 text-sm min-h-[36px] dark:border-gray-700 dark:bg-gray-900 dark:text-white" />
            </div>
            <div>
              <label className="block text-xs text-gray-500 mb-1">Password History (prevent reuse)</label>
              <input type="number" min={0} max={24} value={policy.password_history_count}
                onChange={e => setPolicy({ ...policy, password_history_count: parseInt(e.target.value) || 0 })}
                className="w-full rounded border border-gray-300 px-2 py-1 text-sm min-h-[36px] dark:border-gray-700 dark:bg-gray-900 dark:text-white" />
            </div>
            <div>
              <label className="block text-xs text-gray-500 mb-1">Max Age (days, 0 = no expiry)</label>
              <input type="number" min={0} max={365} value={policy.password_max_age_days}
                onChange={e => setPolicy({ ...policy, password_max_age_days: parseInt(e.target.value) || 0 })}
                className="w-full rounded border border-gray-300 px-2 py-1 text-sm min-h-[36px] dark:border-gray-700 dark:bg-gray-900 dark:text-white" />
            </div>
            <div className="space-y-2 pt-2">
              <label className="flex items-center gap-2 text-xs">
                <input type="checkbox" checked={policy.password_require_uppercase} onChange={e => setPolicy({ ...policy, password_require_uppercase: e.target.checked })} />
                Require uppercase letter
              </label>
              <label className="flex items-center gap-2 text-xs">
                <input type="checkbox" checked={policy.password_require_number} onChange={e => setPolicy({ ...policy, password_require_number: e.target.checked })} />
                Require number
              </label>
              <label className="flex items-center gap-2 text-xs">
                <input type="checkbox" checked={policy.password_require_special} onChange={e => setPolicy({ ...policy, password_require_special: e.target.checked })} />
                Require special character
              </label>
            </div>
          </div>
        </section>

        {/* Lockout Policy */}
        <section className="rounded-lg border border-gray-200 bg-white p-4 dark:border-gray-800 dark:bg-gray-950">
          <h2 className="text-sm font-medium mb-3">Lockout Policy</h2>
          <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
            <div>
              <label className="block text-xs text-gray-500 mb-1">Failed Attempts Before Lock</label>
              <input type="number" min={3} max={20} value={policy.lockout_threshold}
                onChange={e => setPolicy({ ...policy, lockout_threshold: parseInt(e.target.value) || 5 })}
                className="w-full rounded border border-gray-300 px-2 py-1 text-sm min-h-[36px] dark:border-gray-700 dark:bg-gray-900 dark:text-white" />
            </div>
            <div>
              <label className="block text-xs text-gray-500 mb-1">Lock Duration (minutes)</label>
              <input type="number" min={1} max={1440} value={policy.lockout_duration_minutes}
                onChange={e => setPolicy({ ...policy, lockout_duration_minutes: parseInt(e.target.value) || 15 })}
                className="w-full rounded border border-gray-300 px-2 py-1 text-sm min-h-[36px] dark:border-gray-700 dark:bg-gray-900 dark:text-white" />
            </div>
          </div>
        </section>

        {/* Session Policy */}
        <section className="rounded-lg border border-gray-200 bg-white p-4 dark:border-gray-800 dark:bg-gray-950">
          <h2 className="text-sm font-medium mb-3">Session Policy</h2>
          <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
            <div>
              <label className="block text-xs text-gray-500 mb-1">Idle Timeout (minutes)</label>
              <input type="number" min={5} max={1440} value={policy.session_idle_timeout_minutes}
                onChange={e => setPolicy({ ...policy, session_idle_timeout_minutes: parseInt(e.target.value) || 240 })}
                className="w-full rounded border border-gray-300 px-2 py-1 text-sm min-h-[36px] dark:border-gray-700 dark:bg-gray-900 dark:text-white" />
            </div>
            <div>
              <label className="block text-xs text-gray-500 mb-1">Max Concurrent Sessions</label>
              <input type="number" min={1} max={20} value={policy.session_max_concurrent}
                onChange={e => setPolicy({ ...policy, session_max_concurrent: parseInt(e.target.value) || 5 })}
                className="w-full rounded border border-gray-300 px-2 py-1 text-sm min-h-[36px] dark:border-gray-700 dark:bg-gray-900 dark:text-white" />
            </div>
          </div>
        </section>

        {/* MFA Policy */}
        <section className="rounded-lg border border-gray-200 bg-white p-4 dark:border-gray-800 dark:bg-gray-950">
          <h2 className="text-sm font-medium mb-3">MFA Policy</h2>
          <div>
            <label className="block text-xs text-gray-500 mb-1">MFA Requirement</label>
            <select value={policy.mfa_mode} onChange={e => setPolicy({ ...policy, mfa_mode: e.target.value as SecurityPolicy['mfa_mode'] })}
              className="w-full max-w-xs rounded border border-gray-300 px-2 py-1 text-sm min-h-[36px] dark:border-gray-700 dark:bg-gray-900 dark:text-white">
              <option value="optional">Optional — users can choose to enrol</option>
              <option value="encouraged">Encouraged — prompt on login but allow skip</option>
              <option value="required">Required — must enrol MFA before first use</option>
            </select>
          </div>
        </section>

        <button type="submit" disabled={saving}
          className="rounded-md bg-indigo-600 px-4 py-2 text-sm font-medium text-white min-h-[44px] hover:bg-indigo-700 disabled:opacity-50">
          {saving ? 'Saving…' : 'Save Security Policy'}
        </button>
      </form>
    </div>
  )
}
