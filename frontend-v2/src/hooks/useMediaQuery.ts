import { useState, useEffect } from 'react'

/**
 * useMediaQuery - track whether a CSS media query currently matches.
 *
 * Backed by `window.matchMedia` and subscribed via the modern
 * `addEventListener('change', ...)` API (NOT a `resize` listener), so it only
 * re-renders when the query's match state actually flips. The listener is
 * cleaned up on unmount.
 *
 * When `window.matchMedia` is unavailable (e.g. an unsupported environment or a
 * non-DOM test runner), the hook defaults to `true` so callers fall back to the
 * Wide tier (both panes shown) rather than throwing.
 *
 * @param query - a CSS media query string, e.g. `'(min-width: 1280px)'`.
 * @returns whether the media query currently matches.
 */
export function useMediaQuery(query: string): boolean {
  const getMatches = (q: string): boolean => {
    if (typeof window === 'undefined' || typeof window.matchMedia !== 'function') {
      // Unsupported environment: default to the Wide tier.
      return true
    }
    return window.matchMedia(q).matches
  }

  const [matches, setMatches] = useState<boolean>(() => getMatches(query))

  useEffect(() => {
    if (typeof window === 'undefined' || typeof window.matchMedia !== 'function') {
      // No matchMedia: keep the Wide-tier default and skip subscribing.
      setMatches(true)
      return
    }

    const mql = window.matchMedia(query)

    // Sync immediately in case the query changed between render and effect.
    setMatches(mql.matches)

    const handler = (event: MediaQueryListEvent) => setMatches(event.matches)

    mql.addEventListener('change', handler)
    return () => mql.removeEventListener('change', handler)
  }, [query])

  return matches
}
