/**
 * Expiry status badge — mirrors the backend Property 16 colour rules.
 *
 * Implements: B2B Fleet Portal task 14.3 — Requirements 6.3, 6.4, 7.8.
 */
import type { BadgeColour } from '../api/types'

interface ExpiryBadgeProps {
  colour: BadgeColour | null
  label?: string
  className?: string
}

const COLOUR_TO_CLASSES: Record<BadgeColour, string> = {
  red: 'bg-red-100 text-red-800 dark:bg-red-900/40 dark:text-red-200',
  amber: 'bg-amber-100 text-amber-800 dark:bg-amber-900/40 dark:text-amber-200',
  green: 'bg-green-100 text-green-800 dark:bg-green-900/40 dark:text-green-200',
}

const COLOUR_TO_TEXT: Record<BadgeColour, string> = {
  red: 'Expired',
  amber: 'Expiring soon',
  green: 'OK',
}

export function ExpiryBadge({ colour, label, className }: ExpiryBadgeProps) {
  if (colour === null) {
    return (
      <span
        className={
          'inline-flex items-center rounded-full px-2 py-0.5 text-xs font-medium ' +
          'bg-gray-100 text-gray-600 dark:bg-gray-800 dark:text-gray-400 ' +
          (className ?? '')
        }
      >
        Not recorded
      </span>
    )
  }

  return (
    <span
      className={
        'inline-flex items-center rounded-full px-2 py-0.5 text-xs font-medium ' +
        (COLOUR_TO_CLASSES[colour] ?? '') +
        ' ' +
        (className ?? '')
      }
    >
      {label ?? COLOUR_TO_TEXT[colour]}
    </span>
  )
}
