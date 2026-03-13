import { useState, useEffect, useCallback } from 'react'
import apiClient from '../../api/client'
import { Spinner, Badge } from '../../components/ui'
import { useModules } from '../../contexts/ModuleContext'

/* ------------------------------------------------------------------ */
/*  Types — aligned to backend grouped response                        */
/* ------------------------------------------------------------------ */

interface NotificationPref {
  notification_type: string
  is_enabled: boolean
  channel: 'email' | 'sms' | 'both'
}

interface CategoryGroup {
  category: string
  preferences: NotificationPref[]
}

interface PreferencesResponse {
  categories: CategoryGroup[]
}

/**
 * Notification preferences — individually toggleable per notification type,
 * grouped by category, with independent channel config (email/SMS/both).
 *
 * Requirements: 83.1, 83.2, 83.3, 83.4
 */
export default function NotificationPreferences() {
  const [categories, setCategories] = useState<CategoryGroup[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const [saving, setSaving] = useState<string | null>(null)
  const { isEnabled } = useModules()

  const fetchPrefs = useCallback(async () => {
    setLoading(true)
    setError('')
    try {
      const res = await apiClient.get<PreferencesResponse>('/notifications/settings')
      setCategories(res.data.categories)
    } catch {
      setError('Failed to load notification preferences.')
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => { fetchPrefs() }, [fetchPrefs])

  const updatePref = async (
    notificationType: string,
    updates: { is_enabled?: boolean; channel?: 'email' | 'sms' | 'both' },
  ) => {
    setSaving(notificationType)

    // Find current pref across all categories
    let current: NotificationPref | undefined
    for (const cat of categories) {
      current = cat.preferences.find((p) => p.notification_type === notificationType)
      if (current) break
    }
    if (!current) return

    const updated: NotificationPref = {
      ...current,
      ...updates,
    }

    // Optimistic update
    setCategories((prev) =>
      prev.map((cat) => ({
        ...cat,
        preferences: cat.preferences.map((p) =>
          p.notification_type === notificationType ? updated : p,
        ),
      })),
    )

    try {
      await apiClient.put('/notifications/settings', {
        notification_type: notificationType,
        is_enabled: updated.is_enabled,
        channel: updated.channel,
      })
    } catch {
      // Revert on failure
      setCategories((prev) =>
        prev.map((cat) => ({
          ...cat,
          preferences: cat.preferences.map((p) =>
            p.notification_type === notificationType ? current! : p,
          ),
        })),
      )
      setError('Failed to save preference.')
    } finally {
      setSaving(null)
    }
  }

  /** Format notification_type for display (e.g. "invoice_issued" → "Invoice Issued") */
  const formatLabel = (notificationType: string) =>
    notificationType
      .split('_')
      .map((w) => w.charAt(0).toUpperCase() + w.slice(1))
      .join(' ')

  if (loading) {
    return <div className="py-16"><Spinner label="Loading preferences" /></div>
  }

  if (error && !categories.length) {
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
        {categories
          .filter((group) => {
            // Hide "Vehicle Reminders" when vehicles module is disabled
            if (group.category === 'Vehicle Reminders' && !isEnabled('vehicles')) return false
            return true
          })
          .map((group) => (
          <section key={group.category} aria-labelledby={`cat-${group.category}`}>
            <div className="mb-3">
              <h3 id={`cat-${group.category}`} className="text-lg font-medium text-gray-900">{group.category}</h3>
            </div>

            {group.preferences.length === 0 ? (
              <p className="text-sm text-gray-400 italic">No notification types in this category.</p>
            ) : (
              <div className="divide-y divide-gray-100 rounded-lg border border-gray-200 bg-white">
                {group.preferences.map((pref) => (
                  <div key={pref.notification_type} className="flex flex-col gap-3 px-4 py-4 sm:flex-row sm:items-center sm:justify-between">
                    <div className="flex items-center gap-3 min-w-0">
                      {/* Enable/disable toggle */}
                      <button
                        role="switch"
                        aria-checked={pref.is_enabled}
                        aria-label={`Toggle ${formatLabel(pref.notification_type)}`}
                        onClick={() => updatePref(pref.notification_type, { is_enabled: !pref.is_enabled })}
                        disabled={saving === pref.notification_type}
                        className={`relative inline-flex h-6 w-11 shrink-0 cursor-pointer rounded-full border-2 border-transparent transition-colors
                          focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-blue-500 focus-visible:ring-offset-2
                          ${pref.is_enabled ? 'bg-blue-600' : 'bg-gray-200'}
                          ${saving === pref.notification_type ? 'opacity-50' : ''}`}
                      >
                        <span
                          aria-hidden="true"
                          className={`pointer-events-none inline-block h-5 w-5 rounded-full bg-white shadow ring-0 transition-transform
                            ${pref.is_enabled ? 'translate-x-5' : 'translate-x-0'}`}
                        />
                      </button>
                      <div className="min-w-0">
                        <span className="text-sm font-medium text-gray-900">{formatLabel(pref.notification_type)}</span>
                        {pref.is_enabled && (
                          <Badge variant="success" className="ml-2">Active</Badge>
                        )}
                      </div>
                    </div>

                    {/* Channel selector — only shown when enabled */}
                    {pref.is_enabled && (
                      <div className="flex items-center gap-4 ml-14 sm:ml-0">
                        <select
                          value={pref.channel}
                          onChange={(e) => updatePref(pref.notification_type, { channel: e.target.value as 'email' | 'sms' | 'both' })}
                          disabled={saving === pref.notification_type}
                          className="rounded-md border-gray-300 text-sm focus:border-blue-500 focus:ring-blue-500"
                          aria-label={`Channel for ${formatLabel(pref.notification_type)}`}
                        >
                          <option value="email">Email</option>
                          <option value="sms">SMS</option>
                          <option value="both">Both</option>
                        </select>
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
