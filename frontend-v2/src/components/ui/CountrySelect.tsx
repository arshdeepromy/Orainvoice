import { useState, useRef, useEffect } from 'react'

/**
 * CountrySelect — searchable country dropdown (Task 13 port of
 * frontend/src/components/ui/CountrySelect).
 *
 * ALL logic is copied verbatim from the original: the COUNTRIES list, the
 * LEGACY_MAP backward-compat resolver, `resolveCountryCode`, the
 * outside-click-to-close effect, the focus-on-open effect, and the
 * search/filter behaviour. Only the markup classes are remapped to the design
 * tokens (the trigger styled as the prototype's `.field` button + `.input`
 * surface; the popover as a token card with shadow-pop; rows hover accent-soft).
 */
export interface Country {
  code: string
  name: string
  flag: string
}

export const COUNTRIES: Country[] = [
  { code: 'NZ', name: 'New Zealand', flag: '🇳🇿' },
  { code: 'AU', name: 'Australia', flag: '🇦🇺' },
  { code: 'US', name: 'United States', flag: '🇺🇸' },
  { code: 'GB', name: 'United Kingdom', flag: '🇬🇧' },
  { code: 'CA', name: 'Canada', flag: '🇨🇦' },
  { code: 'IE', name: 'Ireland', flag: '🇮🇪' },
  { code: 'ZA', name: 'South Africa', flag: '🇿🇦' },
  { code: 'IN', name: 'India', flag: '🇮🇳' },
  { code: 'PH', name: 'Philippines', flag: '🇵🇭' },
  { code: 'FJ', name: 'Fiji', flag: '🇫🇯' },
  { code: 'WS', name: 'Samoa', flag: '🇼🇸' },
  { code: 'TO', name: 'Tonga', flag: '🇹🇴' },
  { code: 'PG', name: 'Papua New Guinea', flag: '🇵🇬' },
  { code: 'SG', name: 'Singapore', flag: '🇸🇬' },
  { code: 'MY', name: 'Malaysia', flag: '🇲🇾' },
  { code: 'JP', name: 'Japan', flag: '🇯🇵' },
  { code: 'KR', name: 'South Korea', flag: '🇰🇷' },
  { code: 'CN', name: 'China', flag: '🇨🇳' },
  { code: 'DE', name: 'Germany', flag: '🇩🇪' },
  { code: 'FR', name: 'France', flag: '🇫🇷' },
  { code: 'IT', name: 'Italy', flag: '🇮🇹' },
  { code: 'ES', name: 'Spain', flag: '🇪🇸' },
  { code: 'PT', name: 'Portugal', flag: '🇵🇹' },
  { code: 'NL', name: 'Netherlands', flag: '🇳🇱' },
  { code: 'SE', name: 'Sweden', flag: '🇸🇪' },
  { code: 'NO', name: 'Norway', flag: '🇳🇴' },
  { code: 'DK', name: 'Denmark', flag: '🇩🇰' },
  { code: 'FI', name: 'Finland', flag: '🇫🇮' },
  { code: 'CH', name: 'Switzerland', flag: '🇨🇭' },
  { code: 'AT', name: 'Austria', flag: '🇦🇹' },
  { code: 'BE', name: 'Belgium', flag: '🇧🇪' },
  { code: 'BR', name: 'Brazil', flag: '🇧🇷' },
  { code: 'MX', name: 'Mexico', flag: '🇲🇽' },
  { code: 'AR', name: 'Argentina', flag: '🇦🇷' },
  { code: 'CL', name: 'Chile', flag: '🇨🇱' },
  { code: 'AE', name: 'United Arab Emirates', flag: '🇦🇪' },
  { code: 'TH', name: 'Thailand', flag: '🇹🇭' },
  { code: 'ID', name: 'Indonesia', flag: '🇮🇩' },
  { code: 'VN', name: 'Vietnam', flag: '🇻🇳' },
  { code: 'PL', name: 'Poland', flag: '🇵🇱' },
  { code: 'CZ', name: 'Czech Republic', flag: '🇨🇿' },
  { code: 'HU', name: 'Hungary', flag: '🇭🇺' },
  { code: 'RO', name: 'Romania', flag: '🇷🇴' },
  { code: 'GR', name: 'Greece', flag: '🇬🇷' },
  { code: 'TR', name: 'Turkey', flag: '🇹🇷' },
  { code: 'IL', name: 'Israel', flag: '🇮🇱' },
  { code: 'EG', name: 'Egypt', flag: '🇪🇬' },
  { code: 'NG', name: 'Nigeria', flag: '🇳🇬' },
  { code: 'KE', name: 'Kenya', flag: '🇰🇪' },
  { code: 'CO', name: 'Colombia', flag: '🇨🇴' },
  { code: 'PE', name: 'Peru', flag: '🇵🇪' },
]

/** Map old free-text values to country codes for backward compat */
const LEGACY_MAP: Record<string, string> = {
  'new zealand': 'NZ',
  'australia': 'AU',
  'united states': 'US',
  'united kingdom': 'GB',
  'canada': 'CA',
  'ireland': 'IE',
  'south africa': 'ZA',
  'india': 'IN',
}

export function resolveCountryCode(value: string): string {
  if (!value) return ''
  // Already a 2-letter code?
  if (value.length === 2 && COUNTRIES.some((c) => c.code === value.toUpperCase())) {
    return value.toUpperCase()
  }
  return LEGACY_MAP[value.toLowerCase()] || value
}

interface CountrySelectProps {
  label?: string
  value: string
  onChange: (code: string) => void
  error?: string
}

export function CountrySelect({ label = 'Country', value, onChange, error }: CountrySelectProps) {
  const [open, setOpen] = useState(false)
  const [search, setSearch] = useState('')
  const ref = useRef<HTMLDivElement>(null)
  const inputRef = useRef<HTMLInputElement>(null)

  const resolved = resolveCountryCode(value)
  const selected = COUNTRIES.find((c) => c.code === resolved)

  const filtered = search
    ? COUNTRIES.filter(
        (c) =>
          c.name.toLowerCase().includes(search.toLowerCase()) ||
          c.code.toLowerCase().includes(search.toLowerCase()),
      )
    : COUNTRIES

  useEffect(() => {
    const handler = (e: MouseEvent) => {
      if (ref.current && !ref.current.contains(e.target as Node)) setOpen(false)
    }
    document.addEventListener('mousedown', handler)
    return () => document.removeEventListener('mousedown', handler)
  }, [])

  useEffect(() => {
    if (open) {
      setSearch('')
      setTimeout(() => inputRef.current?.focus(), 0)
    }
  }, [open])

  const selectId = label.toLowerCase().replace(/\s+/g, '-')
  const errorId = `${selectId}-error`

  return (
    <div className="relative flex flex-col gap-[7px]" ref={ref}>
      {label && (
        <label htmlFor={selectId} className="text-[12.5px] font-medium text-text">
          {label}
        </label>
      )}
      <button
        id={selectId}
        type="button"
        onClick={() => setOpen(!open)}
        className={`h-[42px] w-full rounded-ctl border bg-card px-[13px] text-left text-[13.5px] text-text transition-[border-color,box-shadow] duration-150
          focus:outline-none focus:shadow-[0_0_0_3px_var(--accent-soft)]
          ${error ? 'border-danger' : 'border-border focus:border-accent'}`}
        aria-haspopup="listbox"
        aria-expanded={open}
        aria-invalid={error ? 'true' : undefined}
        aria-describedby={error ? errorId : undefined}
      >
        {selected ? (
          <span className="flex items-center gap-2">
            <span className="text-lg leading-none">{selected.flag}</span>
            <span>{selected.name}</span>
          </span>
        ) : (
          <span className="text-muted-2">Select a country</span>
        )}
      </button>

      {open && (
        <div className="absolute left-0 right-0 top-full z-50 mt-1 max-h-60 overflow-hidden rounded-ctl border border-border bg-card shadow-pop">
          <div className="border-b border-border p-2">
            <input
              ref={inputRef}
              type="text"
              value={search}
              onChange={(e) => setSearch(e.target.value)}
              placeholder="Search countries..."
              className="w-full rounded-ctl border border-border px-3 py-1.5 text-[13px] focus:outline-none focus:border-accent focus:shadow-[0_0_0_3px_var(--accent-soft)]"
            />
          </div>
          <ul role="listbox" className="max-h-48 overflow-y-auto">
            {filtered.map((c) => (
              <li
                key={c.code}
                role="option"
                aria-selected={c.code === resolved}
                className={`flex cursor-pointer items-center gap-2 px-3 py-2 text-[13px] hover:bg-accent-soft ${
                  c.code === resolved ? 'bg-accent-soft font-medium' : ''
                }`}
                onClick={() => {
                  onChange(c.code)
                  setOpen(false)
                }}
              >
                <span className="text-lg leading-none">{c.flag}</span>
                <span>{c.name}</span>
                <span className="ml-auto text-[11px] text-muted-2">{c.code}</span>
              </li>
            ))}
            {filtered.length === 0 && (
              <li className="px-3 py-2 text-[13px] text-muted-2">No countries found</li>
            )}
          </ul>
        </div>
      )}

      {error && (
        <p id={errorId} className="text-[12.5px] text-danger" role="alert">
          {error}
        </p>
      )}
    </div>
  )
}
