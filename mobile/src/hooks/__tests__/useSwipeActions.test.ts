import { renderHook, act } from '@testing-library/react'
import { describe, it, expect, vi } from 'vitest'
import { useSwipeActions } from '../useSwipeActions'

// Helper to create a minimal React.TouchEvent
function makeTouchEvent(clientX: number, clientY: number = 0) {
  return {
    touches: [{ clientX, clientY }],
  } as unknown as React.TouchEvent
}

describe('useSwipeActions', () => {
  it('starts with closed state', () => {
    const { result } = renderHook(() => useSwipeActions())
    expect(result.current.state).toEqual({
      offsetX: 0,
      isOpen: null,
      isDragging: false,
    })
  })

  it('tracks horizontal offset during touch move', () => {
    const { result } = renderHook(() => useSwipeActions())

    act(() => {
      result.current.handlers.onTouchStart(makeTouchEvent(100))
    })
    // Move enough to establish horizontal direction
    act(() => {
      result.current.handlers.onTouchMove(makeTouchEvent(110))
    })
    // Now the actual move
    act(() => {
      result.current.handlers.onTouchMove(makeTouchEvent(130))
    })

    expect(result.current.state.offsetX).toBe(30)
    expect(result.current.state.isDragging).toBe(true)
  })

  it('snaps open right when swipe exceeds threshold', () => {
    const onOpen = vi.fn()
    const { result } = renderHook(() =>
      useSwipeActions({ threshold: 80, onOpen }),
    )

    act(() => {
      result.current.handlers.onTouchStart(makeTouchEvent(100))
    })
    act(() => {
      result.current.handlers.onTouchMove(makeTouchEvent(110))
    })
    act(() => {
      result.current.handlers.onTouchMove(makeTouchEvent(200))
    })
    act(() => {
      result.current.handlers.onTouchEnd()
    })

    expect(result.current.state.isOpen).toBe('left')
    expect(result.current.state.offsetX).toBe(80)
    expect(result.current.state.isDragging).toBe(false)
    expect(onOpen).toHaveBeenCalledWith('left')
  })

  it('snaps open left when swiping left past threshold', () => {
    const onOpen = vi.fn()
    const { result } = renderHook(() =>
      useSwipeActions({ threshold: 80, onOpen }),
    )

    act(() => {
      result.current.handlers.onTouchStart(makeTouchEvent(200))
    })
    act(() => {
      result.current.handlers.onTouchMove(makeTouchEvent(190))
    })
    act(() => {
      result.current.handlers.onTouchMove(makeTouchEvent(100))
    })
    act(() => {
      result.current.handlers.onTouchEnd()
    })

    expect(result.current.state.isOpen).toBe('right')
    expect(result.current.state.offsetX).toBe(-80)
    expect(onOpen).toHaveBeenCalledWith('right')
  })

  it('snaps back when below threshold', () => {
    const onClose = vi.fn()
    const { result } = renderHook(() =>
      useSwipeActions({ threshold: 80, onClose }),
    )

    act(() => {
      result.current.handlers.onTouchStart(makeTouchEvent(100))
    })
    act(() => {
      result.current.handlers.onTouchMove(makeTouchEvent(110))
    })
    act(() => {
      result.current.handlers.onTouchMove(makeTouchEvent(140))
    })
    act(() => {
      result.current.handlers.onTouchEnd()
    })

    expect(result.current.state.offsetX).toBe(0)
    expect(result.current.state.isOpen).toBeNull()
    expect(onClose).toHaveBeenCalled()
  })

  it('close() resets state', () => {
    const { result } = renderHook(() => useSwipeActions({ threshold: 80 }))

    // Open it first
    act(() => {
      result.current.handlers.onTouchStart(makeTouchEvent(100))
    })
    act(() => {
      result.current.handlers.onTouchMove(makeTouchEvent(110))
    })
    act(() => {
      result.current.handlers.onTouchMove(makeTouchEvent(200))
    })
    act(() => {
      result.current.handlers.onTouchEnd()
    })
    expect(result.current.state.isOpen).toBe('left')

    // Close it
    act(() => {
      result.current.close()
    })
    expect(result.current.state).toEqual({
      offsetX: 0,
      isOpen: null,
      isDragging: false,
    })
  })

  it('uses custom threshold', () => {
    const { result } = renderHook(() => useSwipeActions({ threshold: 40 }))

    act(() => {
      result.current.handlers.onTouchStart(makeTouchEvent(100))
    })
    act(() => {
      result.current.handlers.onTouchMove(makeTouchEvent(110))
    })
    act(() => {
      result.current.handlers.onTouchMove(makeTouchEvent(150))
    })
    act(() => {
      result.current.handlers.onTouchEnd()
    })

    expect(result.current.state.isOpen).toBe('left')
    expect(result.current.state.offsetX).toBe(40)
  })
})
