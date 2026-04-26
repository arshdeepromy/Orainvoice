import type { ReactNode } from 'react'
import { useCallback } from 'react'
import { useSwipeActions } from '@/hooks/useSwipeActions'

async function triggerHaptic(style: 'light' | 'medium' = 'light') {
  try {
    const { Haptics, ImpactStyle } = await import('@capacitor/haptics')
    await Haptics.impact({ style: style === 'medium' ? ImpactStyle.Medium : ImpactStyle.Light })
  } catch {
    // Not available in browser
  }
}

export interface SwipeActionConfig {
  /** Button label text */
  label: string
  /** Icon component rendered inside the button */
  icon: React.ComponentType<{ className?: string }>
  /** Tailwind colour class for the button background (e.g. 'bg-red-500') */
  color: string
  /** Called when the action button is tapped */
  onAction: () => void
}

export interface SwipeActionProps {
  children: ReactNode
  /** Actions revealed when swiping right (left-side buttons) */
  leftActions?: SwipeActionConfig[]
  /** Actions revealed when swiping left (right-side buttons) */
  rightActions?: SwipeActionConfig[]
  /** Pixel threshold to snap open (default: 80) */
  threshold?: number
}

/**
 * Horizontal swipe on list items revealing left/right action buttons.
 *
 * - Touch event handlers: onTouchStart, onTouchMove, onTouchEnd
 * - Configurable threshold (default 80px)
 * - Snap-back animation when below threshold
 * - Smooth CSS transitions for snap-back
 * - Dark mode support
 * - 44px minimum touch targets on action buttons
 *
 * Requirements: 7.6, 8.6
 */
export function SwipeAction({
  children,
  leftActions = [],
  rightActions = [],
  threshold = 80,
}: SwipeActionProps) {
  const { state, close, handlers } = useSwipeActions({
    threshold,
    onOpen: () => { void triggerHaptic('light') },
  })
  const { offsetX, isDragging } = state

  const hasLeft = leftActions.length > 0
  const hasRight = rightActions.length > 0

  // Clamp offset: only allow swiping in directions that have actions
  const clampedOffset = (() => {
    let val = offsetX
    if (!hasLeft && val > 0) val = 0
    if (!hasRight && val < 0) val = 0
    return val
  })()

  const handleActionClick = useCallback((action: SwipeActionConfig) => {
    void triggerHaptic('medium')
    action.onAction()
    close()
  }, [close])

  return (
    <div className="relative overflow-hidden" role="group" aria-label="Swipeable item">
      {/* Left actions (revealed when swiping right) */}
      {hasLeft && (
        <div
          className="absolute inset-y-0 left-0 flex items-stretch"
          aria-hidden={clampedOffset <= 0}
        >
          {leftActions.map((action) => (
            <button
              key={action.label}
              type="button"
              onClick={() => handleActionClick(action)}
              className={`flex min-w-[80px] flex-col items-center justify-center px-3 text-white ${action.color}`}
              style={{ minHeight: 44, minWidth: 44 }}
              aria-label={action.label}
            >
              <action.icon className="h-5 w-5" />
              <span className="mt-1 text-xs font-medium">{action.label}</span>
            </button>
          ))}
        </div>
      )}

      {/* Right actions (revealed when swiping left) */}
      {hasRight && (
        <div
          className="absolute inset-y-0 right-0 flex items-stretch"
          aria-hidden={clampedOffset >= 0}
        >
          {rightActions.map((action) => (
            <button
              key={action.label}
              type="button"
              onClick={() => handleActionClick(action)}
              className={`flex min-w-[80px] flex-col items-center justify-center px-3 text-white ${action.color}`}
              style={{ minHeight: 44, minWidth: 44 }}
              aria-label={action.label}
            >
              <action.icon className="h-5 w-5" />
              <span className="mt-1 text-xs font-medium">{action.label}</span>
            </button>
          ))}
        </div>
      )}

      {/* Swipeable content */}
      <div
        className="relative z-10 bg-white dark:bg-gray-900"
        style={{
          transform: `translateX(${clampedOffset}px)`,
          transition: isDragging ? 'none' : 'transform 0.25s ease-out',
        }}
        {...handlers}
      >
        {children}
      </div>
    </div>
  )
}
