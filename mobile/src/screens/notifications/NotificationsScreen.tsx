import { useState, useCallback, useRef, useEffect, useMemo } from 'react'
import { useNavigate } from 'react-router-dom'
import { PullRefresh } from '@/components/gestures/PullRefresh'
import { MobileList } from '@/components/ui/MobileList'
import { MobileListItem } from '@/components/ui/MobileListItem'
import type { InboxItem, GetInboxParams } from '@/api/inbox'
import { getInbox, markRead } from '@/api/inbox'

/* ------------------------------------------------------------------ */
/* Constants                                                          */
/* ------------------------------------------------------------------ */

const PAGE_SIZE = 25

/** Known mobile routes that link_url values can map to */
const KNOWN_ROUTE_PREFIXES = [
  '/invoices',
  '/quotes',
  '/customers',
  '/bookings',
  '/vehicles',
  '/jobs',
  '/inventory',
  '/staff',
  '/expenses',
  '/recurring',
  '/purchase-orders',
  '/projects',
] as const

/** Filter chip definitions for the unread toggle */
const UNREAD_FILTERS = [
  { key: 'all', label: 'All' },
  { key: 'unread', label: 'Unread' },
] as const

/** Severity filter chips */
const SEVERITY_FILTERS = [
  { key: 'all', label: 'All' },
  { key: 'info', label: 'Info' },
  { key: 'warning', label: 'Warning' },
  { key: 'error', label: 'Error' },
  { key: 'success', label: 'Success' },
] as const

/* ------------------------------------------------------------------ */
/* Helpers                                                            */
/* ------------------------------------------------------------------ */

/** Format a date string as relative time (e.g. "5m ago", "2h ago") */
function formatRelativeTime(dateStr: string | null | undefined): string {
  if (!dateStr) return ''
  try {
    const date = new Date(dateStr)
    const now = new Date()
    const diffMs = now.getTime() - date.getTime()
    const diffMin = Math.floor(diffMs / 60_000)

    if (diffMin < 1) return 'now'
    if (diffMin < 60) return `${diffMin}m ago`
    const diffHr = Math.floor(diffMin / 60)
    if (diffHr < 24) return `${diffHr}h ago`
    const diffDays = Math.floor(diffHr / 24)
    if (diffDays < 30) return `${diffDays}d ago`
    return date.toLocaleDateString('en-NZ', { day: 'numeric', month: 'short' })
  } catch {
    return ''
  }
}

/** Check if a link_url maps to a known mobile route */
function isKnownRoute(linkUrl: string | null | undefined): boolean {
  if (!linkUrl) return false
  return KNOWN_ROUTE_PREFIXES.some((prefix) => linkUrl.startsWith(prefix))
}

/** Get severity icon color classes */
function getSeverityClasses(severity: string): { bg: string; text: string } {
  switch (severity) {
    case 'error':
      return { bg: 'bg-red-50 dark:bg-red-900/30', text: 'text-red-500 dark:text-red-400' }
    case 'warning':
      return { bg: 'bg-amber-50 dark:bg-amber-900/30', text: 'text-amber-500 dark:text-amber-400' }
    case 'success':
      return { bg: 'bg-green-50 dark:bg-green-900/30', text: 'text-green-500 dark:text-green-400' }
    case 'info':
    default:
      return { bg: 'bg-blue-50 dark:bg-blue-900/30', text: 'text-blue-500 dark:text-blue-400' }
  }
}

/* ------------------------------------------------------------------ */
/* Severity Icon Component                                            */
/* ------------------------------------------------------------------ */

function SeverityIcon({ severity }: { severity: string }) {
  const { bg, text } = getSeverityClasses(severity)

  const iconPath = useMemo(() => {
    switch (severity) {
      case 'error':
        return 'M10 14l2-2m0 0l2-2m-2 2l-2-2m2 2l2 2m7-2a9 9 0 11-18 0 9 9 0 0118 0z'
      case 'warning':
        return 'M12 9v2m0 4h.01m-6.938 4h13.856c1.54 0 2.502-1.667 1.732-2.5L13.732 4c-.77-.833-1.964-.833-2.732 0L4.082 16.5c-.77.833.192 2.5 1.732 2.5z'
      case 'success':
        return 'M9 12l2 2 4-4m6 2a9 9 0 11-18 0 9 9 0 0118 0z'
      case 'info':
      default:
        return 'M13 16h-1v-4h-1m1-4h.01M21 12a9 9 0 11-18 0 9 9 0 0118 0z'
    }
  }, [severity])

  return (
    <div className={`flex h-8 w-8 items-center justify-center rounded-full ${bg}`}>
      <svg
        className={`h-5 w-5 ${text}`}
        viewBox="0 0 24 24"
        fill="none"
        stroke="currentColor"
        strokeWidth="1.5"
        strokeLinecap="round"
        strokeLinejoin="round"
        aria-hidden="true"
      >
        <path d={iconPath} />
      </svg>
    </div>
  )
}

/* ------------------------------------------------------------------ */
/* Main Component                                                     */
/* ------------------------------------------------------------------ */

/**
 * Notifications inbox screen for mobile.
 *
 * - PullRefresh + MobileList with infinite scroll
 * - Filter chips: All/Unread toggle + severity filter
 * - Tap row: mark read + navigate (or open detail screen if no known route)
 * - Touch targets ≥44px, dark mode, safe-area
 * - AbortController cleanup on unmount
 *
 * Requirements: 7.2, 7.4, 7.5
 */
export default function NotificationsScreen() {
  const navigate = useNavigate()

  // ── State ──────────────────────────────────────────────────────────
  const [items, setItems] = useState<InboxItem[]>([])
  const [total, setTotal] = useState(0)
  const [isLoading, setIsLoading] = useState(true)
  const [isRefreshing, setIsRefreshing] = useState(false)
  const [offset, setOffset] = useState(0)
  const [unreadFilter, setUnreadFilter] = useState<'all' | 'unread'>('all')
  const [severityFilter, setSeverityFilter] = useState<string>('all')

  const abortRef = useRef<AbortController | null>(null)

  const hasMore = items.length < total

  // ── Fetch data ─────────────────────────────────────────────────────
  const fetchNotifications = useCallback(
    async (currentOffset: number, isRefresh: boolean, signal: AbortSignal) => {
      if (isRefresh) {
        setIsRefreshing(true)
      } else if (currentOffset === 0) {
        setIsLoading(true)
      }

      try {
        const params: GetInboxParams = {
          offset: currentOffset,
          limit: PAGE_SIZE,
        }
        if (unreadFilter === 'unread') {
          params.unread_only = true
        }
        if (severityFilter !== 'all') {
          params.severity = severityFilter
        }

        const res = await getInbox(params, signal)
        const newItems = res?.items ?? []
        const newTotal = res?.total ?? 0

        if (currentOffset === 0 || isRefresh) {
          setItems(newItems)
        } else {
          setItems((prev) => [...prev, ...newItems])
        }
        setTotal(newTotal)
      } catch (err: unknown) {
        if ((err as { name?: string })?.name !== 'CanceledError') {
          // Silently handle — keep last-known state
        }
      } finally {
        setIsLoading(false)
        setIsRefreshing(false)
      }
    },
    [unreadFilter, severityFilter],
  )

  // Fetch on mount and when filters change (reset to offset 0)
  useEffect(() => {
    abortRef.current?.abort()
    const controller = new AbortController()
    abortRef.current = controller

    setOffset(0)
    fetchNotifications(0, false, controller.signal)

    return () => controller.abort()
  }, [fetchNotifications])

  // ── Pull-to-refresh ────────────────────────────────────────────────
  const handleRefresh = useCallback(async () => {
    abortRef.current?.abort()
    const controller = new AbortController()
    abortRef.current = controller

    setOffset(0)
    await fetchNotifications(0, true, controller.signal)
  }, [fetchNotifications])

  // ── Load more (infinite scroll) ───────────────────────────────────
  const handleLoadMore = useCallback(() => {
    if (isLoading || isRefreshing || !hasMore) return

    const nextOffset = offset + PAGE_SIZE
    setOffset(nextOffset)

    abortRef.current?.abort()
    const controller = new AbortController()
    abortRef.current = controller

    fetchNotifications(nextOffset, false, controller.signal)
  }, [isLoading, isRefreshing, hasMore, offset, fetchNotifications])

  // ── Tap row handler ────────────────────────────────────────────────
  const handleTapItem = useCallback(
    async (item: InboxItem) => {
      // Mark as read (fire-and-forget, don't block navigation)
      if (!item.is_read) {
        markRead(item.id).catch(() => {
          // Silently ignore mark-read failures
        })
        // Optimistic update
        setItems((prev) =>
          prev.map((n) => (n.id === item.id ? { ...n, is_read: true } : n)),
        )
      }

      // Navigate or show detail
      const linkUrl = item.link_url
      if (linkUrl && isKnownRoute(linkUrl)) {
        navigate(linkUrl)
      } else {
        // Navigate to detail screen for body view
        navigate(`/notifications/${item.id}`)
      }
    },
    [navigate],
  )

  // ── Render item ────────────────────────────────────────────────────
  const renderItem = useCallback(
    (item: InboxItem) => (
      <MobileListItem
        title={item.title ?? ''}
        subtitle={formatRelativeTime(item.created_at)}
        leading={<SeverityIcon severity={item.severity ?? 'info'} />}
        trailing={
          !item.is_read ? (
            <div className="h-2.5 w-2.5 rounded-full bg-blue-500" aria-label="Unread" />
          ) : undefined
        }
        onTap={() => handleTapItem(item)}
        className="min-h-[44px]"
      />
    ),
    [handleTapItem],
  )

  // ── Empty message based on filters ─────────────────────────────────
  const emptyMessage = useMemo(() => {
    if (unreadFilter === 'unread' || severityFilter !== 'all') {
      return 'No matching notifications'
    }
    return "You're all caught up"
  }, [unreadFilter, severityFilter])

  return (
    <PullRefresh onRefresh={handleRefresh} isRefreshing={isRefreshing}>
      <div className="flex flex-col pb-safe">
        {/* ── Header ──────────────────────────────────────────────── */}
        <div className="flex items-center justify-between px-4 pt-4 pb-1">
          <h1 className="text-xl font-semibold text-gray-900 dark:text-gray-100">
            Notifications
          </h1>
        </div>

        {/* ── Unread filter chips ─────────────────────────────────── */}
        <div className="flex gap-2 overflow-x-auto px-4 py-2">
          {UNREAD_FILTERS.map((filter) => {
            const isActive = unreadFilter === filter.key
            return (
              <button
                key={filter.key}
                type="button"
                onClick={() => setUnreadFilter(filter.key as 'all' | 'unread')}
                className={`min-h-[44px] shrink-0 rounded-full px-4 py-2 text-sm font-medium transition-colors ${
                  isActive
                    ? 'bg-blue-600 text-white dark:bg-blue-500'
                    : 'bg-gray-100 text-gray-700 dark:bg-gray-800 dark:text-gray-300'
                }`}
                data-testid={`filter-unread-${filter.key}`}
              >
                {filter.label}
              </button>
            )
          })}
        </div>

        {/* ── Severity filter chips ───────────────────────────────── */}
        <div className="flex gap-2 overflow-x-auto px-4 pb-2">
          {SEVERITY_FILTERS.map((filter) => {
            const isActive = severityFilter === filter.key
            return (
              <button
                key={filter.key}
                type="button"
                onClick={() => setSeverityFilter(filter.key)}
                className={`min-h-[44px] shrink-0 rounded-full px-4 py-2 text-sm font-medium transition-colors ${
                  isActive
                    ? 'bg-blue-600 text-white dark:bg-blue-500'
                    : 'bg-gray-100 text-gray-700 dark:bg-gray-800 dark:text-gray-300'
                }`}
                data-testid={`filter-severity-${filter.key}`}
              >
                {filter.label}
              </button>
            )
          })}
        </div>

        {/* ── Notification list ───────────────────────────────────── */}
        <MobileList
          items={items}
          renderItem={renderItem}
          onRefresh={handleRefresh}
          onLoadMore={handleLoadMore}
          isLoading={isLoading}
          isRefreshing={isRefreshing}
          hasMore={hasMore}
          emptyMessage={emptyMessage}
          keyExtractor={(item) => item.id}
        />
      </div>
    </PullRefresh>
  )
}
