/**
 * PayRunPage — bulk pay-run console (Staff Management Phase 4, task D1).
 *
 * Per design.md §6.1:
 *   - Period selector — defaults to the first `status='open'` period.
 *   - "Generate drafts" button → creates one payslip per active staff.
 *   - Table of staff × draft payslip with totals.
 *   - Click row → opens PayslipDetail as a drawer.
 *   - "Finalise all" button → bulk-finalise with email-all checkbox.
 *   - Reopen button → opens reason modal; disabled with tooltip when
 *     period.status='paid' (G21).
 *
 * Conventions:
 *   - Typed client only — `frontend/src/api/payslips.ts`.
 *   - All API responses consumed with `?.` + `?? []` / `?? 0`.
 *   - Every effect uses an AbortController.
 *   - Decimal fields arrive as strings; formatted via Intl.NumberFormat.
 *   - Module-gated by `payroll`.
 */

import { lazy, Suspense, useCallback, useEffect, useMemo, useState } from 'react'
import { ModuleGate } from '@/components/common/ModuleGate'
import { Button, Spinner, AlertBanner, Modal, Badge } from '@/components/ui'
import {
  bulkFinalisePeriod,
  generatePeriodPayslips,
  listPayPeriods,
  listPeriodPayslips,
  reopenPayPeriod,
} from '@/api/payslips'
import type {
  BulkFinaliseResult,
  PayPeriod,
  PayPeriodStatus,
  Payslip,
  PayslipStatus,
} from '@/api/payslips'

// PayslipDetail is rendered inside a drawer overlay — lazy-load to keep the
// initial PayRunPage bundle small. Falls back to a spinner while loading.
const PayslipDetail = lazy(() => import('./PayslipDetail'))

const NZD = new Intl.NumberFormat('en-NZ', {
  style: 'currency',
  currency: 'NZD',
})

function formatMoney(value: string | number | null | undefined): string {
  const n = typeof value === 'string' ? Number(value) : (value ?? 0)
  if (!Number.isFinite(n)) return NZD.format(0)
  return NZD.format(n)
}

function formatHours(value: string | null | undefined): string {
  const n = typeof value === 'string' ? Number(value) : 0
  if (!Number.isFinite(n)) return '0.00'
  return n.toFixed(2)
}

function formatDateRange(period: PayPeriod | null | undefined): string {
  if (!period) return '—'
  const fmt = (iso: string) =>
    new Date(`${iso}T00:00:00`).toLocaleDateString('en-NZ', {
      day: 'numeric',
      month: 'short',
      year: 'numeric',
    })
  return `${fmt(period.start_date)} – ${fmt(period.end_date)}`
}

function payslipStatusVariant(
  status: PayslipStatus | string,
): 'success' | 'warning' | 'error' | 'info' | 'neutral' {
  switch (status) {
    case 'finalised':
      return 'success'
    case 'voided':
      return 'error'
    case 'draft':
    default:
      return 'warning'
  }
}

function periodStatusLabel(status: PayPeriodStatus | string): string {
  if (status === 'open') return 'Open'
  if (status === 'finalised') return 'Finalised'
  if (status === 'paid') return 'Paid'
  return status
}

function readErrorMessage(err: unknown): string {
  if (err instanceof DOMException && err.name === 'AbortError') return ''
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

// ───────────────────────────────────────────── BulkFinaliseConfirm ──

interface BulkFinaliseConfirmProps {
  open: boolean
  draftCount: number
  busy: boolean
  result: BulkFinaliseResult | null
  error: string | null
  onConfirm: (emailAll: boolean) => void
  onClose: () => void
}

function BulkFinaliseConfirm({
  open,
  draftCount,
  busy,
  result,
  error,
  onConfirm,
  onClose,
}: BulkFinaliseConfirmProps) {
  const [emailAll, setEmailAll] = useState<boolean>(true)
  return (
    <Modal open={open} onClose={onClose} title="Finalise all draft payslips">
      <div className="space-y-4">
        <p className="text-sm text-gray-700 dark:text-gray-300">
          {draftCount} draft{draftCount === 1 ? '' : 's'} will be finalised. Each
          finalised payslip will be locked and a PDF generated.
        </p>
        <label className="flex items-start gap-2 text-sm text-gray-800 dark:text-gray-200">
          <input
            type="checkbox"
            checked={emailAll}
            onChange={(e) => setEmailAll(e.target.checked)}
            data-testid="bulk-finalise-email-all"
            className="mt-0.5"
          />
          <span>Email each staff member their payslip after finalising.</span>
        </label>
        {busy && (
          <div className="flex items-center gap-2 rounded-md border border-blue-200 bg-blue-50 p-3 dark:border-blue-700 dark:bg-blue-900/20">
            <Spinner size="sm" />
            <span className="text-sm text-blue-900 dark:text-blue-100">
              Finalising{result ? `: ${result.finalised_count ?? 0}` : '…'}
            </span>
          </div>
        )}
        {result && !busy && (
          <div className="rounded-md border border-emerald-200 bg-emerald-50 p-3 text-sm text-emerald-900 dark:border-emerald-700 dark:bg-emerald-900/20 dark:text-emerald-100">
            <p className="font-medium">
              Finalised {result.finalised_count ?? 0} payslip
              {(result.finalised_count ?? 0) === 1 ? '' : 's'}.
            </p>
            {(result.emailed_count ?? 0) > 0 && (
              <p>Emailed {result.emailed_count ?? 0}.</p>
            )}
            {(result.failed_count ?? 0) > 0 && (
              <p className="text-amber-800 dark:text-amber-200">
                {result.failed_count ?? 0} failed — check the table.
              </p>
            )}
          </div>
        )}
        {error && <AlertBanner variant="error">{error}</AlertBanner>}
        <div className="flex justify-end gap-2">
          <Button variant="secondary" onClick={onClose} disabled={busy}>
            {result ? 'Close' : 'Cancel'}
          </Button>
          {!result && (
            <Button
              variant="primary"
              onClick={() => onConfirm(emailAll)}
              loading={busy}
              disabled={busy || draftCount === 0}
              data-testid="bulk-finalise-confirm"
            >
              Finalise all
            </Button>
          )}
        </div>
      </div>
    </Modal>
  )
}

// ───────────────────────────────────────────────── ReopenModal ──

interface ReopenModalProps {
  open: boolean
  busy: boolean
  error: string | null
  onConfirm: (reason: string) => void
  onClose: () => void
}

function ReopenModal({
  open,
  busy,
  error,
  onConfirm,
  onClose,
}: ReopenModalProps) {
  const [reason, setReason] = useState<string>('')
  return (
    <Modal open={open} onClose={onClose} title="Reopen pay period">
      <div className="space-y-4">
        <p className="text-sm text-gray-700 dark:text-gray-300">
          Reopening unlocks the period for new draft payslips that will sit
          alongside the existing finalised ones. Existing finalised payslips
          remain locked.
        </p>
        <label className="block">
          <span className="block text-sm font-medium text-gray-800 dark:text-gray-200">
            Reason
          </span>
          <textarea
            value={reason}
            onChange={(e) => setReason(e.target.value)}
            data-testid="reopen-reason-input"
            rows={3}
            className="mt-1 block w-full rounded-md border border-gray-300 bg-white px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500 dark:border-gray-600 dark:bg-gray-900 dark:text-gray-100"
            placeholder="e.g. correction for missed timesheet approval"
          />
        </label>
        {error && <AlertBanner variant="error">{error}</AlertBanner>}
        <div className="flex justify-end gap-2">
          <Button variant="secondary" onClick={onClose} disabled={busy}>
            Cancel
          </Button>
          <Button
            variant="primary"
            onClick={() => onConfirm(reason.trim())}
            loading={busy}
            disabled={busy || reason.trim().length === 0}
            data-testid="reopen-confirm"
          >
            Reopen
          </Button>
        </div>
      </div>
    </Modal>
  )
}

// ──────────────────────────────────────────────────── PayRunPage ──

export default function PayRunPage() {
  return (
    <ModuleGate module="payroll">
      <PayRunPageInner />
    </ModuleGate>
  )
}

function PayRunPageInner() {
  // Period state
  const [periods, setPeriods] = useState<PayPeriod[]>([])
  const [periodsLoading, setPeriodsLoading] = useState<boolean>(true)
  const [periodsError, setPeriodsError] = useState<string | null>(null)
  const [selectedPeriodId, setSelectedPeriodId] = useState<string | null>(null)

  // Payslip state for the selected period
  const [payslips, setPayslips] = useState<Payslip[]>([])
  const [payslipsLoading, setPayslipsLoading] = useState<boolean>(false)
  const [payslipsError, setPayslipsError] = useState<string | null>(null)

  // Mutations
  const [generating, setGenerating] = useState<boolean>(false)
  const [generateError, setGenerateError] = useState<string | null>(null)

  const [bulkOpen, setBulkOpen] = useState<boolean>(false)
  const [bulkBusy, setBulkBusy] = useState<boolean>(false)
  const [bulkResult, setBulkResult] = useState<BulkFinaliseResult | null>(null)
  const [bulkError, setBulkError] = useState<string | null>(null)

  const [reopenOpen, setReopenOpen] = useState<boolean>(false)
  const [reopenBusy, setReopenBusy] = useState<boolean>(false)
  const [reopenError, setReopenError] = useState<string | null>(null)

  // Drawer
  const [drawerPayslipId, setDrawerPayslipId] = useState<string | null>(null)

  // Refresh tick — bumped when a mutation should re-fetch the payslip list.
  const [refreshTick, setRefreshTick] = useState<number>(0)

  // ── Load all pay periods (open + finalised + paid) ──
  useEffect(() => {
    const controller = new AbortController()
    setPeriodsLoading(true)
    setPeriodsError(null)
    ;(async () => {
      try {
        // Pull a generous slice — most orgs have <100 periods historically.
        const res = await listPayPeriods({ limit: 100 }, controller.signal)
        const items = res.items ?? []
        setPeriods(items)

        // Auto-select the first 'open' period if no selection yet.
        setSelectedPeriodId((prev) => {
          if (prev && items.some((p) => p.id === prev)) return prev
          const firstOpen = items.find((p) => p.status === 'open')
          return firstOpen?.id ?? items[0]?.id ?? null
        })
      } catch (err) {
        if (isAbortError(err)) return
        setPeriodsError(readErrorMessage(err))
      } finally {
        if (!controller.signal.aborted) setPeriodsLoading(false)
      }
    })()
    return () => controller.abort()
  }, [])

  // ── Load payslips for the selected period ──
  useEffect(() => {
    if (!selectedPeriodId) {
      setPayslips([])
      return
    }
    const controller = new AbortController()
    setPayslipsLoading(true)
    setPayslipsError(null)
    ;(async () => {
      try {
        const res = await listPeriodPayslips(
          selectedPeriodId,
          { limit: 200 },
          controller.signal,
        )
        setPayslips(res.items ?? [])
      } catch (err) {
        if (isAbortError(err)) return
        setPayslipsError(readErrorMessage(err))
      } finally {
        if (!controller.signal.aborted) setPayslipsLoading(false)
      }
    })()
    return () => controller.abort()
  }, [selectedPeriodId, refreshTick])

  const selectedPeriod = useMemo<PayPeriod | null>(
    () => (periods ?? []).find((p) => p.id === selectedPeriodId) ?? null,
    [periods, selectedPeriodId],
  )

  const draftCount = useMemo<number>(
    () => (payslips ?? []).filter((p) => p?.status === 'draft').length,
    [payslips],
  )

  const periodIsLocked =
    selectedPeriod?.status === 'finalised' || selectedPeriod?.status === 'paid'

  const handleGenerate = useCallback(async () => {
    if (!selectedPeriodId) return
    setGenerating(true)
    setGenerateError(null)
    try {
      await generatePeriodPayslips(selectedPeriodId)
      setRefreshTick((t) => t + 1)
    } catch (err) {
      setGenerateError(readErrorMessage(err))
    } finally {
      setGenerating(false)
    }
  }, [selectedPeriodId])

  const handleBulkFinalise = useCallback(
    async (emailAll: boolean) => {
      if (!selectedPeriodId) return
      setBulkBusy(true)
      setBulkError(null)
      setBulkResult(null)
      try {
        const res = await bulkFinalisePeriod(selectedPeriodId, {
          email_all: emailAll,
        })
        setBulkResult(res)
        // Refresh the period (status may have flipped to 'finalised') and
        // the payslip list.
        setRefreshTick((t) => t + 1)
        // Re-fetch the period header so the status chip updates.
        try {
          const periodsRes = await listPayPeriods({ limit: 100 })
          setPeriods(periodsRes.items ?? [])
        } catch {
          // best-effort refresh — surfaced via error if list call failed
        }
      } catch (err) {
        setBulkError(readErrorMessage(err))
      } finally {
        setBulkBusy(false)
      }
    },
    [selectedPeriodId],
  )

  const handleReopen = useCallback(
    async (reason: string) => {
      if (!selectedPeriodId) return
      setReopenBusy(true)
      setReopenError(null)
      try {
        await reopenPayPeriod(selectedPeriodId, { reason })
        setReopenOpen(false)
        setRefreshTick((t) => t + 1)
        try {
          const periodsRes = await listPayPeriods({ limit: 100 })
          setPeriods(periodsRes.items ?? [])
        } catch {
          /* ignore — already showed success */
        }
      } catch (err) {
        setReopenError(readErrorMessage(err))
      } finally {
        setReopenBusy(false)
      }
    },
    [selectedPeriodId],
  )

  const closeBulk = useCallback(() => {
    setBulkOpen(false)
    setBulkBusy(false)
    setBulkError(null)
    setBulkResult(null)
  }, [])

  return (
    <div
      className="mx-auto w-full max-w-6xl px-4 py-6"
      data-testid="pay-run-page"
    >
      <header className="mb-6 flex flex-wrap items-start justify-between gap-3">
        <div>
          <h1 className="text-2xl font-semibold text-gray-900 dark:text-gray-100">
            Pay run
          </h1>
          <p className="mt-1 text-sm text-gray-600 dark:text-gray-400">
            Generate, edit and finalise payslips for the selected pay period.
          </p>
        </div>
      </header>

      {periodsError && (
        <AlertBanner variant="error" className="mb-4">
          {periodsError}
        </AlertBanner>
      )}

      {/* Period selector + actions */}
      <section className="mb-4 flex flex-wrap items-end gap-3">
        <label className="block">
          <span className="block text-xs font-medium uppercase tracking-wide text-gray-600 dark:text-gray-400">
            Pay period
          </span>
          <select
            value={selectedPeriodId ?? ''}
            onChange={(e) => setSelectedPeriodId(e.target.value || null)}
            data-testid="period-selector"
            disabled={periodsLoading || (periods ?? []).length === 0}
            className="mt-1 block min-h-[44px] min-w-[280px] rounded-md border border-gray-300 bg-white px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500 disabled:opacity-50 dark:border-gray-600 dark:bg-gray-900 dark:text-gray-100"
          >
            {(periods ?? []).length === 0 && (
              <option value="">No pay periods yet</option>
            )}
            {(periods ?? []).map((p) => (
              <option key={p.id} value={p.id}>
                {formatDateRange(p)} · {periodStatusLabel(p.status)}
              </option>
            ))}
          </select>
        </label>

        {selectedPeriod && (
          <div className="flex flex-col gap-1">
            <span className="text-xs uppercase tracking-wide text-gray-600 dark:text-gray-400">
              Status
            </span>
            <Badge
              variant={
                selectedPeriod.status === 'open'
                  ? 'info'
                  : selectedPeriod.status === 'paid'
                    ? 'success'
                    : 'warning'
              }
            >
              {periodStatusLabel(selectedPeriod.status)}
            </Badge>
          </div>
        )}

        <div className="ml-auto flex flex-wrap items-end gap-2">
          <Button
            variant="secondary"
            onClick={handleGenerate}
            disabled={!selectedPeriodId || periodIsLocked || generating}
            loading={generating}
            data-testid="generate-drafts-button"
          >
            Generate drafts
          </Button>
          <Button
            variant="primary"
            onClick={() => setBulkOpen(true)}
            disabled={
              !selectedPeriodId ||
              periodIsLocked ||
              draftCount === 0 ||
              payslipsLoading
            }
            data-testid="bulk-finalise-button"
          >
            Finalise all ({draftCount})
          </Button>
          {selectedPeriod?.status === 'finalised' && (
            <Button
              variant="secondary"
              onClick={() => setReopenOpen(true)}
              data-testid="reopen-button"
            >
              Reopen
            </Button>
          )}
          {selectedPeriod?.status === 'paid' && (
            <span
              title="Already paid — contact support"
              data-testid="reopen-disabled"
            >
              <Button variant="secondary" disabled>
                Reopen
              </Button>
            </span>
          )}
        </div>
      </section>

      {generateError && (
        <AlertBanner variant="error" className="mb-4">
          {generateError}
        </AlertBanner>
      )}
      {payslipsError && (
        <AlertBanner variant="error" className="mb-4">
          {payslipsError}
        </AlertBanner>
      )}

      {/* Payslip table */}
      {periodsLoading || payslipsLoading ? (
        <div className="flex items-center justify-center py-12">
          <Spinner size="lg" />
        </div>
      ) : (payslips ?? []).length === 0 ? (
        <div
          className="rounded-md border border-dashed border-gray-300 px-4 py-12 text-center text-sm text-gray-500 dark:border-gray-600 dark:text-gray-400"
          data-testid="payslips-empty"
        >
          {selectedPeriodId
            ? 'No draft payslips yet — click "Generate drafts" to create one per active staff member.'
            : 'Select a pay period to begin.'}
        </div>
      ) : (
        <div
          className="overflow-hidden rounded-md border border-gray-200 dark:border-gray-700"
          data-testid="payslips-table-wrapper"
        >
          <table
            className="min-w-full divide-y divide-gray-200 text-sm dark:divide-gray-700"
            data-testid="payslips-table"
          >
            <thead className="bg-gray-50 dark:bg-gray-800">
              <tr>
                <th className="px-4 py-2 text-left font-medium text-gray-600 dark:text-gray-300">
                  Staff
                </th>
                <th className="px-4 py-2 text-left font-medium text-gray-600 dark:text-gray-300">
                  Status
                </th>
                <th className="px-4 py-2 text-right font-medium text-gray-600 dark:text-gray-300">
                  Ord. hours
                </th>
                <th className="px-4 py-2 text-right font-medium text-gray-600 dark:text-gray-300">
                  Gross
                </th>
                <th className="px-4 py-2 text-right font-medium text-gray-600 dark:text-gray-300">
                  Net
                </th>
                <th className="px-4 py-2 text-right font-medium text-gray-600 dark:text-gray-300">
                  Action
                </th>
              </tr>
            </thead>
            <tbody className="divide-y divide-gray-100 bg-white dark:divide-gray-800 dark:bg-gray-900">
              {(payslips ?? []).map((p) => (
                <tr
                  key={p?.id ?? Math.random().toString(36)}
                  className="cursor-pointer hover:bg-gray-50 dark:hover:bg-gray-800"
                  onClick={() => setDrawerPayslipId(p?.id ?? null)}
                  data-testid={`payslip-row-${p?.id ?? ''}`}
                >
                  <td className="px-4 py-2 text-gray-900 dark:text-gray-100">
                    {p?.staff_name ?? '—'}
                  </td>
                  <td className="px-4 py-2">
                    <Badge variant={payslipStatusVariant(p?.status ?? 'draft')}>
                      {p?.status ?? 'draft'}
                    </Badge>
                  </td>
                  <td className="px-4 py-2 text-right tabular-nums text-gray-700 dark:text-gray-300">
                    {formatHours(p?.ordinary_hours)}
                  </td>
                  <td className="px-4 py-2 text-right tabular-nums text-gray-900 dark:text-gray-100">
                    {formatMoney(p?.gross_pay)}
                  </td>
                  <td className="px-4 py-2 text-right tabular-nums text-gray-900 dark:text-gray-100">
                    {formatMoney(p?.net_pay)}
                  </td>
                  <td className="px-4 py-2 text-right">
                    <button
                      type="button"
                      onClick={(e) => {
                        e.stopPropagation()
                        setDrawerPayslipId(p?.id ?? null)
                      }}
                      className="min-h-[36px] rounded border border-gray-300 px-3 py-1 text-xs font-medium text-gray-700 hover:bg-gray-50 dark:border-gray-600 dark:text-gray-200 dark:hover:bg-gray-800"
                    >
                      {p?.status === 'draft' ? 'Edit' : 'View'}
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {/* Bulk finalise modal */}
      <BulkFinaliseConfirm
        open={bulkOpen}
        draftCount={draftCount}
        busy={bulkBusy}
        result={bulkResult}
        error={bulkError}
        onConfirm={handleBulkFinalise}
        onClose={closeBulk}
      />

      {/* Reopen modal */}
      <ReopenModal
        open={reopenOpen}
        busy={reopenBusy}
        error={reopenError}
        onConfirm={handleReopen}
        onClose={() => {
          setReopenOpen(false)
          setReopenError(null)
        }}
      />

      {/* Drawer */}
      {drawerPayslipId && (
        <PayslipDrawer
          payslipId={drawerPayslipId}
          onClose={() => {
            setDrawerPayslipId(null)
            setRefreshTick((t) => t + 1)
          }}
        />
      )}
    </div>
  )
}

// ────────────────────────────────────────────────── PayslipDrawer ──

interface PayslipDrawerProps {
  payslipId: string
  onClose: () => void
}

function PayslipDrawer({ payslipId, onClose }: PayslipDrawerProps) {
  // Close on Escape.
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') onClose()
    }
    document.addEventListener('keydown', onKey)
    return () => document.removeEventListener('keydown', onKey)
  }, [onClose])

  return (
    <div
      role="dialog"
      aria-modal="true"
      aria-labelledby="payslip-drawer-title"
      data-testid="payslip-drawer"
      className="fixed inset-0 z-50 flex justify-end bg-black/50"
      onClick={onClose}
    >
      <div
        className="flex h-full w-full max-w-3xl flex-col overflow-y-auto bg-white shadow-xl dark:bg-gray-900"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="flex items-center justify-between border-b border-gray-200 px-4 py-3 dark:border-gray-700">
          <h2
            id="payslip-drawer-title"
            className="text-lg font-semibold text-gray-900 dark:text-gray-100"
          >
            Payslip detail
          </h2>
          <button
            type="button"
            onClick={onClose}
            aria-label="Close drawer"
            className="min-h-[44px] min-w-[44px] rounded p-2 text-gray-500 hover:text-gray-700 focus:outline-none focus:ring-2 focus:ring-blue-500 dark:text-gray-400 dark:hover:text-gray-200"
          >
            <span aria-hidden="true" className="text-xl leading-none">
              ×
            </span>
          </button>
        </div>
        <div className="flex-1 px-4 py-4">
          <Suspense fallback={<Spinner size="lg" />}>
            <PayslipDetail payslipId={payslipId} onClose={onClose} embedded />
          </Suspense>
        </div>
      </div>
    </div>
  )
}
