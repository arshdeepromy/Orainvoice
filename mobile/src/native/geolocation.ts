/**
 * Geolocation — convenience re-export + standalone function.
 *
 * Import from `@/native` instead of `@/hooks` for non-hook contexts.
 */

export { useGeolocation } from '@/hooks/useGeolocation'
export type { UseGeolocationResult } from '@/hooks/useGeolocation'

/**
 * Standalone position lookup — usable outside React components.
 * Returns null on web, permission denial, or timeout.
 */
export async function getCurrentPosition(): Promise<{ lat: number; lng: number } | null> {
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
    return null
  }
}
