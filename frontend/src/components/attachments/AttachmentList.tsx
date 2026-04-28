import { useCallback, useEffect, useState } from 'react'
import apiClient from '@/api/client'
import type { Attachment } from './AttachmentUploader'

/* ------------------------------------------------------------------ */
/*  Types                                                              */
/* ------------------------------------------------------------------ */

interface AttachmentListProps {
  attachments: Attachment[]
  onDelete?: (id: string) => void
  onImageClick?: (attachment: Attachment) => void
  readOnly?: boolean
}

/* ------------------------------------------------------------------ */
/*  Helpers                                                            */
/* ------------------------------------------------------------------ */

/** Format bytes into a human-readable string (B / KB / MB). */
function formatFileSize(bytes: number): string {
  const size = bytes ?? 0
  if (size < 1024) return `${size} B`
  if (size < 1_048_576) return `${(size / 1024).toFixed(1)} KB`
  return `${(size / 1_048_576).toFixed(1)} MB`
}

/** Returns true when the MIME type represents an image the browser can display. */
function isImageMime(mime: string | undefined | null): boolean {
  return !!mime && mime.startsWith('image/')
}

/** Returns true when the MIME type is a PDF. */
function isPdfMime(mime: string | undefined | null): boolean {
  return mime === 'application/pdf'
}

/** Build the API path for an attachment (no leading /api/v1 — apiClient adds the base). */
function apiPath(attachment: Attachment): string {
  return `/job-cards/${attachment.job_card_id}/attachments/${attachment.id}`
}

/* ------------------------------------------------------------------ */
/*  Blob-based image thumbnail                                         */
/* ------------------------------------------------------------------ */

/** Fetches the image via apiClient (with auth) and renders a blob-based thumbnail. */
function ImageThumbnail({ attachment }: { attachment: Attachment }) {
  const [blobUrl, setBlobUrl] = useState<string | null>(null)

  useEffect(() => {
    const controller = new AbortController()
    let url: string | null = null

    apiClient
      .get(apiPath(attachment), {
        responseType: 'blob',
        signal: controller.signal,
      })
      .then((res) => {
        url = URL.createObjectURL(res.data as Blob)
        setBlobUrl(url)
      })
      .catch(() => {
        /* ignore — thumbnail just won't load */
      })

    return () => {
      controller.abort()
      if (url) URL.revokeObjectURL(url)
    }
  }, [attachment.id, attachment.job_card_id])

  if (!blobUrl) {
    // Placeholder while loading
    return (
      <div className="flex h-10 w-10 items-center justify-center rounded bg-gray-100 text-gray-400">
        <svg className="h-5 w-5 animate-pulse" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1.5}>
          <path strokeLinecap="round" strokeLinejoin="round" d="M2.25 15.75l5.159-5.159a2.25 2.25 0 013.182 0l5.159 5.159m-1.5-1.5l1.409-1.409a2.25 2.25 0 013.182 0l2.909 2.909M3.75 21h16.5" />
        </svg>
      </div>
    )
  }

  return (
    <img
      src={blobUrl}
      alt={attachment.file_name ?? 'Attachment'}
      className="h-10 w-10 rounded object-cover"
    />
  )
}

/* ------------------------------------------------------------------ */
/*  Sub-components                                                     */
/* ------------------------------------------------------------------ */

/** Thumbnail for images, PDF icon for PDFs, generic file icon otherwise. */
function AttachmentThumbnail({ attachment }: { attachment: Attachment }) {
  if (isImageMime(attachment.mime_type)) {
    return <ImageThumbnail attachment={attachment} />
  }

  if (isPdfMime(attachment.mime_type)) {
    return (
      <div
        className="flex h-10 w-10 items-center justify-center rounded bg-red-100 text-red-600"
        aria-hidden="true"
      >
        <svg className="h-6 w-6" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1.5}>
          <path strokeLinecap="round" strokeLinejoin="round" d="M19.5 14.25v-2.625a3.375 3.375 0 00-3.375-3.375h-1.5A1.125 1.125 0 0113.5 7.125v-1.5a3.375 3.375 0 00-3.375-3.375H8.25m2.25 0H5.625c-.621 0-1.125.504-1.125 1.125v17.25c0 .621.504 1.125 1.125 1.125h12.75c.621 0 1.125-.504 1.125-1.125V11.25a9 9 0 00-9-9z" />
        </svg>
      </div>
    )
  }

  return (
    <div
      className="flex h-10 w-10 items-center justify-center rounded bg-gray-100 text-gray-500"
      aria-hidden="true"
    >
      <svg className="h-6 w-6" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1.5}>
        <path strokeLinecap="round" strokeLinejoin="round" d="M19.5 14.25v-2.625a3.375 3.375 0 00-3.375-3.375h-1.5A1.125 1.125 0 0113.5 7.125v-1.5a3.375 3.375 0 00-3.375-3.375H8.25m2.25 0H5.625c-.621 0-1.125.504-1.125 1.125v17.25c0 .621.504 1.125 1.125 1.125h12.75c.621 0 1.125-.504 1.125-1.125V11.25a9 9 0 00-9-9z" />
      </svg>
    </div>
  )
}

/* ------------------------------------------------------------------ */
/*  Main component                                                     */
/* ------------------------------------------------------------------ */

export default function AttachmentList({
  attachments,
  onDelete,
  onImageClick,
  readOnly = false,
}: AttachmentListProps) {
  /** Open the attachment — images use the onImageClick callback (lightbox),
   *  PDFs and other files are fetched as blobs and opened in a new tab. */
  const handleView = useCallback(
    async (attachment: Attachment) => {
      if (isImageMime(attachment.mime_type) && onImageClick) {
        onImageClick(attachment)
        return
      }
      // Fetch via apiClient with auth, then open blob in new tab
      try {
        const res = await apiClient.get(apiPath(attachment), { responseType: 'blob' })
        const blob = res.data as Blob
        const url = URL.createObjectURL(blob)
        window.open(url, '_blank', 'noopener,noreferrer')
        // Revoke after a short delay to allow the tab to load
        setTimeout(() => URL.revokeObjectURL(url), 10_000)
      } catch {
        // Fallback: try direct URL (may fail if auth is cookie-based)
        const url = `/api/v1/job-cards/${attachment.job_card_id}/attachments/${attachment.id}`
        window.open(url, '_blank', 'noopener,noreferrer')
      }
    },
    [onImageClick],
  )

  const safeAttachments = attachments ?? []

  if (safeAttachments.length === 0) {
    return null
  }

  return (
    <ul className="divide-y divide-gray-200 rounded-lg border border-gray-200" role="list">
      {safeAttachments.map((attachment) => (
        <li key={attachment.id} className="flex items-center gap-3 px-3 py-2">
          {/* Clickable area: thumbnail + file info */}
          <button
            type="button"
            className="flex min-w-0 flex-1 items-center gap-3 rounded text-left hover:bg-gray-50 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-blue-500 focus-visible:ring-offset-1 p-1 -m-1 transition-colors"
            onClick={() => handleView(attachment)}
            title={`View ${attachment.file_name ?? 'attachment'}`}
            aria-label={`View ${attachment.file_name ?? 'attachment'}`}
          >
            <AttachmentThumbnail attachment={attachment} />

            <div className="min-w-0 flex-1">
              <p className="truncate text-sm font-medium text-gray-900">
                {attachment.file_name ?? 'Unnamed file'}
              </p>
              <p className="text-xs text-gray-500">
                {formatFileSize(attachment.file_size)}
              </p>
            </div>
          </button>

          {/* Delete button */}
          {!readOnly && onDelete && (
            <button
              type="button"
              className="flex-shrink-0 rounded p-1.5 text-gray-400 hover:bg-red-50 hover:text-red-600 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-red-500 transition-colors"
              onClick={() => onDelete(attachment.id)}
              title={`Delete ${attachment.file_name ?? 'attachment'}`}
              aria-label={`Delete ${attachment.file_name ?? 'attachment'}`}
            >
              <svg
                className="h-5 w-5"
                fill="none"
                viewBox="0 0 24 24"
                stroke="currentColor"
                strokeWidth={1.5}
                aria-hidden="true"
              >
                <path
                  strokeLinecap="round"
                  strokeLinejoin="round"
                  d="M14.74 9l-.346 9m-4.788 0L9.26 9m9.968-3.21c.342.052.682.107 1.022.166m-1.022-.165L18.16 19.673a2.25 2.25 0 01-2.244 2.077H8.084a2.25 2.25 0 01-2.244-2.077L4.772 5.79m14.456 0a48.108 48.108 0 00-3.478-.397m-12 .562c.34-.059.68-.114 1.022-.165m0 0a48.11 48.11 0 013.478-.397m7.5 0v-.916c0-1.18-.91-2.164-2.09-2.201a51.964 51.964 0 00-3.32 0c-1.18.037-2.09 1.022-2.09 2.201v.916m7.5 0a48.667 48.667 0 00-7.5 0"
                />
              </svg>
            </button>
          )}
        </li>
      ))}
    </ul>
  )
}
