import { useState } from 'react'
import { usePartsSearch } from '../hooks'
import type { PackageComponent, PartSearchResult } from '../types'
import ComponentRow from './ComponentRow'

interface PartsSelectorProps {
  components: PackageComponent[]
  userRole: string
  onChange: (components: PackageComponent[]) => void
}

/**
 * Searchable dropdown calling `GET /catalogue/parts/search?part_type=part`.
 * Uses `usePartsSearch` hook from hooks.ts.
 * On select: adds component with default quantity 1.
 * Renders `ComponentRow` for each selected part.
 *
 * Validates: Requirements 4.1, 4.2, 4.3, 4.4
 */
export default function PartsSelector({ components, userRole, onChange }: PartsSelectorProps) {
  const [searchQuery, setSearchQuery] = useState('')
  const [showDropdown, setShowDropdown] = useState(false)
  const { items: searchResults, loading } = usePartsSearch(searchQuery, 'part')

  const partComponents = (components ?? []).filter((c) => c.catalogue_type === 'part')

  const handleSelectPart = (part: PartSearchResult) => {
    // Don't add duplicates
    const exists = components.some((c) => c.catalogue_item_id === part.id)
    if (exists) return

    const newComponent: PackageComponent = {
      catalogue_item_id: part.id,
      catalogue_type: 'part',
      quantity: 1,
      cost_per_unit_snapshot: part.cost_per_unit ?? 0,
    }
    onChange([...components, newComponent])
    setSearchQuery('')
    setShowDropdown(false)
  }

  const handleQuantityChange = (catalogueItemId: string, quantity: number) => {
    const updated = components.map((c) =>
      c.catalogue_item_id === catalogueItemId && c.catalogue_type === 'part'
        ? { ...c, quantity }
        : c
    )
    onChange(updated)
  }

  const handleRemove = (catalogueItemId: string) => {
    const updated = components.filter(
      (c) => !(c.catalogue_item_id === catalogueItemId && c.catalogue_type === 'part')
    )
    onChange(updated)
  }

  return (
    <div className="space-y-3">
      <h4 className="text-sm font-medium text-text">Parts</h4>

      {/* Search input */}
      <div className="relative">
        <input
          type="text"
          value={searchQuery}
          onChange={(e) => {
            setSearchQuery(e.target.value)
            setShowDropdown(true)
          }}
          onFocus={() => setShowDropdown(true)}
          placeholder="Search parts..."
          className="min-h-[44px] w-full rounded-ctl border border-border bg-card px-3 py-2 text-sm text-text placeholder:text-muted-2 focus:border-accent focus:outline-none focus:shadow-[0_0_0_3px_var(--accent-soft)]"
          aria-label="Search parts catalogue"
        />

        {/* Dropdown results */}
        {showDropdown && searchQuery.trim().length >= 2 && (
          <div className="absolute z-10 mt-1 max-h-60 w-full overflow-auto rounded-ctl border border-border bg-card shadow-pop">
            {loading && (
              <p className="px-3 py-2 text-sm text-muted">Searching...</p>
            )}
            {!loading && (searchResults ?? []).length === 0 && (
              <p className="px-3 py-2 text-sm text-muted">No parts found</p>
            )}
            {!loading &&
              (searchResults ?? []).map((part: PartSearchResult) => {
                const alreadyAdded = components.some((c) => c.catalogue_item_id === part.id)
                return (
                  <button
                    key={part.id}
                    type="button"
                    disabled={alreadyAdded}
                    onClick={() => handleSelectPart(part)}
                    className={`min-h-[44px] w-full px-3 py-2 text-left text-sm ${
                      alreadyAdded
                        ? 'cursor-not-allowed bg-canvas text-muted-2'
                        : 'hover:bg-accent-soft'
                    }`}
                  >
                    <span className="font-medium text-text">
                      {part.name}
                    </span>
                    {part.part_number && (
                      <span className="mono ml-2 text-muted">
                        ({part.part_number})
                      </span>
                    )}
                    {part.brand && (
                      <span className="ml-2 text-xs text-muted-2">
                        {part.brand}
                      </span>
                    )}
                    {alreadyAdded && (
                      <span className="ml-2 text-xs text-muted-2">Already added</span>
                    )}
                  </button>
                )
              })}
          </div>
        )}
      </div>

      {/* Click-away handler */}
      {showDropdown && (
        <div
          className="fixed inset-0 z-0"
          onClick={() => setShowDropdown(false)}
          aria-hidden="true"
        />
      )}

      {/* Selected parts list */}
      {partComponents.length > 0 && (
        <div className="space-y-2">
          {partComponents.map((comp) => (
            <ComponentRow
              key={comp.catalogue_item_id}
              component={comp}
              name={comp.catalogue_item_id} // Will be resolved by parent or via search cache
              costPerUnit={comp.cost_per_unit_snapshot ?? null}
              isAvailable={true}
              userRole={userRole}
              onQuantityChange={(qty) => handleQuantityChange(comp.catalogue_item_id, qty)}
              onRemove={() => handleRemove(comp.catalogue_item_id)}
            />
          ))}
        </div>
      )}
    </div>
  )
}
