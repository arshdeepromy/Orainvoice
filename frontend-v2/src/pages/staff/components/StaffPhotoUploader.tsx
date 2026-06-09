/**
 * StaffPhotoUploader — circular avatar with click-to-upload + delete + preview.
 *
 * Renders the staff member's current `on_file_photo_url` as a 96×96 round
 * avatar. Click to open the OS file picker (image/*); the chosen file is
 * resized client-side via canvas to ≤ 512px on the long edge at JPEG quality
 * 0.85 BEFORE upload so we never push a 4MB phone selfie over the wire — the
 * server then re-runs the same passport-size compression as a defence-in-depth
 * pass (≤ 512px / quality 78). End result: typically 25–40 KB stored.
 *
 * Backend wires:
 *   - POST /api/v2/uploads/staff-photos      multipart → { file_key, ... }
 *
 * The component is intentionally thin — it does NOT call the staff PUT endpoint
 * itself. It surfaces `onChange(value)` carrying the FULL photo URL
 * (`/api/v2/uploads/<file_key>`) so the parent OverviewTab folds it into the
 * existing edit form alongside every other field; the edit form submits one
 * PUT /staff/{id} on save just like any other field change.
 *
 * Edit-mode-only by design: `editing=false` → read-only avatar with no
 * hover/click behaviour, mirroring the rest of OverviewTab's read/edit toggle.
 */

import { useCallback, useEffect, useRef, useState } from 'react'
import apiClient from '@/api/client'
import useAuthorizedImage from '@/hooks/useAuthorizedImage'

interface StaffPhotoUploaderProps {
  /** Current photo URL (file_key path or full /api/v2/uploads/... URL). */
  value: string | null
  /** Initials fallback shown when no photo is on file. */
  initials: string
  /** Edit mode flag — outside the parent's edit toggle the avatar is read-only. */
  editing: boolean
  /** Called with the new URL after a successful upload, or `null` after delete. */
  onChange: (value: string | null) => void
}

interface UploadResult {
  file_key: string
  file_name: string
  file_size: number
}

const MAX_INPUT_BYTES = 10 * 1024 * 1024 // 10 MB pre-resize ceiling
const ALLOWED_TYPES = ['image/jpeg', 'image/jpg', 'image/png', 'image/webp']
const TARGET_LONG_EDGE = 512
const JPEG_QUALITY = 0.85

/** Resize an image File via an in-memory canvas to ≤ 512px on the long edge,
 *  JPEG quality 0.85. Falls back to the original blob if the canvas pipeline
 *  fails for any reason (e.g. browser without `OffscreenCanvas` doing
 *  something unexpected). */
async function compressClientSide(file: File): Promise<Blob> {
  return new Promise<Blob>((resolve, reject) => {
    const url = URL.createObjectURL(file)
    const img = new Image()
    img.onload = () => {
      const canvas = document.createElement('canvas')
      const w = img.naturalWidth || img.width
      const h = img.naturalHeight || img.height
      const longEdge = Math.max(w, h)
      const ratio = longEdge > TARGET_LONG_EDGE ? TARGET_LONG_EDGE / longEdge : 1
      canvas.width = Math.round(w * ratio)
      canvas.height = Math.round(h * ratio)
      const ctx = canvas.getContext('2d')
      if (!ctx) {
        URL.revokeObjectURL(url)
        // Fall back to the original file rather than crashing.
        resolve(file)
        return
      }
      // Flatten transparency onto white so a PNG-with-alpha doesn't render as
      // black after the JPEG conversion.
      ctx.fillStyle = '#ffffff'
      ctx.fillRect(0, 0, canvas.width, canvas.height)
      ctx.drawImage(img, 0, 0, canvas.width, canvas.height)
      canvas.toBlob(
        (blob) => {
          URL.revokeObjectURL(url)
          if (blob) resolve(blob)
          else resolve(file)
        },
        'image/jpeg',
        JPEG_QUALITY,
      )
    }
    img.onerror = () => {
      URL.revokeObjectURL(url)
      reject(new Error('Could not read the selected image. Please try a different file.'))
    }
    img.src = url
  })
}

/** Resolve a value (file_key OR full URL OR null) into a renderable `<img src>`.
 *  - Full URLs (http://… / https://… / data:…) pass through untouched.
 *  - Bare file_keys get the `/api/v2/uploads/` prefix prepended.
 *  - Already-prefixed paths pass through.
 *  - Null / empty returns null so the caller renders the initials fallback.
 *
 *  NOTE: this helper is retained for callers that render a saved photo
 *  WITHOUT the JWT-aware fetch (e.g. test fixtures, dev tools). The
 *  in-component renderer prefers the `useAuthorizedImage` hook because the
 *  upload route is JWT-protected and `<img src>` doesn't carry headers. */
function resolvePhotoSrc(value: string | null | undefined): string | null {
  if (!value) return null
  const trimmed = value.trim()
  if (!trimmed) return null
  if (
    trimmed.startsWith('http://') ||
    trimmed.startsWith('https://') ||
    trimmed.startsWith('data:') ||
    trimmed.startsWith('/api/')
  ) {
    return trimmed
  }
  return `/api/v2/uploads/${trimmed.replace(/^\/+/, '')}`
}

void resolvePhotoSrc

export default function StaffPhotoUploader({
  value,
  initials,
  editing,
  onChange,
}: StaffPhotoUploaderProps) {
  const inputRef = useRef<HTMLInputElement | null>(null)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  // Local object-URL preview so the chosen photo appears INSTANTLY in the
  // avatar — independent of the upload round-trip and the server URL the
  // parent ultimately persists. Revoked on unmount + on every replace so we
  // never leak a blob URL into memory.
  const [localPreview, setLocalPreview] = useState<string | null>(null)
  const previewUrlRef = useRef<string | null>(null)

  // Cleanup: revoke any pending object URL on unmount.
  useEffect(() => {
    return () => {
      if (previewUrlRef.current) {
        URL.revokeObjectURL(previewUrlRef.current)
        previewUrlRef.current = null
      }
    }
  }, [])

  // Resolve the saved/remote URL through the JWT-aware fetch hook so the
  // browser renders the encrypted-at-rest /api/v2/uploads/... blob despite
  // <img> not carrying the bearer token. Local preview wins while present.
  const remote = useAuthorizedImage(localPreview ? null : value)
  const photoSrc = localPreview ?? remote.src

  const setPreviewFromBlob = useCallback((blob: Blob | null) => {
    // Always revoke the previous URL before swapping so successive picks
    // don't leak.
    if (previewUrlRef.current) {
      URL.revokeObjectURL(previewUrlRef.current)
      previewUrlRef.current = null
    }
    if (!blob) {
      setLocalPreview(null)
      return
    }
    const url = URL.createObjectURL(blob)
    previewUrlRef.current = url
    setLocalPreview(url)
  }, [])

  const handlePick = useCallback(() => {
    if (!editing || busy) return
    inputRef.current?.click()
  }, [editing, busy])

  const handleFileChange = useCallback(
    async (e: React.ChangeEvent<HTMLInputElement>) => {
      const file = e.target.files?.[0]
      // Reset the input so picking the same filename twice still fires onChange.
      e.target.value = ''
      if (!file) return

      setError(null)

      // Type guard — the server will also reject non-images with 415, but we
      // catch it here so the user gets immediate feedback.
      if (!ALLOWED_TYPES.includes(file.type.toLowerCase())) {
        setError('Please choose a JPG, PNG, or WebP image.')
        return
      }
      if (file.size > MAX_INPUT_BYTES) {
        setError('That image is too large. Please pick something under 10 MB.')
        return
      }

      // Show the original file in the avatar IMMEDIATELY — the canvas resize
      // + network round-trip can take a beat on slow connections, and the
      // user expects to see what they picked the moment the picker closes.
      setPreviewFromBlob(file)

      setBusy(true)
      try {
        const blob = await compressClientSide(file)
        // Swap the preview to the resized (smaller) blob so memory pressure
        // drops and the eventual remote URL we persist matches what's shown.
        setPreviewFromBlob(blob)

        const formData = new FormData()
        // Force the resized output to land at .jpg server-side regardless of
        // input extension. Smaller filename + matches the JPEG mime type.
        formData.append('file', blob, 'profile.jpg')

        const res = await apiClient.post<UploadResult>(
          '/api/v2/uploads/staff-photos',
          formData,
          { headers: { 'Content-Type': 'multipart/form-data' } },
        )
        const fileKey = res.data?.file_key ?? ''
        if (!fileKey) {
          setError("Upload finished but the file key was empty. Please try again.")
          return
        }
        // Save the resolvable URL on the parent so existing <img src> renderers
        // (kiosk lookup, hours tab, table rows) can render the photo without
        // any further plumbing. Keep the local preview alive — the parent
        // hasn't refetched yet, and the `<img>` will simply prefer the local
        // preview over the remote URL until this component unmounts (next
        // refresh will pick up the persisted URL on a fresh mount).
        const fullUrl = `/api/v2/uploads/${fileKey}`
        onChange(fullUrl)
      } catch (err: unknown) {
        // Upload failed — drop the preview so the user knows the photo
        // didn't actually land on the server.
        setPreviewFromBlob(null)

        const status = (err as { response?: { status?: number } })?.response
          ?.status
        if (status === 413) {
          setError('That photo is too large. Please pick a smaller one.')
        } else if (status === 415) {
          setError('That image format is not supported. Try a JPG or PNG.')
        } else if (err instanceof Error && err.message) {
          setError(err.message)
        } else {
          setError("Couldn't upload the photo. Please try again.")
        }
      } finally {
        setBusy(false)
      }
    },
    [onChange, setPreviewFromBlob],
  )

  const handleRemove = useCallback(() => {
    if (!editing || busy) return
    setError(null)
    setPreviewFromBlob(null)
    onChange(null)
  }, [editing, busy, onChange, setPreviewFromBlob])

  return (
    <div className="flex items-start gap-4">
      {/* Avatar */}
      <div className="relative">
        <div
          className={[
            'grid h-24 w-24 place-items-center overflow-hidden rounded-full border-2 border-border bg-canvas',
            editing && !busy ? 'cursor-pointer hover:border-accent' : '',
            busy ? 'opacity-60' : '',
          ].join(' ')}
          onClick={handlePick}
          role={editing ? 'button' : undefined}
          aria-label={
            editing ? 'Upload profile photo' : 'Profile photo'
          }
          tabIndex={editing ? 0 : -1}
          onKeyDown={(e) => {
            if (!editing) return
            if (e.key === 'Enter' || e.key === ' ') {
              e.preventDefault()
              handlePick()
            }
          }}
        >
          {photoSrc ? (
            <img
              src={photoSrc}
              alt="Profile"
              className="h-full w-full object-cover"
            />
          ) : (
            <span
              className="text-2xl font-bold uppercase text-muted-2"
              aria-hidden="true"
            >
              {initials || '?'}
            </span>
          )}
        </div>

        {/* Edit-mode camera badge */}
        {editing && (
          <span
            aria-hidden="true"
            className="absolute -bottom-1 -right-1 inline-flex h-7 w-7 items-center justify-center rounded-full bg-accent text-white shadow-card ring-2 ring-card"
          >
            <svg
              className="h-3.5 w-3.5"
              viewBox="0 0 24 24"
              fill="none"
              stroke="currentColor"
              strokeWidth={2}
              strokeLinecap="round"
              strokeLinejoin="round"
            >
              <path d="M3 9a2 2 0 012-2h2.5l1.5-2h6l1.5 2H19a2 2 0 012 2v9a2 2 0 01-2 2H5a2 2 0 01-2-2V9z" />
              <circle cx="12" cy="13" r="3.5" />
            </svg>
          </span>
        )}

        {/* Hidden file input */}
        <input
          ref={inputRef}
          type="file"
          accept="image/jpeg,image/png,image/webp"
          onChange={handleFileChange}
          className="hidden"
        />
      </div>

      {/* Edit-mode controls beside the avatar */}
      {editing && (
        <div className="flex flex-col gap-2 pt-1">
          <button
            type="button"
            onClick={handlePick}
            disabled={busy}
            className="min-h-[36px] rounded-ctl border border-border bg-card px-3 py-1.5 text-[13px] font-medium text-text shadow-card hover:bg-canvas focus:outline-none focus:ring-2 focus:ring-accent disabled:cursor-not-allowed disabled:opacity-60"
          >
            {busy
              ? 'Uploading…'
              : photoSrc
              ? 'Change photo'
              : 'Upload photo'}
          </button>
          {photoSrc && !busy && (
            <button
              type="button"
              onClick={handleRemove}
              className="min-h-[28px] rounded-ctl px-3 py-1 text-[12px] font-medium text-danger hover:bg-danger-soft focus:outline-none focus:ring-2 focus:ring-danger"
            >
              Remove
            </button>
          )}
          <p className="text-[11px] text-muted-2">
            JPG, PNG, or WebP. Resized + compressed automatically.
          </p>
          {error && (
            <p
              role="alert"
              className="rounded-ctl bg-danger-soft px-2 py-1 text-[11.5px] font-medium text-danger"
            >
              {error}
            </p>
          )}
        </div>
      )}
    </div>
  )
}
