/**
 * Camera — convenience re-export + standalone function.
 *
 * Import from `@/native` instead of `@/hooks` for non-hook contexts.
 */

export { useCamera } from '@/hooks/useCamera'
export type { CameraPhoto, UseCameraResult } from '@/hooks/useCamera'

/**
 * Standalone photo capture — usable outside React components.
 * Returns null on web or when the user cancels.
 */
export async function takePhoto(): Promise<{ dataUrl: string; format: string } | null> {
  const isNative = !!(window as any).Capacitor?.isNativePlatform?.()

  if (isNative) {
    try {
      const { Camera, CameraResultType, CameraSource } = await import('@capacitor/camera')
      const photo = await Camera.getPhoto({
        quality: 85,
        allowEditing: false,
        resultType: CameraResultType.Uri,
        source: CameraSource.Prompt,
        width: 1200,
        height: 1200,
      })
      return {
        dataUrl: photo.webPath ?? photo.path ?? '',
        format: `image/${photo.format ?? 'jpeg'}`,
      }
    } catch {
      return null
    }
  }

  // Web fallback — not available as standalone (use the hook for file-input flow)
  return null
}
