import { useState, useEffect, useCallback } from 'react'
import apiClient from '../../api/client'
import { Button, Input, Select, Spinner } from '../../components/ui'

/* ------------------------------------------------------------------ */
/*  Types                                                              */
/* ------------------------------------------------------------------ */

interface BackendOverdueRule {
  id: string
  org_id: string
  days_after_due: number
  send_email: boolean
  send_sms: boolean
  sort_order: number
  is_enabled: boolean
}

interface OverdueRulesResponse {
  rules: BackendOverdueRule[]
  total: number
  reminders_enabled: boolean
}

/** UI-facing rule with a derived `channel` for the dropdown. */
interface OverdueRule {
  id: string
  days_after_due: number
  channel: 'email' | 'sms' | 'both'
  send_email: boolean
  send_sms: boolean
  is_enabled: boolean
  /** true when the rule hasn't been persisted yet */
  _isNew?: boolean
}

const MAX_RULES = 3

const CHANNEL_OPTIONS = [
  { value: 'email', label: 'Email only' },
  { value: 'sms', label: 'SMS only' },
  { value: 'both', label: 'Email + SMS' },
]

/* ------------------------------------------------------------------ */
/*  Mapping helpers: channel ↔ send_email / send_sms                   */
/* ------------------------------------------------------------------ */

function channelFromBooleans(send_email: boolean, send_sms: boolean): 'email' | 'sms' | 'both' {
  if (send_email && send_sms) return 'both'
  if (send_sms) return 'sms'
  return 'email'
}

function booleansFromChannel(channel: 'email' | 'sms' | 'both'): { send_email: boolean; send_sms: boolean } {
  switch (channel) {
    case 'both':
      return { send_email: true, send_sms: true }
    case 'sms':
      return { send_email: false, send_sms: true }
    case 'email':
    default:
      return { send_email: true, send_sms: false }
  }
}

function backendToUiRule(rule: BackendOverdueRule): OverdueRule {
  return {
    id: rule.id,
    days_after_due: rule.days_after_due,
    channel: channelFromBooleans(rule.send_email, rule.send_sms),
    send_email: rule.send_email,
    send_sms: rule.send_sms,
    is_enabled: rule.is_enabled,
  }
}

/**
 * Overdue reminder rules configuration — up to 3 rules per org,
 * each specifying days after due date and channel (email/SMS/both).
 * Feature is disabled by default, automatic once enabled.
 *
 * Requirements: 38.1, 38.2, 38.3, 38.4
 */
export default function OverdueRules() {
  const [enabled, setEnabled] = useState(false)
  const [rules, setRules] = useState<OverdueRule[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const [saving, setSaving] = useState(false)

  const fetchRules = useCallback(async () => {
    setLoading(true)
    setError('')
    try {
      const res = await apiClient.get<OverdueRulesResponse>('/notifications/overdue-rules')
      setEnabled(res.data.reminders_enabled)
      setRules((res.data?.rules ?? []).map(backendToUiRule))
    } catch {
      setError('Failed to load overdue reminder rules.')
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => { fetchRules() }, [fetchRules])

  const toggleEnabled = async () => {
    setSaving(true)
    setError('')
    try {
      await apiClient.put(`/notifications/overdue-rules-toggle?enabled=${!enabled}`)
      setEnabled(!enabled)
    } catch {
      setError('Failed to update overdue reminders.')
    } finally {
      setSaving(false)
    }
  }

  const addRule = () => {
    if (rules.length >= MAX_RULES) return
    setRules((prev) => [
      ...prev,
      {
        id: `new-${Date.now()}`,
        days_after_due: 7,
        channel: 'email',
        send_email: true,
        send_sms: false,
        is_enabled: true,
        _isNew: true,
      },
    ])
  }

  const updateRule = (index: number, updates: Partial<OverdueRule>) => {
    setRules((prev) =>
      prev.map((r, i) => {
        if (i !== index) return r
        const merged = { ...r, ...updates }
        // Keep send_email/send_sms in sync when channel changes
        if (updates.channel) {
          const bools = booleansFromChannel(updates.channel)
          merged.send_email = bools.send_email
          merged.send_sms = bools.send_sms
        }
        return merged
      }),
    )
  }

  const removeRule = async (index: number) => {
    const rule = rules[index]
    if (!rule._isNew) {
      setSaving(true)
      setError('')
      try {
        await apiClient.delete(`/notifications/overdue-rules/${rule.id}`)
      } catch {
        setError('Failed to delete rule.')
        setSaving(false)
        return
      } finally {
        setSaving(false)
      }
    }
    setRules((prev) => prev.filter((_, i) => i !== index))
  }

  const handleSave = async () => {
    setSaving(true)
    setError('')
    try {
      for (const rule of rules) {
        const payload = {
          days_after_due: rule.days_after_due,
          send_email: rule.send_email,
          send_sms: rule.send_sms,
          is_enabled: rule.is_enabled,
        }
        if (rule._isNew) {
          await apiClient.post('/notifications/overdue-rules', payload)
        } else {
          await apiClient.put(`/notifications/overdue-rules/${rule.id}`, payload)
        }
      }
      // Re-fetch to get server-assigned IDs and clear _isNew flags
      await fetchRules()
    } catch {
      setError('Failed to save overdue reminder rules.')
    } finally {
      setSaving(false)
    }
  }

  if (loading) {
    return <div className="py-16"><Spinner label="Loading overdue rules" /></div>
  }

  return (
    <div>
      <p className="text-sm text-gray-500 mb-6">
        Configure automated reminders for overdue invoices. Up to {MAX_RULES} rules per organisation.
        Reminders skip voided and fully paid invoices.
      </p>

      {error && (
        <div className="mb-4 rounded-md border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700" role="alert">
          {error}
        </div>
      )}

      {/* Master toggle */}
      <div className="mb-6 flex items-center gap-3 rounded-lg border border-gray-200 bg-white px-4 py-4">
        <button
          role="switch"
          aria-checked={enabled}
          aria-label="Enable overdue payment reminders"
          onClick={toggleEnabled}
          disabled={saving}
          className={`relative inline-flex h-6 w-11 shrink-0 cursor-pointer rounded-full border-2 border-transparent transition-colors
            focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-blue-500 focus-visible:ring-offset-2
            ${enabled ? 'bg-blue-600' : 'bg-gray-200'}
            ${saving ? 'opacity-50' : ''}`}
        >
          <span
            aria-hidden="true"
            className={`pointer-events-none inline-block h-5 w-5 rounded-full bg-white shadow ring-0 transition-transform
              ${enabled ? 'translate-x-5' : 'translate-x-0'}`}
          />
        </button>
        <div>
          <span className="text-sm font-medium text-gray-900">Overdue payment reminders</span>
          <p className="text-xs text-gray-500">
            {enabled
              ? 'Reminders are active and will be sent automatically.'
              : 'Reminders are disabled. Enable to start sending automatically.'}
          </p>
        </div>
      </div>

      {/* Rules list */}
      {enabled && (
        <div className="space-y-4">
          {rules.map((rule, idx) => (
            <div key={rule.id} className="flex flex-col gap-3 sm:flex-row sm:items-end rounded-lg border border-gray-200 bg-white px-4 py-4">
              <div className="flex-1">
                <Input
                  label={`Rule ${idx + 1} — Days after due date`}
                  type="number"
                  min={1}
                  max={365}
                  value={String(rule.days_after_due)}
                  onChange={(e) => updateRule(idx, { days_after_due: Math.max(1, parseInt(e.target.value) || 1) })}
                />
              </div>
              <div className="w-48">
                <Select
                  label="Send via"
                  value={rule.channel}
                  onChange={(e) => updateRule(idx, { channel: e.target.value as OverdueRule['channel'] })}
                  options={CHANNEL_OPTIONS}
                />
              </div>
              <Button size="sm" variant="secondary" onClick={() => removeRule(idx)}>
                Remove
              </Button>
            </div>
          ))}

          {rules.length < MAX_RULES && (
            <Button size="sm" variant="secondary" onClick={addRule}>
              + Add Rule
            </Button>
          )}

          {rules.length > 0 && (
            <div className="flex justify-end pt-2">
              <Button onClick={handleSave} loading={saving}>Save Rules</Button>
            </div>
          )}

          {rules.length === 0 && (
            <p className="text-sm text-gray-500 italic">
              No rules configured. Add a rule to start sending overdue reminders.
            </p>
          )}
        </div>
      )}
    </div>
  )
}
