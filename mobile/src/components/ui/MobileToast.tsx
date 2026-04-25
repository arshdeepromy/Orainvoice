import { useEffect, useState } from 'react'

export type ToastVariant = 'success' | 'error' | 'info'

export interface MobileToastProps {
  /** Toast message */
  message: string
  /** Visual variant */
  variant?: ToastVariant
  /** Whether the toast is visible */
  isVisible: boolean
  /** Called when the toast should hide */
  onDismiss: () => void
  /** Auto-dismiss duration in ms (default: 3000, 0 to disable) */
  duration?: number
}

const variantStyles: Record<ToastVariant, string> = {
  success: 'bg-green-600 dark:bg-green-700',
  error: 'bg-red-600 dark:bg-red-700',
  info: 'bg-blue-600 dark:bg-blue-700',
}

const variantIcons: Record<ToastVariant, string> = {
  success: 'M20 6 9 17l-5-5',
  error: 'M18 6 6 18M6 6l12 12',
  info: 'M12 16v-4M12 8h.01',
}

/**
 * Toast notification for success, error, and info messages.
 *
 * - Slides in from top
 * - Auto-dismisses after duration
 * - Tap to dismiss
 * - Dark mode support
 * - Accessible: role="alert"
 *
 * Requirements: 1.3, 1.5, 1.6
 */
export function MobileToast({
  message,
  variant = 'info',
  isVisible,
  onDismiss,
  duration = 3000,
}: MobileToastProps) {
  const [show, setShow] = useState(false)

  // Animate in
  useEffect(() => {
    if (isVisible) {
      // Small delay for CSS transition
      const timer = setTimeout(() => setShow(true), 10)
      return () => clearTimeout(timer)
    } else {
      setShow(false)
    }
  }, [isVisible])

  // Auto-dismiss
  useEffect(() => {
    if (!isVisible || duration === 0) return
    const timer = setTimeout(onDismiss, duration)
    return () => clearTimeout(timer)
  }, [isVisible, duration, onDismiss])

  if (!isVisible) return null

  return (
    <div
      className={`fixed left-4 right-4 top-[env(safe-area-inset-top)] z-[60] mt-2 transition-all duration-300 ${
        show ? 'translate-y-0 opacity-100' : '-translate-y-4 opacity-0'
      }`}
    >
      <div
        role="alert"
        onClick={onDismiss}
        className={`flex min-h-[44px] cursor-pointer items-center gap-3 rounded-xl px-4 py-3 text-white shadow-lg ${variantStyles[variant]}`}
      >
        <svg
          className="h-5 w-5 flex-shrink-0"
          viewBox="0 0 24 24"
          fill="none"
          stroke="currentColor"
          strokeWidth="2"
          strokeLinecap="round"
          strokeLinejoin="round"
          aria-hidden="true"
        >
          <path d={variantIcons[variant]} />
        </svg>
        <p className="flex-1 text-sm font-medium">{message}</p>
      </div>
    </div>
  )
}
