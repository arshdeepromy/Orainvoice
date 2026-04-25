import type { ReactNode, MouseEvent, KeyboardEvent } from 'react'

export interface MobileCardProps {
  children: ReactNode
  /** Optional tap handler — makes the card interactive */
  onTap?: () => void
  /** Additional CSS classes */
  className?: string
  /** Padding override (default: p-4) */
  padding?: string
}

/**
 * Card container with shadow, rounded corners, dark mode support, and optional tap handler.
 *
 * - Rounded corners (rounded-xl)
 * - Shadow in light mode, subtle border in dark mode
 * - 44px min touch target when tappable
 * - Accessible: role="button" + keyboard support when tappable
 *
 * Requirements: 1.3, 1.5, 1.6
 */
export function MobileCard({
  children,
  onTap,
  className = '',
  padding = 'p-4',
}: MobileCardProps) {
  const isInteractive = !!onTap

  const handleKeyDown = (e: KeyboardEvent<HTMLDivElement>) => {
    if (onTap && (e.key === 'Enter' || e.key === ' ')) {
      e.preventDefault()
      onTap()
    }
  }

  const handleClick = (e: MouseEvent<HTMLDivElement>) => {
    if (onTap) {
      e.stopPropagation()
      onTap()
    }
  }

  return (
    <div
      className={`rounded-xl bg-white shadow-sm ring-1 ring-gray-100 dark:bg-gray-800 dark:ring-gray-700 ${padding} ${
        isInteractive
          ? 'min-h-[44px] cursor-pointer active:bg-gray-50 dark:active:bg-gray-700'
          : ''
      } ${className}`}
      role={isInteractive ? 'button' : undefined}
      tabIndex={isInteractive ? 0 : undefined}
      onClick={isInteractive ? handleClick : undefined}
      onKeyDown={isInteractive ? handleKeyDown : undefined}
    >
      {children}
    </div>
  )
}
