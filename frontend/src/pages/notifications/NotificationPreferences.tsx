import { useState, useEffect, useCallback } from 'react'
import apiClient from '../../api/client'
import { Spinner, Badge } from '../../components/ui'

/* ------------------------------------------------------------------ */
/*  Types                                                              */
/* ------------------------------------------------------------------ */

interface NotificationPref {
  type: string
  label: string
  category: string
  enabled: boolean
  channels: { email: boolean; sms: boolean }
  supports_sms: boolean
}

interface PreferencesResponse {
  preferences: NotificationPref[]
}

const CATEGORIES = [
  { key: 'invoicing', label: 'Invoicing', description: 'Invoice lifecycle notifications' },
  { key: 'payments', label: 'Payments', description: 'Payment and billing notifications' },
  { key: 'vehicle_reminders', label: 'Vehicle Reminders', description: 'WOF and registration expiry alerts' },
  { key: 'system', label: 'System Alerts', description: 'Storage, subscription, and security alerts' },
]

/**
 * Notification preferences — individually toggleable per notification type,
 * grouped by category, with independent channel config (email/SMS/both).
 *
 * Requirements: 83.1, 83.2, 83.3, 83.4
 */
export default function NotificationPreferences() {
  const [prefs, setPrefs] = useState<NotificationPref[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const [saving, setSaving] = useState<string | null>(null)

  const fetchPrefs = useCallback(async () => {
    setLoading(true)
    setError('')
    try {
      const res = await apiClient.get<PreferencesResponse>('/notifications/settings')
      setPrefs(res.data.preferences)
    } catch {
      setError('Failed to load notification preferences.')
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => { fetchPrefs() }, [fetchPrefs])

  const updatePref = async (type: string, updates: Partial<Pick<NotificationPref, 'enabled' | 'channels'>>) => {
    setSaving(type)
    const current = prefs.find((p) => p.type === type)
    if (!current) return

    const updated = {
      ...current,
      ...updates,
      channels: { ...current.channels, ...(updates.channels || {}) },
    }

    // Optimistic update
    setPrefs((prev) => prev.map((p) => (p.type === type ? updated : p)))

    try {
      await apiClient.put('/notifications/settings', {
        type,
        enabled: updated.enabled,
        channels: updated.channels,
      })
    } catch {
      // Revert on failure
      setPrefs((prev) => prev.map((p) => (p.type === type ? current : p)))
      setError('Failed to save preference.')
    } finally {
      setSaving(null)
    }
  }

  const grouped = CATEGORIES.map((cat) => ({
    ...cat,
    items: prefs.filter((p) => p.category === cat.key),
  }))

  if (loading) {
    return <div className="py-16"><Spinner label="Loading preferences" /></div>
  }

  if (error && !prefs.length) {
    return (
      <div className="rounded-md border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700" role="alert">
        {error}
      </div>
    )
  }

  return (
    <div>
      <p className="text-sm text-gray-500 mb-6">
        Enable or disable individual notification types and configure sending channels. All notifications are disabled by default.
      </p>

      {error && (
        <div className="mb-4 rounded-md border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700" role="alert">
          {error}
        </div>
      )}

      <div className="space-y-8">
        {grouped.map((group) => (
          <section key={group.key} aria-labelledby={`cat-${group.key}`}>
            <div className="mb-3">
              <h3 id={`cat-${group.key}`} className="text-lg font-medium text-gray-900">{group.label}</h3>
              <p className="text-sm text-gray-500">{group.description}</p>
            </div>

            {group.items.length === 0 ? (
              <p className="text-sm text-gray-400 italic">No notification types in this category.</p>
            ) : (
              <div className="divide-y divide-gray-100 rounded-lg border border-gray-200 bg-white">
                {group.items.map((pref) => (
                  <div key={pref.type} className="flex flex-col gap-3 px-4 py-4 sm:flex-row sm:items-center sm:justify-between">
                    <div className="flex items-center gap-3 min-w-0">
                      {/* Enable/disable toggle */}
                      <button
                        role="switch"
                        aria-checked={pref.enabled}
                        aria-label={`Toggle ${pref.label}`}
                        onClick={() => updatePref(pref.type, { enabled: !pref.enabled })}
                        disabled={saving === pref.type}
                        className={`relative inline-flex h-6 w-11 shrink-0 cursor-pointer rounded-full border-2 border-transparent transition-colors
                          focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-blue-500 focus-visible:ring-offset-2
                          ${pref.enabled ? 'bg-blue-600' : 'bg-gray-200'}
                          ${saving === pref.type ? 'opacity-50' : ''}`}
                      >
                        <span
                          aria-hidden="true"
                          className={`pointer-events-none inline-block h-5 w-5 rounded-full bg-white shadow ring-0 transition-transform
                            ${pref.enabled ? 'translate-x-5' : 'translate-x-0'}`}
                        />
                      </button>
                      <div className="min-w-0">
                        <span className="text-sm font-medium text-gray-900">{pref.label}</span>
                        {pref.enabled && (
                          <Badge variant="success" className="ml-2">Active</Badge>
                        )}
                      </div>
                    </div>

                    {/* Channel toggles — only shown when enabled */}
                    {pref.enabled && (
                      <div className="flex items-center gap-4 ml-14 sm:ml-0">
                        <label className="flex items-center gap-2 text-sm text-gray-700 cursor-pointer">
                          <input
                            type="checkbox"
                            checked={pref.channels.email}
                            onChange={(e) => updatePref(pref.type, { channels: { ...pref.channels, email: e.target.checked } })}
                            disabled={saving === pref.type}
                            className="h-4 w-4 rounded border-gray-300 text-blue-600 focus:ring-blue-500"
                          />
                          Email
                        </label>
                        {pref.supports_sms && (
                          <label className="flex items-center gap-2 text-sm text-gray-700 cursor-pointer">
                            <input
                              type="checkbox"
                              checked={pref.channels.sms}
                              onChange={(e) => updatePref(pref.type, { channels: { ...pref.channels, sms: e.target.checked } })}
                              disabled={saving === pref.type}
                              className="h-4 w-4 rounded border-gray-300 text-blue-600 focus:ring-blue-500"
                            />
                            SMS
                          </label>
                        )}
                      </div>
                    )}
                  </div>
                ))}
              </div>
            )}
          </section>
        ))}
      </div>
    </div>
  )
}
