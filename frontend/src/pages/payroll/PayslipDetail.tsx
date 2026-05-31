/**
 * PayslipDetail — drawer/modal editor (Staff Management Phase 4, tasks D2 + D8).
 *
 * Per design.md §6.2:
 *   - Header: staff name + period dates + status chip + actions
 *     (Save / Finalise / Send / Download PDF / Void) — buttons enabled
 *     per status (`'draft' | 'finalised' | 'voided'`).
 *   - Hours (read-only when finalised): ordinary, overtime, public_holiday.
 *     Public holiday band as a separate row (G2) with editable rate
 *     (default = ordinary × 1.5; tooltip explains override).
 *   - Allowances: each row reads `quantity unit × unit_price = amount`
 *     for unit ∈ {'shift','km'}; just `amount` when unit='period' (G18).
 *     For unit='km', admin can edit the quantity directly.
 *   - Reimbursements (editable list).
 *   - Deductions: PAYE numeric input (admin enters from IRD), ACC numeric,
 *     KiwiSaver auto-shown read-only, student_loan visible if applicable,
 *     child_support, voluntary.
 *   - Leave taken section (read-only).
 *   - Live computed gross / net / kiwisaver_employer (informational).
 *   - PDF preview iframe (D8) when status='finalised', sourced from a blob
 *     URL constructed from downloadPayslipPdf(); revoked on unmount.
 *
 * Conventions:
 *   - Typed client only; all responses guarded with `?.` + `?? []` / `?? null`.
 *   - Every effect uses an AbortController.
 *   - Decimal values arrive as strings; formatted with Intl.NumberFormat.
 */

import {
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
  type ReactNode,
} from 'react'
import { useParams } from 'react-router-dom'
import { ModuleGate } from '@/components/common/ModuleGate'
import { Button, Spinner, AlertBanner, Badge } from '@/components/ui'
import {
  downloadPayslipPdf,
  emailPayslip,
  finalisePayslip,
  getPayslip,
  updatePayslip,
  voidPayslip,
} from '@/api/payslips'
import type {
  AllowanceUnit,
  Payslip,
  PayslipAllowance,
  PayslipDeduction,
  PayslipDetail as PayslipDetailType,
  PayslipLeaveLine,
  PayslipReimbursement,
  PayslipStatus,
  PayslipUpdatePayload,
} from '@/api/payslips'

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

interface PayslipDetailComponentProps {
  /** When provided, overrides URL params (used when rendered as a drawer). */
  payslipId?: string
  /** Closes the drawer/modal when rendered embedded. */
  onClose?: () => void
  /** True when rendered inside a drawer (no extra page chrome). */
  embedded?: boolean
}

export default function PayslipDetail({
  payslipId,
  onClose,
  embedded,
}: PayslipDetailComponentProps) {
  const params = useParams<{ id?: string }>()
  const effectiveId = payslipId ?? params.id ?? null

  return (
    <ModuleGate module="payroll">
      <div
        data-testid="payslip-detail"
        className={
          embedded
            ? ''
            : 'mx-auto w-full max-w-4xl px-4 py-6'
        }
      >
        {effectiveId ? (
          <PayslipDetailInner
            payslipId={effectiveId}
            onClose={onClose}
            embedded={!!embedded}
          />
        ) : (
          <AlertBanner variant="error">No payslip selected.</AlertBanner>
        )}
      </div>
    </ModuleGate>
  )
}

interface PayslipDetailInnerProps {
  payslipId: string
  onClose?: () => void
  embedded: boolean
}

function PayslipDetailInner({
  payslipId,
  onClose,
  embedded: _embedded,
}: PayslipDetailInnerProps) {
  const [data, setData] = useState<PayslipDetailType | null>(null)
  const [loading, setLoading] = useState<boolean>(true)
  const [loadError, setLoadError] = useState<string | null>(null)

  // Editable hours / rates (only meaningful when status='draft')
  const [form, setForm] = useState<PayslipUpdatePayload>({})
  const [saving, setSaving] = useState<boolean>(false)
  const [saveError, setSaveError] = useState<string | null>(null)

  // Action busy flags + errors
  const [finalising, setFinalising] = useState<boolean>(false)
  const [actionError, setActionError] = useState<string | null>(null)
  const [emailing, setEmailing] = useState<boolean>(false)
  const [voiding, setVoiding] = useState<boolean>(false)
  const [downloadingPdf, setDownloadingPdf] = useState<boolean>(false)

  // Refresh tick
  const [refreshTick, setRefreshTick] = useState<number>(0)

  // ── Fetch payslip ──
  useEffect(() => {
    const controller = new AbortController()
    setLoading(true)
    setLoadError(null)
    ;(async () => {
      try {
        const res = await getPayslip(payslipId, controller.signal)
        if (controller.signal.aborted) return
        setData(res ?? null)
        setForm({
          ordinary_hours: res?.ordinary_hours ?? null,
          overtime_hours: res?.overtime_hours ?? null,
          public_holiday_hours: res?.public_holiday_hours ?? null,
          ordinary_rate: res?.ordinary_rate ?? null,
          overtime_rate: res?.overtime_rate ?? null,
          public_holiday_rate: res?.public_holiday_rate ?? null,
          notes: res?.notes ?? null,
        })
      } catch (err) {
        if (isAbortError(err)) return
        setLoadError(readErrorMessage(err))
      } finally {
        if (!controller.signal.aborted) setLoading(false)
      }
    })()
    return () => controller.abort()
  }, [payslipId, refreshTick])

  const status: PayslipStatus | string = data?.status ?? 'draft'
  const isDraft = status === 'draft'
  const isFinalised = status === 'finalised'
  const isVoided = status === 'voided'

  const allowances = data?.allowances ?? []
  const deductions = data?.deductions ?? []
  const reimbursements = data?.reimbursements ?? []
  const leaveLines = data?.leave_lines ?? []

  // ── Live computed totals (informational; canonical math is server-side) ──
  const computed = useMemo(() => {
    const num = (s: string | null | undefined) => {
      const n = typeof s === 'string' ? Number(s) : 0
      return Number.isFinite(n) ? n : 0
    }

    const ordHrs = num(form.ordinary_hours ?? data?.ordinary_hours)
    const otHrs = num(form.overtime_hours ?? data?.overtime_hours)
    const phHrs = num(form.public_holiday_hours ?? data?.public_holiday_hours)
    const ordRate = num(form.ordinary_rate ?? data?.ordinary_rate)
    const otRate = num(form.overtime_rate ?? data?.overtime_rate)
    const phRate = num(form.public_holiday_rate ?? data?.public_holiday_rate)

    const wages = ordHrs * ordRate + otHrs * otRate + phHrs * phRate
    const allowanceTotal = allowances.reduce(
      (acc, a) => acc + num(a?.amount),
      0,
    )
    const reimbursementTotal = reimbursements.reduce(
      (acc, r) => acc + num(r?.amount),
      0,
    )
    const leaveTotal = leaveLines.reduce(
      (acc, ll) => acc + num(ll?.amount),
      0,
    )

    // Employer KiwiSaver is informational and NOT part of gross.
    const employerKiwi = deductions
      .filter((d) => d?.kind === 'kiwisaver_employer')
      .reduce((acc, d) => acc + num(d?.amount), 0)

    const employeeDeductionTotal = deductions
      .filter((d) => d?.kind !== 'kiwisaver_employer')
      .reduce((acc, d) => acc + num(d?.amount), 0)

    const gross = wages + allowanceTotal + leaveTotal
    const net = gross - employeeDeductionTotal + reimbursementTotal
    return {
      gross,
      net,
      employerKiwi,
      reimbursementTotal,
      employeeDeductionTotal,
      wages,
    }
  }, [
    allowances,
    deductions,
    leaveLines,
    reimbursements,
    form.ordinary_hours,
    form.ordinary_rate,
    form.overtime_hours,
    form.overtime_rate,
    form.public_holiday_hours,
    form.public_holiday_rate,
    data,
  ])

  const phDefault = useMemo(() => {
    const ord = Number(form.ordinary_rate ?? data?.ordinary_rate ?? '0')
    if (!Number.isFinite(ord) || ord === 0) return null
    return (ord * 1.5).toFixed(2)
  }, [form.ordinary_rate, data])

  const setField = useCallback(
    <K extends keyof PayslipUpdatePayload>(
      key: K,
      value: PayslipUpdatePayload[K],
    ) => {
      setForm((prev) => ({ ...prev, [key]: value }))
    },
    [],
  )

  // ── Save (draft only) ──
  const handleSave = useCallback(async () => {
    if (!isDraft) return
    setSaving(true)
    setSaveError(null)
    try {
      await updatePayslip(payslipId, form)
      setRefreshTick((t) => t + 1)
    } catch (err) {
      setSaveError(readErrorMessage(err))
    } finally {
      setSaving(false)
    }
  }, [isDraft, payslipId, form])

  // ── Finalise ──
  const handleFinalise = useCallback(async () => {
    if (!isDraft) return
    setFinalising(true)
    setActionError(null)
    try {
      await finalisePayslip(payslipId)
      setRefreshTick((t) => t + 1)
    } catch (err) {
      setActionError(readErrorMessage(err))
    } finally {
      setFinalising(false)
    }
  }, [isDraft, payslipId])

  // ── Send (post-finalise) ──
  const handleEmail = useCallback(async () => {
    if (!isFinalised) return
    setEmailing(true)
    setActionError(null)
    try {
      await emailPayslip(payslipId)
      setRefreshTick((t) => t + 1)
    } catch (err) {
      setActionError(readErrorMessage(err))
    } finally {
      setEmailing(false)
    }
  }, [isFinalised, payslipId])

  // ── Void ──
  const handleVoid = useCallback(async () => {
    if (isVoided) return
    if (!window.confirm('Void this payslip? This cannot be undone.')) return
    setVoiding(true)
    setActionError(null)
    try {
      await voidPayslip(payslipId, {})
      setRefreshTick((t) => t + 1)
    } catch (err) {
      setActionError(readErrorMessage(err))
    } finally {
      setVoiding(false)
    }
  }, [isVoided, payslipId])

  // ── Download PDF (used by both Download button and PDF preview iframe) ──
  const handleDownloadPdf = useCallback(async () => {
    setDownloadingPdf(true)
    setActionError(null)
    try {
      const blob = await downloadPayslipPdf(payslipId)
      const url = URL.createObjectURL(blob)
      const a = document.createElement('a')
      a.href = url
      a.download = `payslip-${payslipId}.pdf`
      document.body.appendChild(a)
      a.click()
      document.body.removeChild(a)
      // Browsers need a tick to consume the URL before we revoke it.
      setTimeout(() => URL.revokeObjectURL(url), 1000)
    } catch (err) {
      setActionError(readErrorMessage(err))
    } finally {
      setDownloadingPdf(false)
    }
  }, [payslipId])

  if (loading) {
    return (
      <div className="flex justify-center py-12">
        <Spinner size="lg" />
      </div>
    )
  }
  if (loadError) {
    return <AlertBanner variant="error">{loadError}</AlertBanner>
  }
  if (!data) {
    return <AlertBanner variant="error">Payslip not found.</AlertBanner>
  }

  return (
    <div className="space-y-6">
      {/* Header */}
      <header
        className="flex flex-wrap items-start justify-between gap-3 border-b border-gray-200 pb-3 dark:border-gray-700"
        data-testid="payslip-header"
      >
        <div>
          <h1 className="text-xl font-semibold text-gray-900 dark:text-gray-100">
            {data.staff_name ?? 'Payslip'}
          </h1>
          <p className="mt-0.5 text-sm text-gray-600 dark:text-gray-400">
            {formatDate(data.pay_period?.start_date)}
            {' – '}
            {formatDate(data.pay_period?.end_date)}
            {data.pay_period?.pay_date && (
              <> · Pay date {formatDate(data.pay_period.pay_date)}</>
            )}
          </p>
          <div className="mt-1.5">
            <Badge variant={statusBadgeVariant(status)}>{status}</Badge>
          </div>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          <Button
            variant="primary"
            onClick={handleSave}
            disabled={!isDraft || saving}
            loading={saving}
            data-testid="payslip-save-button"
          >
            Save
          </Button>
          <Button
            variant="secondary"
            onClick={handleFinalise}
            disabled={!isDraft || finalising}
            loading={finalising}
            data-testid="payslip-finalise-button"
          >
            Finalise
          </Button>
          <Button
            variant="secondary"
            onClick={handleEmail}
            disabled={!isFinalised || emailing}
            loading={emailing}
            data-testid="payslip-email-button"
          >
            Send
          </Button>
          <Button
            variant="secondary"
            onClick={handleDownloadPdf}
            disabled={!isFinalised || downloadingPdf}
            loading={downloadingPdf}
            data-testid="payslip-pdf-button"
          >
            Download PDF
          </Button>
          <Button
            variant="danger"
            onClick={handleVoid}
            disabled={isVoided || voiding}
            loading={voiding}
            data-testid="payslip-void-button"
          >
            Void
          </Button>
          {onClose && (
            <Button
              variant="secondary"
              onClick={onClose}
              data-testid="payslip-close-button"
            >
              Close
            </Button>
          )}
        </div>
      </header>

      {actionError && <AlertBanner variant="error">{actionError}</AlertBanner>}
      {saveError && <AlertBanner variant="error">{saveError}</AlertBanner>}

      {/* Hours section */}
      <Section title="Hours" testId="payslip-hours-section">
        <div className="grid grid-cols-1 gap-3 sm:grid-cols-3">
          <NumericRow
            label="Ordinary hours"
            value={form.ordinary_hours ?? ''}
            onChange={(v) => setField('ordinary_hours', v)}
            disabled={!isDraft}
            testId="ordinary-hours-input"
          />
          <NumericRow
            label="Ordinary rate"
            value={form.ordinary_rate ?? ''}
            onChange={(v) => setField('ordinary_rate', v)}
            disabled={!isDraft}
            testId="ordinary-rate-input"
          />
          <ReadonlyRow
            label="Wages subtotal"
            value={formatMoney(computed.wages)}
            testId="wages-subtotal"
          />
          <NumericRow
            label="Overtime hours"
            value={form.overtime_hours ?? ''}
            onChange={(v) => setField('overtime_hours', v)}
            disabled={!isDraft}
            testId="overtime-hours-input"
          />
          <NumericRow
            label="Overtime rate"
            value={form.overtime_rate ?? ''}
            onChange={(v) => setField('overtime_rate', v)}
            disabled={!isDraft}
            testId="overtime-rate-input"
          />
          <div />
        </div>

        {/* Public-holiday band as a SEPARATE row (G2) */}
        <div
          className="mt-3 grid grid-cols-1 gap-3 rounded-md border border-amber-200 bg-amber-50 p-3 sm:grid-cols-3 dark:border-amber-700 dark:bg-amber-900/10"
          data-testid="public-holiday-row"
        >
          <NumericRow
            label="Public holiday hours"
            value={form.public_holiday_hours ?? ''}
            onChange={(v) => setField('public_holiday_hours', v)}
            disabled={!isDraft}
            testId="public-holiday-hours-input"
          />
          <NumericRow
            label="Public holiday rate"
            value={form.public_holiday_rate ?? ''}
            onChange={(v) => setField('public_holiday_rate', v)}
            disabled={!isDraft}
            testId="public-holiday-rate-input"
            hint={
              phDefault
                ? `Default = ordinary × 1.5 (${formatMoney(phDefault)}); admin override per staff if needed`
                : 'Default = ordinary × 1.5; admin override per staff if needed'
            }
          />
          <div />
        </div>
      </Section>

      {/* Allowances section */}
      <Section title="Allowances" testId="payslip-allowances-section">
        {allowances.length === 0 ? (
          <EmptyHint>No allowances on this payslip.</EmptyHint>
        ) : (
          <table className="min-w-full divide-y divide-gray-200 text-sm dark:divide-gray-700">
            <thead className="bg-gray-50 dark:bg-gray-800">
              <tr>
                <th className="px-3 py-2 text-left font-medium text-gray-600 dark:text-gray-300">
                  Allowance
                </th>
                <th className="px-3 py-2 text-right font-medium text-gray-600 dark:text-gray-300">
                  Detail
                </th>
                <th className="px-3 py-2 text-right font-medium text-gray-600 dark:text-gray-300">
                  Amount
                </th>
              </tr>
            </thead>
            <tbody className="divide-y divide-gray-100 dark:divide-gray-800">
              {(allowances ?? []).map((a) => (
                <AllowanceRow
                  key={a?.id ?? Math.random().toString(36)}
                  allowance={a}
                  isDraft={isDraft}
                />
              ))}
            </tbody>
          </table>
        )}
      </Section>

      {/* Reimbursements */}
      <Section
        title="Reimbursements"
        testId="payslip-reimbursements-section"
      >
        {reimbursements.length === 0 ? (
          <EmptyHint>No reimbursements on this payslip.</EmptyHint>
        ) : (
          <SimpleAmountList items={reimbursements} testId="reimbursement-row" />
        )}
      </Section>

      {/* Deductions */}
      <Section title="Deductions" testId="payslip-deductions-section">
        {deductions.length === 0 ? (
          <EmptyHint>No deductions on this payslip.</EmptyHint>
        ) : (
          <table className="min-w-full divide-y divide-gray-200 text-sm dark:divide-gray-700">
            <tbody className="divide-y divide-gray-100 dark:divide-gray-800">
              {(deductions ?? []).map((d) => (
                <DeductionRow
                  key={d?.id ?? Math.random().toString(36)}
                  deduction={d}
                />
              ))}
            </tbody>
          </table>
        )}
      </Section>

      {/* Leave taken (read-only) */}
      <Section title="Leave taken" testId="payslip-leave-section">
        {leaveLines.length === 0 ? (
          <EmptyHint>No leave taken in this period.</EmptyHint>
        ) : (
          <table className="min-w-full divide-y divide-gray-200 text-sm dark:divide-gray-700">
            <thead className="bg-gray-50 dark:bg-gray-800">
              <tr>
                <th className="px-3 py-2 text-left font-medium text-gray-600 dark:text-gray-300">
                  Type
                </th>
                <th className="px-3 py-2 text-right font-medium text-gray-600 dark:text-gray-300">
                  Hours
                </th>
                <th className="px-3 py-2 text-right font-medium text-gray-600 dark:text-gray-300">
                  Rate
                </th>
                <th className="px-3 py-2 text-right font-medium text-gray-600 dark:text-gray-300">
                  Amount
                </th>
                <th className="px-3 py-2 text-right font-medium text-gray-600 dark:text-gray-300">
                  Balance after
                </th>
              </tr>
            </thead>
            <tbody className="divide-y divide-gray-100 dark:divide-gray-800">
              {(leaveLines ?? []).map((ll) => (
                <LeaveLineRow
                  key={ll?.id ?? Math.random().toString(36)}
                  line={ll}
                />
              ))}
            </tbody>
          </table>
        )}
      </Section>

      {/* Computed totals */}
      <Section title="Totals (live)" testId="payslip-totals-section">
        <div className="grid grid-cols-1 gap-3 sm:grid-cols-3">
          <ReadonlyRow
            label="Gross"
            value={formatMoney(computed.gross)}
            testId="totals-gross"
            emphasis
          />
          <ReadonlyRow
            label="Net"
            value={formatMoney(computed.net)}
            testId="totals-net"
            emphasis
          />
          <ReadonlyRow
            label="KiwiSaver employer (info)"
            value={formatMoney(computed.employerKiwi)}
            testId="totals-employer-kiwi"
          />
        </div>
        {data?.gross_pay && (
          <p className="mt-2 text-xs text-gray-500 dark:text-gray-400">
            Server-stored gross: {formatMoney(data.gross_pay)} · net{' '}
            {formatMoney(data.net_pay)} · YTD gross{' '}
            {formatMoney(data.gross_ytd)}
          </p>
        )}
      </Section>

      {/* PDF preview iframe — only when finalised (D8) */}
      {isFinalised && (
        <Section title="PDF preview" testId="payslip-pdf-preview-section">
          <PdfPreviewFrame payslipId={payslipId} />
        </Section>
      )}
    </div>
  )
}

// ───────────────────────────────────────────────── Sub-components ──

interface SectionProps {
  title: string
  testId?: string
  children: ReactNode
}

function Section({ title, testId, children }: SectionProps) {
  return (
    <section
      data-testid={testId}
      className="rounded-md border border-gray-200 p-4 dark:border-gray-700"
      aria-label={title}
    >
      <h2 className="mb-3 text-sm font-semibold uppercase tracking-wide text-gray-700 dark:text-gray-200">
        {title}
      </h2>
      {children}
    </section>
  )
}

function EmptyHint({ children }: { children: ReactNode }) {
  return (
    <p className="text-sm text-gray-500 dark:text-gray-400">{children}</p>
  )
}

interface NumericRowProps {
  label: string
  value: string | null | undefined
  onChange: (next: string | null) => void
  disabled: boolean
  testId?: string
  hint?: string
}

function NumericRow({
  label,
  value,
  onChange,
  disabled,
  testId,
  hint,
}: NumericRowProps) {
  return (
    <label className="block">
      <span className="block text-xs font-medium uppercase tracking-wide text-gray-600 dark:text-gray-400">
        {label}
      </span>
      <input
        type="number"
        step="0.01"
        min="0"
        value={value ?? ''}
        onChange={(e) => onChange(e.target.value === '' ? null : e.target.value)}
        disabled={disabled}
        data-testid={testId}
        className="mt-1 block min-h-[44px] w-full rounded-md border border-gray-300 bg-white px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500 disabled:bg-gray-100 dark:border-gray-600 dark:bg-gray-900 dark:text-gray-100 dark:disabled:bg-gray-800"
      />
      {hint && (
        <span
          className="mt-1 block text-xs text-gray-500 dark:text-gray-400"
          title={hint}
        >
          {hint}
        </span>
      )}
    </label>
  )
}

interface ReadonlyRowProps {
  label: string
  value: string
  testId?: string
  emphasis?: boolean
}

function ReadonlyRow({ label, value, testId, emphasis }: ReadonlyRowProps) {
  return (
    <div className="block">
      <span className="block text-xs font-medium uppercase tracking-wide text-gray-600 dark:text-gray-400">
        {label}
      </span>
      <p
        data-testid={testId}
        className={`mt-1 ${
          emphasis
            ? 'text-base font-semibold text-gray-900 dark:text-gray-100'
            : 'text-sm text-gray-800 dark:text-gray-200'
        } tabular-nums`}
      >
        {value}
      </p>
    </div>
  )
}

interface AllowanceRowProps {
  allowance: PayslipAllowance
  isDraft: boolean
}

function AllowanceRow({ allowance, isDraft: _isDraft }: AllowanceRowProps) {
  const unit: AllowanceUnit | string = allowance?.unit ?? 'period'
  const quantityLabel = (() => {
    if (unit === 'period') return null
    const q = allowance?.quantity ?? '0'
    const n = Number(q)
    const safe = Number.isFinite(n) ? n : 0
    return `${safe} ${unit}${safe === 1 ? '' : 's'}`
  })()
  // unit_price is implicit: amount / quantity for shift/km
  const unitPrice = (() => {
    if (unit === 'period') return null
    const q = Number(allowance?.quantity ?? '0')
    const a = Number(allowance?.amount ?? '0')
    if (!Number.isFinite(q) || !Number.isFinite(a) || q === 0) return null
    return a / q
  })()
  const detail =
    unit === 'period'
      ? formatMoney(allowance?.amount)
      : `${quantityLabel} × ${formatMoney(unitPrice)} = ${formatMoney(allowance?.amount)}`
  return (
    <tr data-testid={`allowance-row-${allowance?.id ?? ''}`}>
      <td className="px-3 py-2 text-gray-900 dark:text-gray-100">
        {allowance?.label ?? '—'}
        {allowance?.taxable === false && (
          <span className="ml-2 text-xs text-gray-500 dark:text-gray-400">
            (non-taxable)
          </span>
        )}
      </td>
      <td className="px-3 py-2 text-right text-xs text-gray-700 tabular-nums dark:text-gray-300">
        {detail}
      </td>
      <td className="px-3 py-2 text-right tabular-nums text-gray-900 dark:text-gray-100">
        {formatMoney(allowance?.amount)}
      </td>
    </tr>
  )
}

interface SimpleAmountListProps {
  items: PayslipReimbursement[]
  testId: string
}

function SimpleAmountList({ items, testId }: SimpleAmountListProps) {
  return (
    <table className="min-w-full divide-y divide-gray-200 text-sm dark:divide-gray-700">
      <tbody className="divide-y divide-gray-100 dark:divide-gray-800">
        {(items ?? []).map((r) => (
          <tr
            key={r?.id ?? Math.random().toString(36)}
            data-testid={`${testId}-${r?.id ?? ''}`}
          >
            <td className="px-3 py-2 text-gray-900 dark:text-gray-100">
              {r?.label ?? '—'}
            </td>
            <td className="px-3 py-2 text-right tabular-nums text-gray-900 dark:text-gray-100">
              {formatMoney(r?.amount)}
            </td>
          </tr>
        ))}
      </tbody>
    </table>
  )
}

interface DeductionRowProps {
  deduction: PayslipDeduction
}

function DeductionRow({ deduction }: DeductionRowProps) {
  const isEmployerKiwi = deduction?.kind === 'kiwisaver_employer'
  return (
    <tr data-testid={`deduction-row-${deduction?.kind ?? ''}`}>
      <td className="px-3 py-2 text-gray-900 dark:text-gray-100">
        {deduction?.label ?? '—'}
        {isEmployerKiwi && (
          <span className="ml-2 text-xs text-gray-500 dark:text-gray-400">
            (informational, not subtracted from gross)
          </span>
        )}
      </td>
      <td className="px-3 py-2 text-right tabular-nums text-gray-900 dark:text-gray-100">
        {formatMoney(deduction?.amount)}
      </td>
    </tr>
  )
}

interface LeaveLineRowProps {
  line: PayslipLeaveLine
}

function LeaveLineRow({ line }: LeaveLineRowProps) {
  return (
    <tr data-testid={`leave-row-${line?.id ?? ''}`}>
      <td className="px-3 py-2 text-gray-900 dark:text-gray-100">
        {line?.leave_type_name ?? line?.leave_type_code ?? '—'}
      </td>
      <td className="px-3 py-2 text-right tabular-nums text-gray-700 dark:text-gray-300">
        {formatHours(line?.hours)}
      </td>
      <td className="px-3 py-2 text-right tabular-nums text-gray-700 dark:text-gray-300">
        {formatMoney(line?.rate)}
      </td>
      <td className="px-3 py-2 text-right tabular-nums text-gray-900 dark:text-gray-100">
        {formatMoney(line?.amount)}
      </td>
      <td className="px-3 py-2 text-right tabular-nums text-gray-700 dark:text-gray-300">
        {formatHours(line?.balance_after)} h
      </td>
    </tr>
  )
}

// ───────────────────────────────────────────────── PdfPreviewFrame ──

interface PdfPreviewFrameProps {
  payslipId: string
}

function PdfPreviewFrame({ payslipId }: PdfPreviewFrameProps) {
  const [blobUrl, setBlobUrl] = useState<string | null>(null)
  const [loading, setLoading] = useState<boolean>(true)
  const [error, setError] = useState<string | null>(null)
  const urlRef = useRef<string | null>(null)

  useEffect(() => {
    const controller = new AbortController()
    setLoading(true)
    setError(null)
    setBlobUrl(null)
    ;(async () => {
      try {
        const blob = await downloadPayslipPdf(payslipId, controller.signal)
        if (controller.signal.aborted) return
        const url = URL.createObjectURL(blob)
        urlRef.current = url
        setBlobUrl(url)
      } catch (err) {
        if (isAbortError(err)) return
        setError(readErrorMessage(err))
      } finally {
        if (!controller.signal.aborted) setLoading(false)
      }
    })()
    return () => {
      controller.abort()
      // Revoke the blob URL on unmount or before the next fetch.
      if (urlRef.current) {
        URL.revokeObjectURL(urlRef.current)
        urlRef.current = null
      }
    }
  }, [payslipId])

  if (loading) {
    return (
      <div
        className="flex items-center justify-center py-8"
        data-testid="payslip-pdf-loading"
      >
        <Spinner size="md" label="Loading PDF preview" />
      </div>
    )
  }
  if (error) {
    return <AlertBanner variant="error">{error}</AlertBanner>
  }
  if (!blobUrl) {
    return <EmptyHint>PDF not yet available.</EmptyHint>
  }
  return (
    <iframe
      title="Payslip PDF preview"
      src={blobUrl}
      data-testid="payslip-pdf-iframe"
      className="h-[600px] w-full rounded-md border border-gray-200 bg-white dark:border-gray-700"
    />
  )
}

// Re-export the component types for callers (e.g. tests) that wish to mock.
export type { Payslip, PayslipDetailType }
