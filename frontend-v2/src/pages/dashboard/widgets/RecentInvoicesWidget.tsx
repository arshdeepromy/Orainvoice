/**
 * Recent Invoices Widget with period selector, profit margin, and View All modal.
 *
 * Self-fetching widget (like CashFlowChartWidget) — fetches its own data
 * from /dashboard/widgets/recent-invoices with period/pagination params.
 *
 * Period selector: Daily (last 1 day) | Weekly (last 7 days) | Monthly (last 30 days)
 * Profit margin % is only visible to org_admin/global_admin roles.
 *
 * Ported from frontend/src/pages/dashboard/widgets/RecentInvoicesWidget.tsx
 * (Task 18). ALL logic preserved verbatim (FR-1): the `useAuth()` margin role
 * gate (org_admin/global_admin), the `PERIOD_CONFIG` (daily 1 / weekly 7 /
 * monthly 30), the widget self-fetch + the modal paginated fetch (both from
 * `GET /dashboard/widgets/recent-invoices?period=…&offset=…&limit=…` with
 * AbortController + CanceledError guards and `res.data?.items ?? []` /
 * `?? 0`), the WIDGET_LIMIT=5 / MODAL_LIMIT=10 paging, the period totals summary
 * and the View All modal. Presentation remapped onto the redesign tokens
 * (FR-2): the period chips, the status pills, `.mono` money and the token Modal.
 */

import { useState, useEffect, useRef } from 'react'
import apiClient from '@/api/client'
import { useAuth } from '@/contexts/AuthContext'
import { WidgetCard } from './WidgetCard'
import { Modal, cx } from '@/components/ui'
import type { RecentInvoiceItem } from './types'

// ---------------------------------------------------------------------------
// Props
// ---------------------------------------------------------------------------

interface RecentInvoicesWidgetProps {
  isLoading: boolean
  error: string | null
}

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

type Period = 'daily' | 'weekly' | 'monthly'

const PERIOD_CONFIG: Record<Period, { label: string; days: number }> = {
  daily: { label: 'Today', days: 1 },
  weekly: { label: 'This Week', days: 7 },
  monthly: { label: 'This Month', days: 30 },
}

// ---------------------------------------------------------------------------
// Icon
// ---------------------------------------------------------------------------

function InvoiceIcon({ className }: { className?: string }) {
  return (
    <svg className={className} fill="none" viewBox="0 0 24 24" stroke="currentColor" aria-hidden="true">
      <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5} d="M9 12h3.75M9 15h3.75M9 18h3.75m3 .75H18a2.25 2.25 0 002.25-2.25V6.108c0-1.135-.845-2.098-1.976-2.192a48.424 48.424 0 00-1.123-.08m-5.801 0c-.065.21-.1.433-.1.664 0 .414.336.75.75.75h4.5a.75.75 0 00.75-.75 2.25 2.25 0 00-.1-.664m-5.8 0A2.251 2.251 0 0113.5 2.25H15a2.25 2.25 0 012.15 1.586m-5.8 0c-.376.023-.75.05-1.124.08C9.095 4.01 8.25 4.973 8.25 6.108V8.25m0 0H4.875c-.621 0-1.125.504-1.125 1.125v11.25c0 .621.504 1.125 1.125 1.125h9.75c.621 0 1.125-.504 1.125-1.125V9.375c0-.621-.504-1.125-1.125-1.125H8.25zM6.75 12h.008v.008H6.75V12zm0 3h.008v.008H6.75V15zm0 3h.008v.008H6.75V18z" />
    </svg>
  )
}

// ---------------------------------------------------------------------------
// Status badge
// ---------------------------------------------------------------------------

function StatusBadge({ status }: { status: string }) {
  const config: Record<string, { cls: string; label: string }> = {
    paid: { cls: 'bg-ok-soft text-ok', label: 'Paid' },
    issued: { cls: 'bg-accent-soft text-accent', label: 'Issued' },
    overdue: { cls: 'bg-danger-soft text-danger', label: 'Overdue' },
    partially_paid: { cls: 'bg-warn-soft text-warn', label: 'Partial' },
  }
  const c = config[status] ?? { cls: 'bg-[#EEF0F4] text-muted', label: status }
  return (
    <span className={`inline-flex items-center rounded px-1.5 py-0.5 text-[10px] font-medium ${c.cls}`}>
      {c.label}
    </span>
  )
}

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function formatNZD(v: number | null | undefined): string {
  return `${(v ?? 0).toLocaleString('en-NZ', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`
}

// ---------------------------------------------------------------------------
// Invoice row (shared between widget and modal)
// ---------------------------------------------------------------------------

function InvoiceRow({ item, showMargin }: { item: RecentInvoiceItem; showMargin: boolean }) {
  const marginPct = item?.margin_pct ?? 0
  const hasCostData = (item?.cost ?? 0) > 0

  return (
    <div className="flex items-center justify-between gap-2 py-2">
      <div className="min-w-0 flex-1">
        <div className="flex items-center gap-2">
          <span className="mono truncate text-[13.5px] font-medium text-text">
            {item?.invoice_number ?? 'DRAFT'}
          </span>
          <StatusBadge status={item?.status ?? 'issued'} />
        </div>
        <div className="truncate text-[12px] text-muted">
          {item?.customer_name ?? 'Unknown'} · {item?.date ?? ''}
        </div>
      </div>
      <div className="shrink-0 text-right">
        <div className="mono text-[13.5px] font-medium text-text">
          {formatNZD(item?.total)}
        </div>
        {showMargin && hasCostData && (
          <div className={cx('mono text-[12px]', marginPct >= 0 ? 'text-ok' : 'text-danger')}>
            {formatNZD(item?.profit ?? 0)} ({marginPct.toFixed(1)}%)
          </div>
        )}
      </div>
    </div>
  )
}

// ---------------------------------------------------------------------------
// Main widget
// ---------------------------------------------------------------------------

const WIDGET_LIMIT = 5
const MODAL_LIMIT = 10

export function RecentInvoicesWidget({ isLoading: parentLoading, error: parentError }: RecentInvoicesWidgetProps) {
  const { user } = useAuth()
  const canViewMargins = user?.role === 'org_admin' || user?.role === 'global_admin'

  const [period, setPeriod] = useState<Period>('monthly')
  const [items, setItems] = useState<RecentInvoiceItem[]>([])
  const [total, setTotal] = useState(0)
  const [loading, setLoading] = useState(false)
  const [fetchError, setFetchError] = useState<string | null>(null)

  // Modal state
  const [modalOpen, setModalOpen] = useState(false)
  const [modalItems, setModalItems] = useState<RecentInvoiceItem[]>([])
  const [modalTotal, setModalTotal] = useState(0)
  const [modalPage, setModalPage] = useState(1)
  const [modalLoading, setModalLoading] = useState(false)

  const abortRef = useRef<AbortController | undefined>(undefined)

  // Fetch widget data when period changes
  useEffect(() => {
    const controller = new AbortController()
    abortRef.current = controller

    const fetchData = async () => {
      setLoading(true)
      setFetchError(null)
      try {
        const res = await apiClient.get<{ items: RecentInvoiceItem[]; total: number }>(
          `/dashboard/widgets/recent-invoices?period=${period}&offset=0&limit=${WIDGET_LIMIT}`,
          { signal: controller.signal },
        )
        setItems(res.data?.items ?? [])
        setTotal(res.data?.total ?? 0)
      } catch (err: unknown) {
        if ((err as { name?: string })?.name === 'CanceledError') return
        setFetchError('Failed to load recent invoices')
      } finally {
        if (!controller.signal.aborted) setLoading(false)
      }
    }

    fetchData()
    return () => controller.abort()
  }, [period])

  // Fetch modal data when modal opens or page changes
  useEffect(() => {
    if (!modalOpen) return

    const controller = new AbortController()

    const fetchModalData = async () => {
      setModalLoading(true)
      try {
        const offset = (modalPage - 1) * MODAL_LIMIT
        const res = await apiClient.get<{ items: RecentInvoiceItem[]; total: number }>(
          `/dashboard/widgets/recent-invoices?period=${period}&offset=${offset}&limit=${MODAL_LIMIT}`,
          { signal: controller.signal },
        )
        setModalItems(res.data?.items ?? [])
        setModalTotal(res.data?.total ?? 0)
      } catch (err: unknown) {
        if ((err as { name?: string })?.name === 'CanceledError') return
      } finally {
        if (!controller.signal.aborted) setModalLoading(false)
      }
    }

    fetchModalData()
    return () => controller.abort()
  }, [modalOpen, modalPage, period])

  const handleOpenModal = () => {
    setModalPage(1)
    setModalOpen(true)
  }

  const totalModalPages = Math.max(1, Math.ceil(modalTotal / MODAL_LIMIT))

  const isWidgetLoading = parentLoading || loading

  return (
    <>
      <WidgetCard
        title="Recent Invoices"
        icon={InvoiceIcon}
        isLoading={isWidgetLoading}
        error={parentError || fetchError}
      >
        {/* Period selector */}
        <div className="mb-3 flex gap-1">
          {(Object.entries(PERIOD_CONFIG) as [Period, { label: string; days: number }][]).map(([key, config]) => (
            <button
              key={key}
              onClick={() => setPeriod(key)}
              className={cx(
                'rounded-chip px-3 py-1 text-[12px] font-medium transition-colors',
                period === key
                  ? 'bg-accent-soft text-accent'
                  : 'bg-canvas text-muted hover:text-text',
              )}
            >
              {config.label}
            </button>
          ))}
        </div>

        {/* Invoice list */}
        {(items ?? []).length === 0 ? (
          <p className="text-[13px] text-muted">No invoices found for this period</p>
        ) : (
          <>
            {/* Period totals summary */}
            {canViewMargins && (() => {
              const totalRevenue = (items ?? []).reduce((s, i) => s + (i?.revenue ?? 0), 0)
              const totalProfit = (items ?? []).reduce((s, i) => s + (i?.profit ?? 0), 0)
              const overallMargin = totalRevenue > 0 ? (totalProfit / totalRevenue) * 100 : 0
              return (
                <div className="mb-2 flex items-center justify-between rounded-ctl bg-canvas px-3 py-2 text-[12px]">
                  <div className="text-muted">
                    Revenue: <span className="mono font-medium text-text">{formatNZD(totalRevenue)}</span>
                  </div>
                  <div className={cx('mono font-medium', totalProfit >= 0 ? 'text-ok' : 'text-danger')}>
                    Profit: {formatNZD(totalProfit)} ({overallMargin.toFixed(1)}%)
                  </div>
                </div>
              )
            })()}
            <div className="divide-y divide-border">
              {(items ?? []).map((item) => (
                <InvoiceRow key={item?.id ?? Math.random().toString()} item={item} showMargin={canViewMargins} />
              ))}
            </div>
          </>
        )}

        {/* Footer with View All */}
        {total > WIDGET_LIMIT && (
          <button
            onClick={handleOpenModal}
            className="mt-3 w-full rounded-ctl py-1.5 text-center text-[12px] font-medium text-accent transition-colors hover:bg-accent-soft hover:text-accent-press"
          >
            View All ({total ?? 0})
          </button>
        )}
      </WidgetCard>

      {/* View All Modal */}
      <Modal
        open={modalOpen}
        onClose={() => setModalOpen(false)}
        title={`Invoices — ${PERIOD_CONFIG[period].label}`}
        className="max-w-2xl"
      >
        {modalLoading ? (
          <div className="flex items-center justify-center py-8">
            <div className="h-6 w-6 animate-spin rounded-full border-2 border-accent border-t-transparent" />
          </div>
        ) : (modalItems ?? []).length === 0 ? (
          <p className="py-4 text-[13px] text-muted">No invoices found</p>
        ) : (
          <div className="divide-y divide-border">
            {(modalItems ?? []).map((item) => (
              <InvoiceRow key={item?.id ?? Math.random().toString()} item={item} showMargin={canViewMargins} />
            ))}
          </div>
        )}

        {/* Pagination */}
        {totalModalPages > 1 && (
          <div className="mt-3 flex items-center justify-between border-t border-border pt-3">
            <button
              onClick={() => setModalPage((p) => Math.max(1, p - 1))}
              disabled={modalPage <= 1}
              className="rounded-ctl bg-canvas px-3 py-1.5 text-[12px] font-medium text-text transition-colors hover:bg-border disabled:cursor-not-allowed disabled:opacity-40"
            >
              Previous
            </button>
            <span className="mono text-[12px] text-muted">
              Page {modalPage} of {totalModalPages}
            </span>
            <button
              onClick={() => setModalPage((p) => Math.min(totalModalPages, p + 1))}
              disabled={modalPage >= totalModalPages}
              className="rounded-ctl bg-canvas px-3 py-1.5 text-[12px] font-medium text-text transition-colors hover:bg-border disabled:cursor-not-allowed disabled:opacity-40"
            >
              Next
            </button>
          </div>
        )}
      </Modal>
    </>
  )
}
