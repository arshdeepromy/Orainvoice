import { useState } from 'react'
import { MobileButton } from '@/components/ui'
import { useCamera } from '@/hooks/useCamera'
import type { CameraPhoto } from '@/hooks/useCamera'

/* ------------------------------------------------------------------ */
/* Icons                                                              */
/* ------------------------------------------------------------------ */

function CameraIcon({ className }: { className?: string }) {
  return (
    <svg
      className={className}
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="2"
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
    >
      <path d="M14.5 4h-5L7 7H4a2 2 0 0 0-2 2v9a2 2 0 0 0 2 2h16a2 2 0 0 0 2-2V9a2 2 0 0 0-2-2h-3l-2.5-3z" />
      <circle cx="12" cy="13" r="3" />
    </svg>
  )
}

function GalleryIcon({ className }: { className?: string }) {
  return (
    <svg
      className={className}
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="2"
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
    >
      <rect width="18" height="18" x="3" y="3" rx="2" ry="2" />
      <circle cx="9" cy="9" r="2" />
      <path d="m21 15-3.086-3.086a2 2 0 0 0-2.828 0L6 21" />
    </svg>
  )
}

/* ------------------------------------------------------------------ */
/* Props                                                              */
/* ------------------------------------------------------------------ */

export interface CameraCaptureProps {
  /** Called when user confirms a captured photo */
  onCapture: (photo: CameraPhoto) => void
  /** Optional label for the capture area */
  label?: string
  /** Additional CSS classes */
  className?: string
}

/**
 * Camera UI component with capture, preview, retake/confirm flow,
 * and 2MB compression (handled by Capacitor quality settings).
 *
 * Requirements: 43.4, 43.5
 */
export function CameraCapture({
  onCapture,
  label = 'Capture Photo',
  className = '',
}: CameraCaptureProps) {
  const { takePhoto, pickFromGallery, isLoading, error } = useCamera()
  const [preview, setPreview] = useState<CameraPhoto | null>(null)

  const handleTakePhoto = async () => {
    const photo = await takePhoto()
    if (photo) {
      setPreview(photo)
    }
  }

  const handlePickGallery = async () => {
    const photo = await pickFromGallery()
    if (photo) {
      setPreview(photo)
    }
  }

  const handleConfirm = () => {
    if (preview) {
      onCapture(preview)
      setPreview(null)
    }
  }

  const handleRetake = () => {
    setPreview(null)
  }

  // Preview mode — show captured image with retake/confirm buttons
  if (preview) {
    return (
      <div className={`flex flex-col gap-3 ${className}`}>
        <p className="text-sm font-medium text-gray-700 dark:text-gray-300">
          {label}
        </p>
        <div className="overflow-hidden rounded-lg border border-gray-200 dark:border-gray-700">
          <img
            src={preview.dataUrl}
            alt="Captured preview"
            className="h-48 w-full object-cover"
          />
        </div>
        <div className="flex gap-3">
          <MobileButton variant="secondary" size="sm" onClick={handleRetake}>
            Retake
          </MobileButton>
          <MobileButton variant="primary" size="sm" onClick={handleConfirm}>
            Confirm
          </MobileButton>
        </div>
      </div>
    )
  }

  // Capture mode — show camera/gallery buttons
  return (
    <div className={`flex flex-col gap-3 ${className}`}>
      <p className="text-sm font-medium text-gray-700 dark:text-gray-300">
        {label}
      </p>
      <div className="flex gap-3">
        <MobileButton
          variant="secondary"
          size="sm"
          onClick={handleTakePhoto}
          isLoading={isLoading}
          icon={<CameraIcon className="h-4 w-4" />}
        >
          Camera
        </MobileButton>
        <MobileButton
          variant="secondary"
          size="sm"
          onClick={handlePickGallery}
          isLoading={isLoading}
          icon={<GalleryIcon className="h-4 w-4" />}
        >
          Gallery
        </MobileButton>
      </div>
      {error && (
        <p className="text-sm text-red-600 dark:text-red-400" role="alert">
          {error}
        </p>
      )}
    </div>
  )
}
