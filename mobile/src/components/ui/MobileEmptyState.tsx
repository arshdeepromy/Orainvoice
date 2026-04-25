import type { ReactNode } from 'react'

export interface MobileEmptyStateProps {
  /** Message to display */
  message: string
  /** Optional icon (defaults to a generic empty icon) */
  icon?: ReactNode
  /** Optional action button */
  action?: ReactNode
  /** Additional CSS classes */
  className?: string
}

/**
 * Empty list placeholder with icon and message.
 *
 * - Centered layout
 * - Default empty state icon
 * - Optional action button (e.g. "Create first item")
 * - Dark mode support
 *
 * Requirements: 1.3, 1.5, 1.6
 */
export function MobileEmptyState({
  message,
  icon,
  action,
  className = '',
}: MobileEmptyStateProps) {
  return (
    <div
      className={`flex flex-col items-center justify-center px-8 py-16 ${className}`}
    >
      {icon ?? (
        <svg
          className="mb-4 h-16 w-16 text-gray-300 dark:text-gray-600"
          viewBox="0 0 24 24"
          fill="none"
          stroke="currentColor"
          strokeWidth="1"
          strokeLinecap="round"
          strokeLinejoin="round"
          aria-hidden="true"
        >
          <path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z" />
          <polyline points="14 2 14 8 20 8" />
          <line x1="12" y1="18" x2="12" y2="12" />
          <line x1="9" y1="15" x2="15" y2="15" />
        </svg>
      )}
      <p className="text-center text-base text-gray-500 dark:text-gray-400">{message}</p>
      {action && <div className="mt-4">{action}</div>}
    </div>
  )
}
