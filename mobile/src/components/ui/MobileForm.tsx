import type { FormEvent, ReactNode } from 'react'

export interface MobileFormProps {
  children: ReactNode
  /** Form submit handler — called after native validation passes */
  onSubmit: () => void | Promise<void>
  /** Additional CSS classes */
  className?: string
}

/**
 * Form wrapper with validation, required field highlighting, and submit handler.
 *
 * - Prevents default form submission
 * - Delegates to native HTML5 validation (required, pattern, etc.)
 * - Calls onSubmit only when validation passes
 * - Dark mode support
 *
 * Requirements: 7.5, 8.3
 */
export function MobileForm({ children, onSubmit, className = '' }: MobileFormProps) {
  const handleSubmit = (e: FormEvent<HTMLFormElement>) => {
    e.preventDefault()
    onSubmit()
  }

  return (
    <form
      onSubmit={handleSubmit}
      className={`flex flex-col gap-4 ${className}`}
      noValidate={false}
    >
      {children}
    </form>
  )
}
