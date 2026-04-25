import { useState, useRef, useCallback } from 'react'

export interface SwipeState {
  /** Current horizontal offset in pixels */
  offsetX: number
  /** Which side is currently open, or null if closed */
  isOpen: 'left' | 'right' | null
  /** Whether the user is actively dragging */
  isDragging: boolean
}

export interface UseSwipeActionsOptions {
  /** Pixel threshold to snap open (default: 80) */
  threshold?: number
  /** Called when swipe opens a side */
  onOpen?: (side: 'left' | 'right') => void
  /** Called when swipe snaps back to closed */
  onClose?: () => void
}

export interface UseSwipeActionsResult {
  state: SwipeState
  /** Reset to closed state */
  close: () => void
  /** Touch event handlers to spread onto the swipeable element */
  handlers: {
    onTouchStart: (e: React.TouchEvent) => void
    onTouchMove: (e: React.TouchEvent) => void
    onTouchEnd: () => void
  }
}

/**
 * Gesture state hook for horizontal swipe actions on list items.
 *
 * Tracks touch start/move/end to compute a horizontal offset.
 * When the offset exceeds the threshold on release, the swipe
 * snaps open to reveal action buttons. Below threshold it snaps back.
 *
 * Requirements: 7.6, 6.2
 */
export function useSwipeActions(
  options: UseSwipeActionsOptions = {},
): UseSwipeActionsResult {
  const { threshold = 80, onOpen, onClose } = options

  const [state, setState] = useState<SwipeState>({
    offsetX: 0,
    isOpen: null,
    isDragging: false,
  })

  const startXRef = useRef(0)
  const startYRef = useRef(0)
  const isHorizontalRef = useRef<boolean | null>(null)

  const handleTouchStart = useCallback((e: React.TouchEvent) => {
    const touch = e.touches[0]
    startXRef.current = touch.clientX
    startYRef.current = touch.clientY
    isHorizontalRef.current = null
    setState((prev) => ({ ...prev, isDragging: true }))
  }, [])

  const handleTouchMove = useCallback((e: React.TouchEvent) => {
    const touch = e.touches[0]
    const deltaX = touch.clientX - startXRef.current
    const deltaY = touch.clientY - startYRef.current

    // Determine swipe direction on first significant movement
    if (isHorizontalRef.current === null) {
      if (Math.abs(deltaX) > 5 || Math.abs(deltaY) > 5) {
        isHorizontalRef.current = Math.abs(deltaX) > Math.abs(deltaY)
      }
      return
    }

    // If vertical scroll, don't interfere
    if (!isHorizontalRef.current) return

    setState((prev) => ({
      ...prev,
      offsetX: deltaX,
      isDragging: true,
    }))
  }, [])

  const handleTouchEnd = useCallback(() => {
    setState((prev) => {
      const { offsetX } = prev

      // If swipe exceeded threshold, snap open
      if (offsetX > threshold) {
        onOpen?.('left')
        return { offsetX: threshold, isOpen: 'left', isDragging: false }
      }
      if (offsetX < -threshold) {
        onOpen?.('right')
        return { offsetX: -threshold, isOpen: 'right', isDragging: false }
      }

      // Below threshold — snap back
      onClose?.()
      return { offsetX: 0, isOpen: null, isDragging: false }
    })
    isHorizontalRef.current = null
  }, [threshold, onOpen, onClose])

  const close = useCallback(() => {
    setState({ offsetX: 0, isOpen: null, isDragging: false })
    onClose?.()
  }, [onClose])

  return {
    state,
    close,
    handlers: {
      onTouchStart: handleTouchStart,
      onTouchMove: handleTouchMove,
      onTouchEnd: handleTouchEnd,
    },
  }
}
