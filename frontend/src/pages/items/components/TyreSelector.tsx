import { useState } from 'react'
import { usePartsSearch } from '../hooks'
import type { PackageComponent, PartSearchResult } from '../types'
import ComponentRow from './ComponentRow'

interface TyreSelectorProps {
  components: PackageComponent[]
  userRole: string
  onChange: (components: PackageComponent[]) => void
}

/**
 * Searchable dropdown calling `GET /catalogue/parts/search?part_type=tyre`.
 * Uses `usePartsSearch` hook from hooks.ts.
 * On select: adds component with default quantity 1.
 * Renders `ComponentRow` for each selected tyre.
 *
 * Validates: Requirements 4.5, 4.6, 4.7, 4.8
 */
export default function TyreSelector({ components, userRole, onChange }: TyreSelectorProps) {
  const [searchQuery, setSearchQuery] = useState('')
  const [showDropdown, setShowDropdown] = useState(false)
  const { items: searchResults, loading } = usePartsSearch(searchQuery, 'tyre')

  const tyreComponents = (components ?? []).filter((c) => c.catalogue_type === 'tyre')

  const handleSelectTyre = (tyre: PartSearchResult) => {
    // Don't add duplicates
    const exists = components.some((c) => c.catalogue_item_id === tyre.id)
    if (exists) return

    const newComponent: PackageComponent = {
      catalogue_item_id: tyre.id,
      catalogue_type: 'tyre',
      quantity: 1,
      cost_per_unit_snapshot: tyre.cost_per_unit ?? 0,
    }
    onChange([...components, newComponent])
    setSearchQuery('')
    setShowDropdown(false)
  }

  const handleQuantityChange = (catalogueItemId: string, quantity: number) => {
    const updated = components.map((c) =>
      c.catalogue_item_id === catalogueItemId && c.catalogue_type === 'tyre'
        ? { ...c, quantity }
        : c
    )
    onChange(updated)
  }

  const handleRemove = (catalogueItemId: string) => {
    const updated = components.filter(
      (c) => !(c.catalogue_item_id === catalogueItemId && c.catalogue_type === 'tyre')
    )
    onChange(updated)
  }

  return (
    <div className="space-y-3">
      <h4 className="text-sm font-medium text-gray-700 dark:text-gray-300">Tyres</h4>

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
          placeholder="Search tyres..."
          className="min-h-[44px] w-full rounded-md border border-gray-300 px-3 py-2 text-sm placeholder-gray-400 dark:border-gray-600 dark:bg-gray-700 dark:text-gray-100 dark:placeholder-gray-500"
          aria-label="Search tyres catalogue"
        />

        {/* Dropdown results */}
        {showDropdown && searchQuery.trim().length >= 2 && (
          <div className="absolute z-10 mt-1 max-h-60 w-full overflow-auto rounded-md border border-gray-200 bg-white shadow-lg dark:border-gray-600 dark:bg-gray-800">
            {loading && (
              <p className="px-3 py-2 text-sm text-gray-500 dark:text-gray-400">Searching...</p>
            )}
            {!loading && (searchResults ?? []).length === 0 && (
              <p className="px-3 py-2 text-sm text-gray-500 dark:text-gray-400">No tyres found</p>
            )}
            {!loading &&
              (searchResults ?? []).map((tyre: PartSearchResult) => {
                const alreadyAdded = components.some((c) => c.catalogue_item_id === tyre.id)
                return (
                  <button
                    key={tyre.id}
                    type="button"
                    disabled={alreadyAdded}
                    onClick={() => handleSelectTyre(tyre)}
                    className={`min-h-[44px] w-full px-3 py-2 text-left text-sm ${
                      alreadyAdded
                        ? 'cursor-not-allowed bg-gray-50 text-gray-400 dark:bg-gray-700/50 dark:text-gray-500'
                        : 'hover:bg-blue-50 dark:hover:bg-blue-900/20'
                    }`}
                  >
                    <span className="font-medium text-gray-900 dark:text-gray-100">
                      {tyre.name}
                    </span>
                    {tyre.part_number && (
                      <span className="ml-2 text-gray-500 dark:text-gray-400">
                        ({tyre.part_number})
                      </span>
                    )}
                    {tyre.brand && (
                      <span className="ml-2 text-xs text-gray-400 dark:text-gray-500">
                        {tyre.brand}
                      </span>
                    )}
                    {alreadyAdded && (
                      <span className="ml-2 text-xs text-gray-400">Already added</span>
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

      {/* Selected tyres list */}
      {tyreComponents.length > 0 && (
        <div className="space-y-2">
          {tyreComponents.map((comp) => (
            <ComponentRow
              key={comp.catalogue_item_id}
              component={comp}
              name={comp.catalogue_item_id}
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
