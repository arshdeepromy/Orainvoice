import { useState, useEffect, useRef, useMemo } from 'react'
import { useParams, useNavigate } from 'react-router-dom'
import { Page, Block, Preloader } from 'konsta/react'
import { KonstaNavbar } from '@/components/konsta/KonstaNavbar'
import type { InboxItem } from '@/api/inbox'
import { getInbox } from '@/api/inbox'

/* ------------------------------------------------------------------ */
/* Helpers                                                            */
/* ------------------------------------------------------------------ */

/** Format a date string as a readable timestamp */
function formatTimestamp(dateStr: string | null | undefined): string {
  if (!dateStr) return ''
  try {
    return new Date(dateStr).toLocaleDateString('en-NZ', {
      day: 'numeric',
      month: 'short',
      year: 'numeric',
      hour: '2-digit',
      minute: '2-digit',
    })
  } catch {
    return dateStr ?? ''
  }
}

/** Map category string to a human-readable label */
function getCategoryLabel(category: string | null | undefined): string {
  if (!category) return 'General'
  switch (category) {
    case 'email_failure':
      return 'Email Failure'
    case 'sms_failure':
      return 'SMS Failure'
    case 'stock_alert':
      return 'Stock Alert'
    case 'quote_accepted':
      return 'Quote Accepted'
    case 'quote_declined':
      return 'Quote Declined'
    case 'payment_received':
      return 'Payment Received'
    case 'payment_failed':
      return 'Payment Failed'
    case 'invoice_overdue':
      return 'Invoice Overdue'
    case 'account_locked':
      return 'Account Locked'
    case 'xero_sync_failed':
      return 'Xero Sync Failed'
    case 'system':
      return 'System'
    default:
      return category.replace(/_/g, ' ').replace(/\b\w/g, (c) => c.toUpperCase())
  }
}

/** Get severity icon color classes */
function getSeverityClasses(severity: string): { bg: string; text: string; label: string } {
  switch (severity) {
    case 'error':
      return { bg: 'bg-red-50 dark:bg-red-900/30', text: 'text-red-500 dark:text-red-400', label: 'Error' }
    case 'warning':
      return { bg: 'bg-amber-50 dark:bg-amber-900/30', text: 'text-amber-500 dark:text-amber-400', label: 'Warning' }
    case 'success':
      return { bg: 'bg-green-50 dark:bg-green-900/30', text: 'text-green-500 dark:text-green-400', label: 'Success' }
    case 'info':
    default:
      return { bg: 'bg-blue-50 dark:bg-blue-900/30', text: 'text-blue-500 dark:text-blue-400', label: 'Info' }
  }
}

/* ------------------------------------------------------------------ */
/* Severity Icon Component                                            */
/* ------------------------------------------------------------------ */

function SeverityIcon({ severity, size = 'lg' }: { severity: string; size?: 'sm' | 'lg' }) {
  const { bg, text } = getSeverityClasses(severity)
  const sizeClasses = size === 'lg' ? 'h-12 w-12' : 'h-8 w-8'
  const iconSize = size === 'lg' ? 'h-7 w-7' : 'h-5 w-5'

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
    <div className={`flex ${sizeClasses} items-center justify-center rounded-full ${bg}`}>
      <svg
        className={`${iconSize} ${text}`}
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
 * Notification detail screen — body view fallback when `link_url`
 * doesn't map to a known mobile route.
 *
 * Displays: severity icon, title, full body text, created_at timestamp,
 * category label. Has a "Back" button via KonstaNavbar.
 *
 * Touch targets ≥44px, dark mode, safe-area insets.
 *
 * Requirements: 7.5
 */
export default function NotificationDetailScreen() {
  const { id } = useParams<{ id: string }>()
  const navigate = useNavigate()

  const [notification, setNotification] = useState<InboxItem | null>(null)
  const [isLoading, setIsLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  const abortRef = useRef<AbortController | null>(null)

  useEffect(() => {
    if (!id) {
      setError('Notification not found')
      setIsLoading(false)
      return
    }

    abortRef.current?.abort()
    const controller = new AbortController()
    abortRef.current = controller

    async function fetchNotification() {
      setIsLoading(true)
      setError(null)

      try {
        // Fetch inbox and find the notification by ID
        // The API doesn't have a single-item endpoint, so we fetch the list
        // and find the matching item
        const res = await getInbox({ limit: 50 }, controller.signal)
        const items = res?.items ?? []
        const found = items.find((item) => item.id === id)

        if (found) {
          setNotification(found)
        } else {
          setError('Notification not found')
        }
      } catch (err: unknown) {
        if ((err as { name?: string })?.name !== 'CanceledError') {
          setError('Failed to load notification')
        }
      } finally {
        setIsLoading(false)
      }
    }

    fetchNotification()

    return () => controller.abort()
  }, [id])

  // ── Loading state ──────────────────────────────────────────────────
  if (isLoading) {
    return (
      <Page data-testid="notification-detail-page">
        <KonstaNavbar title="Notification" showBack />
        <div className="flex flex-1 items-center justify-center p-8">
          <Preloader />
        </div>
      </Page>
    )
  }

  // ── Error state ────────────────────────────────────────────────────
  if (error || !notification) {
    return (
      <Page data-testid="notification-detail-page">
        <KonstaNavbar title="Notification" showBack />
        <Block>
          <div className="flex flex-col items-center gap-4 py-8">
            <p className="text-center text-red-600 dark:text-red-400">
              {error ?? 'Notification not found'}
            </p>
            <button
              type="button"
              onClick={() => navigate('/notifications')}
              className="min-h-[44px] rounded-lg bg-blue-600 px-6 py-3 text-sm font-medium text-white dark:bg-blue-500"
            >
              Back to Notifications
            </button>
          </div>
        </Block>
      </Page>
    )
  }

  // ── Detail view ────────────────────────────────────────────────────
  const severity = notification.severity ?? 'info'
  const { label: severityLabel } = getSeverityClasses(severity)
  const categoryLabel = getCategoryLabel(notification.category)

  return (
    <Page data-testid="notification-detail-page">
      <KonstaNavbar title="Notification" showBack />

      <div className="flex flex-col gap-4 px-4 pb-safe pt-4">
        {/* ── Severity icon + title ─────────────────────────────────── */}
        <div className="flex items-start gap-3">
          <SeverityIcon severity={severity} size="lg" />
          <div className="min-w-0 flex-1 pt-1">
            <h1 className="text-lg font-semibold text-gray-900 dark:text-gray-100">
              {notification.title ?? 'Notification'}
            </h1>
            <div className="mt-1 flex flex-wrap items-center gap-2">
              <span className="inline-flex items-center rounded-full bg-gray-100 px-2.5 py-0.5 text-xs font-medium text-gray-700 dark:bg-gray-800 dark:text-gray-300">
                {categoryLabel}
              </span>
              <span className="inline-flex items-center rounded-full bg-gray-100 px-2.5 py-0.5 text-xs font-medium text-gray-700 dark:bg-gray-800 dark:text-gray-300">
                {severityLabel}
              </span>
            </div>
          </div>
        </div>

        {/* ── Timestamp ─────────────────────────────────────────────── */}
        <div className="flex items-center gap-2 text-sm text-gray-500 dark:text-gray-400">
          <svg
            className="h-4 w-4"
            viewBox="0 0 24 24"
            fill="none"
            stroke="currentColor"
            strokeWidth="1.5"
            strokeLinecap="round"
            strokeLinejoin="round"
            aria-hidden="true"
          >
            <path d="M12 6v6l4 2m6-2a9 9 0 11-18 0 9 9 0 0118 0z" />
          </svg>
          <span>{formatTimestamp(notification.created_at)}</span>
        </div>

        {/* ── Body text ─────────────────────────────────────────────── */}
        <div className="rounded-lg bg-gray-50 p-4 dark:bg-gray-800">
          {notification.body ? (
            <p className="whitespace-pre-line text-sm leading-relaxed text-gray-700 dark:text-gray-300">
              {notification.body}
            </p>
          ) : (
            <p className="text-sm italic text-gray-400 dark:text-gray-500">
              No additional details
            </p>
          )}
        </div>

        {/* ── Back button ───────────────────────────────────────────── */}
        <button
          type="button"
          onClick={() => navigate('/notifications')}
          className="mt-4 min-h-[44px] w-full rounded-lg bg-gray-100 px-4 py-3 text-center text-sm font-medium text-gray-700 transition-colors active:bg-gray-200 dark:bg-gray-800 dark:text-gray-300 dark:active:bg-gray-700"
          data-testid="back-to-notifications-button"
        >
          ← Back to Notifications
        </button>
      </div>
    </Page>
  )
}
