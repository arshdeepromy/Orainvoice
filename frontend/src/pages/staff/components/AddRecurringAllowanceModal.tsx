/**
 * AddRecurringAllowanceModal — Phase 4 task D10 (G4 + P4-N31).
 *
 * Modal dialog for creating a recurring allowance rule on a staff
 * member. Used from `RecurringAllowancesPanel` on the Staff Detail
 * Overview tab.
 *
 * Form fields per design §6.7:
 *   - allowance_type (select; populated via `listAllowanceTypes`).
 *   - amount override (numeric, optional — placeholder shows the
 *     selected type's `default_amount`).
 *   - quantity override (optional — meaningful for `unit='km'`; left
 *     null otherwise so the backend derives shifts from approved
 *     timesheets).
 *   - notes (optional).
 *
 * Validation: `allowance_type_id` is required. Numeric inputs are
 * captured as strings to preserve the Decimal-string contract of the
 * typed API client.
 *
 * **Validates: Staff Management Phase 4 task D10, R3.5, G4**
 */

import { useEffect, useMemo, useState } from 'react'
import { Button, Modal, AlertBanner } from '@/components/ui'
import {
  createRecurringAllowance,
  listAllowanceTypes,
} from '@/api/payslips'
import type {
  AllowanceType,
  StaffRecurringAllowanceCreatePayload,
} from '@/api/payslips'

interface Props {
  staffId: string
  open: boolean
  onClose: () => void
  /** Called after a successful create — used to refresh the parent list. */
  onCreated?: () => void
}

interface FormState {
  allowance_type_id: string
  amount: string
  quantity: string
  notes: string
}

const EMPTY_FORM: FormState = {
  allowance_type_id: '',
  amount: '',
  quantity: '',
  notes: '',
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
  return 'Failed to add recurring allowance.'
}

export default function AddRecurringAllowanceModal({
  staffId,
  open,
  onClose,
  onCreated,
}: Props) {
  const [form, setForm] = useState<FormState>(EMPTY_FORM)
  const [types, setTypes] = useState<AllowanceType[]>([])
  const [typesLoading, setTypesLoading] = useState<boolean>(false)
  const [typesError, setTypesError] = useState<string | null>(null)

  const [busy, setBusy] = useState<boolean>(false)
  const [error, setError] = useState<string | null>(null)

  // Reset form whenever the modal opens or closes.
  useEffect(() => {
    if (!open) {
      setForm(EMPTY_FORM)
      setError(null)
    }
  }, [open])

  // Load allowance types when the modal opens.
  useEffect(() => {
    if (!open) return
    const controller = new AbortController()
    setTypesLoading(true)
    setTypesError(null)
    ;(async () => {
      try {
        const res = await listAllowanceTypes(
          { include_inactive: false },
          controller.signal,
        )
        if (controller.signal.aborted) return
        setTypes(res.items ?? [])
      } catch (err) {
        if (isAbortError(err)) return
        setTypesError(readErrorMessage(err))
      } finally {
        if (!controller.signal.aborted) setTypesLoading(false)
      }
    })()
    return () => controller.abort()
  }, [open])

  const selectedType = useMemo<AllowanceType | null>(() => {
    if (!form.allowance_type_id) return null
    return (types ?? []).find((t) => t?.id === form.allowance_type_id) ?? null
  }, [types, form.allowance_type_id])

  const canSubmit = !busy && form.allowance_type_id.trim().length > 0

  const handleSubmit = async () => {
    if (!canSubmit) return
    setBusy(true)
    setError(null)
    try {
      const payload: StaffRecurringAllowanceCreatePayload = {
        allowance_type_id: form.allowance_type_id,
      }
      const trimmedAmount = form.amount.trim()
      if (trimmedAmount !== '') {
        payload.amount = trimmedAmount
      }
      const trimmedQty = form.quantity.trim()
      if (trimmedQty !== '') {
        payload.quantity = trimmedQty
      }
      const trimmedNotes = form.notes.trim()
      if (trimmedNotes !== '') {
        payload.notes = trimmedNotes
      }
      await createRecurringAllowance(staffId, payload)
      setBusy(false)
      onCreated?.()
      onClose()
    } catch (err) {
      setBusy(false)
      setError(readErrorMessage(err))
    }
  }

  return (
    <Modal
      open={open}
      onClose={busy ? () => undefined : onClose}
      title="Add recurring allowance"
    >
      <div className="space-y-3" data-testid="add-recurring-allowance-modal">
        <p className="text-sm text-gray-600 dark:text-gray-400">
          This rule will automatically attach a line to every new draft
          payslip generated for this staff member. Admins can still override
          or remove the line on individual payslips.
        </p>

        {typesError && (
          <AlertBanner variant="error">{typesError}</AlertBanner>
        )}

        <label className="block text-sm font-medium text-gray-800 dark:text-gray-200">
          Allowance type *
          <select
            value={form.allowance_type_id}
            onChange={(e) =>
              setForm((s) => ({ ...s, allowance_type_id: e.target.value }))
            }
            disabled={busy || typesLoading}
            data-testid="recurring-allowance-type"
            className="mt-1 block w-full rounded-md border border-gray-300 bg-white px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500 disabled:opacity-60 dark:border-gray-600 dark:bg-gray-900 dark:text-gray-100"
          >
            <option value="">
              {typesLoading
                ? 'Loading…'
                : 'Select an allowance type'}
            </option>
            {(types ?? []).map((t) => (
              <option key={t?.id ?? ''} value={t?.id ?? ''}>
                {t?.name}
                {t?.default_amount
                  ? ` — default $${Number(t.default_amount).toFixed(2)}/${t?.unit ?? 'period'}`
                  : ''}
              </option>
            ))}
          </select>
        </label>

        <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
          <label className="block text-sm font-medium text-gray-800 dark:text-gray-200">
            Amount override
            <input
              type="number"
              step="0.01"
              min="0"
              value={form.amount}
              onChange={(e) =>
                setForm((s) => ({ ...s, amount: e.target.value }))
              }
              placeholder={
                selectedType?.default_amount
                  ? Number(selectedType.default_amount).toFixed(2)
                  : 'optional'
              }
              disabled={busy}
              data-testid="recurring-allowance-amount"
              className="mt-1 block w-full rounded-md border border-gray-300 bg-white px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500 disabled:opacity-60 dark:border-gray-600 dark:bg-gray-900 dark:text-gray-100"
            />
            <span className="mt-1 block text-xs text-gray-500 dark:text-gray-400">
              Leave blank to use the type's default amount.
            </span>
          </label>

          <label className="block text-sm font-medium text-gray-800 dark:text-gray-200">
            Quantity override
            <input
              type="number"
              step="0.01"
              min="0"
              value={form.quantity}
              onChange={(e) =>
                setForm((s) => ({ ...s, quantity: e.target.value }))
              }
              placeholder="optional"
              disabled={busy}
              data-testid="recurring-allowance-quantity"
              className="mt-1 block w-full rounded-md border border-gray-300 bg-white px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500 disabled:opacity-60 dark:border-gray-600 dark:bg-gray-900 dark:text-gray-100"
            />
            <span className="mt-1 block text-xs text-gray-500 dark:text-gray-400">
              Leave blank to derive from approved shifts (unit=shift) or use
              1 (unit=period).
            </span>
          </label>
        </div>

        <label className="block text-sm font-medium text-gray-800 dark:text-gray-200">
          Notes
          <textarea
            value={form.notes}
            onChange={(e) =>
              setForm((s) => ({ ...s, notes: e.target.value }))
            }
            rows={2}
            placeholder="optional"
            disabled={busy}
            data-testid="recurring-allowance-notes"
            className="mt-1 block w-full rounded-md border border-gray-300 bg-white px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500 disabled:opacity-60 dark:border-gray-600 dark:bg-gray-900 dark:text-gray-100"
          />
        </label>

        {error && <AlertBanner variant="error">{error}</AlertBanner>}

        <div className="flex justify-end gap-2 pt-2">
          <Button
            variant="secondary"
            onClick={onClose}
            disabled={busy}
            data-testid="recurring-allowance-cancel"
          >
            Cancel
          </Button>
          <Button
            variant="primary"
            onClick={handleSubmit}
            loading={busy}
            disabled={!canSubmit}
            data-testid="recurring-allowance-submit"
          >
            Add rule
          </Button>
        </div>
      </div>
    </Modal>
  )
}
