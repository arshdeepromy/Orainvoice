import type { ReactNode } from 'react'
import { usePullRefresh } from '@/hooks/usePullRefresh'
import { MobileSpinner } from '@/components/ui/MobileSpinner'

export interface PullRefreshProps {
  children: ReactNode
  /** Async callback invoked when pull exceeds threshold */
  onRefresh: () => Promise<void>
  /** Whether a refresh is currently in progress */
  isRefreshing: boolean
  /** Pixel threshold to trigger refresh (default: 60) */
  threshold?: number
}

/**
 * Pull-to-refresh wrapper with spinner and configurable threshold.
 *
 * - Wraps scrollable content
 * - Shows a spinner indicator when pulling down
 * - Triggers onRefresh callback when pull exceeds threshold
 * - Smooth CSS transitions for snap-back
 * - Resistance curve on pull distance
 * - Dark mode support
 *
 * Requirements: 6.2, 7.3, 8.8
 */
export function PullRefresh({
  children,
  onRefresh,
  isRefreshing,
  threshold = 60,
}: PullRefreshProps) {
  const { state, handlers } = usePullRefresh({
    onRefresh,
    isRefreshing,
    threshold,
  })

  const { pullDistance, isPulling } = state

  // Calculate spinner opacity based on pull progress
  const progress = Math.min(pullDistance / threshold, 1)
  const showIndicator = pullDistance > 0 || isRefreshing

  return (
    <div
      className="relative h-full overflow-y-auto"
      {...handlers}
    >
      {/* Pull indicator */}
      {showIndicator && (
        <div
          className="flex items-center justify-center overflow-hidden"
          style={{
            height: isRefreshing ? threshold * 0.6 : pullDistance,
            transition: isPulling ? 'none' : 'height 0.25s ease-out',
          }}
          aria-live="polite"
        >
          <div
            className="flex flex-col items-center"
            style={{
              opacity: isRefreshing ? 1 : progress,
              transform: `rotate(${progress * 360}deg)`,
              transition: isPulling ? 'none' : 'opacity 0.2s ease-out',
            }}
          >
            {isRefreshing ? (
              <MobileSpinner size="sm" />
            ) : (
              <svg
                className="h-6 w-6 text-blue-600 dark:text-blue-400"
                viewBox="0 0 24 24"
                fill="none"
                stroke="currentColor"
                strokeWidth="2"
                strokeLinecap="round"
                strokeLinejoin="round"
                aria-hidden="true"
              >
                <path d="M12 5v14" />
                <path d="m19 12-7 7-7-7" />
              </svg>
            )}
            {!isRefreshing && progress >= 1 && (
              <span className="mt-1 text-xs text-gray-500 dark:text-gray-400">
                Release to refresh
              </span>
            )}
          </div>
        </div>
      )}

      {/* Scrollable content */}
      {children}
    </div>
  )
}
