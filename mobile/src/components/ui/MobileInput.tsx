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
  /** Prefix symbol rendered inside the input (e.g. "$") */
  prefix?: string
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
    { label, error, helperText, className = '', id: externalId, prefix, ...rest },
    ref,
  ) {
    const generatedId = useId()
    const inputId = externalId ?? generatedId
    const errorId = error ? `${inputId}-error` : undefined
    const helperId = helperText && !error ? `${inputId}-helper` : undefined

    const borderClass = error
      ? 'border-red-500 focus-within:ring-2 focus-within:ring-red-500 dark:border-red-400'
      : 'border-gray-300 focus-within:ring-2 focus-within:ring-blue-500 dark:border-gray-600 dark:focus-within:ring-blue-400'

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
        <div
          className={`flex min-h-[44px] items-center rounded-lg border transition-colors dark:bg-gray-800 ${borderClass}`}
        >
          {prefix && (
            <span className="select-none pl-3 text-base text-gray-500 dark:text-gray-400">
              {prefix}
            </span>
          )}
          <input
            ref={ref}
            id={inputId}
            className={`min-h-[44px] w-full bg-transparent py-2 text-base text-gray-900 placeholder-gray-400 focus:outline-none dark:text-gray-100 dark:placeholder-gray-500 ${prefix ? 'pl-1 pr-3' : 'px-3'}`}
            aria-invalid={error ? true : undefined}
            aria-describedby={errorId ?? helperId}
            {...rest}
          />
        </div>
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
