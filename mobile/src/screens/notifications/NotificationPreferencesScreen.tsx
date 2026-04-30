import { useState, useCallback, useRef, useEffect } from 'react'
import { Page, List, ListItem, Block, Preloader, Toggle } from 'konsta/react'
import { PullRefresh } from '@/components/gestures/PullRefresh'
import apiClient from '@/api/client'

interface NotificationPreference {
  category: string
  label: string | null
  enabled: boolean
  description: string | null
}

/**
 * Notification Preferences screen — preferences with Toggle. No module gate.
 * Requirements: 47.1, 47.2, 47.3, 47.4
 */
export default function NotificationPreferencesScreen() {
  const [preferences, setPreferences] = useState<NotificationPreference[]>([])
  const [isLoading, setIsLoading] = useState(true)
  const [isRefreshing, setIsRefreshing] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [updatingIds, setUpdatingIds] = useState<Set<string>>(new Set())
  const [localOverrides, setLocalOverrides] = useState<Record<string, boolean>>({})

  const abortRef = useRef<AbortController | null>(null)

  const fetchPrefs = useCallback(async (isRefresh: boolean, signal: AbortSignal) => {
    if (isRefresh) setIsRefreshing(true); else setIsLoading(true)
    setError(null)
    try {
      const res = await apiClient.get<{ items?: NotificationPreference[]; total?: number }>('/api/v1/notifications/preferences', { params: { offset: 0, limit: 50 }, signal })
      setPreferences(res.data?.items ?? [])
    } catch (err: unknown) {
      if ((err as { name?: string })?.name !== 'CanceledError') setError('Failed to load preferences')
    } finally { setIsLoading(false); setIsRefreshing(false) }
  }, [])

  useEffect(() => {
    abortRef.current?.abort()
    const c = new AbortController(); abortRef.current = c
    fetchPrefs(false, c.signal)
    return () => c.abort()
  }, [fetchPrefs])

  const handleRefresh = useCallback(async () => {
    setLocalOverrides({})
    abortRef.current?.abort()
    const c = new AbortController(); abortRef.current = c
    await fetchPrefs(true, c.signal)
  }, [fetchPrefs])

  const handleToggle = useCallback(async (pref: NotificationPreference) => {
    const newEnabled = !(localOverrides[pref.category] ?? pref.enabled)

    // Optimistic update
    setLocalOverrides((prev) => ({ ...prev, [pref.category]: newEnabled }))
    setUpdatingIds((prev) => new Set(prev).add(pref.category))

    try {
      await apiClient.put(`/api/v1/notifications/preferences/${pref.category}`, { enabled: newEnabled })
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
  }, [localOverrides])

  if (isLoading) {
    return (<Page data-testid="notifications-page"><div className="flex flex-1 items-center justify-center p-8"><Preloader /></div></Page>)
  }

  return (
    <Page data-testid="notifications-page">
      <PullRefresh onRefresh={handleRefresh} isRefreshing={isRefreshing}>
        <div className="flex flex-col pb-24">
          <Block>
            <p className="text-sm text-gray-500 dark:text-gray-400">
              Choose which notifications you want to receive.
            </p>
          </Block>

          {error && (
            <Block><div role="alert" className="rounded-lg bg-red-50 p-3 text-sm text-red-700 dark:bg-red-900/30 dark:text-red-300">{error}</div></Block>
          )}

          {preferences.length === 0 ? (
            <Block className="text-center"><p className="text-sm text-gray-400 dark:text-gray-500">No notification preferences available</p></Block>
          ) : (
            <List strongIos outlineIos dividersIos data-testid="notification-prefs-list">
              {preferences.map((pref) => {
                const isEnabled = localOverrides[pref.category] ?? pref.enabled
                const isUpdating = updatingIds.has(pref.category)

                return (
                  <ListItem
                    key={pref.category}
                    title={<span className="text-gray-900 dark:text-gray-100">{pref.label ?? pref.category}</span>}
                    subtitle={pref.description ? <span className="text-xs text-gray-500 dark:text-gray-400">{pref.description}</span> : undefined}
                    after={
                      <Toggle
                        checked={isEnabled}
                        onChange={() => handleToggle(pref)}
                        disabled={isUpdating}
                        data-testid={`toggle-${pref.category}`}
                      />
                    }
                    data-testid={`pref-item-${pref.category}`}
                  />
                )
              })}
            </List>
          )}
        </div>
      </PullRefresh>
    </Page>
  )
}
