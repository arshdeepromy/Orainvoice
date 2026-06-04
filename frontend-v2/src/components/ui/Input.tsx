import React from 'react'

/**
 * Input — labelled text field (Task 13 port of frontend/src/components/ui/Input).
 *
 * The component API is preserved verbatim from the original (`label`, `error`,
 * `helperText`, plus all native input props + derived id/aria wiring) so every
 * auth page that consumes it keeps its exact behaviour. Only the styling is
 * remapped to the new design system: the prototype's `.field` + `.input` rules
 * from OraInvoice_Handoff/app/ds.css —
 *   .field  flex column, gap 7px; label 12.5px / 500 / text colour.
 *   .input  h-42, px-13, 1px border, rounded-ctl (10px), card bg, 13.5px text,
 *           focus → accent border + 3px accent-soft ring.
 * Error state swaps the border/ring to the danger token; the muted-2 token is
 * used for the placeholder, matching the prototype.
 */
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
    <div className="flex flex-col gap-[7px]">
      {label && (
        <label htmlFor={inputId} className="text-[12.5px] font-medium text-text">
          {label}
        </label>
      )}
      <input
        id={inputId}
        className={`h-[42px] w-full rounded-ctl border bg-card px-[13px] text-[13.5px] text-text transition-[border-color,box-shadow] duration-150
          placeholder:text-muted-2
          focus:outline-none focus:shadow-[0_0_0_3px_var(--accent-soft)]
          ${error ? 'border-danger focus:border-danger' : 'border-border focus:border-accent'}
          ${className}`}
        aria-invalid={error ? 'true' : undefined}
        aria-describedby={
          [error && errorId, helperText && helperId].filter(Boolean).join(' ') || undefined
        }
        {...props}
      />
      {error && (
        <p id={errorId} className="text-[12.5px] text-danger" role="alert">
          {error}
        </p>
      )}
      {helperText && !error && (
        <p id={helperId} className="text-[12px] text-muted">
          {helperText}
        </p>
      )}
    </div>
  )
}
