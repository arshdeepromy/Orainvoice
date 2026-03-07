type BadgeVariant = 'success' | 'warning' | 'error' | 'info' | 'neutral'

interface BadgeProps {
  variant?: BadgeVariant
  children: React.ReactNode
  className?: string
}

const variantClasses: Record<BadgeVariant, string> = {
  success: 'bg-green-100 text-green-800 border-green-300',
  warning: 'bg-amber-100 text-amber-800 border-amber-300',
  error: 'bg-red-100 text-red-800 border-red-300',
  info: 'bg-blue-100 text-blue-800 border-blue-300',
  neutral: 'bg-gray-100 text-gray-800 border-gray-300',
}

// Icons provide a non-colour indicator alongside the text label
const variantIcons: Record<BadgeVariant, string> = {
  success: '✓',
  warning: '⚠',
  error: '✕',
  info: 'ℹ',
  neutral: '•',
}

export function Badge({ variant = 'neutral', children, className = '' }: BadgeProps) {
  return (
    <span
      className={`inline-flex items-center gap-1 rounded-full border px-2.5 py-0.5 text-xs font-medium
        ${variantClasses[variant]} ${className}`}
    >
      <span aria-hidden="true">{variantIcons[variant]}</span>
      <span className="sr-only">{`${variant}: `}</span>
      {children}
    </span>
  )
}
