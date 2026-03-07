import { useState, useEffect, useCallback } from 'react'
import apiClient from '../../api/client'
import { Button, Input, Select, Spinner } from '../../components/ui'

/* ------------------------------------------------------------------ */
/*  Types                                                              */
/* ------------------------------------------------------------------ */

interface WofRegoSettings {
  wof_enabled: boolean
  wof_days_in_advance: number
  rego_enabled: boolean
  rego_days_in_advance: number
  channel: 'email' | 'sms' | 'both'
}

const CHANNEL_OPTIONS = [
  { value: 'email', label: 'Email only' },
  { value: 'sms', label: 'SMS only' },
  { value: 'both', label: 'Email + SMS' },
]

/**
 * WOF and registration expiry reminder settings — enable/disable per org,
 * configurable days in advance, channel selection.
 *
 * Requirements: 39.1, 39.2, 39.3, 39.4
 */
export default function WofRegoReminders() {
  const [settings, setSettings] = useState<WofRegoSettings>({
    wof_enabled: false,
    wof_days_in_advance: 30,
    rego_enabled: false,
    rego_days_in_advance: 30,
    channel: 'email',
  })
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const [saving, setSaving] = useState(false)
  const [saved, setSaved] = useState(false)

  const fetchSettings = useCallback(async () => {
    setLoading(true)
    setError('')
    try {
      const res = await apiClient.get<WofRegoSettings>('/notifications/wof-rego-settings')
      setSettings(res.data)
    } catch {
      setError('Failed to load WOF/rego reminder settings.')
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => { fetchSettings() }, [fetchSettings])

  const update = (updates: Partial<WofRegoSettings>) => {
    setSettings((prev) => ({ ...prev, ...updates }))
    setSaved(false)
  }

  const handleSave = async () => {
    setSaving(true)
    setError('')
    setSaved(false)
    try {
      await apiClient.put('/notifications/wof-rego-settings', settings)
      setSaved(true)
    } catch {
      setError('Failed to save WOF/rego reminder settings.')
    } finally {
      setSaving(false)
    }
  }

  if (loading) {
    return <div className="py-16"><Spinner label="Loading WOF/rego settings" /></div>
  }

  return (
    <div>
      <p className="text-sm text-gray-500 mb-6">
        Send automated reminders to customers when their vehicle's WOF or registration is about to expire.
        Reminders include the vehicle rego, expiry type, date, and your workshop contact details.
      </p>

      {error && (
        <div className="mb-4 rounded-md border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700" role="alert">
          {error}
        </div>
      )}

      {saved && (
        <div className="mb-4 rounded-md border border-green-200 bg-green-50 px-4 py-3 text-sm text-green-700" role="status">
          Settings saved successfully.
        </div>
      )}

      <div className="space-y-6">
        {/* WOF Reminders */}
        <div className="rounded-lg border border-gray-200 bg-white p-4 space-y-4">
          <div className="flex items-center gap-3">
            <button
              role="switch"
              aria-checked={settings.wof_enabled}
              aria-label="Enable WOF expiry reminders"
              onClick={() => update({ wof_enabled: !settings.wof_enabled })}
              className={`relative inline-flex h-6 w-11 shrink-0 cursor-pointer rounded-full border-2 border-transparent transition-colors
                focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-blue-500 focus-visible:ring-offset-2
                ${settings.wof_enabled ? 'bg-blue-600' : 'bg-gray-200'}`}
            >
              <span
                aria-hidden="true"
                className={`pointer-events-none inline-block h-5 w-5 rounded-full bg-white shadow ring-0 transition-transform
                  ${settings.wof_enabled ? 'translate-x-5' : 'translate-x-0'}`}
              />
            </button>
            <div>
              <span className="text-sm font-medium text-gray-900">WOF Expiry Reminders</span>
              <p className="text-xs text-gray-500">
                {settings.wof_enabled
                  ? 'Active — reminders sent automatically.'
                  : 'Disabled — no WOF reminders will be sent.'}
              </p>
            </div>
          </div>

          {settings.wof_enabled && (
            <div className="ml-14 max-w-xs">
              <Input
                label="Days before expiry"
                type="number"
                min={1}
                max={90}
                value={String(settings.wof_days_in_advance)}
                onChange={(e) => update({ wof_days_in_advance: Math.max(1, parseInt(e.target.value) || 30) })}
              />
            </div>
          )}
        </div>

        {/* Registration Reminders */}
        <div className="rounded-lg border border-gray-200 bg-white p-4 space-y-4">
          <div className="flex items-center gap-3">
            <button
              role="switch"
              aria-checked={settings.rego_enabled}
              aria-label="Enable registration expiry reminders"
              onClick={() => update({ rego_enabled: !settings.rego_enabled })}
              className={`relative inline-flex h-6 w-11 shrink-0 cursor-pointer rounded-full border-2 border-transparent transition-colors
                focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-blue-500 focus-visible:ring-offset-2
                ${settings.rego_enabled ? 'bg-blue-600' : 'bg-gray-200'}`}
            >
              <span
                aria-hidden="true"
                className={`pointer-events-none inline-block h-5 w-5 rounded-full bg-white shadow ring-0 transition-transform
                  ${settings.rego_enabled ? 'translate-x-5' : 'translate-x-0'}`}
              />
            </button>
            <div>
              <span className="text-sm font-medium text-gray-900">Registration Expiry Reminders</span>
              <p className="text-xs text-gray-500">
                {settings.rego_enabled
                  ? 'Active — reminders sent automatically.'
                  : 'Disabled — no registration reminders will be sent.'}
              </p>
            </div>
          </div>

          {settings.rego_enabled && (
            <div className="ml-14 max-w-xs">
              <Input
                label="Days before expiry"
                type="number"
                min={1}
                max={90}
                value={String(settings.rego_days_in_advance)}
                onChange={(e) => update({ rego_days_in_advance: Math.max(1, parseInt(e.target.value) || 30) })}
              />
            </div>
          )}
        </div>

        {/* Shared channel config */}
        {(settings.wof_enabled || settings.rego_enabled) && (
          <div className="rounded-lg border border-gray-200 bg-white p-4">
            <div className="max-w-xs">
              <Select
                label="Reminder channel"
                value={settings.channel}
                onChange={(e) => update({ channel: e.target.value as WofRegoSettings['channel'] })}
                options={CHANNEL_OPTIONS}
              />
              <p className="mt-1 text-xs text-gray-500">
                Applies to both WOF and registration reminders.
              </p>
            </div>
          </div>
        )}

        {/* Save */}
        <div className="flex justify-end">
          <Button onClick={handleSave} loading={saving}>Save Settings</Button>
        </div>
      </div>
    </div>
  )
}
