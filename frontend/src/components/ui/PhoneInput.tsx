import { useState, useRef, useEffect } from 'react'

/* ------------------------------------------------------------------ */
/*  Country Codes Data                                                 */
/* ------------------------------------------------------------------ */

interface CountryCode {
  code: string
  country: string
  dialCode: string
  flag: string
}

const COUNTRY_CODES: CountryCode[] = [
  { code: 'NZ', country: 'New Zealand', dialCode: '+64', flag: '🇳🇿' },
  { code: 'AU', country: 'Australia', dialCode: '+61', flag: '🇦🇺' },
  { code: 'US', country: 'United States', dialCode: '+1', flag: '🇺🇸' },
  { code: 'GB', country: 'United Kingdom', dialCode: '+44', flag: '🇬🇧' },
  { code: 'CA', country: 'Canada', dialCode: '+1', flag: '🇨🇦' },
  { code: 'IN', country: 'India', dialCode: '+91', flag: '🇮🇳' },
  { code: 'CN', country: 'China', dialCode: '+86', flag: '🇨🇳' },
  { code: 'JP', country: 'Japan', dialCode: '+81', flag: '🇯🇵' },
  { code: 'KR', country: 'South Korea', dialCode: '+82', flag: '🇰🇷' },
  { code: 'DE', country: 'Germany', dialCode: '+49', flag: '🇩🇪' },
  { code: 'FR', country: 'France', dialCode: '+33', flag: '🇫🇷' },
  { code: 'IT', country: 'Italy', dialCode: '+39', flag: '🇮🇹' },
  { code: 'ES', country: 'Spain', dialCode: '+34', flag: '🇪🇸' },
  { code: 'NL', country: 'Netherlands', dialCode: '+31', flag: '🇳🇱' },
  { code: 'BE', country: 'Belgium', dialCode: '+32', flag: '🇧🇪' },
  { code: 'CH', country: 'Switzerland', dialCode: '+41', flag: '🇨🇭' },
  { code: 'AT', country: 'Austria', dialCode: '+43', flag: '🇦🇹' },
  { code: 'SE', country: 'Sweden', dialCode: '+46', flag: '🇸🇪' },
  { code: 'NO', country: 'Norway', dialCode: '+47', flag: '🇳🇴' },
  { code: 'DK', country: 'Denmark', dialCode: '+45', flag: '🇩🇰' },
  { code: 'FI', country: 'Finland', dialCode: '+358', flag: '🇫🇮' },
  { code: 'IE', country: 'Ireland', dialCode: '+353', flag: '🇮🇪' },
  { code: 'PT', country: 'Portugal', dialCode: '+351', flag: '🇵🇹' },
  { code: 'PL', country: 'Poland', dialCode: '+48', flag: '🇵🇱' },
  { code: 'RU', country: 'Russia', dialCode: '+7', flag: '🇷🇺' },
  { code: 'BR', country: 'Brazil', dialCode: '+55', flag: '🇧🇷' },
  { code: 'MX', country: 'Mexico', dialCode: '+52', flag: '🇲🇽' },
  { code: 'AR', country: 'Argentina', dialCode: '+54', flag: '🇦🇷' },
  { code: 'CL', country: 'Chile', dialCode: '+56', flag: '🇨🇱' },
  { code: 'CO', country: 'Colombia', dialCode: '+57', flag: '🇨🇴' },
  { code: 'PE', country: 'Peru', dialCode: '+51', flag: '🇵🇪' },
  { code: 'ZA', country: 'South Africa', dialCode: '+27', flag: '🇿🇦' },
  { code: 'EG', country: 'Egypt', dialCode: '+20', flag: '🇪🇬' },
  { code: 'NG', country: 'Nigeria', dialCode: '+234', flag: '🇳🇬' },
  { code: 'KE', country: 'Kenya', dialCode: '+254', flag: '🇰🇪' },
  { code: 'AE', country: 'United Arab Emirates', dialCode: '+971', flag: '🇦🇪' },
  { code: 'SA', country: 'Saudi Arabia', dialCode: '+966', flag: '🇸🇦' },
  { code: 'IL', country: 'Israel', dialCode: '+972', flag: '🇮🇱' },
  { code: 'TR', country: 'Turkey', dialCode: '+90', flag: '🇹🇷' },
  { code: 'TH', country: 'Thailand', dialCode: '+66', flag: '🇹🇭' },
  { code: 'VN', country: 'Vietnam', dialCode: '+84', flag: '🇻🇳' },
  { code: 'MY', country: 'Malaysia', dialCode: '+60', flag: '🇲🇾' },
  { code: 'SG', country: 'Singapore', dialCode: '+65', flag: '🇸🇬' },
  { code: 'PH', country: 'Philippines', dialCode: '+63', flag: '🇵🇭' },
  { code: 'ID', country: 'Indonesia', dialCode: '+62', flag: '🇮🇩' },
  { code: 'PK', country: 'Pakistan', dialCode: '+92', flag: '🇵🇰' },
  { code: 'BD', country: 'Bangladesh', dialCode: '+880', flag: '🇧🇩' },
  { code: 'LK', country: 'Sri Lanka', dialCode: '+94', flag: '🇱🇰' },
  { code: 'NP', country: 'Nepal', dialCode: '+977', flag: '🇳🇵' },
  { code: 'FJ', country: 'Fiji', dialCode: '+679', flag: '🇫🇯' },
  { code: 'WS', country: 'Samoa', dialCode: '+685', flag: '🇼🇸' },
  { code: 'TO', country: 'Tonga', dialCode: '+676', flag: '🇹🇴' },
  { code: 'PG', country: 'Papua New Guinea', dialCode: '+675', flag: '🇵🇬' },
]

// Map country names to codes for org settings lookup
const COUNTRY_NAME_TO_CODE: Record<string, string> = {
  'new zealand': 'NZ',
  'australia': 'AU',
  'united states': 'US',
  'usa': 'US',
  'united kingdom': 'GB',
  'uk': 'GB',
  'canada': 'CA',
  'india': 'IN',
  // Add more as needed
}

export function getCountryCodeFromName(countryName: string): string {
  const normalized = countryName.toLowerCase().trim()
  return COUNTRY_NAME_TO_CODE[normalized] || 'NZ'
}

export function getDialCodeForCountry(countryCode: string): string {
  const country = COUNTRY_CODES.find(c => c.code === countryCode)
  return country?.dialCode || '+64'
}

/* ------------------------------------------------------------------ */
/*  Phone Input Component                                              */
/* ------------------------------------------------------------------ */

interface PhoneInputProps {
  label: string
  value: string
  onChange: (value: string) => void
  countryCode?: string
  onCountryCodeChange?: (code: string) => void
  error?: string
  placeholder?: string
  required?: boolean
}

export function PhoneInput({
  label,
  value,
  onChange,
  countryCode = 'NZ',
  onCountryCodeChange,
  error,
  placeholder = 'Phone number',
  required = false,
}: PhoneInputProps) {
  const [showDropdown, setShowDropdown] = useState(false)
  const [search, setSearch] = useState('')
  const [selectedCountry, setSelectedCountry] = useState(() => 
    COUNTRY_CODES.find(c => c.code === countryCode) || COUNTRY_CODES[0]
  )
  const containerRef = useRef<HTMLDivElement>(null)
  const searchInputRef = useRef<HTMLInputElement>(null)

  // Update selected country when prop changes
  useEffect(() => {
    const country = COUNTRY_CODES.find(c => c.code === countryCode)
    if (country) setSelectedCountry(country)
  }, [countryCode])

  // Click outside to close
  useEffect(() => {
    const handleClickOutside = (e: MouseEvent) => {
      if (containerRef.current && !containerRef.current.contains(e.target as Node)) {
        setShowDropdown(false)
        setSearch('')
      }
    }
    document.addEventListener('mousedown', handleClickOutside)
    return () => document.removeEventListener('mousedown', handleClickOutside)
  }, [])

  // Focus search input when dropdown opens
  useEffect(() => {
    if (showDropdown && searchInputRef.current) {
      searchInputRef.current.focus()
    }
  }, [showDropdown])

  // Filter countries based on search
  const filteredCountries = COUNTRY_CODES.filter(c =>
    c.country.toLowerCase().includes(search.toLowerCase()) ||
    c.dialCode.includes(search) ||
    c.code.toLowerCase().includes(search.toLowerCase())
  )

  // Format phone number - remove leading 0
  const handlePhoneChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    let phoneValue = e.target.value
    
    // Remove any non-digit characters except for formatting
    phoneValue = phoneValue.replace(/[^\d\s\-]/g, '')
    
    // Remove leading 0 (common in NZ/AU numbers)
    if (phoneValue.startsWith('0')) {
      phoneValue = phoneValue.substring(1)
    }
    
    onChange(phoneValue)
  }

  const handleCountrySelect = (country: CountryCode) => {
    setSelectedCountry(country)
    onCountryCodeChange?.(country.code)
    setShowDropdown(false)
    setSearch('')
  }

  return (
    <div className="flex flex-col gap-1">
      <label className="text-sm font-medium text-gray-700">
        {label}{required && ' *'}
      </label>
      <div ref={containerRef} className="flex gap-2">
        {/* Country Code Selector */}
        <div className="relative">
          <button
            type="button"
            onClick={() => setShowDropdown(!showDropdown)}
            className="h-[42px] flex items-center gap-1 rounded-md border border-gray-300 bg-white px-3 py-2 text-sm text-gray-900 shadow-sm hover:bg-gray-50 focus:outline-none focus:ring-2 focus:ring-blue-500 min-w-[90px]"
          >
            <span className="text-base">{selectedCountry.flag}</span>
            <span>{selectedCountry.dialCode}</span>
            <svg className="h-4 w-4 text-gray-400 ml-auto" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M19 9l-7 7-7-7" />
            </svg>
          </button>

          {showDropdown && (
            <div className="absolute top-full left-0 z-50 mt-1 w-64 rounded-md border border-gray-200 bg-white shadow-lg">
              {/* Search input */}
              <div className="p-2 border-b border-gray-100">
                <input
                  ref={searchInputRef}
                  type="text"
                  value={search}
                  onChange={(e) => setSearch(e.target.value)}
                  placeholder="Search country..."
                  className="w-full rounded border border-gray-300 px-2 py-1.5 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
                />
              </div>
              {/* Country list */}
              <div className="max-h-48 overflow-auto">
                {filteredCountries.map((country) => (
                  <button
                    key={country.code}
                    type="button"
                    onClick={() => handleCountrySelect(country)}
                    className={`w-full flex items-center gap-2 px-3 py-2 text-sm text-left hover:bg-blue-50 ${
                      selectedCountry.code === country.code ? 'bg-blue-50 text-blue-700' : 'text-gray-900'
                    }`}
                  >
                    <span className="text-base">{country.flag}</span>
                    <span className="flex-1">{country.country}</span>
                    <span className="text-gray-500">{country.dialCode}</span>
                  </button>
                ))}
                {filteredCountries.length === 0 && (
                  <div className="px-3 py-2 text-sm text-gray-500">No countries found</div>
                )}
              </div>
            </div>
          )}
        </div>

        {/* Phone Number Input */}
        <input
          type="tel"
          value={value}
          onChange={handlePhoneChange}
          placeholder={placeholder}
          className={`h-[42px] flex-1 rounded-md border px-3 py-2 text-gray-900 shadow-sm transition-colors
            placeholder:text-gray-400
            focus:outline-none focus:ring-2 focus:ring-blue-500 focus:border-blue-500
            ${error ? 'border-red-500' : 'border-gray-300'}`}
        />
      </div>
      {error && (
        <p className="text-sm text-red-600" role="alert">{error}</p>
      )}
    </div>
  )
}

export { COUNTRY_CODES }
export type { CountryCode }
