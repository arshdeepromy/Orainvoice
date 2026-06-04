import { useState, useCallback } from 'react'
import { useModules } from '@/contexts/ModuleContext'
import type { PackageComponent } from '../types'
import InventoryTypeSelector from './InventoryTypeSelector'
import CostSummary from './CostSummary'
import PackagePreview from './PackagePreview'

interface PackageBuilderProps {
  components: PackageComponent[]
  onChange: (components: PackageComponent[]) => void
  sellPrice: number
  userRole: string
  itemId?: string | null
}

/**
 * Main PackageBuilder component.
 * Contains "Include Inventory Usage" checkbox.
 * Module gate: only render when `useModules().isEnabled('vehicles') && useModules().isEnabled('inventory')`.
 * Manages local state for component selections.
 * When checkbox is unchecked, clears all components via onChange([]).
 *
 * Validates: Requirements 1.1, 1.2, 1.3, 1.4, 1.5
 */
export default function PackageBuilder({
  components,
  onChange,
  sellPrice,
  userRole,
  itemId,
}: PackageBuilderProps) {
  const { isEnabled } = useModules()

  // Module gate: only render when both vehicles AND inventory modules are enabled
  if (!isEnabled('vehicles') || !isEnabled('inventory')) {
    return null
  }

  const hasComponents = (components ?? []).length > 0
  const [includeInventory, setIncludeInventory] = useState(hasComponents)
  const [enabledTypes, setEnabledTypes] = useState<{
    parts: boolean
    fluid: boolean
    tyre: boolean
  }>(() => {
    // Initialize from existing components
    const comps = components ?? []
    return {
      parts: comps.some((c) => c.catalogue_type === 'part'),
      fluid: comps.some((c) => c.catalogue_type === 'fluid'),
      tyre: comps.some((c) => c.catalogue_type === 'tyre'),
    }
  })

  const handleToggleInventory = useCallback(
    (checked: boolean) => {
      setIncludeInventory(checked)
      if (!checked) {
        // Clear all components when unchecked
        onChange([])
        setEnabledTypes({ parts: false, fluid: false, tyre: false })
      }
    },
    [onChange]
  )

  const handleTypeToggle = useCallback(
    (type: 'parts' | 'fluid' | 'tyre', enabled: boolean) => {
      setEnabledTypes((prev) => ({ ...prev, [type]: enabled }))

      if (!enabled) {
        // Clear components of this type
        const catalogueType = type === 'parts' ? 'part' : type
        const filtered = (components ?? []).filter((c) => c.catalogue_type !== catalogueType)
        onChange(filtered)
      }
    },
    [components, onChange]
  )

  return (
    <div className="space-y-4 border-t border-border pt-4">
      {/* Include Inventory Usage checkbox */}
      <label className="inline-flex min-h-[44px] cursor-pointer items-center gap-3">
        <input
          type="checkbox"
          checked={includeInventory}
          onChange={(e) => handleToggleInventory(e.target.checked)}
          className="h-5 w-5 rounded border-border text-accent focus:ring-accent"
        />
        <span className="text-sm font-medium text-text">
          Include Inventory Usage
        </span>
      </label>

      {/* Inventory type selection panel (shown when checkbox is checked) */}
      {includeInventory && (
        <div className="space-y-4 rounded-card border border-border bg-canvas p-4">
          <InventoryTypeSelector
            components={components ?? []}
            userRole={userRole}
            onChange={onChange}
            enabledTypes={enabledTypes}
            onTypeToggle={handleTypeToggle}
          />

          {/* Cost Summary (admin only) */}
          {(components ?? []).length > 0 && (
            <CostSummary
              components={components ?? []}
              sellPrice={sellPrice}
              userRole={userRole}
            />
          )}

          {/* Package Preview */}
          <PackagePreview
            itemId={itemId ?? null}
            components={components ?? []}
            sellPrice={sellPrice}
            userRole={userRole}
          />
        </div>
      )}
    </div>
  )
}
