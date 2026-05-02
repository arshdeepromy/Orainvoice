/**
 * Haptics — convenience re-export + standalone functions.
 *
 * Import from `@/native` instead of `@/hooks` for non-hook contexts.
 */

export { useHaptics } from '@/hooks/useHaptics'
export type { UseHapticsResult } from '@/hooks/useHaptics'

/* ------------------------------------------------------------------ */
/* Standalone haptic functions                                        */
/* ------------------------------------------------------------------ */

function isNative(): boolean {
  return !!(window as any).Capacitor?.isNativePlatform?.()
}

/** Light impact — primary action buttons */
export async function light(): Promise<void> {
  if (!isNative()) return
  try {
    const { Haptics, ImpactStyle } = await import('@capacitor/haptics')
    await Haptics.impact({ style: ImpactStyle.Light })
  } catch {
    // ignore
  }
}

/** Medium impact — toggles, status changes */
export async function medium(): Promise<void> {
  if (!isNative()) return
  try {
    const { Haptics, ImpactStyle } = await import('@capacitor/haptics')
    await Haptics.impact({ style: ImpactStyle.Medium })
  } catch {
    // ignore
  }
}

/** Heavy impact — destructive actions */
export async function heavy(): Promise<void> {
  if (!isNative()) return
  try {
    const { Haptics, ImpactStyle } = await import('@capacitor/haptics')
    await Haptics.impact({ style: ImpactStyle.Heavy })
  } catch {
    // ignore
  }
}

/** Selection feedback — swipe actions, pickers */
export async function selection(): Promise<void> {
  if (!isNative()) return
  try {
    const { Haptics } = await import('@capacitor/haptics')
    await Haptics.selectionStart()
    await Haptics.selectionChanged()
    await Haptics.selectionEnd()
  } catch {
    // ignore
  }
}
