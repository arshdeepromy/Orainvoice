import { useEffect } from 'react'

type FeedbackVariant = 'success' | 'error'

interface ActionFeedbackProps {
  variant: FeedbackVariant
  message: string
  visible: boolean
  onDismiss?: () => void
  autoDismissMs?: number
  className?: string
}

const variantClasses: Record<FeedbackVariant, string> = {
  success: 'bg-green-50 border-green-400 text-green-800',
  error: 'bg-red-50 border-red-400 text-red-800',
}

const variantIcons: Record<FeedbackVariant, string> = {
  success: '✓',
  error: '✕',
}

export function ActionFeedback({
  variant,
  message,
  visible,
  onDismiss,
  autoDismissMs = 4000,
  className = '',
}: ActionFeedbackProps) {
  useEffect(() => {
    if (!visible || !onDismiss || autoDismissMs <= 0) return
    const timer = setTimeout(onDismiss, autoDismissMs)
    return () => clearTimeout(timer)
  }, [visible, onDismiss, autoDismissMs])

  if (!visible) return null

  return (
    <div
      className={`flex items-center gap-2 rounded-md border-l-4 px-4 py-3 ${variantClasses[variant]} ${className}`}
      role={variant === 'error' ? 'alert' : 'status'}
    >
      <span aria-hidden="true">{variantIcons[variant]}</span>
      <p className="flex-1 text-sm font-medium">{message}</p>
      {onDismiss && (
        <button
          onClick={onDismiss}
          className="rounded p-1 hover:bg-black/5 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-current"
          aria-label="Dismiss"
        >
          <span aria-hidden="true">×</span>
        </button>
      )}
    </div>
  )
}
