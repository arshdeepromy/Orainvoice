/**
 * ApprovalQueue — admin/manager page for reviewing pending leave
 * requests and approving or rejecting them in line.
 *
 * Layout (per Phase 2 design §6.2):
 * - Filter chips: All / Pending / Approved / Rejected
 * - Default tab: Pending
 * - Table of leave requests (Staff, Type, Date range, Hours, Status,
 *   Reason, Actions)
 * - Inline Approve / Reject buttons on Pending rows
 * - Reject opens a modal capturing `decision_notes`
 *
 * Confidential filtering: the backend already filters out family-
 * violence requests this user can't see (per design §4.4 and the
 * `_apply_confidential_filter` helper). The frontend simply renders
 * what comes back and decorates rows whose leave_type_code is
 * `family_violence` with a "Confidential" badge.
 *
 * **Validates: Staff Management Phase 2 tasks D6, D10**
 *
 * Task 33 port: logic copied VERBATIM from
 * frontend/src/pages/leave/ApprovalQueue.tsx; presentation remapped onto the
 * design-system tokens (page/page-head, token tab strip, card-wrapped token
 * table, Badge tones) per the LeaveApprovals.html prototype. Button
 * `secondary`→`ghost`; Badge `warning`→`warn`, `error`→`danger`.
 */

import { useCallback, useEffect, useMemo, useState } from 'react'
import axios from 'axios'

import {
  approveLeaveRequest,
  listApprovalQueue,
  listLeaveTypes,
  rejectLeaveRequest,
  type LeaveRequest,
  type LeaveRequestStatus,
  type LeaveType,
} from '@/api/leave'
import { Badge, Button, Modal, Spinner } from '@/components/ui'
import type { BadgeVariant } from '@/components/ui'

type FilterTab = 'all' | 'pending' | 'approved' | 'rejected'

const TABS: { id: FilterTab; label: string }[] = [
  { id: 'pending', label: 'Pending' },
  { id: 'approved', label: 'Approved' },
  { id: 'rejected', label: 'Rejected' },
  { id: 'all', label: 'All' },
]

const PAGE_SIZE = 200

/** Local YYYY-MM-DD (date-only strings compare lexicographically). */
function localDateStr(d: Date): string {
  const y = d.getFullYear()
  const m = String(d.getMonth() + 1).padStart(2, '0')
  const day = String(d.getDate()).padStart(2, '0')
  return `${y}-${m}-${day}`
}

/** Real KPI summary computed from the pending + approved request sets. */
interface KpiStats {
  awaiting: number
  awaitingSoon: number
  onLeaveToday: number
  approvedThisMonth: number
  upcoming: number
  upcomingHours: number
}

const STATUS_BADGE: Record<
  LeaveRequestStatus,
  { variant: BadgeVariant; label: string }
> = {
  pending: { variant: 'warn', label: 'Pending' },
  approved: { variant: 'success', label: 'Approved' },
  rejected: { variant: 'danger', label: 'Rejected' },
  cancelled: { variant: 'neutral', label: 'Cancelled' },
}

function isAbortError(err: unknown): boolean {
  if (axios.isCancel?.(err)) return true
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

function extractError(err: unknown): string {
  if (axios.isAxiosError(err)) {
    const detail = err.response?.data?.detail
    if (typeof detail === 'string') return detail
    if (detail && typeof detail === 'object') {
      const inner = (detail as { reason?: string; detail?: string })
      if (typeof inner.reason === 'string') return inner.reason
      if (typeof inner.detail === 'string') return inner.detail
    }
    if (err.message) return err.message
  }
  if (err instanceof Error && err.message) return err.message
  return 'Action failed'
}

function formatDateRange(start: string | null, end: string | null): string {
  if (!start || !end) return '—'
  const s = new Date(`${start}T00:00:00Z`)
  const e = new Date(`${end}T00:00:00Z`)
  if (Number.isNaN(s.getTime()) || Number.isNaN(e.getTime())) {
    return `${start} – ${end}`
  }
  const fmt = (d: Date) =>
    d.toLocaleDateString('en-NZ', {
      day: 'numeric',
      month: 'short',
      year: 'numeric',
      timeZone: 'UTC',
    })
  if (start === end) return fmt(s)
  return `${fmt(s)} – ${fmt(e)}`
}

function formatHours(hoursStr: string | null | undefined): string {
  const n = parseFloat(hoursStr ?? '') || 0
  const rounded = Math.round(n * 10) / 10
  return Number.isInteger(rounded) ? `${rounded}h` : `${rounded.toFixed(1)}h`
}

function truncate(text: string | null | undefined, max = 60): string {
  if (!text) return ''
  if (text.length <= max) return text
  return `${text.slice(0, max - 1)}…`
}

/* ── Design presentation helpers (LeaveApprovals.html) ── */

/** Initials from a staff name, e.g. "Sina Faleolo" → "SF". */
function initials(name: string | null): string {
  return (
    (name || '?')
      .split(/\s+/)
      .filter(Boolean)
      .slice(0, 2)
      .map((w) => w[0]?.toUpperCase() ?? '')
      .join('') || '?'
  )
}

/** Stable avatar tint from the name (matches the prototype's row-av tones). */
const AVATAR_TONES = [
  { bg: 'var(--accent-soft)', fg: 'var(--accent)' },
  { bg: 'var(--warn-soft)', fg: 'var(--warn)' },
  { bg: 'var(--ok-soft)', fg: 'var(--ok)' },
  { bg: 'var(--purple-soft)', fg: 'var(--purple)' },
]
function avatarTone(name: string | null): { bg: string; fg: string } {
  const s = name || ''
  let h = 0
  for (let i = 0; i < s.length; i++) h = (h * 31 + s.charCodeAt(i)) >>> 0
  return AVATAR_TONES[h % AVATAR_TONES.length]
}

/** Leave-type swatch colour, derived from the type code (no colour in the API). */
function leaveTypeColor(code: string | null): string {
  switch ((code || '').toLowerCase()) {
    case 'annual':
    case 'annual_leave':
      return 'var(--accent)'
    case 'sick':
    case 'sick_leave':
      return 'var(--danger)'
    case 'bereavement':
      return 'var(--purple)'
    case 'public_holiday':
    case 'alternative_holiday':
    case 'alternative':
      return 'var(--ok)'
    case 'family_violence':
      return 'var(--warn)'
    default: {
      // Stable colour for any other/custom leave type, hashed off its code.
      const palette = ['var(--accent)', 'var(--ok)', 'var(--purple)', 'var(--warn)', 'var(--info)']
      const s = code || ''
      let h = 0
      for (let i = 0; i < s.length; i++) h = (h * 31 + s.charCodeAt(i)) >>> 0
      return palette[h % palette.length]
    }
  }
}

/** "requested today" / "requested 28 May" from an ISO timestamp. */
function formatRequested(iso: string | null | undefined): string {
  if (!iso) return ''
  const d = new Date(iso)
  if (Number.isNaN(d.getTime())) return ''
  const now = new Date()
  if (d.toDateString() === now.toDateString()) return 'requested today'
  return `requested ${d.toLocaleDateString('en-NZ', { day: 'numeric', month: 'short' })}`
}

/* ── KPI cards (design .kpi) ── */

const ICON_CLOCK = 'M12 8v4l3 3m6-3a9 9 0 11-18 0 9 9 0 0118 0z'
const ICON_CAL = 'M8 7V3m8 4V3M3 11h18M5 21h14a2 2 0 002-2V7a2 2 0 00-2-2H5a2 2 0 00-2 2v12a2 2 0 002 2z'
const ICON_CHECK = 'M20 6L9 17l-5-5'

const KPI_TONES: Record<string, { bg: string; fg: string }> = {
  amber: { bg: 'var(--warn-soft)', fg: 'var(--warn)' },
  blue: { bg: 'var(--accent-soft)', fg: 'var(--accent)' },
  green: { bg: 'var(--ok-soft)', fg: 'var(--ok)' },
  purple: { bg: 'var(--purple-soft)', fg: 'var(--purple)' },
}

function KpiCard({
  label,
  value,
  tone,
  iconPath,
  delta,
}: {
  label: string
  value: number
  tone: keyof typeof KPI_TONES
  iconPath: string
  delta?: string
}) {
  const t = KPI_TONES[tone]
  return (
    <div className="rounded-card border border-border bg-card p-5 shadow-card">
      <div className="flex items-start justify-between">
        <span className="text-[13px] text-muted">{label}</span>
        <span
          className="grid h-8 w-8 place-items-center rounded-[9px]"
          style={{ background: t.bg, color: t.fg }}
          aria-hidden="true"
        >
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={1.9} className="h-[18px] w-[18px]">
            <path d={iconPath} />
          </svg>
        </span>
      </div>
      <div className="mt-3 text-[28px] font-bold tracking-[-0.02em] text-text">{value.toLocaleString()}</div>
      {delta && <div className="mt-1 text-[12px] text-muted-2">{delta}</div>}
    </div>
  )
}

interface RejectModalState {
  request: LeaveRequest | null
  notes: string
  submitting: boolean
  error: string | null
}

const EMPTY_REJECT: RejectModalState = {
  request: null,
  notes: '',
  submitting: false,
  error: null,
}

export default function ApprovalQueue() {
  const [activeTab, setActiveTab] = useState<FilterTab>('pending')
  const [items, setItems] = useState<LeaveRequest[]>([])
  const [total, setTotal] = useState<number>(0)
  const [loading, setLoading] = useState<boolean>(true)
  const [error, setError] = useState<string | null>(null)
  const [rowError, setRowError] = useState<{ id: string; message: string } | null>(null)
  const [busyRowId, setBusyRowId] = useState<string | null>(null)
  const [rejectState, setRejectState] = useState<RejectModalState>(EMPTY_REJECT)
  const [refreshKey, setRefreshKey] = useState<number>(0)
  const [search, setSearch] = useState<string>('')
  const [typeFilter, setTypeFilter] = useState<string>('') // leave_type_id, '' = all
  const [leaveTypes, setLeaveTypes] = useState<LeaveType[]>([])
  const [kpis, setKpis] = useState<KpiStats | null>(null)

  const refresh = useCallback(() => setRefreshKey((k) => k + 1), [])

  useEffect(() => {
    const controller = new AbortController()
    let cancelled = false
    const load = async () => {
      setLoading(true)
      setError(null)
      try {
        const params: { status?: LeaveRequestStatus | 'all'; limit: number; offset: number } = {
          limit: PAGE_SIZE,
          offset: 0,
        }
        // The router uses 'all' to bypass the status filter; otherwise pass the
        // chip value as the explicit status.
        params.status = activeTab === 'all' ? 'all' : (activeTab as LeaveRequestStatus)
        const res = await listApprovalQueue(params, controller.signal)
        if (cancelled || controller.signal.aborted) return
        setItems(res.items ?? [])
        setTotal(res.total ?? 0)
      } catch (err) {
        if (cancelled || controller.signal.aborted || isAbortError(err)) return
        setError(extractError(err) || 'Failed to load approval queue')
      } finally {
        if (!cancelled && !controller.signal.aborted) setLoading(false)
      }
    }
    void load()
    return () => {
      cancelled = true
      controller.abort()
    }
  }, [activeTab, refreshKey])

  // Leave types — for the "Leave type" filter dropdown (loaded once).
  useEffect(() => {
    const controller = new AbortController()
    listLeaveTypes({ limit: 100 }, controller.signal)
      .then((res) => {
        if (!controller.signal.aborted) setLeaveTypes(res.items ?? [])
      })
      .catch(() => {
        /* non-critical — the filter just shows no options. */
      })
    return () => controller.abort()
  }, [])

  // KPI summary — computed from real pending + approved request sets. Refreshes
  // after every approve/decline (refreshKey). Capped at PAGE_SIZE per status.
  useEffect(() => {
    const controller = new AbortController()
    const load = async () => {
      try {
        const [pending, approved] = await Promise.all([
          listApprovalQueue({ status: 'pending', limit: PAGE_SIZE }, controller.signal),
          listApprovalQueue({ status: 'approved', limit: PAGE_SIZE }, controller.signal),
        ])
        if (controller.signal.aborted) return
        const now = new Date()
        const today = localDateStr(now)
        const in7 = localDateStr(new Date(now.getTime() + 7 * 86400000))
        const in30 = localDateStr(new Date(now.getTime() + 30 * 86400000))
        const ym = today.slice(0, 7)

        const pendingItems = pending.items ?? []
        const approvedItems = approved.items ?? []

        // On leave today — distinct staff whose approved leave spans today.
        const onLeaveStaff = new Set<string>()
        let upcoming = 0
        let upcomingHours = 0
        let approvedThisMonth = 0
        for (const r of approvedItems) {
          if (r.start_date && r.end_date && r.start_date <= today && today <= r.end_date) {
            onLeaveStaff.add(r.staff_id)
          }
          if (r.start_date && r.start_date >= today && r.start_date <= in30) {
            upcoming += 1
            upcomingHours += parseFloat(r.hours_requested ?? '') || 0
          }
          if ((r.decided_at ?? '').slice(0, 7) === ym) approvedThisMonth += 1
        }

        const awaitingSoon = pendingItems.filter(
          (r) => r.start_date && r.start_date >= today && r.start_date <= in7,
        ).length

        setKpis({
          awaiting: pending.total ?? pendingItems.length,
          awaitingSoon,
          onLeaveToday: onLeaveStaff.size,
          approvedThisMonth,
          upcoming,
          upcomingHours,
        })
      } catch {
        if (!controller.signal.aborted) setKpis(null)
      }
    }
    void load()
    return () => controller.abort()
  }, [refreshKey])

  const handleApprove = useCallback(
    async (req: LeaveRequest) => {
      setBusyRowId(req.id)
      setRowError(null)
      try {
        await approveLeaveRequest(req.id, {})
        refresh()
      } catch (err) {
        setRowError({ id: req.id, message: extractError(err) || 'Approval failed' })
      } finally {
        setBusyRowId(null)
      }
    },
    [refresh],
  )

  const openRejectModal = useCallback((req: LeaveRequest) => {
    setRejectState({ request: req, notes: '', submitting: false, error: null })
  }, [])

  const closeRejectModal = useCallback(() => {
    setRejectState(EMPTY_REJECT)
  }, [])

  const confirmReject = useCallback(async () => {
    const target = rejectState.request
    if (!target) return
    setRejectState((s) => ({ ...s, submitting: true, error: null }))
    try {
      await rejectLeaveRequest(target.id, { decision_notes: rejectState.notes || null })
      setRejectState(EMPTY_REJECT)
      refresh()
    } catch (err) {
      setRejectState((s) => ({
        ...s,
        submitting: false,
        error: extractError(err) || 'Reject failed',
      }))
    }
  }, [rejectState, refresh])

  // Client-side staff search + leave-type filter over the loaded page (the
  // backend approvals endpoint has no leave_type param, so this filters the
  // fetched rows — matches the design's "Search staff…" + "Leave type" tools).
  const filteredItems = useMemo(() => {
    let list = items ?? []
    const q = search.trim().toLowerCase()
    if (q) list = list.filter((r) => (r.staff_name ?? '').toLowerCase().includes(q))
    if (typeFilter) list = list.filter((r) => r.leave_type_id === typeFilter)
    return list
  }, [items, search, typeFilter])

  const TH =
    'mono border-b border-border px-4 py-3 text-left text-[10.5px] font-medium uppercase tracking-[0.08em] text-muted-2'

  return (
    <div className="page page-wide" data-testid="approval-queue-page">
      <div className="page-head">
        <div>
          <div className="eyebrow">People · Leave</div>
          <h1>Leave approvals</h1>
          <p className="sub">
            {loading
              ? 'Review and decide on leave requests submitted by staff.'
              : `${total.toLocaleString()} ${activeTab === 'all' ? '' : `${activeTab} `}request${total === 1 ? '' : 's'} in this view`}
          </p>
        </div>
      </div>

      {/* KPI summary — real counts from the pending + approved sets. */}
      {kpis && (
        <div className="mb-4 grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-4">
          <KpiCard
            label="Awaiting approval"
            value={kpis.awaiting}
            tone="amber"
            iconPath={ICON_CLOCK}
            delta={kpis.awaitingSoon > 0 ? `${kpis.awaitingSoon} within 7 days` : undefined}
          />
          <KpiCard label="On leave today" value={kpis.onLeaveToday} tone="blue" iconPath={ICON_CAL} />
          <KpiCard label="Approved this month" value={kpis.approvedThisMonth} tone="green" iconPath={ICON_CHECK} />
          <KpiCard
            label="Upcoming (30d)"
            value={kpis.upcoming}
            tone="purple"
            iconPath={ICON_CAL}
            delta={kpis.upcomingHours > 0 ? `${formatHours(String(kpis.upcomingHours))} total` : undefined}
          />
        </div>
      )}

      {/* Toolbar — segmented status control + staff search + type filter. */}
      <div className="mb-4 flex flex-wrap items-center gap-3">
        <div
          role="tablist"
          aria-label="Approval queue filter"
          className="inline-flex rounded-ctl border border-border bg-canvas p-1"
        >
          {TABS.map((tab) => {
            const active = activeTab === tab.id
            return (
              <button
                key={tab.id}
                role="tab"
                type="button"
                aria-selected={active}
                data-testid={`approval-tab-${tab.id}`}
                onClick={() => setActiveTab(tab.id)}
                className={`min-h-[34px] rounded-[7px] px-3 text-[13px] font-medium transition-colors ${
                  active ? 'bg-card text-text shadow-card' : 'text-muted hover:text-text'
                }`}
              >
                {tab.label}
              </button>
            )
          })}
        </div>
        <div className="flex-1" />
        <div className="flex h-9 items-center gap-2 rounded-ctl border border-border bg-card px-3 text-muted-2">
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={2} className="h-[17px] w-[17px]">
            <path d="M21 21l-5-5m2-5a7 7 0 11-14 0 7 7 0 0114 0z" />
          </svg>
          <input
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            placeholder="Search staff…"
            aria-label="Search staff"
            className="w-44 bg-transparent text-[13.5px] text-text placeholder:text-muted-2 focus:outline-none"
          />
        </div>
        <select
          value={typeFilter}
          onChange={(e) => setTypeFilter(e.target.value)}
          aria-label="Filter by leave type"
          data-testid="leave-type-filter"
          className="h-9 rounded-ctl border border-border bg-card px-3 text-[13.5px] text-text focus:border-accent focus:outline-none"
        >
          <option value="">All leave types</option>
          {leaveTypes.map((lt) => (
            <option key={lt.id} value={lt.id}>
              {lt.name}
            </option>
          ))}
        </select>
      </div>

      {error && (
        <div
          role="alert"
          className="mb-4 rounded-ctl border border-danger/30 bg-danger-soft px-4 py-3 text-sm text-danger"
        >
          <p>{error}</p>
          <button
            type="button"
            onClick={refresh}
            className="mt-2 min-h-[36px] rounded-ctl bg-danger px-3 py-1 text-xs font-medium text-white hover:brightness-95"
          >
            Retry
          </button>
        </div>
      )}

      {loading ? (
        <div className="flex items-center justify-center py-16">
          <Spinner size="lg" label="Loading approval queue" />
        </div>
      ) : filteredItems.length === 0 ? (
        <div
          data-testid="approval-queue-empty"
          className="rounded-card border border-dashed border-border bg-card px-6 py-12 text-center text-sm text-muted"
        >
          No requests in this view.
        </div>
      ) : (
        <section className="overflow-hidden rounded-card border border-border bg-card shadow-card">
          <div className="overflow-x-auto">
            <table className="w-full border-collapse text-sm">
              <thead>
                <tr>
                  <th scope="col" className={TH}>Employee</th>
                  <th scope="col" className={TH}>Type</th>
                  <th scope="col" className={TH}>Dates</th>
                  <th scope="col" className={`${TH} text-right`}>Hours</th>
                  <th scope="col" className={TH}>Reason</th>
                  <th scope="col" className={TH}>Status</th>
                  <th scope="col" className={`${TH} text-right`}>Actions</th>
                </tr>
              </thead>
              <tbody>
                {filteredItems.map((req) => {
                  const status = STATUS_BADGE[req.status] ?? STATUS_BADGE.pending
                  const isConfidential = req.leave_type_code === 'family_violence'
                  const isPending = req.status === 'pending'
                  const isBusy = busyRowId === req.id
                  const errMessage =
                    rowError && rowError.id === req.id ? rowError.message : null
                  const tone = avatarTone(req.staff_name)
                  return (
                    <tr
                      key={req.id}
                      data-testid={`approval-row-${req.id}`}
                      className="border-b border-border last:border-b-0 hover:bg-canvas"
                    >
                      {/* Employee — avatar + name */}
                      <td className="whitespace-nowrap px-4 py-3">
                        <div className="flex items-center gap-3">
                          <span
                            className="grid h-9 w-9 flex-shrink-0 place-items-center rounded-[10px] text-[12px] font-bold"
                            style={{ background: tone.bg, color: tone.fg }}
                            aria-hidden="true"
                          >
                            {initials(req.staff_name)}
                          </span>
                          <span className="text-[13.5px] font-medium text-text">
                            {req.staff_name ?? '—'}
                          </span>
                        </div>
                      </td>
                      {/* Type — colour swatch + name (+ confidential badge) */}
                      <td className="whitespace-nowrap px-4 py-3">
                        <div className="flex items-center gap-2">
                          <span className="inline-flex items-center gap-[7px] text-[13px] font-medium text-text">
                            <span
                              className="h-[9px] w-[9px] flex-shrink-0 rounded-[3px]"
                              style={{ background: leaveTypeColor(req.leave_type_code) }}
                              aria-hidden="true"
                            />
                            {req.leave_type_name ?? req.leave_type_code ?? '—'}
                          </span>
                          {isConfidential && (
                            <Badge variant="info" className="text-[10px] uppercase">
                              <span data-testid={`confidential-badge-${req.id}`}>Confidential</span>
                            </Badge>
                          )}
                        </div>
                      </td>
                      {/* Dates — range + requested-on */}
                      <td className="whitespace-nowrap px-4 py-3">
                        <div className="flex flex-col">
                          <span className="text-[13.5px] font-medium text-text">
                            {formatDateRange(req.start_date, req.end_date)}
                          </span>
                          {formatRequested(req.created_at) && (
                            <span className="mono text-[12px] text-muted-2">
                              {formatRequested(req.created_at)}
                            </span>
                          )}
                        </div>
                      </td>
                      <td className="mono whitespace-nowrap px-4 py-3 text-right text-[13px] font-semibold text-text">
                        {formatHours(req.hours_requested)}
                      </td>
                      <td
                        className="max-w-[16rem] px-4 py-3 text-[13px] text-muted"
                        title={req.reason ?? ''}
                      >
                        {isConfidential
                          ? <span className="italic text-muted-2">Hidden</span>
                          : truncate(req.reason, 60) || '—'}
                      </td>
                      <td className="whitespace-nowrap px-4 py-3">
                        <Badge variant={status.variant}>{status.label}</Badge>
                      </td>
                      <td className="whitespace-nowrap px-4 py-3 text-right">
                        {isPending ? (
                          <div className="flex items-center justify-end gap-2">
                            <Button
                              size="sm"
                              variant="ghost"
                              data-testid={`reject-${req.id}`}
                              onClick={() => openRejectModal(req)}
                              disabled={isBusy}
                            >
                              Decline
                            </Button>
                            <Button
                              size="sm"
                              data-testid={`approve-${req.id}`}
                              onClick={() => handleApprove(req)}
                              loading={isBusy}
                              disabled={isBusy}
                            >
                              Approve
                            </Button>
                          </div>
                        ) : (
                          <span className="text-xs text-muted-2">—</span>
                        )}
                        {errMessage && (
                          <p role="alert" className="mt-1 text-xs text-danger">
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
          {/* Pagination info (design .pagination — count only; the queue is a
              single page of up to PAGE_SIZE, so no page controls are shown). */}
          <div className="flex items-center justify-between border-t border-border px-4 py-3 text-[13px] text-muted">
            <span>
              Showing <span className="mono">{filteredItems.length}</span>{' '}
              {activeTab === 'all' ? '' : `${activeTab} `}request{filteredItems.length === 1 ? '' : 's'}
            </span>
          </div>
        </section>
      )}

      <Modal
        open={rejectState.request !== null}
        onClose={closeRejectModal}
        title="Decline leave request"
      >
        <div className="space-y-3">
          <p className="text-sm text-muted">
            Add an optional note explaining why this request is being declined.
            The staff member will see this on their leave history.
          </p>
          <label className="block text-[12.5px] font-medium text-text">
            Decision notes
            <textarea
              data-testid="reject-notes"
              className="mt-1 min-h-[96px] w-full rounded-ctl border border-border bg-card px-3 py-2 text-sm text-text focus:border-accent focus:outline-none focus:shadow-[0_0_0_3px_var(--accent-soft)]"
              value={rejectState.notes}
              onChange={(e) =>
                setRejectState((s) => ({ ...s, notes: e.target.value }))
              }
              placeholder="Optional"
              maxLength={1000}
            />
          </label>
          {rejectState.error && (
            <div
              role="alert"
              className="rounded-ctl border border-danger/30 bg-danger-soft px-3 py-2 text-xs text-danger"
            >
              {rejectState.error}
            </div>
          )}
          <div className="flex justify-end gap-2 pt-2">
            <Button
              size="sm"
              variant="ghost"
              onClick={closeRejectModal}
              disabled={rejectState.submitting}
            >
              Cancel
            </Button>
            <Button
              size="sm"
              variant="danger"
              data-testid="reject-confirm"
              onClick={confirmReject}
              loading={rejectState.submitting}
              disabled={rejectState.submitting}
            >
              Decline request
            </Button>
          </div>
        </div>
      </Modal>
    </div>
  )
}
