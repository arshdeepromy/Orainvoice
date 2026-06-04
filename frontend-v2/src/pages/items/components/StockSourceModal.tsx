import { useState, useCallback } from 'react'
import { Button, Modal } from '@/components/ui'
import type { StockOption } from '../types'

/* ------------------------------------------------------------------ */
/*  Types                                                              */
/* ------------------------------------------------------------------ */

interface StockSourceComponent {
  catalogue_item_id: string
  catalogue_type: 'part' | 'tyre' | 'fluid'
  name: string
  quantity?: number
  volume?: number
  stock_options: StockOption[]
}

interface StockSourceModalProps {
  open: boolean
  onClose: () => void
  onConfirm: (selections: Record<string, string>) => void // catalogue_item_id -> stock_item_id
  components: StockSourceComponent[]
  userRole: string
}

/* ------------------------------------------------------------------ */
/*  Helpers                                                            */
/* ------------------------------------------------------------------ */

function formatCurrency(value: number | undefined | null): string {
  return `${(value ?? 0).toFixed(2)}`
}

function formatQty(component: StockSourceComponent): string {
  if (component.catalogue_type === 'fluid') {
    return `${component.volume ?? 0}L required`
  }
  return `${component.quantity ?? 0} required`
}

function catalogueTypeLabel(type: 'part' | 'tyre' | 'fluid'): string {
  switch (type) {
    case 'part': return 'Part'
    case 'tyre': return 'Tyre'
    case 'fluid': return 'Fluid'
    default: return type
  }
}

/* ------------------------------------------------------------------ */
/*  Component                                                          */
/* ------------------------------------------------------------------ */

export default function StockSourceModal({
  open,
  onClose,
  onConfirm,
  components,
  userRole,
}: StockSourceModalProps) {
  const [selections, setSelections] = useState<Record<string, string>>({})

  const isAdmin = userRole === 'org_admin' || userRole === 'global_admin'

  const handleSelect = useCallback((catalogueItemId: string, stockItemId: string) => {
    setSelections((prev) => ({ ...prev, [catalogueItemId]: stockItemId }))
  }, [])

  const allSelected = (components ?? []).every(
    (c) => !!selections[c?.catalogue_item_id ?? '']
  )

  const handleConfirm = () => {
    if (!allSelected) return
    onConfirm(selections)
  }

  const handleClose = () => {
    setSelections({})
    onClose()
  }

  return (
    <Modal
      open={open}
      onClose={handleClose}
      title="Select Stock Source"
      className="max-w-2xl"
    >
      <div className="space-y-6">
        <p className="text-sm text-muted">
          The following components have multiple stock sources. Please select which stock item to use for each component.
        </p>

        {(components ?? []).map((component) => (
          <ComponentStockSelection
            key={component?.catalogue_item_id ?? ''}
            component={component}
            selectedStockId={selections[component?.catalogue_item_id ?? ''] ?? null}
            onSelect={(stockItemId) =>
              handleSelect(component?.catalogue_item_id ?? '', stockItemId)
            }
            showCost={isAdmin}
          />
        ))}
      </div>

      <div className="mt-6 flex justify-end gap-2">
        <Button variant="ghost" size="sm" onClick={handleClose}>
          Cancel
        </Button>
        <Button size="sm" onClick={handleConfirm} disabled={!allSelected}>
          Confirm Selection
        </Button>
      </div>
    </Modal>
  )
}

/* ------------------------------------------------------------------ */
/*  ComponentStockSelection sub-component                              */
/* ------------------------------------------------------------------ */

interface ComponentStockSelectionProps {
  component: StockSourceComponent
  selectedStockId: string | null
  onSelect: (stockItemId: string) => void
  showCost: boolean
}

function ComponentStockSelection({
  component,
  selectedStockId,
  onSelect,
  showCost,
}: ComponentStockSelectionProps) {
  const options = component?.stock_options ?? []

  return (
    <div className="rounded-card border border-border p-4">
      {/* Component header */}
      <div className="flex items-center justify-between mb-3">
        <div className="flex items-center gap-2">
          <h3 className="text-sm font-semibold text-text">
            {component?.name ?? 'Unknown Component'}
          </h3>
          <span className="inline-flex items-center rounded-full bg-canvas px-2 py-0.5 text-xs font-medium text-muted">
            {catalogueTypeLabel(component?.catalogue_type ?? 'part')}
          </span>
        </div>
        <span className="text-xs text-muted">
          {formatQty(component)}
        </span>
      </div>

      {/* Stock options list */}
      <div className="space-y-2">
        {options.length === 0 ? (
          <p className="text-sm text-muted-2 italic">
            No stock options available.
          </p>
        ) : (
          options.map((option) => {
            const isSelected = selectedStockId === (option?.stock_item_id ?? '')
            return (
              <label
                key={option?.stock_item_id ?? ''}
                className={`flex items-center gap-3 rounded-ctl border p-3 cursor-pointer transition-colors min-h-[44px]
                  ${isSelected
                    ? 'border-accent bg-accent-soft'
                    : 'border-border hover:border-border-strong hover:bg-canvas'
                  }`}
              >
                <input
                  type="radio"
                  name={`stock-source-${component?.catalogue_item_id ?? ''}`}
                  value={option?.stock_item_id ?? ''}
                  checked={isSelected}
                  onChange={() => onSelect(option?.stock_item_id ?? '')}
                  className="h-4 w-4 text-accent border-border focus:ring-accent min-w-[16px]"
                />
                <div className="flex-1 flex items-center justify-between gap-4">
                  <div className="flex flex-col">
                    <span className="text-sm font-medium text-text">
                      {option?.location ?? 'Unknown Location'}
                    </span>
                    {option?.branch_id && (
                      <span className="text-xs text-muted">
                        Branch: {option?.branch_id ?? '—'}
                      </span>
                    )}
                  </div>
                  <div className="flex items-center gap-4 text-sm">
                    <span
                      className={`font-medium ${
                        (option?.available_qty ?? 0) <= 0
                          ? 'text-danger'
                          : 'text-text'
                      }`}
                    >
                      {(option?.available_qty ?? 0)} available
                    </span>
                    {showCost && (
                      <span className="text-muted font-medium">
                        {formatCurrency(option?.cost_per_unit)}
                        <span className="text-xs text-muted-2">/unit</span>
                      </span>
                    )}
                  </div>
                </div>
              </label>
            )
          })
        )}
      </div>
    </div>
  )
}
