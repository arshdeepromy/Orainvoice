import { renderHook, act } from '@testing-library/react'
import { describe, it, expect, vi } from 'vitest'
import { usePullRefresh } from '../usePullRefresh'

// Helper to create a minimal React.TouchEvent with a scrollable target
function makeTouchEvent(clientY: number, scrollTop = 0) {
  return {
    touches: [{ clientY }],
    currentTarget: { scrollTop },
  } as unknown as React.TouchEvent
}

describe('usePullRefresh', () => {
  it('starts with zero pull distance', () => {
    const { result } = renderHook(() =>
      usePullRefresh({
        onRefresh: vi.fn().mockResolvedValue(undefined),
        isRefreshing: false,
      }),
    )
    expect(result.current.state).toEqual({
      pullDistance: 0,
      isRefreshing: false,
      isPulling: false,
    })
  })

  it('tracks pull distance during downward touch move', () => {
    const { result } = renderHook(() =>
      usePullRefresh({
        onRefresh: vi.fn().mockResolvedValue(undefined),
        isRefreshing: false,
        threshold: 60,
      }),
    )

    act(() => {
      result.current.handlers.onTouchStart(makeTouchEvent(100))
    })
    act(() => {
      result.current.handlers.onTouchMove(makeTouchEvent(160))
    })

    // Pull distance has resistance (deltaY * 0.5)
    expect(result.current.state.pullDistance).toBe(30)
    expect(result.current.state.isPulling).toBe(true)
  })

  it('calls onRefresh when pull exceeds threshold', async () => {
    const onRefresh = vi.fn().mockResolvedValue(undefined)
    const { result } = renderHook(() =>
      usePullRefresh({
        onRefresh,
        isRefreshing: false,
        threshold: 60,
      }),
    )

    act(() => {
      result.current.handlers.onTouchStart(makeTouchEvent(100))
    })
    // Pull far enough: need deltaY * 0.5 >= 60, so deltaY >= 120
    act(() => {
      result.current.handlers.onTouchMove(makeTouchEvent(230))
    })
    await act(async () => {
      result.current.handlers.onTouchEnd()
    })

    expect(onRefresh).toHaveBeenCalledOnce()
  })

  it('does not call onRefresh when pull is below threshold', async () => {
    const onRefresh = vi.fn().mockResolvedValue(undefined)
    const { result } = renderHook(() =>
      usePullRefresh({
        onRefresh,
        isRefreshing: false,
        threshold: 60,
      }),
    )

    act(() => {
      result.current.handlers.onTouchStart(makeTouchEvent(100))
    })
    // Small pull: deltaY * 0.5 = 15 < 60
    act(() => {
      result.current.handlers.onTouchMove(makeTouchEvent(130))
    })
    await act(async () => {
      result.current.handlers.onTouchEnd()
    })

    expect(onRefresh).not.toHaveBeenCalled()
    expect(result.current.state.pullDistance).toBe(0)
  })

  it('does not start pulling when container is scrolled down', () => {
    const { result } = renderHook(() =>
      usePullRefresh({
        onRefresh: vi.fn().mockResolvedValue(undefined),
        isRefreshing: false,
      }),
    )

    // scrollTop > 0 means container is not at top
    act(() => {
      result.current.handlers.onTouchStart(makeTouchEvent(100, 50))
    })
    act(() => {
      result.current.handlers.onTouchMove(makeTouchEvent(200))
    })

    expect(result.current.state.pullDistance).toBe(0)
    expect(result.current.state.isPulling).toBe(false)
  })

  it('does not start pulling when already refreshing', () => {
    const { result } = renderHook(() =>
      usePullRefresh({
        onRefresh: vi.fn().mockResolvedValue(undefined),
        isRefreshing: true,
      }),
    )

    act(() => {
      result.current.handlers.onTouchStart(makeTouchEvent(100))
    })
    act(() => {
      result.current.handlers.onTouchMove(makeTouchEvent(200))
    })

    expect(result.current.state.pullDistance).toBe(0)
  })

  it('resets pull distance after refresh completes', async () => {
    let resolveRefresh: () => void
    const onRefresh = vi.fn(
      () => new Promise<void>((resolve) => { resolveRefresh = resolve }),
    )

    const { result } = renderHook(() =>
      usePullRefresh({
        onRefresh,
        isRefreshing: false,
        threshold: 60,
      }),
    )

    act(() => {
      result.current.handlers.onTouchStart(makeTouchEvent(100))
    })
    act(() => {
      result.current.handlers.onTouchMove(makeTouchEvent(230))
    })
    await act(async () => {
      result.current.handlers.onTouchEnd()
    })

    // While refreshing, pull distance is held at threshold * 0.6
    expect(result.current.state.pullDistance).toBe(36)

    // Complete the refresh
    await act(async () => {
      resolveRefresh!()
    })

    expect(result.current.state.pullDistance).toBe(0)
  })
})
