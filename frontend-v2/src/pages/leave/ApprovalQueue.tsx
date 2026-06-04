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
  rejectLeaveRequest,
  type LeaveRequest,
  type LeaveRequestStatus,
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

const PAGE_SIZE = 50

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

  const filteredItems = useMemo(() => items ?? [], [items])

  const TH =
    'mono border-b border-border px-4 py-3 text-left text-[10.5px] font-medium uppercase tracking-[0.08em] text-muted-2'

  return (
    <div className="page page-wide" data-testid="approval-queue-page">
      <div className="page-head">
        <div>
          <div className="eyebrow">People · Leave</div>
          <h1>Leave approvals</h1>
          <p className="sub">
            Review and decide on leave requests submitted by staff.
          </p>
        </div>
        <div className="head-actions text-sm text-muted">
          {(total ?? 0).toLocaleString()} total
        </div>
      </div>

      {/* Tab strip */}
      <div
        role="tablist"
        aria-label="Approval queue filter"
        className="mb-4 flex flex-wrap gap-1 border-b border-border"
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
              className={`-mb-px min-h-[44px] border-b-2 px-4 py-2 text-sm font-medium transition-colors ${
                active
                  ? 'border-accent text-accent'
                  : 'border-transparent text-muted hover:text-text'
              }`}
            >
              {tab.label}
            </button>
          )
        })}
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
                  <th scope="col" className={TH}>Staff</th>
                  <th scope="col" className={TH}>Leave type</th>
                  <th scope="col" className={TH}>Date range</th>
                  <th scope="col" className={`${TH} text-right`}>Hours</th>
                  <th scope="col" className={TH}>Status</th>
                  <th scope="col" className={TH}>Reason</th>
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
                  return (
                    <tr
                      key={req.id}
                      data-testid={`approval-row-${req.id}`}
                      className="border-b border-border last:border-b-0 hover:bg-canvas"
                    >
                      <td className="whitespace-nowrap px-4 py-3 text-[13.5px] text-text">
                        {req.staff_name ?? '—'}
                      </td>
                      <td className="whitespace-nowrap px-4 py-3 text-[13.5px] text-text">
                        <div className="flex items-center gap-2">
                          <span>{req.leave_type_name ?? req.leave_type_code ?? '—'}</span>
                          {isConfidential && (
                            <Badge
                              variant="info"
                              className="text-[10px] uppercase"
                            >
                              <span data-testid={`confidential-badge-${req.id}`}>
                                Confidential
                              </span>
                            </Badge>
                          )}
                        </div>
                      </td>
                      <td className="mono whitespace-nowrap px-4 py-3 text-[13px] text-muted">
                        {formatDateRange(req.start_date, req.end_date)}
                      </td>
                      <td className="mono whitespace-nowrap px-4 py-3 text-right text-[13px] text-text">
                        {formatHours(req.hours_requested)}
                      </td>
                      <td className="whitespace-nowrap px-4 py-3">
                        <Badge variant={status.variant}>{status.label}</Badge>
                      </td>
                      <td
                        className="max-w-[16rem] px-4 py-3 text-[13px] text-muted"
                        title={req.reason ?? ''}
                      >
                        {isConfidential
                          ? <span className="italic text-muted-2">Hidden</span>
                          : truncate(req.reason, 60) || '—'}
                      </td>
                      <td className="whitespace-nowrap px-4 py-3 text-right">
                        {isPending ? (
                          <div className="flex items-center justify-end gap-2">
                            <Button
                              size="sm"
                              data-testid={`approve-${req.id}`}
                              onClick={() => handleApprove(req)}
                              loading={isBusy}
                              disabled={isBusy}
                            >
                              Approve
                            </Button>
                            <Button
                              size="sm"
                              variant="danger"
                              data-testid={`reject-${req.id}`}
                              onClick={() => openRejectModal(req)}
                              disabled={isBusy}
                            >
                              Reject
                            </Button>
                          </div>
                        ) : (
                          <span className="text-xs text-muted-2">—</span>
                        )}
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
        open={rejectState.request !== null}
        onClose={closeRejectModal}
        title="Reject leave request"
      >
        <div className="space-y-3">
          <p className="text-sm text-muted">
            Add an optional note explaining why this request is being rejected.
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
              Reject request
            </Button>
          </div>
        </div>
      </Modal>
    </div>
  )
}
