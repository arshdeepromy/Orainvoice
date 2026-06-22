/**
 * PayRunPage — bulk pay-run console (Staff Management Phase 4, task D1).
 *
 * Redesigned to match the prototype OraInvoice_Handoff/app/Payroll.html:
 *   - `.page-head` with eyebrow / title / sub + head actions.
 *   - Pay-run bar: period navigator (prev/next) + 4-step progress
 *     (Generate → Review → Finalise → Pay & file) derived from period
 *     status + draft count.
 *   - KPI row (Gross / PAYE / KiwiSaver + ACC / Net), sourced from the
 *     per-payslip deduction subtotals returned on the list response.
 *   - Toolbar: employee search, status segmented filter, CSV export.
 *   - Avatar-prefixed staff table with mono money cells + pagination.
 *   - Footer action bar: pay day note + Reopen / Finalise all.
 *
 * Behaviour (unchanged from the original console):
 *   - Period selector defaults to the first `status='open'` period.
 *   - "Generate drafts" → one payslip per active staff member.
 *   - Click row → opens PayslipDetail in a drawer.
 *   - "Finalise all" → bulk-finalise with email-all checkbox.
 *   - Reopen → reason modal; disabled with tooltip when period.status='paid'.
 *
 * Conventions:
 *   - Typed client only — `@/api/payslips`.
 *   - All API responses consumed with `?.` + `?? []` / `?? 0`.
 *   - Every effect uses an AbortController.
 *   - Decimal fields arrive as strings; formatted via Intl.NumberFormat.
 *   - Module-gated by `payroll`.
 */

import {
  lazy,
  Suspense,
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
  type ReactNode,
} from 'react'
import { useNavigate, useSearchParams } from 'react-router-dom'
import apiClient from '@/api/client'
import { ModuleGate } from '@/components/common/ModuleGate'
import {
  Button,
  Spinner,
  AlertBanner,
  Modal,
  Badge,
  Pagination,
  cx,
} from '@/components/ui'
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

const PAGE_SIZE = 8

const NZD = new Intl.NumberFormat('en-NZ', {
  style: 'currency',
  currency: 'NZD',
})

function formatMoney(value: string | number | null | undefined): string {
  const n = typeof value === 'string' ? Number(value) : (value ?? 0)
  if (!Number.isFinite(n)) return NZD.format(0)
  return NZD.format(n)
}

/** Whole-dollar grouped amount (no symbol) for the KPI cards — matches the
 *  prototype's `38,420` styling where the `$` is a separate muted glyph. */
function formatAmount(value: number): string {
  if (!Number.isFinite(value)) return '0'
  return Math.round(value).toLocaleString('en-NZ')
}

function toNumber(value: string | number | null | undefined): number {
  const n = typeof value === 'string' ? Number(value) : (value ?? 0)
  return Number.isFinite(n) ? n : 0
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

/**
 * Period label that surfaces the pay cycle when known — e.g.
 * `Weekly · 8 – 14 Jun 2026`. Falls back to the bare date range for legacy
 * periods with no `pay_cycle_name` (per-staff-pay-cycle feature).
 */
function formatPeriodLabel(period: PayPeriod | null | undefined): string {
  if (!period) return '—'
  const range = formatDateRange(period)
  return period.pay_cycle_name ? `${period.pay_cycle_name} · ${range}` : range
}

function formatShortDate(iso: string | null | undefined): string {
  if (!iso) return '—'
  return new Date(`${iso}T00:00:00`).toLocaleDateString('en-NZ', {
    weekday: 'short',
    day: 'numeric',
    month: 'short',
  })
}

/** Initials for the avatar chip — first letters of the first two words. */
function initials(name: string | null | undefined): string {
  const parts = (name ?? '').trim().split(/\s+/).filter(Boolean)
  if (parts.length === 0) return '—'
  if (parts.length === 1) return parts[0].slice(0, 2).toUpperCase()
  return (parts[0][0] + parts[parts.length - 1][0]).toUpperCase()
}

function payslipStatusVariant(
  status: PayslipStatus | string,
): 'success' | 'warn' | 'danger' | 'info' | 'neutral' {
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

function payslipStatusLabel(status: PayslipStatus | string): string {
  if (status === 'finalised') return 'Finalised'
  if (status === 'voided') return 'Voided'
  if (status === 'draft') return 'Draft'
  return status
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

// ─────────────────────────────────────────────────────────── Icons ──
// Inline SVGs ported from the prototype so the redesign needs no icon dep.

interface IconProps {
  className?: string
}

function Svg({ children, className }: IconProps & { children: ReactNode }) {
  return (
    <svg
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth={2}
      strokeLinecap="round"
      strokeLinejoin="round"
      className={className}
      aria-hidden="true"
    >
      {children}
    </svg>
  )
}

const PlusIcon = (p: IconProps) => (
  <Svg {...p}>
    <path d="M12 5v14M5 12h14" />
  </Svg>
)
const CheckIcon = (p: IconProps) => (
  <Svg {...p}>
    <path d="M20 6L9 17l-5-5" />
  </Svg>
)
const ChevronLeftIcon = (p: IconProps) => (
  <Svg {...p}>
    <path d="M15 18l-6-6 6-6" />
  </Svg>
)
const ChevronRightIcon = (p: IconProps) => (
  <Svg {...p}>
    <path d="M9 18l6-6-6-6" />
  </Svg>
)
const SearchIcon = (p: IconProps) => (
  <Svg {...p}>
    <path d="M21 21l-5-5m2-5a7 7 0 11-14 0 7 7 0 0114 0z" />
  </Svg>
)
const ExportIcon = (p: IconProps) => (
  <Svg {...p}>
    <path d="M21 15v4a2 2 0 01-2 2H5a2 2 0 01-2-2v-4M7 10l5 5 5-5M12 15V3" />
  </Svg>
)
const DollarIcon = (p: IconProps) => (
  <Svg {...p}>
    <path d="M12 1v22M17 5H9.5a3.5 3.5 0 000 7h5a3.5 3.5 0 010 7H6" />
  </Svg>
)
const TaxIcon = (p: IconProps) => (
  <Svg {...p}>
    <path d="M19 21V5a2 2 0 00-2-2H7a2 2 0 00-2 2v16l3.5-2 3.5 2 3.5-2 3.5 2zM9 8l6 8" />
  </Svg>
)
const WalletIcon = (p: IconProps) => (
  <Svg {...p}>
    <path d="M3 10h18M7 15h1m4 0h1m-7 4h12a3 3 0 003-3V8a3 3 0 00-3-3H6a3 3 0 00-3 3v8a3 3 0 003 3z" />
  </Svg>
)
const UsersIcon = (p: IconProps) => (
  <Svg {...p}>
    <path d="M17 21v-2a4 4 0 00-4-4H5a4 4 0 00-4 4v2M9 11a4 4 0 100-8 4 4 0 000 8zM23 21v-2a4 4 0 00-3-3.87M16 3.13a4 4 0 010 7.75" />
  </Svg>
)

// ────────────────────────────────────────────────────────── KpiCard ──

type KpiTone = 'blue' | 'amber' | 'green' | 'purple'

const KPI_ICON_TONE: Record<KpiTone, string> = {
  blue: 'bg-accent-soft text-accent',
  amber: 'bg-warn-soft text-warn',
  green: 'bg-ok-soft text-ok',
  purple: 'bg-purple-soft text-purple',
}

interface KpiCardProps {
  label: string
  value: string
  money?: boolean
  sub?: string
  icon: React.ComponentType<IconProps>
  tone: KpiTone
}

/** Single KPI card — mirrors the prototype `.kpi` (label/icon, mono value, sub). */
function KpiCard({ label, value, money, sub, icon: Icon, tone }: KpiCardProps) {
  return (
    <div className="rounded-card border border-border bg-card p-5 shadow-card">
      <div className="mb-3.5 flex items-center justify-between">
        <span className="text-[12.5px] font-medium text-muted">{label}</span>
        <span
          className={cx(
            'grid h-8 w-8 place-items-center rounded-[9px]',
            KPI_ICON_TONE[tone],
          )}
        >
          <Icon className="h-[17px] w-[17px]" />
        </span>
      </div>
      <div className="mono text-[27px] font-semibold leading-none tracking-[-0.02em] text-text">
        {money && <span className="text-[17px] text-muted-2">$</span>}
        {value}
      </div>
      {sub && (
        <p className="mono mt-2.5 text-[12px] font-medium text-muted-2">{sub}</p>
      )}
    </div>
  )
}

// ──────────────────────────────────────────────────────────── Stepper ──

const STEPS = ['Generate', 'Review', 'Finalise', 'Pay & file'] as const

/** Active step index derived from period status + whether drafts exist. */
function activeStepIndex(
  period: PayPeriod | null,
  payslipCount: number,
): number {
  if (!period) return 0
  if (period.status === 'paid') return 4 // all done
  if (period.status === 'finalised') return 3 // Pay & file
  if (payslipCount > 0) return 1 // Review
  return 0 // Generate
}

function Stepper({ activeIdx }: { activeIdx: number }) {
  return (
    <div className="ml-auto hidden items-center lg:flex">
      {STEPS.map((label, i) => {
        const done = i < activeIdx
        const on = i === activeIdx
        return (
          <div key={label} className="flex items-center">
            <div
              className={cx(
                'flex items-center gap-2 text-[12.5px]',
                on
                  ? 'font-semibold text-text'
                  : done
                    ? 'text-muted'
                    : 'text-muted',
              )}
            >
              <span
                className={cx(
                  'mono grid h-[22px] w-[22px] place-items-center rounded-full text-[11px] font-semibold',
                  done
                    ? 'bg-ok-soft text-ok'
                    : on
                      ? 'bg-accent text-white'
                      : 'border border-border bg-canvas text-muted',
                )}
              >
                {done ? <CheckIcon className="h-[11px] w-[11px]" /> : i + 1}
              </span>
              {label}
            </div>
            {i < STEPS.length - 1 && (
              <span className="mx-3 h-px w-[30px] bg-border" />
            )}
          </div>
        )
      })}
    </div>
  )
}

// ─────────────────────────────────────────── BulkFinaliseConfirm ──

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
        <p className="text-sm text-muted">
          {draftCount} draft{draftCount === 1 ? '' : 's'} will be finalised. Each
          finalised payslip will be locked and a PDF generated.
        </p>
        <label className="flex items-start gap-2 text-sm text-text">
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
          <div className="flex items-center gap-2 rounded-ctl border border-border bg-accent-soft p-3">
            <Spinner size="sm" />
            <span className="text-sm text-accent">
              Finalising{result ? `: ${result.finalised_count ?? 0}` : '…'}
            </span>
          </div>
        )}
        {result && !busy && (
          <div className="rounded-ctl border border-border bg-ok-soft p-3 text-sm text-ok">
            <p className="font-medium">
              Finalised {result.finalised_count ?? 0} payslip
              {(result.finalised_count ?? 0) === 1 ? '' : 's'}.
            </p>
            {(result.emailed_count ?? 0) > 0 && (
              <p>Emailed {result.emailed_count ?? 0}.</p>
            )}
            {(result.failed_count ?? 0) > 0 && (
              <p className="text-warn">
                {result.failed_count ?? 0} failed — check the table.
              </p>
            )}
          </div>
        )}
        {error && <AlertBanner variant="error">{error}</AlertBanner>}
        <div className="flex justify-end gap-2">
          <Button variant="ghost" onClick={onClose} disabled={busy}>
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

// ───────────────────────────────────────────────────── ReopenModal ──

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
        <p className="text-sm text-muted">
          Reopening unlocks the period for new draft payslips that will sit
          alongside the existing finalised ones. Existing finalised payslips
          remain locked.
        </p>
        <label className="block">
          <span className="block text-sm font-medium text-text">Reason</span>
          <textarea
            value={reason}
            onChange={(e) => setReason(e.target.value)}
            data-testid="reopen-reason-input"
            rows={3}
            className="mt-1 block w-full rounded-ctl border border-border bg-card px-3 py-2 text-sm text-text focus:outline-none focus:ring-2 focus:ring-accent"
            placeholder="e.g. correction for missed timesheet approval"
          />
        </label>
        {error && <AlertBanner variant="error">{error}</AlertBanner>}
        <div className="flex justify-end gap-2">
          <Button variant="ghost" onClick={onClose} disabled={busy}>
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

// ──────────────────────────────────────────────────────── PayRunPage ──

export default function PayRunPage() {
  return (
    <ModuleGate module="payroll">
      <PayRunPageInner />
    </ModuleGate>
  )
}

type StatusFilter = 'all' | 'draft' | 'finalised' | 'voided'

const STATUS_FILTERS: { id: StatusFilter; label: string }[] = [
  { id: 'all', label: 'All' },
  { id: 'draft', label: 'Drafts' },
  { id: 'finalised', label: 'Finalised' },
  { id: 'voided', label: 'Voided' },
]

function PayRunPageInner() {
  const navigate = useNavigate()
  const [searchParams] = useSearchParams()
  const periodParam = searchParams.get('period')

  // Period state
  const [periods, setPeriods] = useState<PayPeriod[]>([])
  const [periodsLoading, setPeriodsLoading] = useState<boolean>(true)
  const [periodsError, setPeriodsError] = useState<string | null>(null)
  const [selectedPeriodId, setSelectedPeriodId] = useState<string | null>(null)

  // Payslip state for the selected period
  const [payslips, setPayslips] = useState<Payslip[]>([])
  const [payslipsLoading, setPayslipsLoading] = useState<boolean>(false)
  const [payslipsError, setPayslipsError] = useState<string | null>(null)

  // Toolbar (client-side filter + pagination)
  const [search, setSearch] = useState<string>('')
  const [statusFilter, setStatusFilter] = useState<StatusFilter>('all')
  const [page, setPage] = useState<number>(1)

  // Cycle filter — for multi-cycle orgs the loaded periods can span several
  // distinct pay cycles; this lets an admin focus the navigator/selector on a
  // single cycle. 'all' (the default) shows every cycle's periods.
  const [cycleFilter, setCycleFilter] = useState<string>('all')
  // Tracks whether we've already seeded the cycle filter from a ?period= deep
  // link so a later periods re-fetch (e.g. after finalise) doesn't clobber a
  // filter the admin has since changed by hand.
  const deepLinkCycleApplied = useRef<boolean>(false)

  // Mutations
  const [generating, setGenerating] = useState<boolean>(false)
  const [generateError, setGenerateError] = useState<string | null>(null)

  // Whether this org uses the Staff Timesheets → Pay Runs workflow (signalled
  // by having a pay cycle configured). When true, draft payslips are created
  // from locked timesheets in the Timesheets module, so the Payroll console's
  // own "Generate drafts" button is hidden to avoid a redundant/parallel path.
  const [usesTimesheets, setUsesTimesheets] = useState<boolean>(false)

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
    // Detect whether the org runs the Timesheets → Pay Runs workflow.
    apiClient
      .get<{ items: unknown[]; total: number }>('/api/v2/pay-cycles/', { signal: controller.signal })
      .then((res) => setUsesTimesheets((res.data?.items?.length ?? 0) > 0))
      .catch(() => setUsesTimesheets(false))
    return () => controller.abort()
  }, [])

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

        // Auto-select: a ?period= deep link wins (e.g. arriving from the
        // Timesheets → Pay Runs "Review in Payroll" link), else keep the
        // current selection, else the first 'open' period.
        setSelectedPeriodId((prev) => {
          if (periodParam && items.some((p) => p.id === periodParam)) return periodParam
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
  }, [periodParam])

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

  // Distinct pay-cycle names across the loaded periods. The cycle filter is
  // only useful (and only shown) when the periods span more than one cycle.
  const cycleNames = useMemo<string[]>(() => {
    const set = new Set<string>()
    for (const p of periods ?? []) {
      if (p?.pay_cycle_name) set.add(p.pay_cycle_name)
    }
    return Array.from(set).sort((a, b) => a.localeCompare(b))
  }, [periods])

  const showCycleFilter = cycleNames.length > 1

  // Seed the cycle filter from a ?period= deep link once: if the deep-linked
  // period belongs to a cycle, default the filter to that cycle so the period
  // stays visible/selectable in the navigator (rather than letting the filter
  // hide it).
  useEffect(() => {
    if (deepLinkCycleApplied.current) return
    if (!periodParam) return
    const target = (periods ?? []).find((p) => p.id === periodParam)
    if (!target) return
    if (target.pay_cycle_name) setCycleFilter(target.pay_cycle_name)
    deepLinkCycleApplied.current = true
  }, [periodParam, periods])

  // Periods visible after applying the cycle filter (the navigator + selector
  // operate on this set). 'all' passes everything through.
  const visiblePeriods = useMemo<PayPeriod[]>(
    () =>
      cycleFilter === 'all'
        ? (periods ?? [])
        : (periods ?? []).filter(
            (p) => (p?.pay_cycle_name ?? null) === cycleFilter,
          ),
    [periods, cycleFilter],
  )

  // Periods sorted newest-first for the navigator + selector.
  const sortedPeriods = useMemo<PayPeriod[]>(
    () =>
      [...visiblePeriods].sort((a, b) =>
        b.start_date.localeCompare(a.start_date),
      ),
    [visiblePeriods],
  )

  // If an active cycle filter hides the currently selected period, fall back
  // to the first visible period so the navigator never points at a hidden row.
  useEffect(() => {
    if (cycleFilter === 'all') return
    if (!selectedPeriodId) return
    if (visiblePeriods.some((p) => p.id === selectedPeriodId)) return
    setSelectedPeriodId(visiblePeriods[0]?.id ?? null)
  }, [cycleFilter, visiblePeriods, selectedPeriodId])

  const selectedPeriod = useMemo<PayPeriod | null>(
    () => (periods ?? []).find((p) => p.id === selectedPeriodId) ?? null,
    [periods, selectedPeriodId],
  )

  const selectedIndex = useMemo<number>(
    () => sortedPeriods.findIndex((p) => p.id === selectedPeriodId),
    [sortedPeriods, selectedPeriodId],
  )

  const draftCount = useMemo<number>(
    () => (payslips ?? []).filter((p) => p?.status === 'draft').length,
    [payslips],
  )

  // KPI aggregates across all payslips in the period — sourced from the
  // per-kind deduction subtotals (PAYE / KiwiSaver / ACC) so the summary
  // matches the underlying payslips rather than a derived gross−net figure.
  const totals = useMemo(() => {
    let gross = 0
    let net = 0
    let paye = 0
    let kiwiAcc = 0
    for (const p of payslips ?? []) {
      gross += toNumber(p?.gross_pay)
      net += toNumber(p?.net_pay)
      const sub = p?.deduction_subtotals
      paye += toNumber(sub?.paye)
      // KiwiSaver + ACC KPI = employee + employer KiwiSaver + ACC.
      kiwiAcc +=
        toNumber(sub?.kiwisaver_employee) +
        toNumber(sub?.kiwisaver_employer) +
        toNumber(sub?.acc_levy)
    }
    return { gross, net, paye, kiwiAcc, count: (payslips ?? []).length }
  }, [payslips])

  // Filtered + paginated rows.
  const filteredPayslips = useMemo<Payslip[]>(() => {
    const q = search.trim().toLowerCase()
    return (payslips ?? []).filter((p) => {
      if (statusFilter !== 'all' && p?.status !== statusFilter) return false
      if (q && !(p?.staff_name ?? '').toLowerCase().includes(q)) return false
      return true
    })
  }, [payslips, search, statusFilter])

  const totalPages = Math.max(1, Math.ceil(filteredPayslips.length / PAGE_SIZE))
  const pagedPayslips = useMemo<Payslip[]>(() => {
    const start = (page - 1) * PAGE_SIZE
    return filteredPayslips.slice(start, start + PAGE_SIZE)
  }, [filteredPayslips, page])

  // Reset to page 1 whenever the filter inputs or period change.
  useEffect(() => {
    setPage(1)
  }, [search, statusFilter, selectedPeriodId])

  const periodIsLocked =
    selectedPeriod?.status === 'finalised' || selectedPeriod?.status === 'paid'

  const activeIdx = activeStepIndex(selectedPeriod, totals.count)

  const goToPeriod = useCallback(
    (delta: number) => {
      if (selectedIndex < 0) return
      const next = sortedPeriods[selectedIndex + delta]
      if (next) setSelectedPeriodId(next.id)
    },
    [selectedIndex, sortedPeriods],
  )

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

  const handleExport = useCallback(() => {
    const header = [
      'Staff',
      'Status',
      'Ordinary hours',
      'Overtime hours',
      'Gross',
      'PAYE',
      'KiwiSaver (employee)',
      'KiwiSaver (employer)',
      'ACC',
      'Student loan',
      'Child support',
      'Voluntary',
      'Net',
    ]
    const rows = filteredPayslips.map((p) => {
      const gross = toNumber(p?.gross_pay)
      const net = toNumber(p?.net_pay)
      const sub = p?.deduction_subtotals
      return [
        p?.staff_name ?? '',
        p?.status ?? '',
        formatHours(p?.ordinary_hours),
        formatHours(p?.overtime_hours),
        gross.toFixed(2),
        toNumber(sub?.paye).toFixed(2),
        toNumber(sub?.kiwisaver_employee).toFixed(2),
        toNumber(sub?.kiwisaver_employer).toFixed(2),
        toNumber(sub?.acc_levy).toFixed(2),
        toNumber(sub?.student_loan).toFixed(2),
        toNumber(sub?.child_support).toFixed(2),
        toNumber(sub?.voluntary).toFixed(2),
        net.toFixed(2),
      ]
    })
    const csv = [header, ...rows]
      .map((r) =>
        r.map((c) => `"${String(c).replace(/"/g, '""')}"`).join(','),
      )
      .join('\n')
    const blob = new Blob([csv], { type: 'text/csv;charset=utf-8;' })
    const url = URL.createObjectURL(blob)
    const a = document.createElement('a')
    a.href = url
    a.download = `payrun-${selectedPeriod?.start_date ?? 'export'}.csv`
    document.body.appendChild(a)
    a.click()
    document.body.removeChild(a)
    URL.revokeObjectURL(url)
  }, [filteredPayslips, selectedPeriod])

  const closeBulk = useCallback(() => {
    setBulkOpen(false)
    setBulkBusy(false)
    setBulkError(null)
    setBulkResult(null)
  }, [])

  const navBtn =
    'grid h-[34px] w-[34px] place-items-center rounded-ctl border border-border bg-card text-muted transition-colors hover:bg-canvas hover:text-text disabled:cursor-not-allowed disabled:opacity-40'

  return (
    <div className="page page-wide" data-testid="pay-run-page">
      {/* Page header */}
      <div className="page-head">
        <div>
          <div className="eyebrow">People</div>
          <h1>Payroll</h1>
          <p className="sub">
            {selectedPeriod
              ? `Pay period · ${formatDateRange(selectedPeriod)} · ${totals.count} ${totals.count === 1 ? 'employee' : 'employees'}`
              : 'Generate, review and finalise payslips for a pay period.'}
          </p>
        </div>
        <div className="head-actions">
          <Button
            variant="ghost"
            size="sm"
            onClick={() => navigate('/settings/people/pay-periods')}
          >
            Pay run history
          </Button>
          {usesTimesheets ? (
            <Button
              variant="ghost"
              size="sm"
              onClick={() => navigate('/timesheets?tab=pay-runs')}
              title="This org creates payslip drafts from locked timesheets in Staff Timesheets → Pay Runs"
            >
              Create in Pay Runs
            </Button>
          ) : (
            <Button
              variant="primary"
              size="sm"
              onClick={handleGenerate}
              loading={generating}
              disabled={!selectedPeriodId || periodIsLocked || generating}
              data-testid="generate-drafts-button"
            >
              <PlusIcon className="h-4 w-4" />
              Generate drafts
            </Button>
          )}
        </div>
      </div>

      {periodsError && (
        <AlertBanner variant="error" className="mb-4">
          {periodsError}
        </AlertBanner>
      )}

      {/* Pay-run bar: period navigator + step progress */}
      <div className="mb-gap flex flex-wrap items-center gap-[14px] rounded-card border border-border bg-card px-5 py-4 shadow-card">
        <div className="flex items-center gap-[10px]">
          <button
            type="button"
            className={navBtn}
            aria-label="Previous period"
            onClick={() => goToPeriod(1)}
            disabled={selectedIndex < 0 || selectedIndex >= sortedPeriods.length - 1}
          >
            <ChevronLeftIcon className="h-4 w-4" />
          </button>
          <div>
            <div className="mono text-[11px] font-semibold uppercase tracking-[0.08em] text-muted-2">
              {selectedPeriod
                ? periodStatusLabel(selectedPeriod.status)
                : 'No period'}
            </div>
            <div className="mono text-[13px] font-semibold text-text">
              {selectedPeriod ? formatPeriodLabel(selectedPeriod) : '—'}
            </div>
          </div>
          <button
            type="button"
            className={navBtn}
            aria-label="Next period"
            onClick={() => goToPeriod(-1)}
            disabled={selectedIndex <= 0}
          >
            <ChevronRightIcon className="h-4 w-4" />
          </button>
        </div>

        {/* Direct period jump for keyboard / many-period orgs. */}
        <label className="sr-only" htmlFor="period-selector">
          Pay period
        </label>
        <select
          id="period-selector"
          value={selectedPeriodId ?? ''}
          onChange={(e) => setSelectedPeriodId(e.target.value || null)}
          data-testid="period-selector"
          disabled={periodsLoading || sortedPeriods.length === 0}
          className="mono h-[34px] rounded-ctl border border-border bg-card px-3 text-[13px] text-text focus:outline-none focus:ring-2 focus:ring-accent disabled:opacity-50"
        >
          {sortedPeriods.length === 0 && (
            <option value="">No pay periods yet</option>
          )}
          {sortedPeriods.map((p) => (
            <option key={p.id} value={p.id}>
              {formatPeriodLabel(p)} · {periodStatusLabel(p.status)}
            </option>
          ))}
        </select>

        {/* Cycle filter — only when the loaded periods span >1 pay cycle. */}
        {showCycleFilter && (
          <div
            className="inline-flex gap-0.5 rounded-ctl border border-border bg-card p-[3px]"
            role="group"
            aria-label="Filter by pay cycle"
            data-testid="cycle-filter"
          >
            {[
              { id: 'all', label: 'All cycles' },
              ...cycleNames.map((n) => ({ id: n, label: n })),
            ].map((c) => (
              <button
                key={c.id}
                type="button"
                aria-pressed={cycleFilter === c.id}
                onClick={() => setCycleFilter(c.id)}
                className={cx(
                  'rounded-[7px] px-[13px] py-1.5 text-[12.5px] font-medium transition-colors',
                  cycleFilter === c.id
                    ? 'bg-accent-soft text-accent'
                    : 'text-muted hover:text-text',
                )}
                data-testid={`cycle-filter-option-${c.id}`}
              >
                {c.label}
              </button>
            ))}
          </div>
        )}

        <Stepper activeIdx={activeIdx} />
      </div>

      {generateError && (
        <AlertBanner variant="error" className="mb-4">
          {generateError}
        </AlertBanner>
      )}

      {/* KPI row */}
      <div className="mb-gap grid grid-cols-4 gap-gap max-[1080px]:grid-cols-2 max-[520px]:grid-cols-1">
        <KpiCard
          label="Gross pay"
          value={formatAmount(totals.gross)}
          money
          sub="before deductions"
          icon={DollarIcon}
          tone="blue"
        />
        <KpiCard
          label="PAYE / tax"
          value={formatAmount(totals.paye)}
          money
          sub={
            totals.gross > 0
              ? `${((totals.paye / totals.gross) * 100).toFixed(1)}% of gross`
              : 'pay-as-you-earn'
          }
          icon={TaxIcon}
          tone="amber"
        />
        <KpiCard
          label="KiwiSaver + ACC"
          value={formatAmount(totals.kiwiAcc)}
          money
          sub="employee + employer"
          icon={UsersIcon}
          tone="purple"
        />
        <KpiCard
          label="Net pay"
          value={formatAmount(totals.net)}
          money
          sub={`to ${totals.count} ${totals.count === 1 ? 'employee' : 'employees'}`}
          icon={WalletIcon}
          tone="green"
        />
      </div>

      {/* Toolbar */}
      <div className="mb-4 flex flex-wrap items-center gap-3">
        <div className="relative">
          <SearchIcon className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-2" />
          <input
            type="search"
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            placeholder="Search employees…"
            aria-label="Search employees"
            className="h-[38px] w-64 rounded-ctl border border-border bg-card pl-9 pr-3 text-[13px] text-text placeholder:text-muted-2 focus:outline-none focus:ring-2 focus:ring-accent"
          />
        </div>
        <div
          className="inline-flex gap-0.5 rounded-ctl border border-border bg-card p-[3px]"
          role="group"
          aria-label="Filter by status"
        >
          {STATUS_FILTERS.map((f) => (
            <button
              key={f.id}
              type="button"
              aria-pressed={statusFilter === f.id}
              onClick={() => setStatusFilter(f.id)}
              className={cx(
                'rounded-[7px] px-[13px] py-1.5 text-[12.5px] font-medium transition-colors',
                statusFilter === f.id
                  ? 'bg-accent-soft text-accent'
                  : 'text-muted hover:text-text',
              )}
            >
              {f.label}
            </button>
          ))}
        </div>
        <div className="ml-auto">
          <Button
            variant="ghost"
            size="sm"
            onClick={handleExport}
            disabled={filteredPayslips.length === 0}
          >
            <ExportIcon className="h-4 w-4" />
            Export
          </Button>
        </div>
      </div>

      {payslipsError && (
        <AlertBanner variant="error" className="mb-4">
          {payslipsError}
        </AlertBanner>
      )}

      {/* Payslip table */}
      {periodsLoading || payslipsLoading ? (
        <div className="flex items-center justify-center py-16">
          <Spinner size="lg" label="Loading pay run" />
        </div>
      ) : (payslips ?? []).length === 0 ? (
        <div
          className="rounded-card border border-dashed border-border bg-card px-4 py-16 text-center"
          data-testid="payslips-empty"
        >
          <p className="text-sm font-medium text-text">
            {selectedPeriodId
              ? 'No draft payslips yet'
              : 'Select a pay period to begin'}
          </p>
          <p className="mt-1 text-[13px] text-muted-2">
            {!selectedPeriodId
              ? 'Pay periods are created under Settings → People → Pay periods.'
              : usesTimesheets
                ? 'This org creates payslip drafts from locked timesheets. Go to Staff Timesheets → Pay Runs to generate them.'
                : 'Click “Generate drafts” to create one payslip per active staff member.'}
          </p>
          {selectedPeriodId && !periodIsLocked && (
            <div className="mt-4 flex justify-center">
              {usesTimesheets ? (
                <Button
                  variant="primary"
                  size="sm"
                  onClick={() => navigate('/timesheets?tab=pay-runs')}
                >
                  Go to Pay Runs
                </Button>
              ) : (
                <Button
                  variant="primary"
                  size="sm"
                  onClick={handleGenerate}
                  loading={generating}
                >
                  <PlusIcon className="h-4 w-4" />
                  Generate drafts
                </Button>
              )}
            </div>
          )}
        </div>
      ) : (
        <>
          <section className="overflow-hidden rounded-card border border-border bg-card shadow-card">
            <div className="overflow-x-auto">
              <table
                className="w-full border-collapse text-sm"
                data-testid="payslips-table"
              >
                <thead>
                  <tr>
                    <th className={TH}>Employee</th>
                    <th className={TH}>Status</th>
                    <th className={TH_R}>Ord. hrs</th>
                    <th className={TH_R}>O/T</th>
                    <th className={TH_R}>Gross</th>
                    <th className={TH_R}>PAYE</th>
                    <th className={TH_R}>KiwiSaver</th>
                    <th className={TH_R}>ACC</th>
                    <th className={TH_R}>Other</th>
                    <th className={TH_R}>Net</th>
                    <th className={TH_R} aria-label="Open" />
                  </tr>
                </thead>
                <tbody>
                  {pagedPayslips.length === 0 ? (
                    <tr>
                      <td
                        colSpan={11}
                        className="px-4 py-12 text-center text-[13px] text-muted"
                      >
                        No employees match your filters.
                      </td>
                    </tr>
                  ) : (
                    pagedPayslips.map((p, i) => {
                      const gross = toNumber(p?.gross_pay)
                      const net = toNumber(p?.net_pay)
                      const sub = p?.deduction_subtotals
                      const paye = toNumber(sub?.paye)
                      const kiwi = toNumber(sub?.kiwisaver_employee)
                      const acc = toNumber(sub?.acc_levy)
                      const other =
                        toNumber(sub?.student_loan) +
                        toNumber(sub?.child_support) +
                        toNumber(sub?.voluntary)
                      return (
                        <tr
                          key={p?.id ?? i}
                          className="cursor-pointer border-b border-border last:border-b-0 hover:bg-canvas"
                          onClick={() => setDrawerPayslipId(p?.id ?? null)}
                          data-testid={`payslip-row-${p?.id ?? ''}`}
                        >
                          <td className="whitespace-nowrap px-4 py-3">
                            <div className="flex items-center gap-3">
                              <span
                                className={cx(
                                  'grid h-9 w-9 flex-none place-items-center rounded-full text-[12px] font-semibold',
                                  AVATAR_TONES[i % AVATAR_TONES.length],
                                )}
                              >
                                {initials(p?.staff_name)}
                              </span>
                              <span className="text-[13.5px] font-medium text-text">
                                {p?.staff_name ?? '—'}
                              </span>
                            </div>
                          </td>
                          <td className="whitespace-nowrap px-4 py-3">
                            <Badge
                              variant={payslipStatusVariant(p?.status ?? 'draft')}
                            >
                              {payslipStatusLabel(p?.status ?? 'draft')}
                            </Badge>
                          </td>
                          <td className="mono whitespace-nowrap px-4 py-3 text-right text-[13.5px] text-muted">
                            {formatHours(p?.ordinary_hours)}
                          </td>
                          <td className="mono whitespace-nowrap px-4 py-3 text-right text-[13.5px] text-muted">
                            {formatHours(p?.overtime_hours)}
                          </td>
                          <td className="mono whitespace-nowrap px-4 py-3 text-right text-[13.5px] font-medium text-text">
                            {formatMoney(gross)}
                          </td>
                          <td className="mono whitespace-nowrap px-4 py-3 text-right text-[13.5px] text-muted">
                            {formatMoney(paye)}
                          </td>
                          <td className="mono whitespace-nowrap px-4 py-3 text-right text-[13.5px] text-muted">
                            {formatMoney(kiwi)}
                          </td>
                          <td className="mono whitespace-nowrap px-4 py-3 text-right text-[13.5px] text-muted">
                            {formatMoney(acc)}
                          </td>
                          <td className="mono whitespace-nowrap px-4 py-3 text-right text-[13.5px] text-muted">
                            {other > 0 ? formatMoney(other) : '—'}
                          </td>
                          <td className="mono whitespace-nowrap px-4 py-3 text-right text-[13.5px] font-medium text-text">
                            {formatMoney(net)}
                          </td>
                          <td className="px-4 py-3 text-right">
                            <ChevronRightIcon className="ml-auto h-4 w-4 text-muted-2" />
                          </td>
                        </tr>
                      )
                    })
                  )}
                </tbody>
              </table>
            </div>
            <div className="flex flex-wrap items-center justify-between gap-3 border-t border-border px-4 py-3">
              <div className="text-[13px] text-muted">
                Showing{' '}
                <span className="mono text-text">
                  {filteredPayslips.length === 0
                    ? 0
                    : (page - 1) * PAGE_SIZE + 1}
                  –{Math.min(page * PAGE_SIZE, filteredPayslips.length)}
                </span>{' '}
                of <span className="mono text-text">{filteredPayslips.length}</span>{' '}
                {filteredPayslips.length === 1 ? 'employee' : 'employees'}
                {draftCount > 0 && (
                  <> · {draftCount} need finalising before pay day</>
                )}
              </div>
              {totalPages > 1 && (
                <Pagination
                  currentPage={page}
                  totalPages={totalPages}
                  onPageChange={setPage}
                />
              )}
            </div>
          </section>

          {/* Footer action bar */}
          <div className="mt-gap flex flex-wrap items-center justify-end gap-3">
            <div className="mr-auto text-[13px] text-muted">
              Pay day{' '}
              <span className="mono font-semibold text-text">
                {formatShortDate(selectedPeriod?.pay_date)}
              </span>{' '}
              · IRD filing due same day
            </div>
            {selectedPeriod?.status === 'finalised' && (
              <Button
                variant="ghost"
                onClick={() => setReopenOpen(true)}
                data-testid="reopen-button"
              >
                Reopen
              </Button>
            )}
            {selectedPeriod?.status === 'paid' && (
              <span title="Already paid — contact support" data-testid="reopen-disabled">
                <Button variant="ghost" disabled>
                  Reopen
                </Button>
              </span>
            )}
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
              <CheckIcon className="h-4 w-4" />
              Finalise all ({draftCount})
            </Button>
          </div>
        </>
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

// Table header cell classes — shared with the rest of the redesigned tables.
const TH =
  'mono border-b border-border px-4 py-3 text-left text-[10.5px] font-medium uppercase tracking-[0.08em] text-muted-2'
const TH_R = `${TH} text-right`

// Avatar tone palette — cycled by row index (prototype Payroll.html rows).
const AVATAR_TONES = [
  'bg-accent-soft text-accent',
  'bg-ok-soft text-ok',
  'bg-warn-soft text-warn',
  'bg-purple-soft text-purple',
  'bg-[#EEF0F4] text-muted',
] as const

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
      className="fixed inset-0 z-50 flex justify-end bg-ink/50"
      onClick={onClose}
    >
      <div
        className="flex h-full w-full max-w-3xl flex-col overflow-y-auto bg-card shadow-pop"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="flex items-center justify-between border-b border-border px-4 py-3">
          <h2
            id="payslip-drawer-title"
            className="text-lg font-semibold text-text"
          >
            Payslip detail
          </h2>
          <button
            type="button"
            onClick={onClose}
            aria-label="Close drawer"
            className="min-h-[44px] min-w-[44px] rounded-ctl p-2 text-muted-2 hover:text-text focus:outline-none focus:ring-2 focus:ring-accent"
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
