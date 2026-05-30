import { useEffect, useMemo, useState } from 'react'
import { Button, Modal } from '../ui'

/* ------------------------------------------------------------------ */
/*  Types                                                              */
/* ------------------------------------------------------------------ */

export interface PickableVehicle {
  id: string
  rego: string
  make?: string | null
  model?: string | null
  year?: number | null
}

interface VehiclePickerModalProps {
  open: boolean
  vehicles: PickableVehicle[]
  /** Action label, e.g. "Issue Invoice" or "Issue Quote". Drives the title and confirm-button copy. */
  action: 'invoice' | 'quote'
  onClose: () => void
  /** Called with the user's selection (one or more regos, in the order picked). */
  onConfirm: (selectedRegos: string[]) => void
}

/* ------------------------------------------------------------------ */
/*  Component                                                          */
/* ------------------------------------------------------------------ */

/**
 * Pick one or more linked vehicles before opening the new-invoice /
 * new-quote form. Used by the Customer Profile "Issue Invoice" / "Issue
 * Quote" buttons when the customer has more than one linked vehicle.
 *
 * Multi-select intentionally — the create forms support a primary vehicle
 * plus zero or more additional vehicles, and both InvoiceCreate and
 * QuoteCreate now accept a comma-separated ``vehicle_regos`` URL param
 * that prefills every vehicle in the order the user picks them.
 */
export function VehiclePickerModal({
  open,
  vehicles,
  action,
  onClose,
  onConfirm,
}: VehiclePickerModalProps) {
  // ``selected`` preserves the order the user picked vehicles in, so the
  // first checked vehicle becomes the primary on the create form.
  const [selected, setSelected] = useState<string[]>([])

  // Reset the selection when the modal is opened so old picks don't leak
  // into a fresh interaction.
  useEffect(() => {
    if (open) setSelected([])
  }, [open])

  const titleNoun = action === 'invoice' ? 'Invoice' : 'Quote'
  const confirmLabel = useMemo(() => {
    const count = selected.length
    if (count === 0) return `Continue to ${titleNoun}`
    if (count === 1) return `Continue with 1 vehicle`
    return `Continue with ${count} vehicles`
  }, [selected.length, titleNoun])

  const toggle = (rego: string) => {
    setSelected((prev) =>
      prev.includes(rego) ? prev.filter((r) => r !== rego) : [...prev, rego],
    )
  }

  return (
    <Modal open={open} onClose={onClose} title={`Select vehicles for ${titleNoun.toLowerCase()}`}>
      <div className="flex flex-col gap-4">
        <p className="text-sm text-gray-600">
          This customer has multiple vehicles linked to them. Pick one or more
          to attach to the new {titleNoun.toLowerCase()}. The first vehicle you
          select becomes the primary; the rest are added as additional
          vehicles.
        </p>

        <ul className="flex flex-col divide-y divide-gray-100 rounded-md border border-gray-200">
          {(vehicles ?? []).map((v) => {
            const idx = selected.indexOf(v.rego)
            const checked = idx !== -1
            const orderBadge = checked ? idx + 1 : null
            const labelParts = [v.year ?? null, v.make ?? null, v.model ?? null].filter(Boolean)
            const detail = labelParts.length > 0 ? labelParts.join(' ') : '—'
            return (
              <li key={v.id || v.rego} className="flex items-center">
                <label className="flex w-full cursor-pointer items-center gap-3 px-3 py-2 hover:bg-gray-50">
                  <input
                    type="checkbox"
                    checked={checked}
                    onChange={() => toggle(v.rego)}
                    className="h-4 w-4 rounded border-gray-300 text-blue-600 focus:ring-blue-500"
                    aria-label={`Select vehicle ${v.rego}`}
                  />
                  <span className="font-mono font-semibold text-gray-900">{v.rego}</span>
                  <span className="text-sm text-gray-600">{detail}</span>
                  {orderBadge !== null && (
                    <span
                      className="ml-auto inline-flex h-5 min-w-[1.25rem] items-center justify-center rounded-full bg-blue-600 px-1.5 text-xs font-semibold text-white"
                      aria-label={
                        orderBadge === 1
                          ? 'Primary vehicle'
                          : `Additional vehicle ${orderBadge - 1}`
                      }
                    >
                      {orderBadge === 1 ? 'Primary' : orderBadge}
                    </span>
                  )}
                </label>
              </li>
            )
          })}
        </ul>

        <div className="flex justify-end gap-2 pt-2">
          <Button variant="secondary" size="sm" onClick={onClose}>
            Cancel
          </Button>
          <Button
            variant="primary"
            size="sm"
            disabled={selected.length === 0}
            onClick={() => onConfirm(selected)}
          >
            {confirmLabel}
          </Button>
        </div>
      </div>
    </Modal>
  )
}
