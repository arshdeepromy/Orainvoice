import { describe, it, expect, afterEach, vi } from 'vitest'
import { renderHook, act } from '@testing-library/react'
import { useMediaQuery } from '../useMediaQuery'

/**
 * Unit tests for the useMediaQuery hook (task 2.2).
 *
 * jsdom does not implement `window.matchMedia`, so we install a controllable
 * mock that lets each test:
 *   - set the initial `matches` value the hook reads,
 *   - capture the `change` listener the hook subscribes with,
 *   - dispatch a synthetic `change` event to flip the match state, and
 *   - observe `removeEventListener` being called on unmount.
 *
 * Requirements: 1.1, 1.2
 */

interface MockMediaQueryList {
  matches: boolean
  media: string
  addEventListener: ReturnType<typeof vi.fn>
  removeEventListener: ReturnType<typeof vi.fn>
  // legacy API kept undefined; the hook uses addEventListener
  dispatchChange: (matches: boolean) => void
}

/**
 * Build a controllable matchMedia mock. The returned `installed` map records the
 * MediaQueryList created per query so a test can drive its `change` event.
 */
function createMatchMediaMock(initialMatches: boolean) {
  const installed = new Map<string, MockMediaQueryList>()

  const matchMedia = vi.fn((query: string): MediaQueryList => {
    const listeners = new Set<(e: MediaQueryListEvent) => void>()

    const mql: MockMediaQueryList = {
      matches: initialMatches,
      media: query,
      addEventListener: vi.fn((_type: string, cb: (e: MediaQueryListEvent) => void) => {
        listeners.add(cb)
      }),
      removeEventListener: vi.fn((_type: string, cb: (e: MediaQueryListEvent) => void) => {
        listeners.delete(cb)
      }),
      dispatchChange: (matches: boolean) => {
        mql.matches = matches
        const event = { matches, media: query } as MediaQueryListEvent
        listeners.forEach((cb) => cb(event))
      },
    }

    installed.set(query, mql)
    return mql as unknown as MediaQueryList
  })

  return { matchMedia, installed }
}

const QUERY = '(min-width: 1280px)'

describe('useMediaQuery', () => {
  const originalMatchMedia = window.matchMedia

  afterEach(() => {
    // Restore whatever was on window before each test mutated it.
    if (originalMatchMedia === undefined) {
      // jsdom default: matchMedia is not implemented.
      delete (window as unknown as { matchMedia?: unknown }).matchMedia
    } else {
      window.matchMedia = originalMatchMedia
    }
    vi.restoreAllMocks()
  })

  it('returns the current match value from matchMedia', () => {
    const { matchMedia } = createMatchMediaMock(true)
    window.matchMedia = matchMedia as unknown as typeof window.matchMedia

    const { result } = renderHook(() => useMediaQuery(QUERY))

    expect(result.current).toBe(true)
    expect(matchMedia).toHaveBeenCalledWith(QUERY)
  })

  it('returns false when the query does not currently match', () => {
    const { matchMedia } = createMatchMediaMock(false)
    window.matchMedia = matchMedia as unknown as typeof window.matchMedia

    const { result } = renderHook(() => useMediaQuery(QUERY))

    expect(result.current).toBe(false)
  })

  it('updates when a change event fires', () => {
    const { matchMedia, installed } = createMatchMediaMock(false)
    window.matchMedia = matchMedia as unknown as typeof window.matchMedia

    const { result } = renderHook(() => useMediaQuery(QUERY))
    expect(result.current).toBe(false)

    // The hook subscribed via addEventListener('change', ...).
    const mql = installed.get(QUERY)!
    expect(mql.addEventListener).toHaveBeenCalledWith('change', expect.any(Function))

    act(() => {
      mql.dispatchChange(true)
    })
    expect(result.current).toBe(true)

    act(() => {
      mql.dispatchChange(false)
    })
    expect(result.current).toBe(false)
  })

  it('removes its change listener on unmount', () => {
    const { matchMedia, installed } = createMatchMediaMock(true)
    window.matchMedia = matchMedia as unknown as typeof window.matchMedia

    const { unmount } = renderHook(() => useMediaQuery(QUERY))

    const mql = installed.get(QUERY)!
    expect(mql.removeEventListener).not.toHaveBeenCalled()

    unmount()

    expect(mql.removeEventListener).toHaveBeenCalledWith('change', expect.any(Function))
    // The handler removed must be the same one that was added.
    const addedHandler = mql.addEventListener.mock.calls[0][1]
    const removedHandler = mql.removeEventListener.mock.calls[0][1]
    expect(removedHandler).toBe(addedHandler)
  })

  it('defaults to the Wide tier (true) when window.matchMedia is absent', () => {
    // Simulate an environment without matchMedia support.
    delete (window as unknown as { matchMedia?: unknown }).matchMedia

    const { result } = renderHook(() => useMediaQuery(QUERY))

    expect(result.current).toBe(true)
  })
})
