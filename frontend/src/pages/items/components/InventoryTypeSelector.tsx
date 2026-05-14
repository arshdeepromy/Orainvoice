import type { PackageComponent } from '../types'
import PartsSelector from './PartsSelector'
import TyreSelector from './TyreSelector'
import FluidSelector from './FluidSelector'

interface InventoryTypeSelectorProps {
  components: PackageComponent[]
  userRole: string
  onChange: (components: PackageComponent[]) => void
  enabledTypes: { parts: boolean; fluid: boolean; tyre: boolean }
  onTypeToggle: (type: 'parts' | 'fluid' | 'tyre', enabled: boolean) => void
}

/**
 * Three checkboxes: "Parts", "Fluid", "Tyre".
 * Conditionally renders sub-forms based on checked state.
 * Unchecking clears selections for that type.
 *
 * Validates: Requirements 2.1, 2.2, 2.3, 2.4, 2.5
 */
export default function InventoryTypeSelector({
  components,
  userRole,
  onChange,
  enabledTypes,
  onTypeToggle,
}: InventoryTypeSelectorProps) {
  return (
    <div className="space-y-4">
      {/* Type checkboxes */}
      <div className="flex flex-wrap gap-4">
        <label className="inline-flex min-h-[44px] cursor-pointer items-center gap-2">
          <input
            type="checkbox"
            checked={enabledTypes.parts}
            onChange={(e) => onTypeToggle('parts', e.target.checked)}
            className="h-4 w-4 rounded border-gray-300 text-blue-600 focus:ring-blue-500 dark:border-gray-600 dark:bg-gray-700"
          />
          <span className="text-sm font-medium text-gray-700 dark:text-gray-300">Parts</span>
        </label>

        <label className="inline-flex min-h-[44px] cursor-pointer items-center gap-2">
          <input
            type="checkbox"
            checked={enabledTypes.fluid}
            onChange={(e) => onTypeToggle('fluid', e.target.checked)}
            className="h-4 w-4 rounded border-gray-300 text-blue-600 focus:ring-blue-500 dark:border-gray-600 dark:bg-gray-700"
          />
          <span className="text-sm font-medium text-gray-700 dark:text-gray-300">Fluid</span>
        </label>

        <label className="inline-flex min-h-[44px] cursor-pointer items-center gap-2">
          <input
            type="checkbox"
            checked={enabledTypes.tyre}
            onChange={(e) => onTypeToggle('tyre', e.target.checked)}
            className="h-4 w-4 rounded border-gray-300 text-blue-600 focus:ring-blue-500 dark:border-gray-600 dark:bg-gray-700"
          />
          <span className="text-sm font-medium text-gray-700 dark:text-gray-300">Tyre</span>
        </label>
      </div>

      {/* Sub-forms based on checked state */}
      {enabledTypes.parts && (
        <PartsSelector
          components={components}
          userRole={userRole}
          onChange={onChange}
        />
      )}

      {enabledTypes.tyre && (
        <TyreSelector
          components={components}
          userRole={userRole}
          onChange={onChange}
        />
      )}

      {enabledTypes.fluid && (
        <FluidSelector
          components={components}
          userRole={userRole}
          onChange={onChange}
        />
      )}
    </div>
  )
}
