import React, { useId } from 'react'

interface FormFieldProps {
  label: string
  error?: string
  helperText?: string
  required?: boolean
  children: (props: { id: string; 'aria-invalid'?: 'true'; 'aria-describedby'?: string }) => React.ReactNode
  className?: string
}

export function FormField({
  label,
  error,
  helperText,
  required = false,
  children,
  className = '',
}: FormFieldProps) {
  const generatedId = useId()
  const fieldId = `field-${generatedId}`
  const errorId = `${fieldId}-error`
  const helperId = `${fieldId}-helper`

  const describedBy = [error && errorId, helperText && !error && helperId]
    .filter(Boolean)
    .join(' ') || undefined

  const childProps = {
    id: fieldId,
    ...(error ? { 'aria-invalid': 'true' as const } : {}),
    ...(describedBy ? { 'aria-describedby': describedBy } : {}),
  }

  return (
    <div className={`flex flex-col gap-1 ${className}`}>
      <label htmlFor={fieldId} className="text-sm font-medium text-gray-700">
        {label}
        {required && <span className="ml-1 text-red-500" aria-hidden="true">*</span>}
        {required && <span className="sr-only"> (required)</span>}
      </label>
      {children(childProps)}
      {error && (
        <p id={errorId} className="text-sm text-red-600" role="alert">
          {error}
        </p>
      )}
      {helperText && !error && (
        <p id={helperId} className="text-sm text-gray-500">
          {helperText}
        </p>
      )}
    </div>
  )
}
