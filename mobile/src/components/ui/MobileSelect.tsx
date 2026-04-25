import { forwardRef, useId } from 'react'
import type { SelectHTMLAttributes } from 'react'

export interface MobileSelectOption {
  value: string
  label: string
  disabled?: boolean
}

export interface MobileSelectProps
  extends Omit<SelectHTMLAttributes<HTMLSelectElement>, 'className'> {
  /** Field label */
  label?: string
  /** Error message — shows red border and message below */
  error?: string
  /** Helper text shown below the select */
  helperText?: string
  /** Select options */
  options: MobileSelectOption[]
  /** Placeholder text for the empty option */
  placeholder?: string
  /** Additional CSS classes for the wrapper */
  className?: string
}

/**
 * Form select with label, error state, and 44px touch target.
 *
 * - 44px min height for touch accessibility
 * - Error state with red border and message
 * - Dark mode support
 * - Accessible: label linked via htmlFor/id
 *
 * Requirements: 1.3
 */
export const MobileSelect = forwardRef<HTMLSelectElement, MobileSelectProps>(
  function MobileSelect(
    {
      label,
      error,
      helperText,
      options,
      placeholder,
      className = '',
      id: externalId,
      ...rest
    },
    ref,
  ) {
    const generatedId = useId()
    const selectId = externalId ?? generatedId
    const errorId = error ? `${selectId}-error` : undefined
    const helperId = helperText && !error ? `${selectId}-helper` : undefined

    return (
      <div className={`flex flex-col gap-1 ${className}`}>
        {label && (
          <label
            htmlFor={selectId}
            className="text-sm font-medium text-gray-700 dark:text-gray-300"
          >
            {label}
            {rest.required && (
              <span className="ml-0.5 text-red-500" aria-hidden="true">
                *
              </span>
            )}
          </label>
        )}
        <select
          ref={ref}
          id={selectId}
          className={`min-h-[44px] appearance-none rounded-lg border bg-white px-3 py-2 text-base text-gray-900 transition-colors focus:outline-none focus:ring-2 dark:bg-gray-800 dark:text-gray-100 ${
            error
              ? 'border-red-500 focus:ring-red-500 dark:border-red-400'
              : 'border-gray-300 focus:ring-blue-500 dark:border-gray-600 dark:focus:ring-blue-400'
          }`}
          aria-invalid={error ? true : undefined}
          aria-describedby={errorId ?? helperId}
          {...rest}
        >
          {placeholder && (
            <option value="" disabled>
              {placeholder}
            </option>
          )}
          {options.map((opt) => (
            <option key={opt.value} value={opt.value} disabled={opt.disabled}>
              {opt.label}
            </option>
          ))}
        </select>
        {error && (
          <p id={errorId} className="text-sm text-red-600 dark:text-red-400" role="alert">
            {error}
          </p>
        )}
        {helperText && !error && (
          <p id={helperId} className="text-sm text-gray-500 dark:text-gray-400">
            {helperText}
          </p>
        )}
      </div>
    )
  },
)
