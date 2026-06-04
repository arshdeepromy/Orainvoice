/**
 * AllowanceTypesPage — Settings → People → Allowance Types
 * (Phase 4 task D5).
 *
 * Per design.md §6.5 + R2:
 *   - List allowance types (`listAllowanceTypes({ include_inactive })`).
 *   - Create modal (code, name, taxable, default_amount, unit,
 *     display_order).
 *   - Edit-in-place via PATCH (`updateAllowanceType`).
 *   - "Deactivate" toggles `active=false` via `deactivateAllowanceType`.
 *   - Sortable by display_order (rendered ascending).
 *
 * Conventions:
 *   - Typed client only (`frontend/src/api/payslips.ts`).
 *   - All API responses consumed with `?.` + `?? []` / `?? null`.
 *   - Decimal `default_amount` is sent and received as a string.
 *
 * **Validates: Staff Management Phase 4 task D5, R2**
 */

import { useCallback, useEffect, useMemo, useState } from 'react'
import { Badge, Button, Modal, Spinner, AlertBanner } from '@/components/ui'
import {
  createAllowanceType,
  deactivateAllowanceType,
  listAllowanceTypes,
  updateAllowanceType,
} from '@/api/payslips'
import type {
  AllowanceType,
  AllowanceTypeCreatePayload,
  AllowanceTypeUpdatePayload,
  AllowanceUnit,
} from '@/api/payslips'

const UNITS: AllowanceUnit[] = ['shift', 'period', 'km']

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

function formatAmount(value: string | null | undefined): string {
  if (value == null || value === '') return '—'
  const n = Number(value)
  if (!Number.isFinite(n)) return value
  return n.toFixed(2)
}

interface FormState {
  code: string
  name: string
  taxable: boolean
  default_amount: string
  unit: AllowanceUnit
  display_order: string
  active: boolean
}

const EMPTY_FORM: FormState = {
  code: '',
  name: '',
  taxable: true,
  default_amount: '',
  unit: 'shift',
  display_order: '0',
  active: true,
}

function fromAllowanceType(t: AllowanceType): FormState {
  return {
    code: t.code ?? '',
    name: t.name ?? '',
    taxable: t.taxable ?? true,
    default_amount: t.default_amount ?? '',
    unit: ((t.unit ?? 'shift') as AllowanceUnit),
    display_order: String(t.display_order ?? 0),
    active: t.active ?? true,
  }
}

function toCreatePayload(form: FormState): AllowanceTypeCreatePayload {
  return {
    code: form.code.trim(),
    name: form.name.trim(),
    taxable: form.taxable,
    default_amount:
      form.default_amount.trim() === '' ? null : form.default_amount.trim(),
    unit: form.unit,
    active: form.active,
    display_order: parseInt(form.display_order, 10) || 0,
  }
}

function toUpdatePayload(form: FormState): AllowanceTypeUpdatePayload {
  return {
    name: form.name.trim(),
    taxable: form.taxable,
    default_amount:
      form.default_amount.trim() === '' ? null : form.default_amount.trim(),
    unit: form.unit,
    active: form.active,
    display_order: parseInt(form.display_order, 10) || 0,
  }
}

interface ModalState {
  open: boolean
  mode: 'create' | 'edit'
  target: AllowanceType | null
  form: FormState
  busy: boolean
  error: string | null
}

const EMPTY_MODAL: ModalState = {
  open: false,
  mode: 'create',
  target: null,
  form: EMPTY_FORM,
  busy: false,
  error: null,
}

export default function AllowanceTypesPage() {
  const [items, setItems] = useState<AllowanceType[]>([])
  const [loading, setLoading] = useState<boolean>(true)
  const [loadError, setLoadError] = useState<string | null>(null)
  const [refreshTick, setRefreshTick] = useState<number>(0)

  const [showInactive, setShowInactive] = useState<boolean>(false)
  const [modal, setModal] = useState<ModalState>(EMPTY_MODAL)

  const [busyId, setBusyId] = useState<string | null>(null)
  const [rowError, setRowError] = useState<{
    id: string
    message: string
  } | null>(null)

  const refresh = useCallback(() => setRefreshTick((t) => t + 1), [])

  // ── Load allowance types ──
  useEffect(() => {
    const controller = new AbortController()
    setLoading(true)
    setLoadError(null)
    ;(async () => {
      try {
        const res = await listAllowanceTypes(
          { include_inactive: showInactive },
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
  }, [showInactive, refreshTick])

  // Sort by display_order ascending, then by code as a stable tie-break.
  const sortedItems = useMemo<AllowanceType[]>(() => {
    return [...(items ?? [])].sort((a, b) => {
      const ao = a?.display_order ?? 0
      const bo = b?.display_order ?? 0
      if (ao !== bo) return ao - bo
      return (a?.code ?? '').localeCompare(b?.code ?? '')
    })
  }, [items])

  const openCreate = useCallback(() => {
    setModal({
      open: true,
      mode: 'create',
      target: null,
      form: EMPTY_FORM,
      busy: false,
      error: null,
    })
  }, [])

  const openEdit = useCallback((t: AllowanceType) => {
    setModal({
      open: true,
      mode: 'edit',
      target: t,
      form: fromAllowanceType(t),
      busy: false,
      error: null,
    })
  }, [])

  const closeModal = useCallback(() => setModal(EMPTY_MODAL), [])

  const submitModal = useCallback(async () => {
    setModal((s) => ({ ...s, busy: true, error: null }))
    try {
      if (modal.mode === 'create') {
        await createAllowanceType(toCreatePayload(modal.form))
      } else if (modal.target) {
        await updateAllowanceType(modal.target.id, toUpdatePayload(modal.form))
      }
      setModal(EMPTY_MODAL)
      refresh()
    } catch (err) {
      setModal((s) => ({
        ...s,
        busy: false,
        error: readErrorMessage(err) || 'Save failed',
      }))
    }
  }, [modal, refresh])

  const handleDeactivate = useCallback(
    async (t: AllowanceType) => {
      setBusyId(t.id)
      setRowError(null)
      try {
        await deactivateAllowanceType(t.id)
        refresh()
      } catch (err) {
        setRowError({
          id: t.id,
          message: readErrorMessage(err) || 'Deactivate failed',
        })
      } finally {
        setBusyId(null)
      }
    },
    [refresh],
  )

  const handleReactivate = useCallback(
    async (t: AllowanceType) => {
      setBusyId(t.id)
      setRowError(null)
      try {
        await updateAllowanceType(t.id, { active: true })
        refresh()
      } catch (err) {
        setRowError({
          id: t.id,
          message: readErrorMessage(err) || 'Reactivate failed',
        })
      } finally {
        setBusyId(null)
      }
    },
    [refresh],
  )

  const canSubmitModal =
    !modal.busy &&
    modal.form.name.trim().length > 0 &&
    (modal.mode === 'edit' || modal.form.code.trim().length > 0)

  return (
    <div className="space-y-4" data-testid="allowance-types-page">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <h1 className="text-xl font-semibold text-text">
            Allowance types
          </h1>
          <p className="text-sm text-muted">
            Manage the allowance categories available on payslips. Sorted by
            display order.
          </p>
        </div>
        <div className="flex items-center gap-3">
          <label className="flex items-center gap-2 text-sm text-text">
            <input
              type="checkbox"
              checked={showInactive}
              onChange={(e) => setShowInactive(e.target.checked)}
              data-testid="allowance-types-show-inactive"
            />
            Show inactive
          </label>
          <Button
            size="sm"
            onClick={openCreate}
            data-testid="allowance-types-add"
          >
            Add allowance type
          </Button>
        </div>
      </div>

      {loadError && (
        <AlertBanner variant="error">{loadError}</AlertBanner>
      )}

      {loading ? (
        <div className="flex items-center justify-center py-12">
          <Spinner size="lg" label="Loading allowance types" />
        </div>
      ) : sortedItems.length === 0 ? (
        <div
          className="rounded-card border border-dashed border-border px-4 py-12 text-center text-sm text-muted"
          data-testid="allowance-types-empty"
        >
          No allowance types configured yet.
        </div>
      ) : (
        <div className="overflow-hidden rounded-card border border-border bg-card shadow-card">
          <table
            className="min-w-full text-sm"
            data-testid="allowance-types-table"
          >
            <thead>
              <tr>
                <th className="mono border-b border-border px-4 py-3 text-left text-[10.5px] font-medium uppercase tracking-[0.08em] text-muted-2">
                  Order
                </th>
                <th className="mono border-b border-border px-4 py-3 text-left text-[10.5px] font-medium uppercase tracking-[0.08em] text-muted-2">
                  Code
                </th>
                <th className="mono border-b border-border px-4 py-3 text-left text-[10.5px] font-medium uppercase tracking-[0.08em] text-muted-2">
                  Name
                </th>
                <th className="mono border-b border-border px-4 py-3 text-right text-[10.5px] font-medium uppercase tracking-[0.08em] text-muted-2">
                  Default amount
                </th>
                <th className="mono border-b border-border px-4 py-3 text-left text-[10.5px] font-medium uppercase tracking-[0.08em] text-muted-2">
                  Unit
                </th>
                <th className="mono border-b border-border px-4 py-3 text-left text-[10.5px] font-medium uppercase tracking-[0.08em] text-muted-2">
                  Taxable
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
              {sortedItems.map((t) => {
                const isBusy = busyId === t?.id
                const errMessage =
                  rowError && rowError.id === t?.id ? rowError.message : null
                return (
                  <tr
                    key={t?.id ?? Math.random().toString(36)}
                    data-testid={`allowance-type-row-${t?.id ?? ''}`}
                    className="border-b border-border last:border-b-0 hover:bg-canvas"
                  >
                    <td className="mono px-4 py-2 text-muted">
                      {t?.display_order ?? 0}
                    </td>
                    <td className="mono px-4 py-2 text-xs text-text">
                      {t?.code}
                    </td>
                    <td className="px-4 py-2 text-text">
                      {t?.name}
                    </td>
                    <td className="mono px-4 py-2 text-right text-muted">
                      {formatAmount(t?.default_amount)}
                    </td>
                    <td className="px-4 py-2 text-muted">
                      {t?.unit}
                    </td>
                    <td className="px-4 py-2 text-muted">
                      {t?.taxable ? 'Yes' : 'No'}
                    </td>
                    <td className="px-4 py-2">
                      {t?.active ? (
                        <Badge variant="success">Active</Badge>
                      ) : (
                        <Badge variant="neutral">Inactive</Badge>
                      )}
                    </td>
                    <td className="px-4 py-2 text-right">
                      <div className="flex flex-wrap items-center justify-end gap-2">
                        <Button
                          size="sm"
                          variant="ghost"
                          onClick={() => openEdit(t)}
                          disabled={isBusy}
                          data-testid={`allowance-type-edit-${t?.id ?? ''}`}
                        >
                          Edit
                        </Button>
                        {t?.active ? (
                          <Button
                            size="sm"
                            variant="ghost"
                            onClick={() => handleDeactivate(t)}
                            disabled={isBusy}
                            loading={isBusy}
                            data-testid={`allowance-type-deactivate-${t?.id ?? ''}`}
                          >
                            Deactivate
                          </Button>
                        ) : (
                          <Button
                            size="sm"
                            variant="ghost"
                            onClick={() => handleReactivate(t)}
                            disabled={isBusy}
                            loading={isBusy}
                            data-testid={`allowance-type-reactivate-${t?.id ?? ''}`}
                          >
                            Reactivate
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
      )}

      <Modal
        open={modal.open}
        onClose={modal.busy ? () => undefined : closeModal}
        title={
          modal.mode === 'create'
            ? 'Add allowance type'
            : 'Edit allowance type'
        }
      >
        <div className="space-y-3">
          <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
            <label className="block text-sm font-medium text-text">
              Code
              <input
                type="text"
                value={modal.form.code}
                onChange={(e) =>
                  setModal((s) => ({
                    ...s,
                    form: { ...s.form, code: e.target.value },
                  }))
                }
                disabled={modal.mode === 'edit'}
                data-testid="allowance-type-form-code"
                className="mt-1 block w-full rounded-ctl border border-border bg-card px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-accent disabled:opacity-60"
              />
            </label>
            <label className="block text-sm font-medium text-text">
              Name
              <input
                type="text"
                value={modal.form.name}
                onChange={(e) =>
                  setModal((s) => ({
                    ...s,
                    form: { ...s.form, name: e.target.value },
                  }))
                }
                data-testid="allowance-type-form-name"
                className="mt-1 block w-full rounded-ctl border border-border bg-card px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-accent"
              />
            </label>
          </div>
          <div className="grid grid-cols-1 gap-3 sm:grid-cols-3">
            <label className="block text-sm font-medium text-text">
              Default amount
              <input
                type="number"
                step="0.01"
                min="0"
                value={modal.form.default_amount}
                onChange={(e) =>
                  setModal((s) => ({
                    ...s,
                    form: { ...s.form, default_amount: e.target.value },
                  }))
                }
                data-testid="allowance-type-form-default"
                className="mt-1 block w-full rounded-ctl border border-border bg-card px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-accent"
              />
            </label>
            <label className="block text-sm font-medium text-text">
              Unit
              <select
                value={modal.form.unit}
                onChange={(e) =>
                  setModal((s) => ({
                    ...s,
                    form: { ...s.form, unit: e.target.value as AllowanceUnit },
                  }))
                }
                data-testid="allowance-type-form-unit"
                className="mt-1 block w-full rounded-ctl border border-border bg-card px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-accent"
              >
                {UNITS.map((u) => (
                  <option key={u} value={u}>
                    {u}
                  </option>
                ))}
              </select>
            </label>
            <label className="block text-sm font-medium text-text">
              Display order
              <input
                type="number"
                step="1"
                min="0"
                value={modal.form.display_order}
                onChange={(e) =>
                  setModal((s) => ({
                    ...s,
                    form: { ...s.form, display_order: e.target.value },
                  }))
                }
                data-testid="allowance-type-form-order"
                className="mt-1 block w-full rounded-ctl border border-border bg-card px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-accent"
              />
            </label>
          </div>
          <label className="flex items-center gap-2 text-sm text-text">
            <input
              type="checkbox"
              checked={modal.form.taxable}
              onChange={(e) =>
                setModal((s) => ({
                  ...s,
                  form: { ...s.form, taxable: e.target.checked },
                }))
              }
              data-testid="allowance-type-form-taxable"
            />
            Taxable
          </label>
          {modal.error && (
            <AlertBanner variant="error">{modal.error}</AlertBanner>
          )}
          <div className="flex justify-end gap-2">
            <Button
              variant="ghost"
              onClick={closeModal}
              disabled={modal.busy}
            >
              Cancel
            </Button>
            <Button
              variant="primary"
              onClick={submitModal}
              loading={modal.busy}
              disabled={!canSubmitModal}
              data-testid="allowance-type-form-submit"
            >
              {modal.mode === 'create' ? 'Create' : 'Save'}
            </Button>
          </div>
        </div>
      </Modal>
    </div>
  )
}
