/**
 * LeaveTypesPage — Settings → People → Leave Types.
 *
 * Lists every leave type for the current org sorted by display_order.
 * Statutory rows render with a "Statutory" badge and the Deactivate
 * button is disabled (statutory delete is blocked by the backend; see
 * design §3 / `delete_leave_type`). Custom rows can be deactivated via
 * an `update` PATCH that sets `active=false`.
 *
 * "Above legal minimum" badge: applied to rows whose code matches a
 * known statutory floor (sick = 80h/year, family_violence = 80h/year)
 * AND whose configured `accrual_amount` exceeds that floor — i.e. the
 * org has chosen to be more generous than the Holidays Act 2003 minimum.
 *
 * **Validates: Staff Management Phase 2 task D7**
 */

import { useCallback, useEffect, useMemo, useState } from 'react'
import axios from 'axios'

import {
  createLeaveType,
  listLeaveTypes,
  updateLeaveType,
  type AccrualMethod,
  type AccrualUnit,
  type LeaveType,
  type LeaveTypeCreatePayload,
  type LeaveTypeUpdatePayload,
} from '../../../api/leave'
import { Badge, Button, Modal, Spinner } from '../../../components/ui'

/**
 * Statutory accrual floors (Holidays Act 2003 + Domestic Violence —
 * Victims' Protection Act 2018). Used to decide when a leave type is
 * configured above the legal minimum.
 */
const STATUTORY_MINIMUMS: Record<string, { amount: number; unit: AccrualUnit }> = {
  sick: { amount: 80, unit: 'hours' },
  family_violence: { amount: 80, unit: 'hours' },
}

const ACCRUAL_METHODS: { value: AccrualMethod; label: string }[] = [
  { value: 'anniversary', label: 'Anniversary' },
  { value: 'fixed_annual', label: 'Fixed annual' },
  { value: 'per_period', label: 'Per period' },
  { value: 'unaccrued', label: 'Unaccrued' },
  { value: 'event_based', label: 'Event based' },
]

const ACCRUAL_UNITS: { value: AccrualUnit; label: string }[] = [
  { value: 'hours', label: 'Hours' },
  { value: 'days', label: 'Days' },
]

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
      const inner = detail as { reason?: string; detail?: string }
      if (typeof inner.reason === 'string') return inner.reason
      if (typeof inner.detail === 'string') return inner.detail
    }
    if (err.message) return err.message
  }
  if (err instanceof Error && err.message) return err.message
  return 'Action failed'
}

function formatAmount(amount: string | null | undefined, unit: AccrualUnit): string {
  if (amount == null || amount === '') return '—'
  const n = parseFloat(amount)
  if (Number.isNaN(n)) return amount
  const rounded = Math.round(n * 100) / 100
  const display = Number.isInteger(rounded) ? `${rounded}` : rounded.toString()
  return `${display} ${unit}`
}

function isAboveLegalMinimum(lt: LeaveType): boolean {
  const floor = STATUTORY_MINIMUMS[lt.code]
  if (!floor) return false
  if (lt.accrual_unit !== floor.unit) return false
  const amount = parseFloat(lt.accrual_amount ?? '')
  if (Number.isNaN(amount)) return false
  return amount > floor.amount
}

function formatMethod(method: AccrualMethod | string): string {
  const found = ACCRUAL_METHODS.find((m) => m.value === method)
  return found?.label ?? method
}

interface FormState {
  code: string
  name: string
  is_paid: boolean
  accrual_method: AccrualMethod
  accrual_amount: string
  accrual_unit: AccrualUnit
  carry_over_max: string
  requires_doctor_note: boolean
  confidential_visibility: boolean
  active: boolean
  display_order: string
}

const EMPTY_FORM: FormState = {
  code: '',
  name: '',
  is_paid: true,
  accrual_method: 'fixed_annual',
  accrual_amount: '',
  accrual_unit: 'hours',
  carry_over_max: '',
  requires_doctor_note: false,
  confidential_visibility: false,
  active: true,
  display_order: '0',
}

function fromLeaveType(lt: LeaveType): FormState {
  return {
    code: lt.code ?? '',
    name: lt.name ?? '',
    is_paid: lt.is_paid ?? true,
    accrual_method: lt.accrual_method,
    accrual_amount: lt.accrual_amount ?? '',
    accrual_unit: lt.accrual_unit ?? 'hours',
    carry_over_max: lt.carry_over_max ?? '',
    requires_doctor_note: lt.requires_doctor_note ?? false,
    confidential_visibility: lt.confidential_visibility ?? false,
    active: lt.active ?? true,
    display_order: String(lt.display_order ?? 0),
  }
}

function toCreatePayload(form: FormState): LeaveTypeCreatePayload {
  return {
    code: form.code.trim(),
    name: form.name.trim(),
    is_paid: form.is_paid,
    accrual_method: form.accrual_method,
    accrual_amount:
      form.accrual_amount.trim() === '' ? null : form.accrual_amount.trim(),
    accrual_unit: form.accrual_unit,
    carry_over_max:
      form.carry_over_max.trim() === '' ? null : form.carry_over_max.trim(),
    requires_doctor_note: form.requires_doctor_note,
    confidential_visibility: form.confidential_visibility,
    active: form.active,
    display_order: parseInt(form.display_order, 10) || 0,
  }
}

function toUpdatePayload(form: FormState): LeaveTypeUpdatePayload {
  return toCreatePayload(form)
}

interface EditModalState {
  open: boolean
  mode: 'create' | 'edit'
  target: LeaveType | null
  form: FormState
  submitting: boolean
  error: string | null
}

const EMPTY_EDIT: EditModalState = {
  open: false,
  mode: 'create',
  target: null,
  form: EMPTY_FORM,
  submitting: false,
  error: null,
}

export default function LeaveTypesPage() {
  const [items, setItems] = useState<LeaveType[]>([])
  const [loading, setLoading] = useState<boolean>(true)
  const [error, setError] = useState<string | null>(null)
  const [refreshKey, setRefreshKey] = useState<number>(0)
  const [busyId, setBusyId] = useState<string | null>(null)
  const [rowError, setRowError] = useState<{ id: string; message: string } | null>(null)
  const [edit, setEdit] = useState<EditModalState>(EMPTY_EDIT)

  const refresh = useCallback(() => setRefreshKey((k) => k + 1), [])

  useEffect(() => {
    const controller = new AbortController()
    let cancelled = false
    const load = async () => {
      setLoading(true)
      setError(null)
      try {
        const res = await listLeaveTypes(
          { include_inactive: true, limit: 200 },
          controller.signal,
        )
        if (cancelled || controller.signal.aborted) return
        setItems(res.items ?? [])
      } catch (err) {
        if (cancelled || controller.signal.aborted || isAbortError(err)) return
        setError(extractError(err) || 'Failed to load leave types')
      } finally {
        if (!cancelled && !controller.signal.aborted) setLoading(false)
      }
    }
    void load()
    return () => {
      cancelled = true
      controller.abort()
    }
  }, [refreshKey])

  const sortedItems = useMemo(() => {
    return [...(items ?? [])].sort(
      (a, b) => (a.display_order ?? 0) - (b.display_order ?? 0),
    )
  }, [items])

  const openCreate = useCallback(() => {
    setEdit({
      open: true,
      mode: 'create',
      target: null,
      form: EMPTY_FORM,
      submitting: false,
      error: null,
    })
  }, [])

  const openEdit = useCallback((lt: LeaveType) => {
    setEdit({
      open: true,
      mode: 'edit',
      target: lt,
      form: fromLeaveType(lt),
      submitting: false,
      error: null,
    })
  }, [])

  const closeEdit = useCallback(() => setEdit(EMPTY_EDIT), [])

  const submitEdit = useCallback(async () => {
    setEdit((s) => ({ ...s, submitting: true, error: null }))
    try {
      if (edit.mode === 'create') {
        await createLeaveType(toCreatePayload(edit.form))
      } else if (edit.target) {
        await updateLeaveType(edit.target.id, toUpdatePayload(edit.form))
      }
      setEdit(EMPTY_EDIT)
      refresh()
    } catch (err) {
      setEdit((s) => ({
        ...s,
        submitting: false,
        error: extractError(err) || 'Save failed',
      }))
    }
  }, [edit, refresh])

  const handleDeactivate = useCallback(
    async (lt: LeaveType) => {
      if (lt.is_statutory) return
      setBusyId(lt.id)
      setRowError(null)
      try {
        await updateLeaveType(lt.id, { active: false })
        refresh()
      } catch (err) {
        setRowError({ id: lt.id, message: extractError(err) || 'Failed to deactivate' })
      } finally {
        setBusyId(null)
      }
    },
    [refresh],
  )

  const handleReactivate = useCallback(
    async (lt: LeaveType) => {
      setBusyId(lt.id)
      setRowError(null)
      try {
        await updateLeaveType(lt.id, { active: true })
        refresh()
      } catch (err) {
        setRowError({ id: lt.id, message: extractError(err) || 'Failed to reactivate' })
      } finally {
        setBusyId(null)
      }
    },
    [refresh],
  )

  return (
    <div className="space-y-4" data-testid="leave-types-page">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <h1 className="text-xl font-semibold text-gray-900 dark:text-gray-100">
            Leave types
          </h1>
          <p className="text-sm text-gray-500 dark:text-gray-400">
            Configure leave categories, statutory floors, and carry-over caps.
          </p>
        </div>
        <Button size="sm" onClick={openCreate} data-testid="leave-types-add">
          Add custom leave type
        </Button>
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
          <Spinner size="lg" label="Loading leave types" />
        </div>
      ) : sortedItems.length === 0 ? (
        <div className="rounded-lg border border-dashed border-gray-300 dark:border-gray-700 bg-white dark:bg-gray-900 px-6 py-12 text-center text-sm text-gray-500 dark:text-gray-400">
          No leave types configured yet.
        </div>
      ) : (
        <div className="overflow-x-auto rounded-lg border border-gray-200 dark:border-gray-700 bg-white dark:bg-gray-900">
          <table className="min-w-full divide-y divide-gray-200 dark:divide-gray-700 text-sm">
            <thead className="bg-gray-50 dark:bg-gray-800/40">
              <tr className="text-left text-xs uppercase tracking-wider text-gray-500 dark:text-gray-400">
                <th scope="col" className="px-4 py-2 font-medium">Code</th>
                <th scope="col" className="px-4 py-2 font-medium">Name</th>
                <th scope="col" className="px-4 py-2 font-medium">Paid</th>
                <th scope="col" className="px-4 py-2 font-medium">Statutory</th>
                <th scope="col" className="px-4 py-2 font-medium">Accrual method</th>
                <th scope="col" className="px-4 py-2 font-medium">Amount</th>
                <th scope="col" className="px-4 py-2 font-medium">Active</th>
                <th scope="col" className="px-4 py-2 font-medium text-right">Actions</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-gray-100 dark:divide-gray-800">
              {sortedItems.map((lt) => {
                const aboveMin = isAboveLegalMinimum(lt)
                const isBusy = busyId === lt.id
                const errMessage =
                  rowError && rowError.id === lt.id ? rowError.message : null
                return (
                  <tr
                    key={lt.id}
                    data-testid={`leave-type-row-${lt.id}`}
                    className="hover:bg-gray-50 dark:hover:bg-gray-800/40"
                  >
                    <td className="px-4 py-2 whitespace-nowrap font-mono text-xs text-gray-700 dark:text-gray-200">
                      {lt.code}
                    </td>
                    <td className="px-4 py-2 whitespace-nowrap text-gray-700 dark:text-gray-200">
                      <div className="flex items-center gap-2">
                        <span>{lt.name}</span>
                        {aboveMin && (
                          <Badge
                            variant="success"
                            data-testid={`above-min-${lt.id}`}
                          >
                            Above legal minimum
                          </Badge>
                        )}
                      </div>
                    </td>
                    <td className="px-4 py-2 whitespace-nowrap text-gray-700 dark:text-gray-200">
                      {lt.is_paid ? 'Yes' : 'No'}
                    </td>
                    <td className="px-4 py-2 whitespace-nowrap">
                      {lt.is_statutory ? (
                        <Badge variant="info">Statutory</Badge>
                      ) : (
                        <span className="text-xs text-gray-400 dark:text-gray-500">—</span>
                      )}
                    </td>
                    <td className="px-4 py-2 whitespace-nowrap text-gray-700 dark:text-gray-200">
                      {formatMethod(lt.accrual_method)}
                    </td>
                    <td className="px-4 py-2 whitespace-nowrap text-gray-700 dark:text-gray-200">
                      {formatAmount(lt.accrual_amount, lt.accrual_unit)}
                    </td>
                    <td className="px-4 py-2 whitespace-nowrap">
                      {lt.active ? (
                        <Badge variant="success">Active</Badge>
                      ) : (
                        <Badge variant="neutral">Inactive</Badge>
                      )}
                    </td>
                    <td className="px-4 py-2 whitespace-nowrap text-right">
                      <div className="flex items-center justify-end gap-2">
                        <Button
                          size="sm"
                          variant="secondary"
                          data-testid={`leave-type-edit-${lt.id}`}
                          onClick={() => openEdit(lt)}
                          disabled={isBusy}
                        >
                          Edit
                        </Button>
                        {lt.active ? (
                          <Button
                            size="sm"
                            variant="secondary"
                            data-testid={`leave-type-deactivate-${lt.id}`}
                            onClick={() => handleDeactivate(lt)}
                            disabled={lt.is_statutory || isBusy}
                            title={
                              lt.is_statutory
                                ? 'Statutory leave types cannot be deactivated.'
                                : undefined
                            }
                            loading={isBusy}
                          >
                            Deactivate
                          </Button>
                        ) : (
                          <Button
                            size="sm"
                            variant="secondary"
                            data-testid={`leave-type-reactivate-${lt.id}`}
                            onClick={() => handleReactivate(lt)}
                            disabled={isBusy}
                            loading={isBusy}
                          >
                            Reactivate
                          </Button>
                        )}
                      </div>
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

      <EditLeaveTypeModal
        state={edit}
        onChange={(form) => setEdit((s) => ({ ...s, form }))}
        onClose={closeEdit}
        onSubmit={submitEdit}
      />
    </div>
  )
}

interface EditLeaveTypeModalProps {
  state: EditModalState
  onChange: (form: FormState) => void
  onClose: () => void
  onSubmit: () => void
}

/** Editor modal — covers both create + edit modes. */
function EditLeaveTypeModal({
  state,
  onChange,
  onClose,
  onSubmit,
}: EditLeaveTypeModalProps) {
  const isStatutory = state.target?.is_statutory ?? false
  return (
    <Modal
      open={state.open}
      onClose={onClose}
      title={state.mode === 'create' ? 'Add leave type' : 'Edit leave type'}
    >
      <div className="space-y-3">
        <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
          <label className="block text-sm font-medium text-gray-700 dark:text-gray-200">
            Code
            <input
              type="text"
              data-testid="lt-form-code"
              value={state.form.code}
              onChange={(e) =>
                onChange({ ...state.form, code: e.target.value })
              }
              disabled={state.mode === 'edit'}
              className="mt-1 w-full rounded-md border border-gray-300 dark:border-gray-600 bg-white dark:bg-gray-900 px-3 py-2 text-sm text-gray-900 dark:text-gray-100 focus:outline-none focus:ring-2 focus:ring-blue-500 disabled:opacity-60"
            />
          </label>
          <label className="block text-sm font-medium text-gray-700 dark:text-gray-200">
            Name
            <input
              type="text"
              data-testid="lt-form-name"
              value={state.form.name}
              onChange={(e) =>
                onChange({ ...state.form, name: e.target.value })
              }
              className="mt-1 w-full rounded-md border border-gray-300 dark:border-gray-600 bg-white dark:bg-gray-900 px-3 py-2 text-sm text-gray-900 dark:text-gray-100 focus:outline-none focus:ring-2 focus:ring-blue-500"
            />
          </label>
        </div>

        <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
          <label className="block text-sm font-medium text-gray-700 dark:text-gray-200">
            Accrual method
            <select
              value={state.form.accrual_method}
              onChange={(e) =>
                onChange({
                  ...state.form,
                  accrual_method: e.target.value as AccrualMethod,
                })
              }
              className="mt-1 w-full rounded-md border border-gray-300 dark:border-gray-600 bg-white dark:bg-gray-900 px-3 py-2 text-sm text-gray-900 dark:text-gray-100 focus:outline-none focus:ring-2 focus:ring-blue-500"
            >
              {ACCRUAL_METHODS.map((m) => (
                <option key={m.value} value={m.value}>
                  {m.label}
                </option>
              ))}
            </select>
          </label>
          <label className="block text-sm font-medium text-gray-700 dark:text-gray-200">
            Unit
            <select
              value={state.form.accrual_unit}
              onChange={(e) =>
                onChange({
                  ...state.form,
                  accrual_unit: e.target.value as AccrualUnit,
                })
              }
              className="mt-1 w-full rounded-md border border-gray-300 dark:border-gray-600 bg-white dark:bg-gray-900 px-3 py-2 text-sm text-gray-900 dark:text-gray-100 focus:outline-none focus:ring-2 focus:ring-blue-500"
            >
              {ACCRUAL_UNITS.map((u) => (
                <option key={u.value} value={u.value}>
                  {u.label}
                </option>
              ))}
            </select>
          </label>
        </div>

        <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
          <label className="block text-sm font-medium text-gray-700 dark:text-gray-200">
            Accrual amount
            <input
              type="number"
              step="0.01"
              min="0"
              value={state.form.accrual_amount}
              onChange={(e) =>
                onChange({ ...state.form, accrual_amount: e.target.value })
              }
              className="mt-1 w-full rounded-md border border-gray-300 dark:border-gray-600 bg-white dark:bg-gray-900 px-3 py-2 text-sm text-gray-900 dark:text-gray-100 focus:outline-none focus:ring-2 focus:ring-blue-500"
            />
          </label>
          <label className="block text-sm font-medium text-gray-700 dark:text-gray-200">
            Carry-over max
            <input
              type="number"
              step="0.01"
              min="0"
              value={state.form.carry_over_max}
              onChange={(e) =>
                onChange({ ...state.form, carry_over_max: e.target.value })
              }
              className="mt-1 w-full rounded-md border border-gray-300 dark:border-gray-600 bg-white dark:bg-gray-900 px-3 py-2 text-sm text-gray-900 dark:text-gray-100 focus:outline-none focus:ring-2 focus:ring-blue-500"
            />
          </label>
        </div>

        <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
          <label className="flex items-center gap-2 text-sm text-gray-700 dark:text-gray-200">
            <input
              type="checkbox"
              checked={state.form.is_paid}
              onChange={(e) =>
                onChange({ ...state.form, is_paid: e.target.checked })
              }
            />
            Paid leave
          </label>
          <label className="flex items-center gap-2 text-sm text-gray-700 dark:text-gray-200">
            <input
              type="checkbox"
              checked={state.form.requires_doctor_note}
              onChange={(e) =>
                onChange({
                  ...state.form,
                  requires_doctor_note: e.target.checked,
                })
              }
            />
            Requires doctor's note
          </label>
          <label className="flex items-center gap-2 text-sm text-gray-700 dark:text-gray-200">
            <input
              type="checkbox"
              checked={state.form.confidential_visibility}
              onChange={(e) =>
                onChange({
                  ...state.form,
                  confidential_visibility: e.target.checked,
                })
              }
            />
            Confidential visibility
          </label>
          <label className="flex items-center gap-2 text-sm text-gray-700 dark:text-gray-200">
            <input
              type="checkbox"
              checked={state.form.active}
              onChange={(e) =>
                onChange({ ...state.form, active: e.target.checked })
              }
              disabled={isStatutory}
              title={
                isStatutory
                  ? 'Statutory leave types cannot be deactivated.'
                  : undefined
              }
            />
            Active
          </label>
          <label className="block text-sm font-medium text-gray-700 dark:text-gray-200">
            Display order
            <input
              type="number"
              step="1"
              min="0"
              value={state.form.display_order}
              onChange={(e) =>
                onChange({ ...state.form, display_order: e.target.value })
              }
              className="mt-1 w-full rounded-md border border-gray-300 dark:border-gray-600 bg-white dark:bg-gray-900 px-3 py-2 text-sm text-gray-900 dark:text-gray-100 focus:outline-none focus:ring-2 focus:ring-blue-500"
            />
          </label>
        </div>

        {state.error && (
          <div
            role="alert"
            className="rounded-md border border-red-200 dark:border-red-800 bg-red-50 dark:bg-red-900/20 px-3 py-2 text-xs text-red-700 dark:text-red-300"
          >
            {state.error}
          </div>
        )}

        <div className="flex justify-end gap-2 pt-2">
          <Button
            size="sm"
            variant="secondary"
            onClick={onClose}
            disabled={state.submitting}
          >
            Cancel
          </Button>
          <Button
            size="sm"
            data-testid="lt-form-submit"
            onClick={onSubmit}
            loading={state.submitting}
            disabled={state.submitting}
          >
            {state.mode === 'create' ? 'Create' : 'Save'}
          </Button>
        </div>
      </div>
    </Modal>
  )
}
