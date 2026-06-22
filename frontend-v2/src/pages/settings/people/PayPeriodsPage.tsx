/**
 * PayPeriodsPage — Settings → People → Pay Periods (Phase 4 task D5).
 *
 * Per design.md §6.5 + R1 + G21:
 *   - List pay periods (using listPayPeriods({ limit: 100 })).
 *   - Create modal (start_date / end_date / pay_date).
 *   - Edit-in-place: pay_date + status (open/finalised/paid).
 *   - Reopen button (G21): visible when status='finalised'. Click opens
 *     modal that requires reason text → calls reopenPayPeriod(...).
 *   - Reopen button disabled with tooltip "Already paid — contact support"
 *     when status='paid'.
 *
 * Conventions:
 *   - Typed client only (`frontend/src/api/payslips.ts`).
 *   - All API responses consumed with `?.` + `?? []` / `?? null`.
 *   - Every effect uses an AbortController.
 *
 * **Validates: Staff Management Phase 4 task D5, G21**
 */

import { useCallback, useEffect, useMemo, useState } from 'react'
import { Badge, Button, Modal, Spinner, AlertBanner } from '@/components/ui'
import {
  createPayPeriod,
  listPayPeriods,
  reopenPayPeriod,
  updatePayPeriod,
} from '@/api/payslips'
import type {
  PayPeriod,
  PayPeriodCreatePayload,
  PayPeriodStatus,
} from '@/api/payslips'

const STATUSES: PayPeriodStatus[] = ['open', 'finalised', 'paid']

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
  return 'Action failed'
}

function statusVariant(
  status: PayPeriodStatus | string,
): 'success' | 'warn' | 'info' | 'neutral' {
  switch (status) {
    case 'open':
      return 'info'
    case 'finalised':
      return 'warn'
    case 'paid':
      return 'success'
    default:
      return 'neutral'
  }
}

interface CreateModalState {
  open: boolean
  start_date: string
  end_date: string
  pay_date: string
  busy: boolean
  error: string | null
}

const EMPTY_CREATE: CreateModalState = {
  open: false,
  start_date: '',
  end_date: '',
  pay_date: '',
  busy: false,
  error: null,
}

interface ReopenModalState {
  open: boolean
  periodId: string | null
  reason: string
  busy: boolean
  error: string | null
}

const EMPTY_REOPEN: ReopenModalState = {
  open: false,
  periodId: null,
  reason: '',
  busy: false,
  error: null,
}

interface InlineEdit {
  pay_date: string
  status: PayPeriodStatus
}

export default function PayPeriodsPage() {
  const [items, setItems] = useState<PayPeriod[]>([])
  const [loading, setLoading] = useState<boolean>(true)
  const [loadError, setLoadError] = useState<string | null>(null)
  const [refreshTick, setRefreshTick] = useState<number>(0)

  const [createState, setCreateState] = useState<CreateModalState>(EMPTY_CREATE)
  const [reopenState, setReopenState] = useState<ReopenModalState>(EMPTY_REOPEN)

  const [editingId, setEditingId] = useState<string | null>(null)
  const [editForm, setEditForm] = useState<InlineEdit>({
    pay_date: '',
    status: 'open',
  })
  const [editBusy, setEditBusy] = useState<boolean>(false)
  const [rowError, setRowError] = useState<{
    id: string
    message: string
  } | null>(null)

  const refresh = useCallback(() => setRefreshTick((t) => t + 1), [])

  // ── Load pay periods ──
  useEffect(() => {
    const controller = new AbortController()
    setLoading(true)
    setLoadError(null)
    ;(async () => {
      try {
        const res = await listPayPeriods({ limit: 100 }, controller.signal)
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
  }, [refreshTick])

  // Sort newest first.
  const sortedItems = useMemo<PayPeriod[]>(() => {
    return [...(items ?? [])].sort((a, b) =>
      (b?.start_date ?? '').localeCompare(a?.start_date ?? ''),
    )
  }, [items])

  // ── Create modal ──
  const openCreate = useCallback(() => {
    setCreateState({ ...EMPTY_CREATE, open: true })
  }, [])

  const closeCreate = useCallback(() => {
    setCreateState(EMPTY_CREATE)
  }, [])

  const submitCreate = useCallback(async () => {
    const { start_date, end_date, pay_date } = createState
    if (!start_date || !end_date || !pay_date) return
    setCreateState((s) => ({ ...s, busy: true, error: null }))
    try {
      const payload: PayPeriodCreatePayload = {
        start_date,
        end_date,
        pay_date,
      }
      await createPayPeriod(payload)
      setCreateState(EMPTY_CREATE)
      refresh()
    } catch (err) {
      setCreateState((s) => ({
        ...s,
        busy: false,
        error: readErrorMessage(err) || 'Create failed',
      }))
    }
  }, [createState, refresh])

  const canSubmitCreate =
    !createState.busy &&
    createState.start_date.trim().length > 0 &&
    createState.end_date.trim().length > 0 &&
    createState.pay_date.trim().length > 0

  // ── Inline edit (pay_date + status) ──
  const startEdit = useCallback((p: PayPeriod) => {
    setEditingId(p.id)
    setEditForm({
      pay_date: p.pay_date ?? '',
      status: ((p.status ?? 'open') as PayPeriodStatus),
    })
    setRowError(null)
  }, [])

  const cancelEdit = useCallback(() => {
    setEditingId(null)
    setEditBusy(false)
  }, [])

  const submitEdit = useCallback(
    async (p: PayPeriod) => {
      setEditBusy(true)
      setRowError(null)
      try {
        await updatePayPeriod(p.id, {
          pay_date: editForm.pay_date,
          status: editForm.status,
        })
        setEditingId(null)
        refresh()
      } catch (err) {
        setRowError({
          id: p.id,
          message: readErrorMessage(err) || 'Update failed',
        })
      } finally {
        setEditBusy(false)
      }
    },
    [editForm, refresh],
  )

  // ── Reopen modal (G21) ──
  const openReopen = useCallback((p: PayPeriod) => {
    setReopenState({
      open: true,
      periodId: p.id,
      reason: '',
      busy: false,
      error: null,
    })
  }, [])

  const closeReopen = useCallback(() => {
    setReopenState(EMPTY_REOPEN)
  }, [])

  const submitReopen = useCallback(async () => {
    const id = reopenState.periodId
    const reason = reopenState.reason.trim()
    if (!id || reason.length === 0) return
    setReopenState((s) => ({ ...s, busy: true, error: null }))
    try {
      await reopenPayPeriod(id, { reason })
      setReopenState(EMPTY_REOPEN)
      refresh()
    } catch (err) {
      setReopenState((s) => ({
        ...s,
        busy: false,
        error: readErrorMessage(err) || 'Reopen failed',
      }))
    }
  }, [reopenState, refresh])

  return (
    <div className="space-y-4" data-testid="pay-periods-page">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <h1 className="text-xl font-semibold text-text">
            Pay periods
          </h1>
          <p className="text-sm text-muted">
            Manage pay periods, edit pay dates, and reopen finalised periods
            for corrections.
          </p>
        </div>
        <Button
          size="sm"
          onClick={openCreate}
          data-testid="pay-periods-add"
        >
          Add pay period
        </Button>
      </div>

      {loadError && (
        <AlertBanner variant="error">{loadError}</AlertBanner>
      )}

      {loading ? (
        <div className="flex items-center justify-center py-12">
          <Spinner size="lg" label="Loading pay periods" />
        </div>
      ) : sortedItems.length === 0 ? (
        <div
          className="rounded-card border border-dashed border-border px-4 py-12 text-center text-sm text-muted"
          data-testid="pay-periods-empty"
        >
          No pay periods yet. Add one or wait for the daily roll task to
          create the first batch.
        </div>
      ) : (
        <div className="overflow-hidden rounded-card border border-border bg-card shadow-card">
          <table
            className="min-w-full text-sm"
            data-testid="pay-periods-table"
          >
            <thead>
              <tr>
                <th className="mono border-b border-border px-4 py-3 text-left text-[10.5px] font-medium uppercase tracking-[0.08em] text-muted-2">
                  Start
                </th>
                <th className="mono border-b border-border px-4 py-3 text-left text-[10.5px] font-medium uppercase tracking-[0.08em] text-muted-2">
                  End
                </th>
                <th className="mono border-b border-border px-4 py-3 text-left text-[10.5px] font-medium uppercase tracking-[0.08em] text-muted-2">
                  Pay date
                </th>
                <th className="mono border-b border-border px-4 py-3 text-left text-[10.5px] font-medium uppercase tracking-[0.08em] text-muted-2">
                  Cycle
                </th>
                <th className="mono border-b border-border px-4 py-3 text-left text-[10.5px] font-medium uppercase tracking-[0.08em] text-muted-2">
                  Status
                </th>
                <th className="mono border-b border-border px-4 py-3 text-right text-[10.5px] font-medium uppercase tracking-[0.08em] text-muted-2">
                  Actions
                </th>
              </tr>
            </thead>
            <tbody>
              {sortedItems.map((p) => {
                const isEditing = editingId === p.id
                const status = (p?.status ?? 'open') as PayPeriodStatus
                const isPaid = status === 'paid'
                const isFinalised = status === 'finalised'
                const errMessage =
                  rowError && rowError.id === p?.id ? rowError.message : null
                return (
                  <tr
                    key={p?.id ?? Math.random().toString(36)}
                    data-testid={`pay-period-row-${p?.id ?? ''}`}
                    className="border-b border-border last:border-b-0 hover:bg-canvas"
                  >
                    <td className="mono px-4 py-2 text-text">
                      {formatDate(p?.start_date)}
                    </td>
                    <td className="mono px-4 py-2 text-text">
                      {formatDate(p?.end_date)}
                    </td>
                    <td className="mono px-4 py-2 text-muted">
                      {isEditing ? (
                        <input
                          type="date"
                          value={editForm.pay_date}
                          onChange={(e) =>
                            setEditForm((s) => ({
                              ...s,
                              pay_date: e.target.value,
                            }))
                          }
                          data-testid={`pay-period-edit-pay-date-${p.id}`}
                          className="rounded-ctl border border-border bg-card px-2 py-1 text-sm text-text"
                        />
                      ) : (
                        formatDate(p?.pay_date)
                      )}
                    </td>
                    <td
                      className="px-4 py-2 text-muted"
                      data-testid={`pay-period-cycle-${p?.id ?? ''}`}
                    >
                      {p?.pay_cycle_name ?? '—'}
                    </td>
                    <td className="px-4 py-2">
                      {isEditing ? (
                        <select
                          value={editForm.status}
                          onChange={(e) =>
                            setEditForm((s) => ({
                              ...s,
                              status: e.target.value as PayPeriodStatus,
                            }))
                          }
                          data-testid={`pay-period-edit-status-${p.id}`}
                          className="rounded-ctl border border-border bg-card px-2 py-1 text-sm text-text"
                        >
                          {STATUSES.map((s) => (
                            <option key={s} value={s}>
                              {s}
                            </option>
                          ))}
                        </select>
                      ) : (
                        <Badge variant={statusVariant(status)}>{status}</Badge>
                      )}
                    </td>
                    <td className="px-4 py-2 text-right">
                      <div className="flex flex-wrap items-center justify-end gap-2">
                        {isEditing ? (
                          <>
                            <Button
                              size="sm"
                              variant="primary"
                              onClick={() => submitEdit(p)}
                              loading={editBusy}
                              disabled={editBusy}
                              data-testid={`pay-period-edit-save-${p.id}`}
                            >
                              Save
                            </Button>
                            <Button
                              size="sm"
                              variant="ghost"
                              onClick={cancelEdit}
                              disabled={editBusy}
                            >
                              Cancel
                            </Button>
                          </>
                        ) : (
                          <Button
                            size="sm"
                            variant="ghost"
                            onClick={() => startEdit(p)}
                            data-testid={`pay-period-edit-${p.id}`}
                          >
                            Edit
                          </Button>
                        )}
                        {/* Reopen button — visible only for finalised /
                            paid (paid is shown disabled with tooltip). */}
                        {isFinalised && (
                          <Button
                            size="sm"
                            variant="ghost"
                            onClick={() => openReopen(p)}
                            data-testid={`pay-period-reopen-${p.id}`}
                          >
                            Reopen
                          </Button>
                        )}
                        {isPaid && (
                          <span
                            title="Already paid — contact support"
                            data-testid={`pay-period-reopen-disabled-${p.id}`}
                          >
                            <Button size="sm" variant="ghost" disabled>
                              Reopen
                            </Button>
                          </span>
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
      )}

      {/* Create modal */}
      <Modal
        open={createState.open}
        onClose={createState.busy ? () => undefined : closeCreate}
        title="Add pay period"
      >
        <div className="space-y-4">
          <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
            <label className="block">
              <span className="block text-sm font-medium text-text">
                Start date
              </span>
              <input
                type="date"
                value={createState.start_date}
                onChange={(e) =>
                  setCreateState((s) => ({
                    ...s,
                    start_date: e.target.value,
                  }))
                }
                data-testid="pay-period-create-start"
                className="mt-1 block w-full rounded-ctl border border-border bg-card px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-accent"
              />
            </label>
            <label className="block">
              <span className="block text-sm font-medium text-text">
                End date
              </span>
              <input
                type="date"
                value={createState.end_date}
                onChange={(e) =>
                  setCreateState((s) => ({
                    ...s,
                    end_date: e.target.value,
                  }))
                }
                data-testid="pay-period-create-end"
                className="mt-1 block w-full rounded-ctl border border-border bg-card px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-accent"
              />
            </label>
          </div>
          <label className="block">
            <span className="block text-sm font-medium text-text">
              Pay date
            </span>
            <input
              type="date"
              value={createState.pay_date}
              onChange={(e) =>
                setCreateState((s) => ({
                  ...s,
                  pay_date: e.target.value,
                }))
              }
              data-testid="pay-period-create-pay-date"
              className="mt-1 block w-full rounded-ctl border border-border bg-card px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-accent"
            />
          </label>
          {createState.error && (
            <AlertBanner variant="error">{createState.error}</AlertBanner>
          )}
          <div className="flex justify-end gap-2">
            <Button
              variant="ghost"
              onClick={closeCreate}
              disabled={createState.busy}
            >
              Cancel
            </Button>
            <Button
              variant="primary"
              onClick={submitCreate}
              loading={createState.busy}
              disabled={!canSubmitCreate}
              data-testid="pay-period-create-submit"
            >
              Create
            </Button>
          </div>
        </div>
      </Modal>

      {/* Reopen modal (G21) */}
      <Modal
        open={reopenState.open}
        onClose={reopenState.busy ? () => undefined : closeReopen}
        title="Reopen pay period"
      >
        <div className="space-y-4">
          <p className="text-sm text-text">
            Reopening unlocks this period for new draft payslips that sit
            alongside the existing finalised ones. Existing finalised
            payslips remain locked.
          </p>
          <label className="block">
            <span className="block text-sm font-medium text-text">
              Reason
            </span>
            <textarea
              value={reopenState.reason}
              onChange={(e) =>
                setReopenState((s) => ({ ...s, reason: e.target.value }))
              }
              rows={3}
              placeholder="e.g. correction for missed timesheet approval"
              data-testid="pay-period-reopen-reason"
              className="mt-1 block w-full rounded-ctl border border-border bg-card px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-accent"
            />
          </label>
          {reopenState.error && (
            <AlertBanner variant="error">{reopenState.error}</AlertBanner>
          )}
          <div className="flex justify-end gap-2">
            <Button
              variant="ghost"
              onClick={closeReopen}
              disabled={reopenState.busy}
            >
              Cancel
            </Button>
            <Button
              variant="primary"
              onClick={submitReopen}
              loading={reopenState.busy}
              disabled={
                reopenState.busy ||
                reopenState.reason.trim().length === 0
              }
              data-testid="pay-period-reopen-submit"
            >
              Reopen
            </Button>
          </div>
        </div>
      </Modal>
    </div>
  )
}
