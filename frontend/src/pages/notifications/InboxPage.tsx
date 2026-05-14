import { useState, useEffect, useCallback } from 'react'
import { useSearchParams, useNavigate } from 'react-router-dom'
import apiClient from '../../api/client'
import { Spinner, Pagination, Select } from '../../components/ui'
import InboxItemCard from '@/components/notifications/InboxItemCard'
import type { InboxItemData } from '@/components/notifications/InboxItemCard'

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

interface InboxResponse {
  items: InboxItemData[]
  total: number
  unread_count: number
}

// ---------------------------------------------------------------------------
// Constants
// ---------------------------------------------------------------------------

const PAGE_SIZE = 25

const SEVERITY_OPTIONS = [
  { value: '', label: 'All severities' },
  { value: 'info', label: 'Info' },
  { value: 'success', label: 'Success' },
  { value: 'warning', label: 'Warning' },
  { value: 'error', label: 'Error' },
]

const CATEGORY_OPTIONS = [
  { value: '', label: 'All categories' },
  { value: 'email_failure', label: 'Email Failure' },
  { value: 'sms_failure', label: 'SMS Failure' },
  { value: 'stock_alert', label: 'Stock Alert' },
  { value: 'quote_accepted', label: 'Quote Accepted' },
  { value: 'quote_declined', label: 'Quote Declined' },
  { value: 'payment_received', label: 'Payment Received' },
  { value: 'payment_failed', label: 'Payment Failed' },
  { value: 'invoice_overdue', label: 'Invoice Overdue' },
  { value: 'account_locked', label: 'Account Locked' },
  { value: 'xero_sync_failed', label: 'Xero Sync Failed' },
  { value: 'system', label: 'System' },
]

// ---------------------------------------------------------------------------
// Component
// ---------------------------------------------------------------------------

/**
 * Full inbox page for in-app notifications with filters, pagination,
 * mark-all-read, and dismiss actions.
 *
 * Validates: Requirements 6.2
 */
export default function InboxPage() {
  const navigate = useNavigate()
  const [searchParams, setSearchParams] = useSearchParams()

  // Read filters from URL
  const unreadOnly = searchParams.get('unread') === 'true'
  const severityFilter = searchParams.get('severity') ?? ''
  const categoryFilter = searchParams.get('category') ?? ''
  const pageParam = parseInt(searchParams.get('page') ?? '1', 10)
  const currentPage = isNaN(pageParam) || pageParam < 1 ? 1 : pageParam

  // State
  const [items, setItems] = useState<InboxItemData[]>([])
  const [total, setTotal] = useState(0)
  const [unreadCount, setUnreadCount] = useState(0)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const [actionLoading, setActionLoading] = useState('')

  // ---------------------------------------------------------------------------
  // URL helpers
  // ---------------------------------------------------------------------------

  const updateParams = useCallback(
    (updates: Record<string, string | null>) => {
      setSearchParams((prev) => {
        const next = new URLSearchParams(prev)
        for (const [key, value] of Object.entries(updates)) {
          if (value === null || value === '') {
            next.delete(key)
          } else {
            next.set(key, value)
          }
        }
        return next
      })
    },
    [setSearchParams],
  )

  // ---------------------------------------------------------------------------
  // Fetch inbox
  // ---------------------------------------------------------------------------

  const fetchInbox = useCallback(
    async (signal: AbortSignal) => {
      setLoading(true)
      setError('')
      try {
        const params: Record<string, string | number | boolean> = {
          limit: PAGE_SIZE,
          offset: (currentPage - 1) * PAGE_SIZE,
        }
        if (unreadOnly) params.unread_only = true
        if (severityFilter) params.severity = severityFilter
        if (categoryFilter) params.category = categoryFilter

        const res = await apiClient.get<InboxResponse>('/notifications/inbox', {
          params,
          signal,
        })
        setItems(res.data?.items ?? [])
        setTotal(res.data?.total ?? 0)
        setUnreadCount(res.data?.unread_count ?? 0)
      } catch (err: unknown) {
        if ((err as { name?: string })?.name === 'CanceledError') return
        setError('Failed to load notifications')
      } finally {
        setLoading(false)
      }
    },
    [currentPage, unreadOnly, severityFilter, categoryFilter],
  )

  useEffect(() => {
    const controller = new AbortController()
    fetchInbox(controller.signal)
    return () => controller.abort()
  }, [fetchInbox])

  // ---------------------------------------------------------------------------
  // Actions
  // ---------------------------------------------------------------------------

  const handleItemClick = useCallback(
    async (item: InboxItemData) => {
      // Mark read
      try {
        await apiClient.post(`/notifications/inbox/${item.id}/read`)
      } catch {
        // best-effort
      }
      // Navigate if link_url present
      if (item.link_url) {
        navigate(item.link_url)
      } else {
        // Optimistic: mark as read in local state
        setItems((prev) =>
          prev.map((i) => (i.id === item.id ? { ...i, is_read: true } : i)),
        )
        setUnreadCount((c) => Math.max(0, c - (item.is_read ? 0 : 1)))
      }
    },
    [navigate],
  )

  const handleDismiss = useCallback(async (item: InboxItemData) => {
    // Optimistic removal
    setItems((prev) => prev.filter((i) => i.id !== item.id))
    setTotal((t) => Math.max(0, t - 1))
    if (!item.is_read) {
      setUnreadCount((c) => Math.max(0, c - 1))
    }
    try {
      await apiClient.post(`/notifications/inbox/${item.id}/dismiss`)
    } catch {
      // Revert on failure — refetch
      const controller = new AbortController()
      fetchInbox(controller.signal)
    }
  }, [fetchInbox])

  const handleMarkAllRead = useCallback(async () => {
    setActionLoading('mark-all-read')
    try {
      await apiClient.post('/notifications/inbox/mark-all-read')
      // Optimistic update
      setItems((prev) => prev.map((i) => ({ ...i, is_read: true })))
      setUnreadCount(0)
    } catch {
      // Refetch on failure
      const controller = new AbortController()
      fetchInbox(controller.signal)
    } finally {
      setActionLoading('')
    }
  }, [fetchInbox])

  const handleDismissRead = useCallback(async () => {
    setActionLoading('dismiss-read')
    try {
      await apiClient.post('/notifications/inbox/dismiss-all-read')
      // Remove read items from local state
      setItems((prev) => {
        const remaining = prev.filter((i) => !i.is_read)
        setTotal(remaining.length)
        return remaining
      })
    } catch {
      // Refetch on failure
      const controller = new AbortController()
      fetchInbox(controller.signal)
    } finally {
      setActionLoading('')
    }
  }, [fetchInbox])

  // ---------------------------------------------------------------------------
  // Derived
  // ---------------------------------------------------------------------------

  const totalPages = Math.ceil(total / PAGE_SIZE)
  const hasUnread = unreadCount > 0
  const hasReadItems = items.some((i) => i.is_read)
  const hasActiveFilter = unreadOnly || !!severityFilter || !!categoryFilter

  // ---------------------------------------------------------------------------
  // Render
  // ---------------------------------------------------------------------------

  return (
    <div className="px-4 py-6 sm:px-6 lg:px-8">
      {/* Header */}
      <h1 className="text-2xl font-semibold text-gray-900 dark:text-gray-100 mb-4">
        Notifications
      </h1>

      {/* Toolbar */}
      <div className="flex flex-col gap-3 sm:flex-row sm:items-end sm:justify-between mb-4">
        {/* Left: Filters */}
        <div className="flex flex-wrap items-end gap-3">
          {/* All / Unread toggle */}
          <div className="flex rounded-md shadow-sm" role="group" aria-label="Read filter">
            <button
              type="button"
              onClick={() => updateParams({ unread: null, page: null })}
              className={`px-4 py-2 text-sm font-medium rounded-l-md border transition-colors ${
                !unreadOnly
                  ? 'bg-blue-600 text-white border-blue-600'
                  : 'bg-white text-gray-700 border-gray-300 hover:bg-gray-50 dark:bg-gray-800 dark:text-gray-300 dark:border-gray-600 dark:hover:bg-gray-700'
              }`}
            >
              All
            </button>
            <button
              type="button"
              onClick={() => updateParams({ unread: 'true', page: null })}
              className={`px-4 py-2 text-sm font-medium rounded-r-md border-t border-b border-r transition-colors ${
                unreadOnly
                  ? 'bg-blue-600 text-white border-blue-600'
                  : 'bg-white text-gray-700 border-gray-300 hover:bg-gray-50 dark:bg-gray-800 dark:text-gray-300 dark:border-gray-600 dark:hover:bg-gray-700'
              }`}
            >
              Unread
            </button>
          </div>

          {/* Severity dropdown */}
          <div className="w-40">
            <Select
              label="Severity"
              value={severityFilter}
              onChange={(e) =>
                updateParams({ severity: e.target.value || null, page: null })
              }
              options={SEVERITY_OPTIONS}
            />
          </div>

          {/* Category dropdown */}
          <div className="w-44">
            <Select
              label="Category"
              value={categoryFilter}
              onChange={(e) =>
                updateParams({ category: e.target.value || null, page: null })
              }
              options={CATEGORY_OPTIONS}
            />
          </div>
        </div>

        {/* Right: Actions */}
        <div className="flex items-center gap-2">
          <button
            type="button"
            onClick={handleMarkAllRead}
            disabled={!hasUnread || actionLoading === 'mark-all-read'}
            className="px-3 py-2 text-sm font-medium text-blue-600 hover:text-blue-800 disabled:opacity-50 disabled:cursor-not-allowed dark:text-blue-400 dark:hover:text-blue-300 transition-colors"
          >
            {actionLoading === 'mark-all-read' ? 'Marking…' : 'Mark all read'}
          </button>
          <button
            type="button"
            onClick={handleDismissRead}
            disabled={!hasReadItems || actionLoading === 'dismiss-read'}
            className="px-3 py-2 text-sm font-medium text-gray-600 hover:text-red-600 disabled:opacity-50 disabled:cursor-not-allowed dark:text-gray-400 dark:hover:text-red-400 transition-colors"
          >
            {actionLoading === 'dismiss-read' ? 'Dismissing…' : 'Dismiss read'}
          </button>
        </div>
      </div>

      {/* Error state */}
      {error && (
        <div
          className="mb-4 rounded-md border border-red-200 bg-red-50 dark:bg-red-900/20 dark:border-red-800 px-4 py-3 text-sm text-red-700 dark:text-red-300 flex items-center justify-between"
          role="alert"
        >
          <span>{error}</span>
          <button
            type="button"
            onClick={() => {
              const controller = new AbortController()
              fetchInbox(controller.signal)
            }}
            className="ml-3 text-sm font-medium text-red-700 hover:text-red-900 dark:text-red-300 dark:hover:text-red-100 underline"
          >
            Retry
          </button>
        </div>
      )}

      {/* Loading state */}
      {loading && items.length === 0 && (
        <div className="py-16">
          <Spinner label="Loading notifications" />
        </div>
      )}

      {/* Content */}
      {!loading && (
        <>
          {items.length === 0 ? (
            /* Empty state */
            <div className="py-16 text-center">
              <p className="text-gray-500 dark:text-gray-400 text-sm">
                {hasActiveFilter
                  ? 'No matching notifications'
                  : "You're all caught up"}
              </p>
            </div>
          ) : (
            /* List */
            <div className="rounded-lg border border-gray-200 dark:border-gray-700 divide-y divide-gray-200 dark:divide-gray-700 overflow-hidden">
              {items.map((item) => (
                <InboxItemCard
                  key={item.id}
                  item={item}
                  onClick={handleItemClick}
                  onDismiss={handleDismiss}
                />
              ))}
            </div>
          )}

          {/* Pagination */}
          {totalPages > 1 && (
            <div className="mt-4">
              <Pagination
                currentPage={currentPage}
                totalPages={totalPages}
                onPageChange={(page) => updateParams({ page: String(page) })}
              />
            </div>
          )}
        </>
      )}
    </div>
  )
}
