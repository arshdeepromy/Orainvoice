import { useState, useCallback } from 'react'
import type { NotificationPreference } from '@shared/types/notification'
import { useApiList } from '@/hooks/useApiList'
import { MobileCard, MobileSpinner } from '@/components/ui'
import { PullRefresh } from '@/components/gestures/PullRefresh'
import apiClient from '@/api/client'

/**
 * Notification preferences screen — list of notification categories with
 * toggles. Toggle updates preference via backend API.
 *
 * Requirements: 29.1, 29.2, 29.3, 29.4
 */
export default function NotificationPreferencesScreen() {
  const [updatingIds, setUpdatingIds] = useState<Set<string>>(new Set())

  const {
    items: preferences,
    isLoading,
    isRefreshing,
    refresh,
  } = useApiList<NotificationPreference>({
    endpoint: '/api/v1/notifications/preferences',
    dataKey: 'items',
    pageSize: 50,
  })

  // Local state for optimistic updates
  const [localOverrides, setLocalOverrides] = useState<Record<string, boolean>>({})

  const handleToggle = useCallback(
    async (pref: NotificationPreference) => {
      const newEnabled = !(localOverrides[pref.category] ?? pref.enabled)

      // Optimistic update
      setLocalOverrides((prev) => ({ ...prev, [pref.category]: newEnabled }))
      setUpdatingIds((prev) => new Set(prev).add(pref.category))

      try {
        await apiClient.put(`/api/v1/notifications/preferences/${pref.category}`, {
          enabled: newEnabled,
        })
      } catch {
        // Revert on failure
        setLocalOverrides((prev) => {
          const next = { ...prev }
          delete next[pref.category]
          return next
        })
      } finally {
        setUpdatingIds((prev) => {
          const next = new Set(prev)
          next.delete(pref.category)
          return next
        })
      }
    },
    [localOverrides],
  )

  const handleRefresh = useCallback(async () => {
    setLocalOverrides({})
    await refresh()
  }, [refresh])

  return (
    <PullRefresh onRefresh={handleRefresh} isRefreshing={isRefreshing}>
      <div className="flex flex-col gap-4 p-4">
        <h1 className="text-xl font-semibold text-gray-900 dark:text-gray-100">
          Notification Preferences
        </h1>

        <p className="text-sm text-gray-500 dark:text-gray-400">
          Choose which notifications you want to receive.
        </p>

        {isLoading ? (
          <div className="flex justify-center py-8">
            <MobileSpinner size="md" />
          </div>
        ) : preferences.length === 0 ? (
          <p className="py-8 text-center text-sm text-gray-400 dark:text-gray-500">
            No notification preferences available
          </p>
        ) : (
          <MobileCard>
            <div className="flex flex-col divide-y divide-gray-100 dark:divide-gray-700">
              {preferences.map((pref) => {
                const isEnabled = localOverrides[pref.category] ?? pref.enabled
                const isUpdating = updatingIds.has(pref.category)

                return (
                  <div
                    key={pref.category}
                    className="flex items-center justify-between py-3"
                  >
                    <div className="min-w-0 flex-1">
                      <p className="text-sm font-medium text-gray-900 dark:text-gray-100">
                        {pref.label ?? pref.category}
                      </p>
                    </div>
                    <button
                      type="button"
                      role="switch"
                      aria-checked={isEnabled}
                      aria-label={`${pref.label ?? pref.category} notifications`}
                      onClick={() => handleToggle(pref)}
                      disabled={isUpdating}
                      className={`relative inline-flex h-7 w-12 min-w-[48px] flex-shrink-0 items-center rounded-full transition-colors ${
                        isEnabled
                          ? 'bg-blue-600 dark:bg-blue-500'
                          : 'bg-gray-300 dark:bg-gray-600'
                      } ${isUpdating ? 'opacity-50' : ''}`}
                    >
                      <span
                        className={`inline-block h-5 w-5 transform rounded-full bg-white shadow transition-transform ${
                          isEnabled ? 'translate-x-6' : 'translate-x-1'
                        }`}
                      />
                    </button>
                  </div>
                )
              })}
            </div>
          </MobileCard>
        )}
      </div>
    </PullRefresh>
  )
}
