import React, { useId } from 'react'

/**
 * FormField — labelled form-control wrapper with error / helper text wiring.
 *
 * API ported VERBATIM from frontend/src/components/ui/FormField.tsx (Task 19)
 * so the credit-note / refund modals (and Task 22's modals) drop in unchanged:
 * the render-prop passes the derived `id` + aria attributes down to the field.
 * Only the styling is remapped onto the design-system tokens (`text`, `muted`,
 * `danger`) to match the prototype's `.field` language.
 */
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
    <div className={`flex flex-col gap-[7px] ${className}`}>
      <label htmlFor={fieldId} className="text-[12.5px] font-medium text-text">
        {label}
        {required && <span className="ml-1 text-danger" aria-hidden="true">*</span>}
        {required && <span className="sr-only"> (required)</span>}
      </label>
      {children(childProps)}
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

export default FormField
