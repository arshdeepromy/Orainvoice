import { useCallback } from 'react'

/* ------------------------------------------------------------------ */
/* Types                                                              */
/* ------------------------------------------------------------------ */

export interface UseHapticsResult {
  /** Trigger a light impact haptic (primary action buttons) */
  light: () => Promise<void>
  /** Trigger a medium impact haptic (toggles, status changes) */
  medium: () => Promise<void>
  /** Trigger a heavy impact haptic (destructive actions) */
  heavy: () => Promise<void>
  /** Trigger a selection haptic (swipe actions) */
  selection: () => Promise<void>
}

/**
 * Wraps `@capacitor/haptics` with platform detection and error handling.
 *
 * All methods are no-ops when running in a web browser or on devices
 * that do not support haptic feedback. Errors are silently swallowed
 * so haptics never block user interactions.
 *
 * Requirements: 9.1, 9.2, 9.3, 9.4, 9.5
 */
export function useHaptics(): UseHapticsResult {
  const light = useCallback(async (): Promise<void> => {
    const isNative = !!(window as any).Capacitor?.isNativePlatform?.()
    if (!isNative) return

    try {
      const { Haptics, ImpactStyle } = await import('@capacitor/haptics')
      await Haptics.impact({ style: ImpactStyle.Light })
    } catch {
      // Silently ignore — device may not support haptics
    }
  }, [])

  const medium = useCallback(async (): Promise<void> => {
    const isNative = !!(window as any).Capacitor?.isNativePlatform?.()
    if (!isNative) return

    try {
      const { Haptics, ImpactStyle } = await import('@capacitor/haptics')
      await Haptics.impact({ style: ImpactStyle.Medium })
    } catch {
      // Silently ignore — device may not support haptics
    }
  }, [])

  const heavy = useCallback(async (): Promise<void> => {
    const isNative = !!(window as any).Capacitor?.isNativePlatform?.()
    if (!isNative) return

    try {
      const { Haptics, ImpactStyle } = await import('@capacitor/haptics')
      await Haptics.impact({ style: ImpactStyle.Heavy })
    } catch {
      // Silently ignore — device may not support haptics
    }
  }, [])

  const selection = useCallback(async (): Promise<void> => {
    const isNative = !!(window as any).Capacitor?.isNativePlatform?.()
    if (!isNative) return

    try {
      const { Haptics } = await import('@capacitor/haptics')
      await Haptics.selectionStart()
      await Haptics.selectionChanged()
      await Haptics.selectionEnd()
    } catch {
      // Silently ignore — device may not support haptics
    }
  }, [])

  return { light, medium, heavy, selection }
}
