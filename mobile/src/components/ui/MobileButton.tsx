import type { ButtonHTMLAttributes, ReactNode } from 'react'

export type MobileButtonVariant = 'primary' | 'secondary' | 'danger' | 'ghost'
export type MobileButtonSize = 'sm' | 'md' | 'lg'

export interface MobileButtonProps
  extends Omit<ButtonHTMLAttributes<HTMLButtonElement>, 'className'> {
  children: ReactNode
  variant?: MobileButtonVariant
  size?: MobileButtonSize
  /** Show a loading spinner and disable the button */
  isLoading?: boolean
  /** Full width button */
  fullWidth?: boolean
  /** Additional CSS classes */
  className?: string
  /** Optional icon before the label */
  icon?: ReactNode
}

const variantStyles: Record<MobileButtonVariant, string> = {
  primary:
    'bg-blue-600 text-white active:bg-blue-700 dark:bg-blue-500 dark:active:bg-blue-600 disabled:bg-blue-300 dark:disabled:bg-blue-800',
  secondary:
    'bg-gray-100 text-gray-900 active:bg-gray-200 dark:bg-gray-700 dark:text-gray-100 dark:active:bg-gray-600 disabled:bg-gray-50 dark:disabled:bg-gray-800 disabled:text-gray-400',
  danger:
    'bg-red-600 text-white active:bg-red-700 dark:bg-red-500 dark:active:bg-red-600 disabled:bg-red-300 dark:disabled:bg-red-800',
  ghost:
    'bg-transparent text-blue-600 active:bg-blue-50 dark:text-blue-400 dark:active:bg-gray-800 disabled:text-gray-400',
}

const sizeStyles: Record<MobileButtonSize, string> = {
  sm: 'min-h-[44px] px-3 py-2 text-sm',
  md: 'min-h-[44px] px-4 py-3 text-base',
  lg: 'min-h-[52px] px-6 py-4 text-lg',
}

/**
 * Touch-optimised button with 44px min height, loading state, and variant styles.
 *
 * Variants: primary, secondary, danger, ghost
 * Sizes: sm, md, lg (all ≥ 44px min height)
 *
 * Requirements: 1.3
 */
export function MobileButton({
  children,
  variant = 'primary',
  size = 'md',
  isLoading = false,
  fullWidth = false,
  className = '',
  icon,
  disabled,
  ...rest
}: MobileButtonProps) {
  return (
    <button
      className={`inline-flex items-center justify-center gap-2 rounded-lg font-medium transition-colors ${variantStyles[variant]} ${sizeStyles[size]} ${
        fullWidth ? 'w-full' : ''
      } ${className}`}
      disabled={disabled || isLoading}
      aria-busy={isLoading || undefined}
      {...rest}
    >
      {isLoading ? (
        <svg
          className="h-5 w-5 animate-spin"
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
      ) : icon ? (
        <span className="flex-shrink-0" aria-hidden="true">
          {icon}
        </span>
      ) : null}
      {children}
    </button>
  )
}
