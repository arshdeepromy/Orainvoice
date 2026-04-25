import type { ReactNode } from 'react'

export interface MobileFormFieldProps {
  /** Field label */
  label: string
  /** Whether the field is required — shows red asterisk */
  required?: boolean
  /** Error message */
  error?: string
  /** Helper text */
  helperText?: string
  /** The form control (input, select, etc.) */
  children: ReactNode
  /** Additional CSS classes */
  className?: string
}

/**
 * Form field wrapper with label, required indicator, error, and helper text.
 *
 * Use this to wrap custom form controls that aren't MobileInput/MobileSelect
 * (which have their own label/error handling).
 *
 * Requirements: 7.5, 8.3
 */
export function MobileFormField({
  label,
  required = false,
  error,
  helperText,
  children,
  className = '',
}: MobileFormFieldProps) {
  return (
    <div className={`flex flex-col gap-1 ${className}`}>
      <span className="text-sm font-medium text-gray-700 dark:text-gray-300">
        {label}
        {required && (
          <span className="ml-0.5 text-red-500" aria-hidden="true">
            *
          </span>
        )}
      </span>
      {children}
      {error && (
        <p className="text-sm text-red-600 dark:text-red-400" role="alert">
          {error}
        </p>
      )}
      {helperText && !error && (
        <p className="text-sm text-gray-500 dark:text-gray-400">{helperText}</p>
      )}
    </div>
  )
}
