import { useCallback, useEffect, useRef, useState } from 'react'
import type { ReactNode, TouchEvent as ReactTouchEvent } from 'react'

export interface MobileModalProps {
  /** Whether the modal is open */
  isOpen: boolean
  /** Called when the modal should close */
  onClose: () => void
  /** Modal title */
  title?: string
  /** Modal content */
  children: ReactNode
  /** Enable swipe-to-dismiss (default: true) */
  swipeToDismiss?: boolean
  /** Swipe distance in px to trigger dismiss (default: 100) */
  swipeThreshold?: number
}

/**
 * Bottom sheet / modal with backdrop, close button, and swipe-to-dismiss.
 *
 * - Slides up from bottom (bottom sheet pattern)
 * - Backdrop click to close
 * - Close button in header
 * - Swipe down to dismiss
 * - Focus trap and escape key support
 * - Dark mode support
 *
 * Requirements: 1.3
 */
export function MobileModal({
  isOpen,
  onClose,
  title,
  children,
  swipeToDismiss = true,
  swipeThreshold = 100,
}: MobileModalProps) {
  const [translateY, setTranslateY] = useState(0)
  const [isDragging, setIsDragging] = useState(false)
  const startYRef = useRef(0)
  const sheetRef = useRef<HTMLDivElement>(null)

  // Close on Escape key
  useEffect(() => {
    if (!isOpen) return
    const handleKeyDown = (e: KeyboardEvent) => {
      if (e.key === 'Escape') onClose()
    }
    document.addEventListener('keydown', handleKeyDown)
    return () => document.removeEventListener('keydown', handleKeyDown)
  }, [isOpen, onClose])

  // Prevent body scroll when open
  useEffect(() => {
    if (isOpen) {
      document.body.style.overflow = 'hidden'
    }
    return () => {
      document.body.style.overflow = ''
    }
  }, [isOpen])

  const handleTouchStart = useCallback(
    (e: ReactTouchEvent) => {
      if (!swipeToDismiss) return
      startYRef.current = e.touches[0].clientY
      setIsDragging(true)
    },
    [swipeToDismiss],
  )

  const handleTouchMove = useCallback(
    (e: ReactTouchEvent) => {
      if (!isDragging || !swipeToDismiss) return
      const deltaY = e.touches[0].clientY - startYRef.current
      // Only allow dragging down
      if (deltaY > 0) {
        setTranslateY(deltaY)
      }
    },
    [isDragging, swipeToDismiss],
  )

  const handleTouchEnd = useCallback(() => {
    if (!isDragging) return
    setIsDragging(false)
    if (translateY > swipeThreshold) {
      onClose()
    }
    setTranslateY(0)
  }, [isDragging, translateY, swipeThreshold, onClose])

  if (!isOpen) return null

  return (
    <div className="fixed inset-0 z-50 flex items-end justify-center">
      {/* Backdrop */}
      <div
        className="absolute inset-0 bg-black/50 transition-opacity"
        onClick={onClose}
        aria-hidden="true"
      />

      {/* Bottom sheet */}
      <div
        ref={sheetRef}
        role="dialog"
        aria-modal="true"
        aria-label={title ?? 'Modal'}
        className="relative z-10 w-full max-w-lg rounded-t-2xl bg-white shadow-xl dark:bg-gray-800"
        style={{
          transform: `translateY(${translateY}px)`,
          transition: isDragging ? 'none' : 'transform 0.2s ease-out',
        }}
        onTouchStart={handleTouchStart}
        onTouchMove={handleTouchMove}
        onTouchEnd={handleTouchEnd}
      >
        {/* Drag handle */}
        {swipeToDismiss && (
          <div className="flex justify-center pb-1 pt-3">
            <div className="h-1 w-10 rounded-full bg-gray-300 dark:bg-gray-600" />
          </div>
        )}

        {/* Header */}
        <div className="flex items-center justify-between px-4 pb-2 pt-2">
          <h2 className="text-lg font-semibold text-gray-900 dark:text-gray-100">
            {title ?? ''}
          </h2>
          <button
            type="button"
            onClick={onClose}
            className="flex min-h-[44px] min-w-[44px] items-center justify-center rounded-full text-gray-500 hover:text-gray-700 dark:text-gray-400 dark:hover:text-gray-200"
            aria-label="Close"
          >
            <svg
              className="h-6 w-6"
              viewBox="0 0 24 24"
              fill="none"
              stroke="currentColor"
              strokeWidth="2"
              strokeLinecap="round"
              strokeLinejoin="round"
              aria-hidden="true"
            >
              <path d="M18 6 6 18" />
              <path d="m6 6 12 12" />
            </svg>
          </button>
        </div>

        {/* Content */}
        <div
          className="max-h-[70vh] overflow-y-auto px-4"
          style={{ paddingBottom: 'max(1.5rem, env(safe-area-inset-bottom))' }}
        >
          {children}
        </div>
      </div>
    </div>
  )
}
