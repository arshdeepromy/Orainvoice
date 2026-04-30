import { useState, useCallback } from 'react'

/* ------------------------------------------------------------------ */
/* Types                                                              */
/* ------------------------------------------------------------------ */

export interface CameraPhoto {
  /** Base64-encoded image data or web object URL */
  dataUrl: string
  /** MIME type of the image */
  format: string
}

export interface UseCameraResult {
  /** Take a photo using the device camera */
  takePhoto: () => Promise<CameraPhoto | null>
  /** Pick a photo from the device gallery */
  pickFromGallery: () => Promise<CameraPhoto | null>
  /** Whether a camera operation is in progress */
  isLoading: boolean
  /** Error message from the last operation */
  error: string | null
}

/**
 * Capacitor camera wrapper for photo capture and gallery selection.
 * Falls back to file input in browser environments where Capacitor
 * Camera plugin is not available.
 *
 * Requirements: 43.1, 43.2, 43.3, 43.4, 43.5
 */
export function useCamera(): UseCameraResult {
  const [isLoading, setIsLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const captureViaFileInput = useCallback(
    (accept: string, capture?: string): Promise<CameraPhoto | null> => {
      return new Promise((resolve) => {
        const input = document.createElement('input')
        input.type = 'file'
        input.accept = accept
        if (capture) input.setAttribute('capture', capture)

        input.onchange = () => {
          const file = input.files?.[0]
          if (!file) {
            resolve(null)
            return
          }
          const reader = new FileReader()
          reader.onload = () => {
            resolve({
              dataUrl: reader.result as string,
              format: file.type || 'image/jpeg',
            })
          }
          reader.onerror = () => {
            resolve(null)
          }
          reader.readAsDataURL(file)
        }

        // User cancelled the file picker
        input.oncancel = () => resolve(null)

        input.click()
      })
    },
    [],
  )

  const takePhoto = useCallback(async (): Promise<CameraPhoto | null> => {
    setIsLoading(true)
    setError(null)

    // Check Capacitor runtime global — avoids bundler issues with require()
    const isNative = !!(window as any).Capacitor?.isNativePlatform?.()

    if (isNative) {
      try {
        const { Camera, CameraResultType, CameraSource } = await import(
          '@capacitor/camera'
        )
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
        // Native camera failed — fall through to file input
      }
    }

    // Web fallback — file input with capture
    try {
      return await captureViaFileInput('image/*', 'environment')
    } catch {
      setError('Failed to capture photo')
      return null
    } finally {
      setIsLoading(false)
    }
  }, [captureViaFileInput])

  const pickFromGallery = useCallback(async (): Promise<CameraPhoto | null> => {
    setIsLoading(true)
    setError(null)

    // Check Capacitor runtime global — avoids bundler issues with require()
    const isNative = !!(window as any).Capacitor?.isNativePlatform?.()

    if (isNative) {
      try {
        const { Camera, CameraResultType, CameraSource } = await import(
          '@capacitor/camera'
        )
        const photo = await Camera.getPhoto({
          quality: 85,
          allowEditing: false,
          resultType: CameraResultType.Uri,
          source: CameraSource.Photos,
          width: 1200,
          height: 1200,
        })
        return {
          dataUrl: photo.webPath ?? photo.path ?? '',
          format: `image/${photo.format ?? 'jpeg'}`,
        }
      } catch {
        // Native gallery failed — fall through to file input
      }
    }

    // Web fallback — file input
    try {
      return await captureViaFileInput('image/*')
    } catch {
      setError('Failed to pick photo')
      return null
    } finally {
      setIsLoading(false)
    }
  }, [captureViaFileInput])

  return { takePhoto, pickFromGallery, isLoading, error }
}
