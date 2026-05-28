import { useState, useEffect, useCallback } from 'react'
import { useNavigate } from 'react-router-dom'
import { Popover, PopoverButton, PopoverPanel } from '@headlessui/react'
import apiClient from '@/api/client'
import { Spinner } from '@/components/ui/Spinner'
import InboxBellBadge from './InboxBellBadge'

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

interface InboxItem {
  id: string
  category: string
  severity: string
  title: string
  body: string | null
  link_url: string | null
  entity_type: string | null
  entity_id: string | null
  metadata: Record<string, unknown>
  created_at: string
  is_read: boolean
  read_at: string | null
}

interface InboxResponse {
  items: InboxItem[]
  total: number
  unread_count: number
}

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

/** Simple relative time formatter — no external dependency. */
function formatRelativeTime(isoDate: string): string {
  const now = Date.now()
  const then = new Date(isoDate).getTime()
  if (isNaN(then)) return ''
  const diffSec = Math.max(0, Math.round((now - then) / 1000))

  if (diffSec < 60) return 'just now'
  const diffMin = Math.round(diffSec / 60)
  if (diffMin < 60) return `${diffMin}m ago`
  const diffHr = Math.round(diffMin / 60)
  if (diffHr < 24) return `${diffHr}h ago`
  const diffDay = Math.round(diffHr / 24)
  if (diffDay < 30) return `${diffDay}d ago`
  return new Date(isoDate).toLocaleDateString()
}

/** Returns Tailwind classes for the severity icon. */
function severityClasses(severity: string): { bg: string; text: string } {
  switch (severity) {
    case 'error':
      return { bg: 'bg-red-50 dark:bg-red-900/30', text: 'text-red-500' }
    case 'warning':
      return { bg: 'bg-amber-50 dark:bg-amber-900/30', text: 'text-amber-500' }
    case 'success':
      return { bg: 'bg-green-50 dark:bg-green-900/30', text: 'text-green-500' }
    default:
      return { bg: 'bg-blue-50 dark:bg-blue-900/30', text: 'text-blue-500' }
  }
}

/** SVG icon per severity. */
function SeverityIcon({ severity }: { severity: string }) {
  const { bg, text } = severityClasses(severity)
  const cls = `h-8 w-8 flex-shrink-0 flex items-center justify-center rounded-full ${bg}`

  if (severity === 'error') {
    return (
      <span className={cls}>
        <svg className={`h-4 w-4 ${text}`} fill="none" viewBox="0 0 24 24" stroke="currentColor">
          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M6 18L18 6M6 6l12 12" />
        </svg>
      </span>
    )
  }
  if (severity === 'warning') {
    return (
      <span className={cls}>
        <svg className={`h-4 w-4 ${text}`} fill="none" viewBox="0 0 24 24" stroke="currentColor">
          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 9v2m0 4h.01m-6.938 4h13.856c1.54 0 2.502-1.667 1.732-3L13.732 4c-.77-1.333-2.694-1.333-3.464 0L3.34 16c-.77 1.333.192 3 1.732 3z" />
        </svg>
      </span>
    )
  }
  if (severity === 'success') {
    return (
      <span className={cls}>
        <svg className={`h-4 w-4 ${text}`} fill="none" viewBox="0 0 24 24" stroke="currentColor">
          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M5 13l4 4L19 7" />
        </svg>
      </span>
    )
  }
  // info (default)
  return (
    <span className={cls}>
      <svg className={`h-4 w-4 ${text}`} fill="none" viewBox="0 0 24 24" stroke="currentColor">
        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M13 16h-1v-4h-1m1-4h.01M21 12a9 9 0 11-18 0 9 9 0 0118 0z" />
      </svg>
    </span>
  )
}

// ---------------------------------------------------------------------------
// Component
// ---------------------------------------------------------------------------

/**
 * Bell button with badge + dropdown panel showing the 10 most recent
 * notifications. Clicking a notification expands it inline to show full
 * details rather than navigating away.
 *
 * Validates: Requirements 6.1.3, 6.1.4, 6.1.5, 6.1.6
 */
export default function InboxBellDropdown() {
  const navigate = useNavigate()
  const [items, setItems] = useState<InboxItem[]>([])
  const [loading, setLoading] = useState(false)
  const [markingAll, setMarkingAll] = useState(false)
  const [expandedId, setExpandedId] = useState<string | null>(null)

  const fetchInbox = useCallback(async (signal: AbortSignal) => {
    setLoading(true)
    try {
      const res = await apiClient.get<InboxResponse>(
        '/notifications/inbox?limit=10',
        { signal },
      )
      setItems(res.data?.items ?? [])
    } catch {
      // Silently ignore aborted/network errors — dropdown stays empty or stale.
    } finally {
      setLoading(false)
    }
  }, [])

  const handleItemClick = useCallback(
    async (item: InboxItem) => {
      // Toggle expand/collapse
      if (expandedId === item.id) {
        setExpandedId(null)
        return
      }
      setExpandedId(item.id)

      // Mark as read (best-effort)
      if (!item.is_read) {
        try {
          await apiClient.post(`/notifications/inbox/${item.id}/read`)
          setItems((prev) =>
            prev.map((i) => (i.id === item.id ? { ...i, is_read: true } : i)),
          )
        } catch {
          // Best-effort — don't block UI.
        }
      }
    },
    [expandedId],
  )

  const handleMarkAllRead = useCallback(async () => {
    setMarkingAll(true)
    try {
      await apiClient.post('/notifications/inbox/mark-all-read')
      setItems((prev) => prev.map((i) => ({ ...i, is_read: true })))
    } catch {
      // Silent failure — user can retry.
    } finally {
      setMarkingAll(false)
    }
  }, [])

  return (
    <Popover className="relative">
      {({ open, close }) => {
        /* Fetch inbox when panel opens */
        return (
          <>
            <PopoverOpenEffect open={open} onOpen={fetchInbox} />

            <PopoverButton
              className="min-h-[44px] min-w-[44px] flex items-center justify-center rounded-lg text-gray-500 hover:text-gray-700 hover:bg-gray-100 dark:text-gray-400 dark:hover:text-gray-200 dark:hover:bg-gray-700 transition-colors relative"
              aria-label="Notifications"
            >
              <svg className="h-6 w-6" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                <path
                  strokeLinecap="round"
                  strokeLinejoin="round"
                  strokeWidth={2}
                  d="M15 17h5l-1.405-1.405A2.032 2.032 0 0118 14.158V11a6.002 6.002 0 00-4-5.659V5a2 2 0 10-4 0v.341C7.67 6.165 6 8.388 6 11v3.159c0 .538-.214 1.055-.595 1.436L4 17h5m6 0v1a3 3 0 11-6 0v-1m6 0H9"
                />
              </svg>
              <InboxBellBadge />
            </PopoverButton>

            <PopoverPanel
              className="absolute right-0 z-50 mt-2 w-96 rounded-lg border border-gray-200 bg-white shadow-lg dark:border-gray-700 dark:bg-gray-800"
              anchor="bottom end"
            >
              {/* Header */}
              <div className="border-b border-gray-200 px-4 py-3 dark:border-gray-700">
                <h3 className="text-sm font-semibold text-gray-900 dark:text-gray-100">
                  Notifications
                </h3>
              </div>

              {/* Body */}
              <div className="max-h-[420px] overflow-y-auto">
                {loading ? (
                  <div className="flex items-center justify-center py-8">
                    <Spinner size="sm" label="Loading notifications" />
                  </div>
                ) : items.length === 0 ? (
                  <div className="px-4 py-8 text-center text-sm text-gray-500 dark:text-gray-400">
                    No new notifications
                  </div>
                ) : (
                  <ul className="divide-y divide-gray-100 dark:divide-gray-700">
                    {items.map((item) => {
                      const isExpanded = expandedId === item.id
                      return (
                        <li key={item.id}>
                          <button
                            type="button"
                            onClick={() => handleItemClick(item)}
                            className={`flex w-full items-start gap-3 px-4 py-3 text-left transition-colors hover:bg-gray-50 dark:hover:bg-gray-700/50 ${
                              !item.is_read ? 'bg-blue-50/50 dark:bg-blue-900/10' : ''
                            }`}
                          >
                            <SeverityIcon severity={item.severity} />
                            <div className="min-w-0 flex-1">
                              <p className="text-sm font-medium text-gray-900 dark:text-gray-100">
                                {item.title}
                              </p>
                              {!isExpanded && item.body && (
                                <p className="mt-0.5 truncate text-xs text-gray-500 dark:text-gray-400">
                                  {item.body}
                                </p>
                              )}
                              {isExpanded && (
                                <div className="mt-1.5 space-y-1.5">
                                  {item.body && (
                                    <p className="text-xs text-gray-600 dark:text-gray-300 whitespace-pre-wrap break-words">
                                      {item.body}
                                    </p>
                                  )}
                                  <p className="text-[11px] text-gray-400 dark:text-gray-500">
                                    {new Date(item.created_at).toLocaleString()}
                                  </p>
                                </div>
                              )}
                            </div>
                            <span className="flex-shrink-0 text-xs text-gray-400 dark:text-gray-500">
                              {formatRelativeTime(item.created_at)}
                            </span>
                          </button>
                        </li>
                      )
                    })}
                  </ul>
                )}
              </div>

              {/* Footer */}
              <div className="flex items-center justify-between border-t border-gray-200 px-4 py-2 dark:border-gray-700">
                <button
                  type="button"
                  onClick={handleMarkAllRead}
                  disabled={markingAll || items.length === 0}
                  className="text-xs font-medium text-blue-600 hover:text-blue-800 disabled:opacity-50 disabled:cursor-not-allowed dark:text-blue-400 dark:hover:text-blue-300"
                >
                  Mark all as read
                </button>
                <button
                  type="button"
                  onClick={() => {
                    close()
                    navigate('/notifications/inbox')
                  }}
                  className="text-xs font-medium text-blue-600 hover:text-blue-800 dark:text-blue-400 dark:hover:text-blue-300"
                >
                  View all →
                </button>
              </div>
            </PopoverPanel>
          </>
        )
      }}
    </Popover>
  )
}

// ---------------------------------------------------------------------------
// Helper component: triggers fetch when popover opens
// ---------------------------------------------------------------------------

/**
 * Fires `onOpen` with an AbortController signal when `open` transitions
 * from false → true. Cleans up on unmount.
 */
function PopoverOpenEffect({
  open,
  onOpen,
}: {
  open: boolean
  onOpen: (signal: AbortSignal) => void
}) {
  useEffect(() => {
    if (!open) return
    const controller = new AbortController()
    onOpen(controller.signal)
    return () => controller.abort()
  }, [open, onOpen])

  return null
}
