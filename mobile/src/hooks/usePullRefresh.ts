import { useState, useRef, useCallback } from 'react'

export interface PullRefreshState {
  /** Current pull distance in pixels */
  pullDistance: number
  /** Whether a refresh is in progress */
  isRefreshing: boolean
  /** Whether the user is actively pulling */
  isPulling: boolean
}

export interface UsePullRefreshOptions {
  /** Async callback invoked when pull exceeds threshold */
  onRefresh: () => Promise<void>
  /** Whether a refresh is already in progress (external control) */
  isRefreshing: boolean
  /** Pixel threshold to trigger refresh (default: 60) */
  threshold?: number
}

export interface UsePullRefreshResult {
  state: PullRefreshState
  /** Touch event handlers to spread onto the scrollable container */
  handlers: {
    onTouchStart: (e: React.TouchEvent) => void
    onTouchMove: (e: React.TouchEvent) => void
    onTouchEnd: () => void
  }
}

/**
 * Gesture state hook for pull-to-refresh.
 *
 * Tracks vertical touch movement when the container is scrolled to the top.
 * When the pull distance exceeds the threshold on release, the onRefresh
 * callback is invoked. Below threshold the pull snaps back.
 *
 * Requirements: 6.2, 7.3
 */
export function usePullRefresh(
  options: UsePullRefreshOptions,
): UsePullRefreshResult {
  const { onRefresh, isRefreshing, threshold = 60 } = options

  const [pullDistance, setPullDistance] = useState(0)
  const [isPulling, setIsPulling] = useState(false)

  const startYRef = useRef(0)
  const pullingRef = useRef(false)

  const handleTouchStart = useCallback((e: React.TouchEvent) => {
    // Only start pull tracking if we're at the top of the scroll container
    const target = e.currentTarget as HTMLElement
    if (target.scrollTop > 0 || isRefreshing) return

    startYRef.current = e.touches[0].clientY
    pullingRef.current = true
    setIsPulling(true)
  }, [isRefreshing])

  const handleTouchMove = useCallback((e: React.TouchEvent) => {
    if (!pullingRef.current || isRefreshing) return

    const deltaY = e.touches[0].clientY - startYRef.current

    // Only track downward pulls
    if (deltaY > 0) {
      // Apply resistance: the further you pull, the harder it gets
      const distance = Math.min(deltaY * 0.5, threshold * 2.5)
      setPullDistance(distance)
    } else {
      // User scrolled up — cancel pull
      pullingRef.current = false
      setIsPulling(false)
      setPullDistance(0)
    }
  }, [isRefreshing, threshold])

  const handleTouchEnd = useCallback(() => {
    if (!pullingRef.current) return

    pullingRef.current = false
    setIsPulling(false)

    if (pullDistance >= threshold && !isRefreshing) {
      // Trigger refresh — keep a small indicator distance while refreshing
      setPullDistance(threshold * 0.6)
      onRefresh().finally(() => {
        setPullDistance(0)
      })
    } else {
      setPullDistance(0)
    }
  }, [pullDistance, threshold, isRefreshing, onRefresh])

  return {
    state: {
      pullDistance,
      isRefreshing,
      isPulling,
    },
    handlers: {
      onTouchStart: handleTouchStart,
      onTouchMove: handleTouchMove,
      onTouchEnd: handleTouchEnd,
    },
  }
}
