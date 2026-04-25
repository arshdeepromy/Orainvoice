import { forwardRef, useId } from 'react'
import type { InputHTMLAttributes } from 'react'

export interface MobileInputProps
  extends Omit<InputHTMLAttributes<HTMLInputElement>, 'className'> {
  /** Field label */
  label?: string
  /** Error message — shows red border and message below */
  error?: string
  /** Helper text shown below the input */
  helperText?: string
  /** Additional CSS classes for the wrapper */
  className?: string
}

/**
 * Form input with label, error state, and 44px touch target.
 *
 * - 44px min height for touch accessibility
 * - Error state with red border and message
 * - Dark mode support
 * - Accessible: label linked via htmlFor/id
 *
 * Requirements: 1.3
 */
export const MobileInput = forwardRef<HTMLInputElement, MobileInputProps>(
  function MobileInput(
    { label, error, helperText, className = '', id: externalId, ...rest },
    ref,
  ) {
    const generatedId = useId()
    const inputId = externalId ?? generatedId
    const errorId = error ? `${inputId}-error` : undefined
    const helperId = helperText && !error ? `${inputId}-helper` : undefined

    return (
      <div className={`flex flex-col gap-1 ${className}`}>
        {label && (
          <label
            htmlFor={inputId}
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
        <input
          ref={ref}
          id={inputId}
          className={`min-h-[44px] rounded-lg border px-3 py-2 text-base text-gray-900 placeholder-gray-400 transition-colors focus:outline-none focus:ring-2 dark:bg-gray-800 dark:text-gray-100 dark:placeholder-gray-500 ${
            error
              ? 'border-red-500 focus:ring-red-500 dark:border-red-400'
              : 'border-gray-300 focus:ring-blue-500 dark:border-gray-600 dark:focus:ring-blue-400'
          }`}
          aria-invalid={error ? true : undefined}
          aria-describedby={errorId ?? helperId}
          {...rest}
        />
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
