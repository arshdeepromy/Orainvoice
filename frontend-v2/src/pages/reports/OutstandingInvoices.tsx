import { useState, useEffect, useCallback, useRef } from 'react'
import apiClient from '@/api/client'
import { Spinner, Badge, Button, PrintButton, useToast, ToastContainer } from '@/components/ui'
import ExportButtons from './ExportButtons'
import { useBranch } from '@/contexts/BranchContext'

interface OutstandingInvoice {
  invoice_id: string
  invoice_number: string | null
  customer_name: string
  vehicle_rego: string | null
  total: number
  balance_due: number
  due_date: string | null
  days_overdue: number
}

interface OutstandingData {
  invoices?: OutstandingInvoice[]
  total_outstanding?: number
}

const fmt = (v: number | undefined) =>
  v != null ? `$${v.toLocaleString('en-NZ', { minimumFractionDigits: 2 })}` : '$0.00'

/** Read the backend `detail` from an axios error, if present. */
function getErrorDetail(err: unknown): string | undefined {
  return (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail
}

/**
 * Derive the row status badge from `days_overdue`:
 *  - > 0 → "Overdue" (danger)
 *  - ≤ 0 → "Outstanding" (warn)
 */
function deriveStatus(daysOverdue: number): { label: string; variant: 'danger' | 'warn' } {
  return daysOverdue > 0
    ? { label: 'Overdue', variant: 'danger' }
    : { label: 'Outstanding', variant: 'warn' }
}

/**
 * Outstanding invoices report. Outstanding balances are point-in-time, so
 * the tab does not present a date-range filter and omits `start_date` /
 * `end_date` from fetch + export params (B1).
 *
 * Send Reminder posts to `POST /invoices/{invoice_id}/send-reminder` with
 * `{ channel: 'email' }`, surfaces success/error toasts, and uses the
 * backend `detail` field on failure (C2). Fetches use AbortController (D1)
 * and include `selectedBranchId` in the useCallback deps (D2).
 *
 * Requirements: 4.1, 4.2, 4.3, 4.4, 4.5, 5.1, 5.2, 5.3, 5.4, 11.1, 11.2,
 *   11.3, 14.1, 14.2, 14.3, 19.1, 19.5, 21.1
 */
export default function OutstandingInvoices() {
  const { selectedBranchId } = useBranch()
  const [data, setData] = useState<OutstandingData | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const [sendingReminder, setSendingReminder] = useState<string | null>(null)
  const { toasts, addToast, dismissToast } = useToast()

  // Track in-flight reminder requests so they can be aborted on unmount.
  const reminderControllersRef = useRef<Set<AbortController>>(new Set())

  const fetchData = useCallback(async (signal?: AbortSignal) => {
    setLoading(true)
    setError('')
    try {
      const params: Record<string, string> = {}
      if (selectedBranchId) params.branch_id = selectedBranchId
      const res = await apiClient.get<OutstandingData>('/reports/outstanding', { params, signal })
      setData(res.data ?? null)
    } catch {
      if (!signal?.aborted) setError('Failed to load outstanding invoices.')
    } finally {
      if (!signal?.aborted) setLoading(false)
    }
  }, [selectedBranchId])

  useEffect(() => {
    const controller = new AbortController()
    fetchData(controller.signal)
    return () => controller.abort()
  }, [fetchData])

  // Abort any in-flight reminder requests on unmount.
  useEffect(() => {
    const controllers = reminderControllersRef.current
    return () => {
      controllers.forEach((c) => c.abort())
      controllers.clear()
    }
  }, [])

  const sendReminder = async (invoiceId: string) => {
    if (!invoiceId) return
    const controller = new AbortController()
    reminderControllersRef.current.add(controller)
    setSendingReminder(invoiceId)
    try {
      await apiClient.post(
        `/invoices/${invoiceId}/send-reminder`,
        { channel: 'email' },
        { signal: controller.signal },
      )
      addToast('success', 'Reminder sent.')
    } catch (err) {
      if (!controller.signal.aborted) {
        addToast('error', getErrorDetail(err) ?? 'Failed to send reminder.')
      }
    } finally {
      reminderControllersRef.current.delete(controller)
      setSendingReminder((curr) => (curr === invoiceId ? null : curr))
    }
  }

  const invoices = data?.invoices ?? []
  const hasRows = invoices.length > 0

  return (
    <div data-print-content>
      <p className="text-sm text-muted mb-4 no-print">
        Outstanding balances are point-in-time. Send payment reminders with one click.
      </p>

      <div className="flex flex-col gap-3 sm:flex-row sm:items-end sm:justify-end mb-6 no-print">
        <div className="flex items-center gap-2">
          <ExportButtons
            endpoint="/reports/outstanding"
            params={selectedBranchId ? { branch_id: selectedBranchId } : {}}
          />
          <PrintButton label="Print Report" />
        </div>
      </div>

      {error && (
        <div className="mb-4 rounded-ctl border border-danger-soft bg-danger-soft px-4 py-3 text-sm text-danger" role="alert">
          {error}
        </div>
      )}

      {loading && <div className="py-16"><Spinner label="Loading outstanding invoices" /></div>}

      {!loading && data && (
        <>
          <div className="rounded-card border border-border bg-card p-4 mb-6 shadow-card">
            <p className="text-sm text-muted mb-1">Total Outstanding</p>
            <p className="text-2xl font-semibold text-danger mono">{fmt(data.total_outstanding ?? 0)}</p>
          </div>

          <div className="overflow-hidden rounded-card border border-border bg-card shadow-card">
            <table className="min-w-full" role="grid">
              <caption className="sr-only">Outstanding invoices</caption>
              <thead>
                <tr>
                  <th scope="col" className="mono border-b border-border px-4 py-3 text-left text-[10.5px] font-medium uppercase tracking-[0.08em] text-muted-2">Invoice</th>
                  <th scope="col" className="mono border-b border-border px-4 py-3 text-left text-[10.5px] font-medium uppercase tracking-[0.08em] text-muted-2">Customer</th>
                  <th scope="col" className="mono border-b border-border px-4 py-3 text-left text-[10.5px] font-medium uppercase tracking-[0.08em] text-muted-2">Rego</th>
                  <th scope="col" className="mono border-b border-border px-4 py-3 text-right text-[10.5px] font-medium uppercase tracking-[0.08em] text-muted-2">Total</th>
                  <th scope="col" className="mono border-b border-border px-4 py-3 text-right text-[10.5px] font-medium uppercase tracking-[0.08em] text-muted-2">Balance Due</th>
                  <th scope="col" className="mono border-b border-border px-4 py-3 text-left text-[10.5px] font-medium uppercase tracking-[0.08em] text-muted-2">Due Date</th>
                  <th scope="col" className="mono border-b border-border px-4 py-3 text-left text-[10.5px] font-medium uppercase tracking-[0.08em] text-muted-2">Status</th>
                  <th scope="col" className="mono border-b border-border px-4 py-3 text-right text-[10.5px] font-medium uppercase tracking-[0.08em] text-muted-2">Action</th>
                </tr>
              </thead>
              <tbody>
                {!hasRows ? (
                  <tr>
                    <td colSpan={8} className="px-4 py-12 text-center text-sm text-muted">
                      No outstanding invoices.
                    </td>
                  </tr>
                ) : (
                  invoices.map((inv, i) => {
                    const status = deriveStatus(inv?.days_overdue ?? 0)
                    const invoiceId = inv?.invoice_id
                    return (
                      <tr key={invoiceId ?? i} className="border-b border-border last:border-b-0 hover:bg-canvas">
                        <td className="whitespace-nowrap px-4 py-3 text-sm font-medium text-text mono">{inv?.invoice_number ?? '—'}</td>
                        <td className="whitespace-nowrap px-4 py-3 text-sm text-muted">{inv?.customer_name ?? '—'}</td>
                        <td className="whitespace-nowrap px-4 py-3 text-sm text-muted mono">{inv?.vehicle_rego ?? '—'}</td>
                        <td className="whitespace-nowrap px-4 py-3 text-sm text-text text-right mono">{fmt(inv?.total ?? 0)}</td>
                        <td className="whitespace-nowrap px-4 py-3 text-sm text-danger font-medium text-right mono">{fmt(inv?.balance_due ?? 0)}</td>
                        <td className="whitespace-nowrap px-4 py-3 text-sm text-muted mono">
                          {inv?.due_date ? new Date(inv.due_date).toLocaleDateString('en-NZ') : '—'}
                        </td>
                        <td className="whitespace-nowrap px-4 py-3 text-sm">
                          <Badge variant={status.variant}>{status.label}</Badge>
                        </td>
                        <td className="whitespace-nowrap px-4 py-3 text-sm text-right">
                          <Button
                            variant="ghost"
                            size="sm"
                            loading={sendingReminder === invoiceId}
                            disabled={!invoiceId}
                            onClick={() => { if (invoiceId) sendReminder(invoiceId) }}
                            aria-label={`Send reminder for ${inv?.invoice_number ?? 'invoice'}`}
                          >
                            Send Reminder
                          </Button>
                        </td>
                      </tr>
                    )
                  })
                )}
              </tbody>
            </table>
          </div>
        </>
      )}

      <ToastContainer toasts={toasts} onDismiss={dismissToast} />
    </div>
  )
}
