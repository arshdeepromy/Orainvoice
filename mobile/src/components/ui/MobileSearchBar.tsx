import { useCallback, useEffect, useRef, useState } from 'react'

export interface MobileSearchBarProps {
  /** Current search value (controlled) */
  value: string
  /** Called with the debounced search value */
  onChange: (value: string) => void
  /** Placeholder text */
  placeholder?: string
  /** Debounce delay in ms (default: 300) */
  debounceMs?: number
  /** Additional CSS classes */
  className?: string
}

/**
 * Search input with debounced onChange, clear button, and search icon.
 *
 * - 44px min height touch target
 * - Debounced onChange to avoid excessive API calls
 * - Clear button to reset search
 * - Search icon for visual affordance
 * - Dark mode support
 *
 * Requirements: 7.2, 8.1, 9.1
 */
export function MobileSearchBar({
  value,
  onChange,
  placeholder = 'Search…',
  debounceMs = 300,
  className = '',
}: MobileSearchBarProps) {
  const [localValue, setLocalValue] = useState(value)
  const timerRef = useRef<ReturnType<typeof setTimeout> | null>(null)

  // Sync external value changes
  useEffect(() => {
    setLocalValue(value)
  }, [value])

  const handleChange = useCallback(
    (newValue: string) => {
      setLocalValue(newValue)
      if (timerRef.current) clearTimeout(timerRef.current)
      timerRef.current = setTimeout(() => {
        onChange(newValue)
      }, debounceMs)
    },
    [onChange, debounceMs],
  )

  // Cleanup timer on unmount
  useEffect(() => {
    return () => {
      if (timerRef.current) clearTimeout(timerRef.current)
    }
  }, [])

  const handleClear = useCallback(() => {
    setLocalValue('')
    if (timerRef.current) clearTimeout(timerRef.current)
    onChange('')
  }, [onChange])

  return (
    <div className={`relative ${className}`}>
      {/* Search icon */}
      <svg
        className="pointer-events-none absolute left-3 top-1/2 h-5 w-5 -translate-y-1/2 text-gray-400 dark:text-gray-500"
        viewBox="0 0 24 24"
        fill="none"
        stroke="currentColor"
        strokeWidth="2"
        strokeLinecap="round"
        strokeLinejoin="round"
        aria-hidden="true"
      >
        <circle cx="11" cy="11" r="8" />
        <path d="m21 21-4.3-4.3" />
      </svg>

      <input
        type="search"
        value={localValue}
        onChange={(e) => handleChange(e.target.value)}
        placeholder={placeholder}
        className="min-h-[44px] w-full rounded-lg border border-gray-300 bg-gray-50 py-2 pl-10 pr-10 text-base text-gray-900 placeholder-gray-400 transition-colors focus:border-blue-500 focus:outline-none focus:ring-2 focus:ring-blue-500 dark:border-gray-600 dark:bg-gray-800 dark:text-gray-100 dark:placeholder-gray-500 dark:focus:border-blue-400 dark:focus:ring-blue-400"
        role="searchbox"
        aria-label={placeholder}
      />

      {/* Clear button */}
      {localValue && (
        <button
          type="button"
          onClick={handleClear}
          className="absolute right-2 top-1/2 flex h-7 w-7 -translate-y-1/2 items-center justify-center rounded-full text-gray-400 hover:text-gray-600 dark:text-gray-500 dark:hover:text-gray-300"
          aria-label="Clear search"
        >
          <svg
            className="h-4 w-4"
            viewBox="0 0 24 24"
            fill="none"
            stroke="currentColor"
            strokeWidth="2"
            strokeLinecap="round"
            strokeLinejoin="round"
            aria-hidden="true"
          >
            <path d="M18 6 6 18" />
            <path d="m6 6 12 12" />
          </svg>
        </button>
      )}
    </div>
  )
}
