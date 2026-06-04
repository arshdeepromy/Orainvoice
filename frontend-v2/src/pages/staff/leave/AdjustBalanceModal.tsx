/**
 * AdjustBalanceModal — admin-only manual balance adjustment.
 *
 * Posts to `POST /api/v2/staff/:id/leave/balances/:type_id/adjust` and
 * writes a `manual_adjustment` ledger row. Delta hours can be negative
 * (e.g., correcting an over-accrual from a legacy import).
 *
 * Auth scope is enforced by the caller (LeaveTab only renders the
 * "Adjust balance" button for admins) AND by the backend (router uses
 * `RequireOrgAdmin`).
 *
 * Presentation remapped onto the design-system tokens. Logic, handlers
 * and every data-testid preserved verbatim.
 *
 * **Validates: Staff Management Phase 2 task D3**
 */

import { useEffect, useMemo, useState } from 'react'
import axios from 'axios'

import { adjustLeaveBalance } from '@/api/leave'
import type { LeaveBalance, LeaveType } from '@/api/leave'

interface Props {
  staffId: string
  leaveTypes: LeaveType[]
  balances: LeaveBalance[]
  onClose: () => void
  onAdjusted: () => void
}

interface FormState {
  leaveTypeId: string
  deltaHours: string
  reason: string
  notes: string
}

const EMPTY: FormState = {
  leaveTypeId: '',
  deltaHours: '',
  reason: '',
  notes: '',
}

function extractError(err: unknown): string {
  if (axios.isAxiosError(err)) {
    const detail = err.response?.data?.detail
    if (typeof detail === 'string') return detail
    if (
      detail &&
      typeof detail === 'object' &&
      'reason' in detail &&
      typeof (detail as { reason?: unknown }).reason === 'string'
    ) {
      return (detail as { reason: string }).reason
    }
    if (err.message) return err.message
  }
  if (err instanceof Error && err.message) return err.message
  return 'Failed to save adjustment'
}

export default function AdjustBalanceModal({
  staffId,
  leaveTypes,
  balances,
  onClose,
  onAdjusted,
}: Props) {
  const [form, setForm] = useState<FormState>(EMPTY)
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState<string | null>(null)

  // Default to the first available leave type — only those with a balance
  // row are actually adjustable since `adjust_balance` joins on the
  // (staff_id, leave_type_id) balance row.
  const adjustableTypes = useMemo<LeaveType[]>(() => {
    const balanceTypeIds = new Set((balances ?? []).map((b) => b.leave_type_id))
    return (leaveTypes ?? []).filter(
      (lt) => lt.active && balanceTypeIds.has(lt.id),
    )
  }, [leaveTypes, balances])

  useEffect(() => {
    if (!form.leaveTypeId && adjustableTypes.length > 0) {
      setForm((f) => ({ ...f, leaveTypeId: adjustableTypes[0].id }))
    }
  }, [adjustableTypes, form.leaveTypeId])

  const update = <K extends keyof FormState>(key: K, value: FormState[K]) => {
    setForm((prev) => ({ ...prev, [key]: value }))
  }

  const canSubmit =
    !!form.leaveTypeId &&
    form.deltaHours.trim() !== '' &&
    !Number.isNaN(parseFloat(form.deltaHours)) &&
    form.reason.trim().length > 0

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault()
    if (!canSubmit || saving) return
    setSaving(true)
    setError(null)
    try {
      const controller = new AbortController()
      // The backend expects delta_hours as a decimal string.
      const deltaNum = parseFloat(form.deltaHours)
      await adjustLeaveBalance(
        staffId,
        form.leaveTypeId,
        {
          staff_id: staffId,
          leave_type_id: form.leaveTypeId,
          delta_hours: deltaNum.toFixed(2),
          reason: form.reason.trim(),
          notes: form.notes.trim() || null,
        },
        controller.signal,
      )
      onAdjusted()
      onClose()
    } catch (err) {
      setError(extractError(err))
    } finally {
      setSaving(false)
    }
  }

  return (
    <div
      role="dialog"
      aria-modal="true"
      aria-labelledby="adjust-balance-title"
      data-testid="adjust-balance-modal"
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/50 p-4"
    >
      <div className="bg-card rounded-card shadow-pop w-full max-w-md max-h-[90vh] overflow-hidden flex flex-col">
        <header className="flex items-center justify-between px-6 py-4 border-b border-border">
          <h2
            id="adjust-balance-title"
            className="text-lg font-semibold text-text"
          >
            Adjust leave balance
          </h2>
          <button
            type="button"
            onClick={onClose}
            disabled={saving}
            aria-label="Close dialog"
            className="rounded-ctl p-1 text-muted-2 hover:text-text focus:outline-none focus:shadow-[0_0_0_3px_var(--accent-soft)] disabled:opacity-50"
          >
            <span aria-hidden="true" className="text-xl leading-none">
              ×
            </span>
          </button>
        </header>

        <form
          onSubmit={handleSubmit}
          className="flex-1 overflow-y-auto px-6 py-4 space-y-4"
        >
          {error && (
            <div
              role="alert"
              data-testid="adjust-balance-error"
              className="rounded-ctl bg-danger-soft border border-danger/30 px-4 py-3 text-sm text-danger"
            >
              {error}
            </div>
          )}

          <div>
            <label
              htmlFor="adjust-leave-type"
              className="block text-sm font-medium text-text mb-1"
            >
              Leave type
            </label>
            <select
              id="adjust-leave-type"
              value={form.leaveTypeId}
              onChange={(e) => update('leaveTypeId', e.target.value)}
              disabled={saving || adjustableTypes.length === 0}
              className="h-[42px] w-full rounded-ctl border border-border bg-card px-[13px] text-[13.5px] text-text focus:border-accent focus:outline-none focus:shadow-[0_0_0_3px_var(--accent-soft)]"
            >
              {adjustableTypes.length === 0 ? (
                <option value="">No leave types with a balance</option>
              ) : (
                adjustableTypes.map((lt) => (
                  <option key={lt.id} value={lt.id}>
                    {lt.name}
                  </option>
                ))
              )}
            </select>
          </div>

          <div>
            <label
              htmlFor="adjust-delta-hours"
              className="block text-sm font-medium text-text mb-1"
            >
              Delta hours
              <span className="ml-1 text-muted font-normal">
                (positive credits, negative debits)
              </span>
            </label>
            <input
              id="adjust-delta-hours"
              type="number"
              step="0.25"
              value={form.deltaHours}
              onChange={(e) => update('deltaHours', e.target.value)}
              disabled={saving}
              placeholder="e.g. 8 or -4"
              className="mono h-[42px] w-full rounded-ctl border border-border bg-card px-[13px] text-[13.5px] text-text focus:border-accent focus:outline-none focus:shadow-[0_0_0_3px_var(--accent-soft)]"
            />
          </div>

          <div>
            <label
              htmlFor="adjust-reason"
              className="block text-sm font-medium text-text mb-1"
            >
              Reason
              <span className="ml-1 text-danger">*</span>
            </label>
            <input
              id="adjust-reason"
              type="text"
              value={form.reason}
              onChange={(e) => update('reason', e.target.value)}
              disabled={saving}
              maxLength={120}
              placeholder='e.g. "Pre-funded for July trip"'
              className="h-[42px] w-full rounded-ctl border border-border bg-card px-[13px] text-[13.5px] text-text focus:border-accent focus:outline-none focus:shadow-[0_0_0_3px_var(--accent-soft)]"
            />
          </div>

          <div>
            <label
              htmlFor="adjust-notes"
              className="block text-sm font-medium text-text mb-1"
            >
              Notes
              <span className="ml-1 text-muted font-normal">
                (optional)
              </span>
            </label>
            <textarea
              id="adjust-notes"
              value={form.notes}
              onChange={(e) => update('notes', e.target.value)}
              disabled={saving}
              rows={3}
              className="w-full rounded-ctl border border-border bg-card px-[13px] py-2 text-[13.5px] text-text focus:border-accent focus:outline-none focus:shadow-[0_0_0_3px_var(--accent-soft)]"
            />
          </div>
        </form>

        <footer className="flex items-center justify-end gap-2 border-t border-border px-6 py-3">
          <button
            type="button"
            onClick={onClose}
            disabled={saving}
            className="px-4 py-2 min-h-[44px] rounded-ctl border border-border text-sm font-medium text-text hover:bg-canvas disabled:opacity-50"
          >
            Cancel
          </button>
          <button
            type="button"
            onClick={handleSubmit}
            disabled={!canSubmit || saving}
            className="px-4 py-2 min-h-[44px] rounded-ctl bg-accent text-white text-sm font-medium hover:bg-accent-press disabled:opacity-50"
          >
            {saving ? 'Saving…' : 'Save adjustment'}
          </button>
        </footer>
      </div>
    </div>
  )
}
