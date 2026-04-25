import type { ReactNode, KeyboardEvent } from 'react'

export interface MobileListItemProps {
  /** Primary text (e.g. name, title) */
  title: string
  /** Secondary text (e.g. email, description) */
  subtitle?: string
  /** Right-side content (e.g. amount, status badge) */
  trailing?: ReactNode
  /** Left-side content (e.g. avatar, icon) */
  leading?: ReactNode
  /** Tap handler */
  onTap?: () => void
  /** Additional CSS classes */
  className?: string
}

/**
 * Generic list item with title, subtitle, leading/trailing content, and tap handler.
 *
 * - 44px min height touch target
 * - Divider line between items (via border-b)
 * - Dark mode support
 * - Accessible: role="button" + keyboard support when tappable
 *
 * Requirements: 7.1, 8.1
 */
export function MobileListItem({
  title,
  subtitle,
  trailing,
  leading,
  onTap,
  className = '',
}: MobileListItemProps) {
  const isInteractive = !!onTap

  const handleKeyDown = (e: KeyboardEvent<HTMLDivElement>) => {
    if (onTap && (e.key === 'Enter' || e.key === ' ')) {
      e.preventDefault()
      onTap()
    }
  }

  return (
    <div
      className={`flex min-h-[44px] items-center gap-3 border-b border-gray-100 px-4 py-3 dark:border-gray-700 ${
        isInteractive
          ? 'cursor-pointer active:bg-gray-50 dark:active:bg-gray-800'
          : ''
      } ${className}`}
      role={isInteractive ? 'button' : undefined}
      tabIndex={isInteractive ? 0 : undefined}
      onClick={onTap}
      onKeyDown={isInteractive ? handleKeyDown : undefined}
    >
      {/* Leading content */}
      {leading && (
        <div className="flex-shrink-0" aria-hidden="true">
          {leading}
        </div>
      )}

      {/* Text content */}
      <div className="min-w-0 flex-1">
        <p className="truncate text-base font-medium text-gray-900 dark:text-gray-100">
          {title}
        </p>
        {subtitle && (
          <p className="truncate text-sm text-gray-500 dark:text-gray-400">
            {subtitle}
          </p>
        )}
      </div>

      {/* Trailing content */}
      {trailing && <div className="flex-shrink-0">{trailing}</div>}

      {/* Chevron for tappable items */}
      {isInteractive && (
        <svg
          className="h-5 w-5 flex-shrink-0 text-gray-400 dark:text-gray-500"
          viewBox="0 0 24 24"
          fill="none"
          stroke="currentColor"
          strokeWidth="2"
          strokeLinecap="round"
          strokeLinejoin="round"
          aria-hidden="true"
        >
          <path d="m9 18 6-6-6-6" />
        </svg>
      )}
    </div>
  )
}
