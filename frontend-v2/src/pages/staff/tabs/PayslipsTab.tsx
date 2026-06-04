/**
 * PayslipsTab — Staff Detail "Payslips" tab (Phase 4 task D3).
 *
 * Per design.md §6.3:
 *   - List of past payslips for this staff member.
 *   - Status chip (draft / finalised / voided).
 *   - Pay period dates.
 *   - Gross / Net columns.
 *   - PDF download button (calls downloadPayslipPdf).
 *   - Email button (calls emailPayslip) — only visible for finalised.
 *   - Void button (admin only) — only visible for non-voided.
 *
 * Conventions:
 *   - Typed client only (`@/api/payslips`).
 *   - All API responses consumed with `?.` + `?? []` / `?? null`.
 *   - Decimal values arrive as strings; formatted via Intl.NumberFormat
 *     with NaN guards.
 *   - Every effect uses an AbortController.
 *
 * **Validates: Staff Management Phase 4 task D3, Requirements R3.5**
 *
 * Presentation remapped onto the design-system tokens. Badge variants are
 * mapped to the v2 tones (warning→warn, error→danger); Button secondary→ghost.
 */

import { useCallback, useEffect, useMemo, useState } from 'react'
import { Badge, Button, Spinner, AlertBanner, Modal } from '@/components/ui'
import type { BadgeVariant } from '@/components/ui'
import { useAuth } from '@/contexts/AuthContext'
import {
  downloadPayslipPdf,
  emailPayslip,
  listStaffPayslips,
  voidPayslip,
} from '@/api/payslips'
import type { Payslip, PayslipStatus } from '@/api/payslips'

const NZD = new Intl.NumberFormat('en-NZ', {
  style: 'currency',
  currency: 'NZD',
})

const ADMIN_ROLES = new Set(['org_admin', 'global_admin'])

function formatMoney(value: string | number | null | undefined): string {
  const n = typeof value === 'string' ? Number(value) : (value ?? 0)
  if (!Number.isFinite(n)) return NZD.format(0)
  return NZD.format(n)
}

function formatDate(iso: string | null | undefined): string {
  if (!iso) return '—'
  try {
    return new Date(`${iso}T00:00:00`).toLocaleDateString('en-NZ', {
      day: 'numeric',
      month: 'short',
      year: 'numeric',
    })
  } catch {
    return iso
  }
}

function formatPeriodRange(p: Payslip): string {
  const period = p?.pay_period ?? null
  if (!period) return '—'
  return `${formatDate(period.start_date)} – ${formatDate(period.end_date)}`
}

function isAbortError(err: unknown): boolean {
  if (err instanceof DOMException && err.name === 'AbortError') return true
  if (
    typeof err === 'object' &&
    err !== null &&
    'code' in err &&
    (err as { code?: string }).code === 'ERR_CANCELED'
  ) {
    return true
  }
  return false
}

function readErrorMessage(err: unknown): string {
  const detail = (err as { response?: { data?: { detail?: unknown } } })
    ?.response?.data?.detail
  if (typeof detail === 'string') return detail
  if (
    detail &&
    typeof detail === 'object' &&
    'detail' in detail &&
    typeof (detail as { detail?: unknown }).detail === 'string'
  ) {
    return (detail as { detail: string }).detail
  }
  if (err instanceof Error) return err.message
  return 'Something went wrong.'
}

function statusBadgeVariant(
  status: PayslipStatus | string,
): BadgeVariant {
  switch (status) {
    case 'finalised':
      return 'success'
    case 'voided':
      return 'danger'
    case 'draft':
    default:
      return 'warn'
  }
}

interface PayslipsTabProps {
  staffId: string
}

interface VoidModalState {
  open: boolean
  payslipId: string | null
  reason: string
  busy: boolean
  error: string | null
}

const EMPTY_VOID: VoidModalState = {
  open: false,
  payslipId: null,
  reason: '',
  busy: false,
  error: null,
}

export default function PayslipsTab({ staffId }: PayslipsTabProps) {
  const { user } = useAuth()
  const role = user?.role ?? null
  const isAdmin = !!role && ADMIN_ROLES.has(role)

  const [items, setItems] = useState<Payslip[]>([])
  const [loading, setLoading] = useState<boolean>(true)
  const [loadError, setLoadError] = useState<string | null>(null)
  const [refreshTick, setRefreshTick] = useState<number>(0)

  // Per-row busy / error state.
  const [busyId, setBusyId] = useState<string | null>(null)
  const [busyAction, setBusyAction] = useState<
    'pdf' | 'email' | 'void' | null
  >(null)
  const [rowError, setRowError] = useState<{
    id: string
    message: string
  } | null>(null)

  const [voidModal, setVoidModal] = useState<VoidModalState>(EMPTY_VOID)

  // ── Fetch staff payslip history ──
  useEffect(() => {
    if (!staffId) return
    const controller = new AbortController()
    setLoading(true)
    setLoadError(null)
    ;(async () => {
      try {
        const res = await listStaffPayslips(
          staffId,
          { limit: 100 },
          controller.signal,
        )
        if (controller.signal.aborted) return
        setItems(res.items ?? [])
      } catch (err) {
        if (isAbortError(err)) return
        setLoadError(readErrorMessage(err))
      } finally {
        if (!controller.signal.aborted) setLoading(false)
      }
    })()
    return () => controller.abort()
  }, [staffId, refreshTick])

  // Sort newest-first by pay_period.end_date when available; fallback to
  // created_at.
  const sortedItems = useMemo<Payslip[]>(() => {
    const safe = items ?? []
    return [...safe].sort((a, b) => {
      const aKey =
        a?.pay_period?.end_date ?? a?.created_at ?? ''
      const bKey =
        b?.pay_period?.end_date ?? b?.created_at ?? ''
      return bKey.localeCompare(aKey)
    })
  }, [items])

  const refresh = useCallback(() => setRefreshTick((t) => t + 1), [])

  // ── PDF download ──
  const handleDownloadPdf = useCallback(
    async (payslip: Payslip) => {
      if (!payslip?.id) return
      setBusyId(payslip.id)
      setBusyAction('pdf')
      setRowError(null)
      try {
        const blob = await downloadPayslipPdf(payslip.id)
        const url = window.URL.createObjectURL(blob)
        const a = document.createElement('a')
        a.href = url
        const periodLabel = payslip?.pay_period?.end_date ?? 'payslip'
        a.download = `payslip-${periodLabel}.pdf`
        document.body.appendChild(a)
        a.click()
        document.body.removeChild(a)
        // Free the blob URL on next tick (browsers tolerate reuse but
        // releasing prevents memory pressure with many downloads).
        setTimeout(() => window.URL.revokeObjectURL(url), 0)
      } catch (err) {
        setRowError({
          id: payslip.id,
          message: readErrorMessage(err) || 'Download failed',
        })
      } finally {
        setBusyId(null)
        setBusyAction(null)
      }
    },
    [],
  )

  // ── Email payslip (finalised only) ──
  const handleEmail = useCallback(
    async (payslip: Payslip) => {
      if (!payslip?.id) return
      setBusyId(payslip.id)
      setBusyAction('email')
      setRowError(null)
      try {
        await emailPayslip(payslip.id)
        refresh()
      } catch (err) {
        setRowError({
          id: payslip.id,
          message: readErrorMessage(err) || 'Email failed',
        })
      } finally {
        setBusyId(null)
        setBusyAction(null)
      }
    },
    [refresh],
  )

  // ── Void modal ──
  const openVoidModal = useCallback((payslip: Payslip) => {
    setVoidModal({
      open: true,
      payslipId: payslip?.id ?? null,
      reason: '',
      busy: false,
      error: null,
    })
  }, [])

  const closeVoidModal = useCallback(() => {
    setVoidModal(EMPTY_VOID)
  }, [])

  const handleConfirmVoid = useCallback(async () => {
    const id = voidModal.payslipId
    const reason = voidModal.reason.trim()
    if (!id || reason.length === 0) return
    setVoidModal((s) => ({ ...s, busy: true, error: null }))
    try {
      await voidPayslip(id, { reason })
      setVoidModal(EMPTY_VOID)
      refresh()
    } catch (err) {
      setVoidModal((s) => ({
        ...s,
        busy: false,
        error: readErrorMessage(err) || 'Void failed',
      }))
    }
  }, [voidModal, refresh])

  return (
    <div
      className="px-6 py-4"
      data-testid="payslips-tab"
    >
      <header className="mb-4 flex flex-wrap items-start justify-between gap-3">
        <div>
          <h2 className="text-lg font-semibold text-text">
            Payslips
          </h2>
          <p className="text-sm text-muted">
            Past payslips generated for this staff member.
          </p>
        </div>
      </header>

      {loadError && (
        <AlertBanner variant="error" className="mb-4">
          {loadError}
        </AlertBanner>
      )}

      {loading ? (
        <div className="flex items-center justify-center py-12">
          <Spinner size="lg" label="Loading payslips" />
        </div>
      ) : sortedItems.length === 0 ? (
        <div
          className="rounded-card border border-dashed border-border px-4 py-12 text-center text-sm text-muted"
          data-testid="payslips-tab-empty"
        >
          No payslips have been generated for this staff member yet.
        </div>
      ) : (
        <section
          className="overflow-hidden rounded-card border border-border bg-card shadow-card"
          data-testid="payslips-tab-table-wrapper"
        >
          <div className="overflow-x-auto">
          <table
            className="w-full border-collapse text-sm"
            data-testid="payslips-tab-table"
          >
            <thead>
              <tr>
                <th className="mono border-b border-border px-4 py-3 text-left text-[10.5px] font-medium uppercase tracking-[0.08em] text-muted-2">
                  Pay period
                </th>
                <th className="mono border-b border-border px-4 py-3 text-left text-[10.5px] font-medium uppercase tracking-[0.08em] text-muted-2">
                  Status
                </th>
                <th className="mono border-b border-border px-4 py-3 text-right text-[10.5px] font-medium uppercase tracking-[0.08em] text-muted-2">
                  Gross
                </th>
                <th className="mono border-b border-border px-4 py-3 text-right text-[10.5px] font-medium uppercase tracking-[0.08em] text-muted-2">
                  Net
                </th>
                <th className="mono border-b border-border px-4 py-3 text-right text-[10.5px] font-medium uppercase tracking-[0.08em] text-muted-2">
                  Actions
                </th>
              </tr>
            </thead>
            <tbody>
              {sortedItems.map((p) => {
                const status = p?.status ?? 'draft'
                const isFinalised = status === 'finalised'
                const isVoided = status === 'voided'
                const isBusy = busyId === p?.id
                const errMessage =
                  rowError && rowError.id === p?.id ? rowError.message : null
                return (
                  <tr
                    key={p?.id ?? Math.random().toString(36)}
                    data-testid={`payslip-tab-row-${p?.id ?? ''}`}
                    className="border-b border-border last:border-b-0 hover:bg-canvas"
                  >
                    <td className="px-4 py-3 text-text">
                      <div className="flex flex-col">
                        <span className="mono">{formatPeriodRange(p)}</span>
                        {p?.emailed_at && (
                          <span className="mono text-xs text-muted">
                            Emailed {formatDate(p.emailed_at.split('T')[0])}
                          </span>
                        )}
                      </div>
                    </td>
                    <td className="px-4 py-3">
                      <Badge variant={statusBadgeVariant(status)}>
                        {status}
                      </Badge>
                    </td>
                    <td className="mono px-4 py-3 text-right text-text">
                      {formatMoney(p?.gross_pay)}
                    </td>
                    <td className="mono px-4 py-3 text-right text-text">
                      {formatMoney(p?.net_pay)}
                    </td>
                    <td className="px-4 py-3 text-right">
                      <div className="flex flex-wrap items-center justify-end gap-2">
                        <Button
                          size="sm"
                          variant="ghost"
                          onClick={() => handleDownloadPdf(p)}
                          disabled={!isFinalised || isBusy}
                          loading={isBusy && busyAction === 'pdf'}
                          title={
                            !isFinalised
                              ? 'PDF available once finalised'
                              : 'Download PDF'
                          }
                          data-testid={`payslip-tab-pdf-${p?.id ?? ''}`}
                        >
                          PDF
                        </Button>
                        {isFinalised && (
                          <Button
                            size="sm"
                            variant="ghost"
                            onClick={() => handleEmail(p)}
                            disabled={isBusy}
                            loading={isBusy && busyAction === 'email'}
                            data-testid={`payslip-tab-email-${p?.id ?? ''}`}
                          >
                            Email
                          </Button>
                        )}
                        {isAdmin && !isVoided && (
                          <Button
                            size="sm"
                            variant="danger"
                            onClick={() => openVoidModal(p)}
                            disabled={isBusy}
                            data-testid={`payslip-tab-void-${p?.id ?? ''}`}
                          >
                            Void
                          </Button>
                        )}
                      </div>
                      {errMessage && (
                        <p
                          role="alert"
                          className="mt-1 text-xs text-danger"
                        >
                          {errMessage}
                        </p>
                      )}
                    </td>
                  </tr>
                )
              })}
            </tbody>
          </table>
          </div>
        </section>
      )}

      <Modal
        open={voidModal.open}
        onClose={voidModal.busy ? () => undefined : closeVoidModal}
        title="Void payslip"
      >
        <div className="space-y-4">
          <p className="text-sm text-muted">
            Voiding marks this payslip as cancelled. Generate a compensating
            draft afterwards if a corrected payslip is needed.
          </p>
          <label className="block">
            <span className="block text-[12.5px] font-medium text-text">
              Reason
            </span>
            <textarea
              value={voidModal.reason}
              onChange={(e) =>
                setVoidModal((s) => ({ ...s, reason: e.target.value }))
              }
              rows={3}
              className="mt-1 block w-full rounded-ctl border border-border bg-card px-3 py-2 text-sm text-text focus:border-accent focus:outline-none focus:shadow-[0_0_0_3px_var(--accent-soft)]"
              placeholder="e.g. duplicate payslip, generated in wrong period"
              data-testid="payslip-tab-void-reason"
            />
          </label>
          {voidModal.error && (
            <AlertBanner variant="error">{voidModal.error}</AlertBanner>
          )}
          <div className="flex justify-end gap-2">
            <Button
              variant="ghost"
              onClick={closeVoidModal}
              disabled={voidModal.busy}
            >
              Cancel
            </Button>
            <Button
              variant="danger"
              onClick={handleConfirmVoid}
              loading={voidModal.busy}
              disabled={
                voidModal.busy || voidModal.reason.trim().length === 0
              }
              data-testid="payslip-tab-void-confirm"
            >
              Void payslip
            </Button>
          </div>
        </div>
      </Modal>
    </div>
  )
}
