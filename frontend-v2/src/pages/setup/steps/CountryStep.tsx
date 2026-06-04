import { useState, useMemo } from 'react'
import { Badge } from '@/components/ui'
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
      <h2 className="text-xl font-semibold text-text">Welcome! Where is your business based?</h2>
      <p className="text-sm text-muted">
        Select your country to auto-configure currency, tax, and date formats.
      </p>

      <div className="flex flex-col gap-1">
        <label htmlFor="country-search" className="text-sm font-medium text-text">
          Search countries
        </label>
        <input
          id="country-search"
          type="search"
          value={search}
          onChange={(e) => setSearch(e.target.value)}
          placeholder="Type to search..."
          className="rounded-ctl border border-border bg-card px-3 py-2 text-text shadow-sm
            placeholder:text-muted-2 focus-visible:outline-none focus-visible:ring-2
            focus-visible:ring-accent focus-visible:border-accent"
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
            className={`flex items-center gap-2 rounded-ctl border px-3 py-2 text-left text-sm transition-colors
              focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent
              ${
                data.countryCode === country.code
                  ? 'border-accent bg-accent-soft text-accent ring-1 ring-accent'
                  : 'border-border hover:border-border-strong hover:bg-canvas text-text'
              }`}
          >
            <span className="font-mono text-xs text-muted-2">{country.code}</span>
            <span className="truncate">{country.name}</span>
          </button>
        ))}
        {filtered.length === 0 && (
          <p className="col-span-full text-sm text-muted py-4 text-center">
            No countries match your search.
          </p>
        )}
      </div>

      {selectedCountry && (
        <div className="rounded-card border border-accent/30 bg-accent-soft p-4 space-y-2">
          <p className="text-sm font-medium text-accent">
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
