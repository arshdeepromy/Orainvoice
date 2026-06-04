import React from 'react'

/**
 * Select — labelled dropdown field (Task 20 port of frontend/src/components/ui/Select).
 *
 * The component API is preserved verbatim from the original (`label`, `options`,
 * `error`, `placeholder`, plus native select props + derived id/aria wiring) so
 * the invoice form + customer modal consume it unchanged. Styling is remapped to
 * the new design system: the prototype's `.field` + `.input` rules from
 * OraInvoice_Handoff/app/ds.css (h-42, ctl radii, accent focus ring) plus a
 * token-coloured chevron, matching the v2 `Input` primitive.
 */
interface SelectOption {
  value: string
  label: string
}

interface SelectProps extends Omit<React.SelectHTMLAttributes<HTMLSelectElement>, 'children'> {
  label: string
  options: SelectOption[]
  error?: string
  placeholder?: string
}

export function Select({
  label,
  options,
  error,
  placeholder,
  id,
  className = '',
  ...props
}: SelectProps) {
  const selectId = id || label.toLowerCase().replace(/\s+/g, '-')
  const errorId = `${selectId}-error`

  return (
    <div className="flex flex-col gap-[7px]">
      {label && (
        <label htmlFor={selectId} className="text-[12.5px] font-medium text-text">
          {label}
        </label>
      )}
      <select
        id={selectId}
        className={`h-[42px] w-full appearance-none rounded-ctl border bg-card px-[13px] text-[13.5px] text-text shadow-sm transition-[border-color,box-shadow] duration-150
          bg-[url('data:image/svg+xml;charset=utf-8,%3Csvg%20xmlns%3D%22http%3A%2F%2Fwww.w3.org%2F2000%2Fsvg%22%20fill%3D%22none%22%20viewBox%3D%220%200%2024%2024%22%20stroke%3D%22%23687283%22%3E%3Cpath%20stroke-linecap%3D%22round%22%20stroke-linejoin%3D%22round%22%20stroke-width%3D%222%22%20d%3D%22M19%209l-7%207-7-7%22%2F%3E%3C%2Fsvg%3E')]
          bg-[length:20px_20px] bg-[right_8px_center] bg-no-repeat pr-10
          focus:outline-none focus:shadow-[0_0_0_3px_var(--accent-soft)]
          ${error ? 'border-danger focus:border-danger' : 'border-border focus:border-accent'}
          ${className}`}
        aria-invalid={error ? 'true' : undefined}
        aria-describedby={error ? errorId : undefined}
        {...props}
      >
        {placeholder && (
          <option value="" disabled>
            {placeholder}
          </option>
        )}
        {options.map((opt) => (
          <option key={opt.value} value={opt.value}>
            {opt.label}
          </option>
        ))}
      </select>
      {error && (
        <p id={errorId} className="text-[12.5px] text-danger" role="alert">
          {error}
        </p>
      )}
    </div>
  )
}

export default Select
