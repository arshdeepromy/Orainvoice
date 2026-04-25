export type BadgeVariant =
  | 'paid'
  | 'overdue'
  | 'draft'
  | 'sent'
  | 'cancelled'
  | 'pending'
  | 'active'
  | 'expired'
  | 'expiring'
  | 'info'

export interface MobileBadgeProps {
  /** Badge text */
  label: string
  /** Visual variant — determines colour */
  variant?: BadgeVariant
  /** Additional CSS classes */
  className?: string
}

const variantStyles: Record<BadgeVariant, string> = {
  paid: 'bg-green-100 text-green-800 dark:bg-green-900 dark:text-green-200',
  active: 'bg-green-100 text-green-800 dark:bg-green-900 dark:text-green-200',
  overdue: 'bg-red-100 text-red-800 dark:bg-red-900 dark:text-red-200',
  expired: 'bg-red-100 text-red-800 dark:bg-red-900 dark:text-red-200',
  draft: 'bg-gray-100 text-gray-800 dark:bg-gray-700 dark:text-gray-200',
  sent: 'bg-blue-100 text-blue-800 dark:bg-blue-900 dark:text-blue-200',
  info: 'bg-blue-100 text-blue-800 dark:bg-blue-900 dark:text-blue-200',
  cancelled: 'bg-gray-100 text-gray-500 dark:bg-gray-700 dark:text-gray-400',
  pending: 'bg-yellow-100 text-yellow-800 dark:bg-yellow-900 dark:text-yellow-200',
  expiring: 'bg-orange-100 text-orange-800 dark:bg-orange-900 dark:text-orange-200',
}

/**
 * Status badge for invoices, quotes, compliance docs, etc.
 *
 * Variants: paid, overdue, draft, sent, cancelled, pending, active, expired, expiring, info
 *
 * Requirements: 1.3, 1.5, 1.6
 */
export function MobileBadge({ label, variant = 'info', className = '' }: MobileBadgeProps) {
  return (
    <span
      className={`inline-flex items-center rounded-full px-2.5 py-0.5 text-xs font-medium ${variantStyles[variant]} ${className}`}
    >
      {label}
    </span>
  )
}
