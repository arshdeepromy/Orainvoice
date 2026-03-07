import React, { useState, useMemo } from 'react'
import { Badge } from '@/components/ui/Badge'
import type { WizardData, CountryOption } from '../types'
import { COUNTRIES } from '../types'

interface CountryStepProps {
  data: WizardData
  onChange: (updates: Partial<WizardData>) => void
}

export function CountryStep({ data, onChange }: CountryStepProps) {
  const [search, setSearch] = useState('')

  const filtered = useMemo(() => {
    if (!search.trim()) return COUNTRIES
    const q = search.toLowerCase()
    return COUNTRIES.filter(
      (c) =>
        c.name.toLowerCase().includes(q) ||
        c.code.toLowerCase().includes(q) ||
        c.currency.toLowerCase().includes(q),
    )
  }, [search])

  const selectedCountry = COUNTRIES.find((c) => c.code === data.countryCode)

  const handleSelect = (country: CountryOption) => {
    onChange({
      countryCode: country.code,
      currency: country.currency,
      taxLabel: country.taxLabel,
      taxRate: country.taxRate,
      dateFormat: country.dateFormat,
      timezone: country.timezone,
      taxNumberLabel: country.taxNumberLabel,
      taxNumberRegex: country.taxNumberRegex,
    })
  }

  return (
    <div className="space-y-4">
      <h2 className="text-xl font-semibold text-gray-900">Welcome! Where is your business based?</h2>
      <p className="text-sm text-gray-500">
        Select your country to auto-configure currency, tax, and date formats.
      </p>

      <div className="flex flex-col gap-1">
        <label htmlFor="country-search" className="text-sm font-medium text-gray-700">
          Search countries
        </label>
        <input
          id="country-search"
          type="search"
          value={search}
          onChange={(e) => setSearch(e.target.value)}
          placeholder="Type to search..."
          className="rounded-md border border-gray-300 px-3 py-2 text-gray-900 shadow-sm
            placeholder:text-gray-400 focus-visible:outline-none focus-visible:ring-2
            focus-visible:ring-blue-500 focus-visible:border-blue-500"
          aria-label="Search countries"
        />
      </div>

      <div
        className="grid grid-cols-2 sm:grid-cols-3 gap-2 max-h-60 overflow-y-auto"
        role="listbox"
        aria-label="Country selection"
      >
        {filtered.map((country) => (
          <button
            key={country.code}
            type="button"
            role="option"
            aria-selected={data.countryCode === country.code}
            onClick={() => handleSelect(country)}
            className={`flex items-center gap-2 rounded-lg border px-3 py-2 text-left text-sm transition-colors
              focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-blue-500
              ${
                data.countryCode === country.code
                  ? 'border-blue-500 bg-blue-50 text-blue-800 ring-1 ring-blue-500'
                  : 'border-gray-200 hover:border-gray-300 hover:bg-gray-50 text-gray-700'
              }`}
          >
            <span className="font-mono text-xs text-gray-400">{country.code}</span>
            <span className="truncate">{country.name}</span>
          </button>
        ))}
        {filtered.length === 0 && (
          <p className="col-span-full text-sm text-gray-500 py-4 text-center">
            No countries match your search.
          </p>
        )}
      </div>

      {selectedCountry && (
        <div className="rounded-lg border border-blue-200 bg-blue-50 p-4 space-y-2">
          <p className="text-sm font-medium text-blue-800">
            Auto-configured for {selectedCountry.name}:
          </p>
          <div className="flex flex-wrap gap-2">
            <Badge variant="info">Currency: {selectedCountry.currency}</Badge>
            <Badge variant="info">{selectedCountry.taxLabel}: {selectedCountry.taxRate}%</Badge>
            <Badge variant="info">Date: {selectedCountry.dateFormat}</Badge>
            <Badge variant="info">Timezone: {selectedCountry.timezone}</Badge>
          </div>
        </div>
      )}
    </div>
  )
}
