import { useCallback } from 'react'

/* ------------------------------------------------------------------ */
/* Types                                                              */
/* ------------------------------------------------------------------ */

export interface UseGeolocationResult {
  /** Request the current GPS position. Returns null silently on failure or permission denial. */
  getCurrentPosition: () => Promise<{ lat: number; lng: number } | null>
}

/**
 * Wraps `@capacitor/geolocation` with platform detection and error handling.
 *
 * Returns `null` silently when running in a web browser, when the user
 * denies location permission, or when the request times out. Geolocation
 * never blocks the calling flow (e.g. timer start).
 *
 * Requirements: 51.1, 51.2, 51.4
 */
export function useGeolocation(): UseGeolocationResult {
  const getCurrentPosition = useCallback(async (): Promise<{ lat: number; lng: number } | null> => {
    const isNative = !!(window as any).Capacitor?.isNativePlatform?.()
    if (!isNative) return null

    try {
      const { Geolocation } = await import('@capacitor/geolocation')
      const position = await Geolocation.getCurrentPosition({
        enableHighAccuracy: false,
        timeout: 5000,
      })
      return {
        lat: position.coords.latitude,
        lng: position.coords.longitude,
      }
    } catch {
      // Silently ignore — permission denied, timeout, or unsupported device
      return null
    }
  }, [])

  return { getCurrentPosition }
}
