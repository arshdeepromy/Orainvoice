export type SpinnerSize = 'sm' | 'md' | 'lg'

export interface MobileSpinnerProps {
  /** Spinner size */
  size?: SpinnerSize
  /** Additional CSS classes */
  className?: string
}

const sizeStyles: Record<SpinnerSize, string> = {
  sm: 'h-5 w-5',
  md: 'h-8 w-8',
  lg: 'h-12 w-12',
}

/**
 * Loading spinner indicator.
 *
 * - Animated spinning circle
 * - Three sizes: sm, md, lg
 * - Dark mode support
 * - Accessible: role="status" with sr-only label
 *
 * Requirements: 1.3, 1.5, 1.6
 */
export function MobileSpinner({ size = 'md', className = '' }: MobileSpinnerProps) {
  return (
    <div role="status" className={`inline-flex items-center justify-center ${className}`}>
      <svg
        className={`animate-spin text-blue-600 dark:text-blue-400 ${sizeStyles[size]}`}
        viewBox="0 0 24 24"
        fill="none"
        aria-hidden="true"
      >
        <circle
          className="opacity-25"
          cx="12"
          cy="12"
          r="10"
          stroke="currentColor"
          strokeWidth="4"
        />
        <path
          className="opacity-75"
          fill="currentColor"
          d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z"
        />
      </svg>
      <span className="sr-only">Loading</span>
    </div>
  )
}
