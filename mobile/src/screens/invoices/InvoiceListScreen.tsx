import { useState, useCallback, useMemo, useRef, useEffect } from 'react'
import { useNavigate } from 'react-router-dom'
import {
  Page,
  Searchbar,
  Chip,
  List,
  ListItem,
  Block,
  Preloader,
} from 'konsta/react'
import type { Invoice } from '@shared/types/invoice'
import { PullRefresh } from '@/components/gestures/PullRefresh'
import { SwipeAction } from '@/components/gestures/SwipeAction'
import StatusBadge from '@/components/konsta/StatusBadge'
import KonstaFAB from '@/components/konsta/KonstaFAB'
import apiClient from '@/api/client'

/* ------------------------------------------------------------------ */
/* Constants                                                          */
/* ------------------------------------------------------------------ */

const PAGE_SIZE = 25

/** Status filter chips — "All" plus every invoice status */
const STATUS_FILTERS = [
  { key: 'all', label: 'All' },
  { key: 'draft', label: 'Draft' },
  { key: 'issued', label: 'Issued' },
  { key: 'partially_paid', label: 'Partially Paid' },
  { key: 'paid', label: 'Paid' },
  { key: 'overdue', label: 'Overdue' },
  { key: 'voided', label: 'Voided' },
  { key: 'refunded', label: 'Refunded' },
  { key: 'partially_refunded', label: 'Partially Refunded' },
] as const

/* ------------------------------------------------------------------ */
/* Inline SVG icon components for swipe actions                       */
/* ------------------------------------------------------------------ */

function SendIcon({ className }: { className?: string }) {
  return (
    <svg
      className={className}
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="2"
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
    >
      <path d="m22 2-7 20-4-9-9-4z" />
      <path d="m22 2-11 11" />
    </svg>
  )
}

function EmailIcon({ className }: { className?: string }) {
  return (
    <svg
      className={className}
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="2"
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
    >
      <rect x="2" y="4" width="20" height="16" rx="2" />
      <path d="m22 7-8.97 5.7a1.94 1.94 0 0 1-2.06 0L2 7" />
    </svg>
  )
}

function VoidIcon({ className }: { className?: string }) {
  return (
    <svg
      className={className}
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="2"
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
    >
      <circle cx="12" cy="12" r="10" />
      <line x1="4.93" y1="4.93" x2="19.07" y2="19.07" />
    </svg>
  )
}

function DollarIcon({ className }: { className?: string }) {
  return (
    <svg
      className={className}
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="2"
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
    >
      <line x1="12" y1="1" x2="12" y2="23" />
      <path d="M17 5H9.5a3.5 3.5 0 0 0 0 7h5a3.5 3.5 0 0 1 0 7H6" />
    </svg>
  )
}

function DuplicateIcon({ className }: { className?: string }) {
  return (
    <svg
      className={className}
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="2"
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
    >
      <rect x="9" y="9" width="13" height="13" rx="2" ry="2" />
      <path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1" />
    </svg>
  )
}

function StripeIcon({ className }: { className?: string }) {
  return (
    <svg
      className={className}
      viewBox="0 0 24 24"
      fill="currentColor"
      aria-hidden="true"
    >
      <path d="M13.976 9.15c-2.172-.806-3.356-1.426-3.356-2.409 0-.831.683-1.305 1.901-1.305 2.227 0 4.515.858 6.09 1.631l.89-5.494C18.252.975 15.697 0 12.165 0 9.667 0 7.589.654 6.104 1.872 4.56 3.147 3.757 4.992 3.757 7.218c0 4.039 2.467 5.76 6.476 7.219 2.585.92 3.445 1.574 3.445 2.583 0 .98-.84 1.545-2.354 1.545-1.875 0-4.965-.921-7.076-2.19l-.893 5.575C4.746 22.77 7.614 24 11.435 24c2.627 0 4.768-.631 6.297-1.82 1.672-1.303 2.511-3.237 2.511-5.744 0-4.115-2.543-5.849-6.267-7.286z" />
    </svg>
  )
}

function PaperclipIcon({ className }: { className?: string }) {
  return (
    <svg
      className={className}
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="2"
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
    >
      <path d="m21.44 11.05-9.19 9.19a6 6 0 0 1-8.49-8.49l9.19-9.19a4 4 0 0 1 5.66 5.66l-9.2 9.19a2 2 0 0 1-2.83-2.83l8.49-8.48" />
    </svg>
  )
}

/* ------------------------------------------------------------------ */
/* Helpers                                                            */
/* ------------------------------------------------------------------ */

/** Safe NZD currency formatting matching the project convention */
function formatNZD(value: number | null | undefined): string {
  return `NZD${Number(value ?? 0).toLocaleString('en-NZ', {
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  })}`
}

function formatDate(dateStr: string | undefined): string {
  if (!dateStr) return ''
  try {
    return new Date(dateStr).toLocaleDateString('en-NZ', {
      day: 'numeric',
      month: 'short',
      year: 'numeric',
    })
  } catch {
    return dateStr
  }
}

/* ------------------------------------------------------------------ */
/* Extended invoice type for API response fields                      */
/* ------------------------------------------------------------------ */

interface InvoiceListItem extends Invoice {
  stripe_payment_intent_id?: string | null
  stripe_invoice_id?: string | null
  attachment_count?: number
  balance_due?: number
}

/* ------------------------------------------------------------------ */
/* Swipe action handlers (exported for testing)                       */
/* ------------------------------------------------------------------ */

export async function handleMarkSent(invoiceId: string): Promise<void> {
  try {
    await apiClient.post(`/api/v1/invoices/${invoiceId}/send`)
  } catch {
    // Swipe action errors are non-blocking
  }
}

/** @deprecated Use handleMarkSent — kept for backward compatibility with tests */
export const handleSendInvoice = handleMarkSent

export async function handleEmailInvoice(invoiceId: string): Promise<void> {
  try {
    await apiClient.post(`/api/v1/invoices/${invoiceId}/email`)
  } catch {
    // Swipe action errors are non-blocking
  }
}

export async function handleVoidInvoice(invoiceId: string): Promise<void> {
  try {
    await apiClient.post(`/api/v1/invoices/${invoiceId}/void`)
  } catch {
    // Swipe action errors are non-blocking
  }
}

export async function handleDuplicateInvoice(invoiceId: string): Promise<void> {
  try {
    await apiClient.post(`/api/v1/invoices/${invoiceId}/duplicate`)
  } catch {
    // Swipe action errors are non-blocking
  }
}

export async function handleRecordPayment(
  invoiceId: string,
  navigate: (path: string) => void,
): Promise<void> {
  navigate(`/invoices/${invoiceId}?action=record-payment`)
}

/* ------------------------------------------------------------------ */
/* Main Component                                                     */
/* ------------------------------------------------------------------ */

/**
 * Invoice list screen — Konsta UI redesign with:
 * - Full-screen list replacing desktop split-pane
 * - Konsta Searchbar with status filter chips
 * - Each invoice as Konsta ListItem with customer name, invoice number,
 *   NZD total, status badge, due date, Stripe icon, paperclip icon
 * - Swipe-left: Mark Sent, Email, Void
 * - Swipe-right: Record Payment, Duplicate
 * - Infinite scroll pagination (25 per page) using offset and limit
 * - FAB for "+ New Invoice"
 * - Pull-to-refresh
 * - Safe API consumption: res.data?.items ?? [], res.data?.total ?? 0
 *
 * Requirements: 18.1, 18.2, 18.3, 18.4, 18.5, 18.6, 18.7, 18.8, 18.9, 18.10, 7.1, 8.1
 */
export default function InvoiceListScreen() {
  const navigate = useNavigate()

  // ── State ──────────────────────────────────────────────────────────
  const [items, setItems] = useState<InvoiceListItem[]>([])
  const [total, setTotal] = useState(0)
  const [isLoading, setIsLoading] = useState(true)
  const [isRefreshing, setIsRefreshing] = useState(false)
  const [isLoadingMore, setIsLoadingMore] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [search, setSearch] = useState('')
  const [statusFilter, setStatusFilter] = useState<string>('all')
  const [offset, setOffset] = useState(0)

  const abortRef = useRef<AbortController | null>(null)
  const sentinelRef = useRef<HTMLDivElement | null>(null)

  const hasMore = items.length < total

  // ── Fetch data ─────────────────────────────────────────────────────
  const fetchInvoices = useCallback(
    async (
      currentOffset: number,
      isRefresh: boolean,
      signal: AbortSignal,
    ) => {
      if (isRefresh) {
        setIsRefreshing(true)
      } else if (currentOffset === 0) {
        setIsLoading(true)
      } else {
        setIsLoadingMore(true)
      }
      setError(null)

      try {
        const params: Record<string, string | number> = {
          offset: currentOffset,
          limit: PAGE_SIZE,
        }
        if (search.trim()) {
          params.search = search.trim()
        }
        if (statusFilter !== 'all') {
          params.status = statusFilter
        }

        const res = await apiClient.get<{ items?: InvoiceListItem[]; total?: number }>(
          '/api/v1/invoices',
          { params, signal },
        )

        // Safe API consumption
        const newItems = res.data?.items ?? []
        const newTotal = res.data?.total ?? 0

        if (currentOffset === 0 || isRefresh) {
          setItems(newItems)
        } else {
          setItems((prev) => [...prev, ...newItems])
        }
        setTotal(newTotal)
      } catch (err: unknown) {
        if ((err as { name?: string })?.name !== 'CanceledError') {
          setError('Failed to load invoices')
        }
      } finally {
        setIsLoading(false)
        setIsRefreshing(false)
        setIsLoadingMore(false)
      }
    },
    [search, statusFilter],
  )

  // Fetch on mount and when search/filter changes (reset to offset 0)
  useEffect(() => {
    abortRef.current?.abort()
    const controller = new AbortController()
    abortRef.current = controller

    setOffset(0)
    fetchInvoices(0, false, controller.signal)

    return () => controller.abort()
  }, [fetchInvoices])

  // ── Pull-to-refresh ────────────────────────────────────────────────
  const handleRefresh = useCallback(async () => {
    abortRef.current?.abort()
    const controller = new AbortController()
    abortRef.current = controller

    setOffset(0)
    await fetchInvoices(0, true, controller.signal)
  }, [fetchInvoices])

  // ── Infinite scroll via IntersectionObserver ───────────────────────
  const loadMore = useCallback(() => {
    if (isLoading || isRefreshing || isLoadingMore || !hasMore) return

    const nextOffset = offset + PAGE_SIZE
    setOffset(nextOffset)

    abortRef.current?.abort()
    const controller = new AbortController()
    abortRef.current = controller

    fetchInvoices(nextOffset, false, controller.signal)
  }, [isLoading, isRefreshing, isLoadingMore, hasMore, offset, fetchInvoices])

  useEffect(() => {
    const sentinel = sentinelRef.current
    if (!sentinel) return

    const observer = new IntersectionObserver(
      (entries) => {
        if (entries[0]?.isIntersecting) {
          loadMore()
        }
      },
      { rootMargin: '200px' },
    )

    observer.observe(sentinel)
    return () => observer.disconnect()
  }, [loadMore])

  // ── Swipe action builders ──────────────────────────────────────────
  const buildLeftActions = useCallback(
    (invoice: InvoiceListItem) => {
      const status = invoice.status ?? 'draft'
      const actions = []

      // Mark Sent — only for draft invoices
      if (status === 'draft') {
        actions.push({
          label: 'Mark Sent',
          icon: SendIcon,
          color: 'bg-blue-500',
          onAction: () => {
            void handleMarkSent(invoice.id)
            void handleRefresh()
          },
        })
      }

      // Email
      actions.push({
        label: 'Email',
        icon: EmailIcon,
        color: 'bg-indigo-500',
        onAction: () => {
          void handleEmailInvoice(invoice.id)
        },
      })

      // Void — not for already voided, paid, or refunded
      if (!['voided', 'paid', 'refunded', 'partially_refunded'].includes(status)) {
        actions.push({
          label: 'Void',
          icon: VoidIcon,
          color: 'bg-red-500',
          onAction: () => {
            void handleVoidInvoice(invoice.id)
            void handleRefresh()
          },
        })
      }

      return actions
    },
    [handleRefresh],
  )

  const buildRightActions = useCallback(
    (invoice: InvoiceListItem) => {
      const status = invoice.status ?? 'draft'
      const actions = []

      // Record Payment — only for unpaid, non-voided invoices
      if (!['paid', 'voided', 'refunded'].includes(status)) {
        actions.push({
          label: 'Payment',
          icon: DollarIcon,
          color: 'bg-green-500',
          onAction: () => {
            void handleRecordPayment(invoice.id, navigate)
          },
        })
      }

      // Duplicate
      actions.push({
        label: 'Duplicate',
        icon: DuplicateIcon,
        color: 'bg-gray-500',
        onAction: () => {
          void handleDuplicateInvoice(invoice.id)
          void handleRefresh()
        },
      })

      return actions
    },
    [navigate, handleRefresh],
  )

  // ── Memoised search handler ────────────────────────────────────────
  const handleSearchChange = useCallback(
    (e: React.ChangeEvent<HTMLInputElement>) => {
      setSearch(e.target.value)
    },
    [],
  )

  const handleSearchClear = useCallback(() => {
    setSearch('')
  }, [])

  // ── Determine if an invoice has Stripe payment ─────────────────────
  const hasStripe = useCallback((inv: InvoiceListItem) => {
    return !!(inv.stripe_payment_intent_id || inv.stripe_invoice_id)
  }, [])

  // ── Active filter chip styling ─────────────────────────────────────
  const activeChipColors = useMemo(
    () => ({
      fillBgIos: 'bg-primary',
      fillBgMaterial: 'bg-primary',
      fillTextIos: 'text-white',
      fillTextMaterial: 'text-white',
    }),
    [],
  )

  // ── Loading state ──────────────────────────────────────────────────
  if (isLoading && items.length === 0) {
    return (
      <Page data-testid="invoice-list-page">
        <div className="flex flex-1 items-center justify-center p-8">
          <Preloader />
        </div>
      </Page>
    )
  }

  return (
    <Page data-testid="invoice-list-page">
      <PullRefresh onRefresh={handleRefresh} isRefreshing={isRefreshing}>
        <div className="flex flex-col pb-24">
          {/* ── Searchbar ─────────────────────────────────────────── */}
          <div className="px-4 pt-3">
            <Searchbar
              value={search}
              onChange={handleSearchChange}
              onClear={handleSearchClear}
              placeholder="Search invoices…"
              data-testid="invoice-searchbar"
            />
          </div>

          {/* ── Status Filter Chips ───────────────────────────────── */}
          <div
            className="-mx-0 flex gap-2 overflow-x-auto px-4 py-2"
            data-testid="status-filter-chips"
          >
            {STATUS_FILTERS.map((filter) => {
              const isActive = statusFilter === filter.key
              return (
                <Chip
                  key={filter.key}
                  className={`shrink-0 cursor-pointer ${
                    isActive ? 'font-semibold' : ''
                  }`}
                  colors={isActive ? activeChipColors : undefined}
                  onClick={() => setStatusFilter(filter.key)}
                  data-testid={`filter-chip-${filter.key}`}
                >
                  {filter.label}
                </Chip>
              )
            })}
          </div>

          {/* ── Error Banner ──────────────────────────────────────── */}
          {error && (
            <Block>
              <div
                role="alert"
                className="rounded-lg bg-red-50 p-3 text-sm text-red-700 dark:bg-red-900/30 dark:text-red-300"
              >
                {error}
                <button
                  type="button"
                  onClick={() => handleRefresh()}
                  className="ml-2 font-medium underline"
                >
                  Retry
                </button>
              </div>
            </Block>
          )}

          {/* ── Invoice List ──────────────────────────────────────── */}
          {items.length === 0 && !isLoading ? (
            <Block className="text-center">
              <p className="text-sm text-gray-400 dark:text-gray-500">
                No invoices found
              </p>
            </Block>
          ) : (
            <List strongIos outlineIos dividersIos data-testid="invoice-list">
              {items.map((invoice) => {
                const status = invoice.status ?? 'draft'
                const leftActions = buildLeftActions(invoice)
                const rightActions = buildRightActions(invoice)

                return (
                  <SwipeAction
                    key={invoice.id}
                    leftActions={leftActions}
                    rightActions={rightActions}
                  >
                    <ListItem
                      link
                      onClick={() => navigate(`/invoices/${invoice.id}`)}
                      title={
                        <span className="font-bold text-gray-900 dark:text-gray-100">
                          {invoice.customer_name ?? 'Unknown'}
                        </span>
                      }
                      subtitle={
                        <span className="flex flex-wrap items-center gap-x-2 gap-y-0.5 text-xs text-gray-500 dark:text-gray-400">
                          <span className="text-gray-400 dark:text-gray-500">
                            {invoice.invoice_number ?? ''}
                          </span>
                          {invoice.due_date && (
                            <span>Due {formatDate(invoice.due_date)}</span>
                          )}
                          {hasStripe(invoice) && (
                            <StripeIcon className="inline-block h-3.5 w-3.5 text-indigo-500" />
                          )}
                          {(invoice.attachment_count ?? 0) > 0 && (
                            <PaperclipIcon className="inline-block h-3.5 w-3.5 text-gray-400" />
                          )}
                        </span>
                      }
                      after={
                        <div className="flex flex-col items-end gap-1">
                          <span className="text-base font-semibold tabular-nums text-gray-900 dark:text-gray-100">
                            {formatNZD(invoice.total)}
                          </span>
                          <StatusBadge status={status} size="sm" />
                        </div>
                      }
                      data-testid={`invoice-item-${invoice.id}`}
                    />
                  </SwipeAction>
                )
              })}
            </List>
          )}

          {/* ── Infinite scroll sentinel ──────────────────────────── */}
          {hasMore && (
            <div ref={sentinelRef} className="flex justify-center py-4">
              {isLoadingMore && <Preloader />}
            </div>
          )}
        </div>
      </PullRefresh>

      {/* ── FAB: + New Invoice ──────────────────────────────────────── */}
      <KonstaFAB
        label="+ New Invoice"
        onClick={() => navigate('/invoices/new')}
      />
    </Page>
  )
}
