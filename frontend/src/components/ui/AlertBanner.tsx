type AlertVariant = 'success' | 'warning' | 'error' | 'info'

interface AlertBannerProps {
  variant?: AlertVariant
  title?: string
  children: React.ReactNode
  onDismiss?: () => void
  className?: string
}

const variantClasses: Record<AlertVariant, string> = {
  success: 'bg-green-50 border-green-400 text-green-800',
  warning: 'bg-amber-50 border-amber-400 text-amber-800',
  error: 'bg-red-50 border-red-400 text-red-800',
  info: 'bg-blue-50 border-blue-400 text-blue-800',
}

const variantIcons: Record<AlertVariant, string> = {
  success: '✓',
  warning: '⚠',
  error: '✕',
  info: 'ℹ',
}

const variantRoles: Record<AlertVariant, 'alert' | 'status'> = {
  success: 'status',
  warning: 'alert',
  error: 'alert',
  info: 'status',
}

export function AlertBanner({
  variant = 'info',
  title,
  children,
  onDismiss,
  className = '',
}: AlertBannerProps) {
  return (
    <div
      className={`flex items-start gap-3 rounded-md border-l-4 p-4 ${variantClasses[variant]} ${className}`}
      role={variantRoles[variant]}
    >
      <span className="mt-0.5 text-lg" aria-hidden="true">
        {variantIcons[variant]}
      </span>
      <div className="flex-1">
        {title && <p className="font-medium">{title}</p>}
        <div className="text-sm">{children}</div>
      </div>
      {onDismiss && (
        <button
          onClick={onDismiss}
          className="ml-auto rounded p-1 hover:bg-black/5 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-current"
          aria-label="Dismiss alert"
        >
          <span aria-hidden="true">×</span>
        </button>
      )}
    </div>
  )
}
