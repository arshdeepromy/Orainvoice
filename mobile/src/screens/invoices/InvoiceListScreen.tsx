import { useCallback } from 'react'
import { useNavigate } from 'react-router-dom'
import type { Invoice } from '@shared/types/invoice'
import { useApiList } from '@/hooks/useApiList'
import { MobileList, MobileListItem, MobileButton, MobileBadge } from '@/components/ui'
import type { BadgeVariant } from '@/components/ui'
import { SwipeAction } from '@/components/gestures/SwipeAction'
import { PullRefresh } from '@/components/gestures/PullRefresh'
import apiClient from '@/api/client'

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

/* ------------------------------------------------------------------ */
/* Helpers                                                            */
/* ------------------------------------------------------------------ */

const statusVariantMap: Record<Invoice['status'], BadgeVariant> = {
  draft: 'draft',
  sent: 'sent',
  paid: 'paid',
  overdue: 'overdue',
  cancelled: 'cancelled',
}

function formatCurrency(amount: number): string {
  return `$${Number(amount ?? 0).toFixed(2)}`
}

function formatDate(dateStr: string): string {
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
/* Swipe action handlers (exported for testing)                       */
/* ------------------------------------------------------------------ */

export async function handleSendInvoice(invoiceId: string): Promise<void> {
  try {
    await apiClient.post(`/api/v1/invoices/${invoiceId}/send`)
  } catch {
    // Swipe action errors are non-blocking; toast would handle in production
  }
}

export async function handleRecordPayment(
  invoiceId: string,
  navigate: (path: string) => void,
): Promise<void> {
  navigate(`/invoices/${invoiceId}?action=record-payment`)
}

/**
 * Invoice list screen — searchable paginated list with swipe actions
 * for Send and Record Payment. Pull-to-refresh support.
 *
 * Requirements: 8.1, 8.6, 8.8
 */
export default function InvoiceListScreen() {
  const navigate = useNavigate()

  const {
    items,
    isLoading,
    isRefreshing,
    hasMore,
    search,
    setSearch,
    refresh,
    loadMore,
  } = useApiList<Invoice>({
    endpoint: '/api/v1/invoices',
    dataKey: 'invoices',
  })

  const handleTap = useCallback(
    (invoice: Invoice) => {
      navigate(`/invoices/${invoice.id}`)
    },
    [navigate],
  )

  const renderItem = useCallback(
    (invoice: Invoice) => {
      const status = invoice.status ?? 'draft'
      const rightActions = [
        ...(status === 'draft'
          ? [
              {
                label: 'Send',
                icon: SendIcon,
                color: 'bg-blue-500',
                onAction: () => {
                  void handleSendInvoice(invoice.id)
                  void refresh()
                },
              },
            ]
          : []),
        ...(status !== 'paid' && status !== 'cancelled'
          ? [
              {
                label: 'Payment',
                icon: DollarIcon,
                color: 'bg-green-500',
                onAction: () => {
                  void handleRecordPayment(invoice.id, navigate)
                },
              },
            ]
          : []),
      ]

      return (
        <SwipeAction rightActions={rightActions}>
          <MobileListItem
            title={invoice.invoice_number ?? 'No Number'}
            subtitle={`${invoice.customer_name ?? 'Unknown'} · ${formatDate(invoice.due_date)}`}
            trailing={
              <div className="flex flex-col items-end gap-1">
                <span className="text-sm font-semibold text-gray-900 dark:text-gray-100">
                  {formatCurrency(invoice.total)}
                </span>
                <MobileBadge
                  label={status.charAt(0).toUpperCase() + status.slice(1)}
                  variant={statusVariantMap[status] ?? 'info'}
                />
              </div>
            }
            onTap={() => handleTap(invoice)}
          />
        </SwipeAction>
      )
    },
    [handleTap, navigate, refresh],
  )

  return (
    <PullRefresh onRefresh={refresh} isRefreshing={isRefreshing}>
      <div className="flex flex-col">
        {/* Header with title and New Invoice button */}
        <div className="flex items-center justify-between px-4 pb-1 pt-4">
          <h1 className="text-xl font-semibold text-gray-900 dark:text-gray-100">
            Invoices
          </h1>
          <MobileButton
            variant="primary"
            size="sm"
            onClick={() => navigate('/invoices/new')}
            icon={
              <svg
                className="h-4 w-4"
                viewBox="0 0 24 24"
                fill="none"
                stroke="currentColor"
                strokeWidth="2"
                strokeLinecap="round"
                strokeLinejoin="round"
                aria-hidden="true"
              >
                <line x1="12" y1="5" x2="12" y2="19" />
                <line x1="5" y1="12" x2="19" y2="12" />
              </svg>
            }
          >
            New
          </MobileButton>
        </div>

        {/* Paginated list with search */}
        <MobileList<Invoice>
          items={items}
          renderItem={renderItem}
          onRefresh={refresh}
          onLoadMore={loadMore}
          isLoading={isLoading}
          isRefreshing={isRefreshing}
          hasMore={hasMore}
          emptyMessage="No invoices found"
          searchValue={search}
          onSearchChange={setSearch}
          searchPlaceholder="Search invoices…"
          keyExtractor={(inv) => inv.id}
        />
      </div>
    </PullRefresh>
  )
}
