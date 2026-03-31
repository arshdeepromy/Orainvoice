import React from 'react'

type ButtonVariant = 'primary' | 'secondary' | 'danger'
type ButtonSize = 'sm' | 'md' | 'lg'

interface ButtonProps extends React.ButtonHTMLAttributes<HTMLButtonElement> {
  variant?: ButtonVariant
  size?: ButtonSize
  loading?: boolean
  children: React.ReactNode
}

const sizeClasses: Record<ButtonSize, string> = {
  sm: 'px-3 py-1.5 text-sm',
  md: 'px-4 py-2 text-base',
  lg: 'px-6 py-3 text-lg',
}

export function Button({
  variant = 'primary',
  size = 'md',
  loading = false,
  disabled,
  children,
  className = '',
  style,
  ...props
}: ButtonProps) {
  const isDisabled = disabled || loading

  const variantStyle: React.CSSProperties =
    variant === 'primary'
      ? { backgroundColor: 'var(--btn-primary-bg)', color: 'var(--btn-primary-text)' }
      : variant === 'danger'
        ? { backgroundColor: 'var(--btn-danger-bg)', color: '#fff' }
        : { backgroundColor: 'var(--btn-secondary-bg)', color: 'var(--btn-secondary-text)' }

  const hoverClass =
    variant === 'primary'
      ? 'hover:[background-color:var(--btn-primary-hover)]'
      : variant === 'danger'
        ? 'hover:[background-color:var(--btn-danger-hover)]'
        : 'hover:[background-color:var(--btn-secondary-hover)]'

  return (
    <button
      className={`inline-flex items-center justify-center font-medium
        transition-all duration-[var(--transition-speed)]
        focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-offset-2 focus-visible:ring-[var(--color-primary-ring)]
        disabled:opacity-50 disabled:cursor-not-allowed
        ${hoverClass} ${sizeClasses[size]} ${className}`}
      style={{
        borderRadius: 'var(--btn-radius)',
        ...variantStyle,
        ...style,
      }}
      disabled={isDisabled}
      aria-disabled={isDisabled}
      aria-busy={loading}
      {...props}
    >
      {loading && (
        <svg
          className="mr-2 h-4 w-4 animate-spin"
          xmlns="http://www.w3.org/2000/svg"
          fill="none"
          viewBox="0 0 24 24"
          aria-hidden="true"
        >
          <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
          <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z" />
        </svg>
      )}
      {children}
    </button>
  )
}
