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
 */

import { useCallback, useEffect, useMemo, useState } from 'react'
import axios from 'axios'

import {
  approveLeaveRequest,
  listApprovalQueue,
  rejectLeaveRequest,
  type LeaveRequest,
  type LeaveRequestStatus,
} from '../../api/leave'
import { Badge, Button, Modal, Spinner } from '../../components/ui'

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
  { variant: 'success' | 'warning' | 'error' | 'info' | 'neutral'; label: string }
> = {
  pending: { variant: 'warning', label: 'Pending' },
  approved: { variant: 'success', label: 'Approved' },
  rejected: { variant: 'error', label: 'Rejected' },
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

  return (
    <div className="p-4 md:p-6 space-y-4" data-testid="approval-queue-page">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h1 className="text-xl font-semibold text-gray-900 dark:text-gray-100">
            Leave approvals
          </h1>
          <p className="text-sm text-gray-500 dark:text-gray-400">
            Review and decide on leave requests submitted by staff.
          </p>
        </div>
        <div className="text-sm text-gray-500 dark:text-gray-400">
          {(total ?? 0).toLocaleString()} total
        </div>
      </div>

      {/* Tab strip */}
      <div
        role="tablist"
        aria-label="Approval queue filter"
        className="flex flex-wrap gap-1 border-b border-gray-200 dark:border-gray-700"
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
              className={`px-4 py-2 -mb-px min-h-[44px] text-sm font-medium border-b-2 transition-colors ${
                active
                  ? 'border-blue-600 text-blue-700 dark:border-blue-400 dark:text-blue-300'
                  : 'border-transparent text-gray-600 dark:text-gray-300 hover:text-gray-900 dark:hover:text-gray-100'
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
          className="rounded-md border border-red-200 dark:border-red-800 bg-red-50 dark:bg-red-900/20 px-4 py-3 text-sm text-red-700 dark:text-red-300"
        >
          <p>{error}</p>
          <button
            type="button"
            onClick={refresh}
            className="mt-2 px-3 py-1 min-h-[36px] rounded bg-red-600 text-white text-xs font-medium hover:bg-red-700"
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
          className="rounded-lg border border-dashed border-gray-300 dark:border-gray-700 bg-white dark:bg-gray-900 px-6 py-12 text-center text-sm text-gray-500 dark:text-gray-400"
        >
          No requests in this view.
        </div>
      ) : (
        <div className="overflow-x-auto rounded-lg border border-gray-200 dark:border-gray-700 bg-white dark:bg-gray-900">
          <table className="min-w-full divide-y divide-gray-200 dark:divide-gray-700 text-sm">
            <thead className="bg-gray-50 dark:bg-gray-800/40">
              <tr className="text-left text-xs uppercase tracking-wider text-gray-500 dark:text-gray-400">
                <th scope="col" className="px-4 py-2 font-medium">Staff</th>
                <th scope="col" className="px-4 py-2 font-medium">Leave type</th>
                <th scope="col" className="px-4 py-2 font-medium">Date range</th>
                <th scope="col" className="px-4 py-2 font-medium text-right">Hours</th>
                <th scope="col" className="px-4 py-2 font-medium">Status</th>
                <th scope="col" className="px-4 py-2 font-medium">Reason</th>
                <th scope="col" className="px-4 py-2 font-medium text-right">Actions</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-gray-100 dark:divide-gray-800">
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
                    className="hover:bg-gray-50 dark:hover:bg-gray-800/40"
                  >
                    <td className="px-4 py-2 whitespace-nowrap text-gray-700 dark:text-gray-200">
                      {req.staff_name ?? '—'}
                    </td>
                    <td className="px-4 py-2 whitespace-nowrap text-gray-700 dark:text-gray-200">
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
                    <td className="px-4 py-2 whitespace-nowrap text-gray-700 dark:text-gray-200">
                      {formatDateRange(req.start_date, req.end_date)}
                    </td>
                    <td className="px-4 py-2 whitespace-nowrap text-right text-gray-700 dark:text-gray-200">
                      {formatHours(req.hours_requested)}
                    </td>
                    <td className="px-4 py-2 whitespace-nowrap">
                      <Badge variant={status.variant}>{status.label}</Badge>
                    </td>
                    <td
                      className="px-4 py-2 max-w-[16rem] text-gray-600 dark:text-gray-400"
                      title={req.reason ?? ''}
                    >
                      {isConfidential
                        ? <span className="italic text-gray-400 dark:text-gray-500">Hidden</span>
                        : truncate(req.reason, 60) || '—'}
                    </td>
                    <td className="px-4 py-2 whitespace-nowrap text-right">
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
                        <span className="text-xs text-gray-400 dark:text-gray-500">—</span>
                      )}
                      {errMessage && (
                        <p
                          role="alert"
                          className="mt-1 text-xs text-red-600 dark:text-red-400"
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
      )}

      <Modal
        open={rejectState.request !== null}
        onClose={closeRejectModal}
        title="Reject leave request"
      >
        <div className="space-y-3">
          <p className="text-sm text-gray-600 dark:text-gray-300">
            Add an optional note explaining why this request is being rejected.
            The staff member will see this on their leave history.
          </p>
          <label className="block text-sm font-medium text-gray-700 dark:text-gray-200">
            Decision notes
            <textarea
              data-testid="reject-notes"
              className="mt-1 w-full min-h-[96px] rounded-md border border-gray-300 dark:border-gray-600 bg-white dark:bg-gray-900 px-3 py-2 text-sm text-gray-900 dark:text-gray-100 focus:outline-none focus:ring-2 focus:ring-blue-500"
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
              className="rounded-md border border-red-200 dark:border-red-800 bg-red-50 dark:bg-red-900/20 px-3 py-2 text-xs text-red-700 dark:text-red-300"
            >
              {rejectState.error}
            </div>
          )}
          <div className="flex justify-end gap-2 pt-2">
            <Button
              size="sm"
              variant="secondary"
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
