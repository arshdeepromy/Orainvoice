import type { PackageComponent } from '../types'
import FluidEntry from './FluidEntry'

interface FluidSelectorProps {
  components: PackageComponent[]
  userRole: string
  onChange: (components: PackageComponent[]) => void
}

/**
 * Manages multiple fluid entries via "+ Add Fluid" button.
 * Renders `FluidEntry` for each fluid.
 *
 * Validates: Requirements 3.1
 */
export default function FluidSelector({ components, userRole, onChange }: FluidSelectorProps) {
  const fluidComponents = (components ?? []).filter((c) => c.catalogue_type === 'fluid')

  const handleAddFluid = () => {
    const newFluid: PackageComponent = {
      catalogue_item_id: '',
      catalogue_type: 'fluid',
      fluid_type: 'oil',
      volume: 0,
    }
    onChange([...components, newFluid])
  }

  const handleUpdateFluid = (index: number, updated: PackageComponent) => {
    // Find the actual index in the full components array
    let fluidIndex = 0
    const newComponents = components.map((c) => {
      if (c.catalogue_type === 'fluid') {
        if (fluidIndex === index) {
          fluidIndex++
          return updated
        }
        fluidIndex++
      }
      return c
    })
    onChange(newComponents)
  }

  const handleRemoveFluid = (index: number) => {
    let fluidIndex = 0
    const newComponents = components.filter((c) => {
      if (c.catalogue_type === 'fluid') {
        if (fluidIndex === index) {
          fluidIndex++
          return false
        }
        fluidIndex++
      }
      return true
    })
    onChange(newComponents)
  }

  return (
    <div className="space-y-3">
      <div className="flex items-center justify-between">
        <h4 className="text-sm font-medium text-gray-700 dark:text-gray-300">Fluids</h4>
        <button
          type="button"
          onClick={handleAddFluid}
          className="min-h-[44px] inline-flex items-center gap-1 rounded-md bg-blue-50 px-3 py-2 text-sm font-medium text-blue-700 hover:bg-blue-100 dark:bg-blue-900/30 dark:text-blue-300 dark:hover:bg-blue-900/50"
        >
          <svg className="h-4 w-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
            <path strokeLinecap="round" strokeLinejoin="round" d="M12 4v16m8-8H4" />
          </svg>
          Add Fluid
        </button>
      </div>

      {fluidComponents.length === 0 && (
        <p className="text-sm text-gray-500 dark:text-gray-400">
          No fluids added. Click &quot;+ Add Fluid&quot; to include fluid usage.
        </p>
      )}

      <div className="space-y-3">
        {fluidComponents.map((comp, index) => (
          <FluidEntry
            key={`fluid-${index}`}
            component={comp}
            userRole={userRole}
            onChange={(updated) => handleUpdateFluid(index, updated)}
            onRemove={() => handleRemoveFluid(index)}
          />
        ))}
      </div>
    </div>
  )
}
