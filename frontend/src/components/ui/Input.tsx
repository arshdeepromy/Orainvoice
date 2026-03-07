import React from 'react'

interface InputProps extends React.InputHTMLAttributes<HTMLInputElement> {
  label: string
  error?: string
  helperText?: string
}

export function Input({
  label,
  error,
  helperText,
  id,
  className = '',
  ...props
}: InputProps) {
  const inputId = id || label.toLowerCase().replace(/\s+/g, '-')
  const errorId = `${inputId}-error`
  const helperId = `${inputId}-helper`

  return (
    <div className="flex flex-col gap-1">
      <label htmlFor={inputId} className="text-sm font-medium text-gray-700">
        {label}
      </label>
      <input
        id={inputId}
        className={`rounded-md border px-3 py-2 text-gray-900 shadow-sm transition-colors
          placeholder:text-gray-400
          focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-blue-500 focus-visible:ring-offset-2 focus-visible:border-blue-500
          ${error ? 'border-red-500 focus-visible:ring-red-500 focus-visible:border-red-500' : 'border-gray-300'}
          ${className}`}
        aria-invalid={error ? 'true' : undefined}
        aria-describedby={
          [error && errorId, helperText && helperId].filter(Boolean).join(' ') || undefined
        }
        {...props}
      />
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
