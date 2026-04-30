import { useCallback, useEffect, useState } from 'react'
import apiClient from '@/api/client'

/* ------------------------------------------------------------------ */
/*  Types                                                              */
/* ------------------------------------------------------------------ */

interface InvoiceAttachment {
  id: string
  file_name: string
  mime_type: string
  file_size: number
  created_at: string
  uploaded_by_name?: string | null
}

interface AttachmentListProps {
  invoiceId: string
  isDraft: boolean
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

/** Format a date string to a short NZ locale format. */
function formatDate(dateStr: string | null | undefined): string {
  if (!dateStr) return '—'
  return new Intl.DateTimeFormat('en-NZ', {
    day: '2-digit',
    month: 'short',
    year: 'numeric',
  }).format(new Date(dateStr))
}

/** Returns true when the MIME type represents an image the browser can display. */
function isImageMime(mime: string | undefined | null): boolean {
  return !!mime && mime.startsWith('image/')
}

/** Returns true when the MIME type is a PDF. */
function isPdfMime(mime: string | undefined | null): boolean {
  return mime === 'application/pdf'
}

/* ------------------------------------------------------------------ */
/*  Sub-components                                                     */
/* ------------------------------------------------------------------ */

/** File type icon — image icon for images, PDF icon for PDFs, generic file icon otherwise. */
function FileTypeIcon({ mimeType }: { mimeType: string | undefined | null }) {
  if (isImageMime(mimeType)) {
    return (
      <div
        className="flex h-9 w-9 items-center justify-center rounded bg-blue-50 text-blue-500"
        aria-hidden="true"
      >
        <svg className="h-5 w-5" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1.5}>
          <path
            strokeLinecap="round"
            strokeLinejoin="round"
            d="M2.25 15.75l5.159-5.159a2.25 2.25 0 013.182 0l5.159 5.159m-1.5-1.5l1.409-1.409a2.25 2.25 0 013.182 0l2.909 2.909M3.75 21h16.5a2.25 2.25 0 002.25-2.25V5.25a2.25 2.25 0 00-2.25-2.25H3.75A2.25 2.25 0 001.5 5.25v13.5A2.25 2.25 0 003.75 21z"
          />
        </svg>
      </div>
    )
  }

  if (isPdfMime(mimeType)) {
    return (
      <div
        className="flex h-9 w-9 items-center justify-center rounded bg-red-50 text-red-500"
        aria-hidden="true"
      >
        <svg className="h-5 w-5" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1.5}>
          <path
            strokeLinecap="round"
            strokeLinejoin="round"
            d="M19.5 14.25v-2.625a3.375 3.375 0 00-3.375-3.375h-1.5A1.125 1.125 0 0113.5 7.125v-1.5a3.375 3.375 0 00-3.375-3.375H8.25m2.25 0H5.625c-.621 0-1.125.504-1.125 1.125v17.25c0 .621.504 1.125 1.125 1.125h12.75c.621 0 1.125-.504 1.125-1.125V11.25a9 9 0 00-9-9z"
          />
        </svg>
      </div>
    )
  }

  return (
    <div
      className="flex h-9 w-9 items-center justify-center rounded bg-gray-100 text-gray-400"
      aria-hidden="true"
    >
      <svg className="h-5 w-5" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1.5}>
        <path
          strokeLinecap="round"
          strokeLinejoin="round"
          d="M19.5 14.25v-2.625a3.375 3.375 0 00-3.375-3.375h-1.5A1.125 1.125 0 0113.5 7.125v-1.5a3.375 3.375 0 00-3.375-3.375H8.25m2.25 0H5.625c-.621 0-1.125.504-1.125 1.125v17.25c0 .621.504 1.125 1.125 1.125h12.75c.621 0 1.125-.504 1.125-1.125V11.25a9 9 0 00-9-9z"
        />
      </svg>
    </div>
  )
}

/* ------------------------------------------------------------------ */
/*  Main component                                                     */
/* ------------------------------------------------------------------ */

export default function AttachmentList({ invoiceId, isDraft }: AttachmentListProps) {
  const [attachments, setAttachments] = useState<InvoiceAttachment[]>([])
  const [loading, setLoading] = useState(true)

  /* Fetch attachments on mount with AbortController cleanup */
  useEffect(() => {
    const controller = new AbortController()

    const fetchAttachments = async () => {
      try {
        const res = await apiClient.get<{ attachments: InvoiceAttachment[]; total: number }>(
          `/invoices/${invoiceId}/attachments`,
          { signal: controller.signal },
        )
        setAttachments(res.data?.attachments ?? [])
      } catch {
        if (!controller.signal.aborted) {
          setAttachments([])
        }
      } finally {
        if (!controller.signal.aborted) {
          setLoading(false)
        }
      }
    }

    fetchAttachments()
    return () => controller.abort()
  }, [invoiceId])

  /* Open attachment in a new tab (full API path since it returns the raw file) */
  const handleOpen = useCallback(
    (attachmentId: string) => {
      window.open(
        `/api/v1/invoices/${invoiceId}/attachments/${attachmentId}`,
        '_blank',
        'noopener,noreferrer',
      )
    },
    [invoiceId],
  )

  /* Delete attachment and remove from local state */
  const handleDelete = useCallback(
    async (attachmentId: string) => {
      try {
        await apiClient.delete(`/invoices/${invoiceId}/attachments/${attachmentId}`)
        setAttachments((prev) => prev.filter((a) => a.id !== attachmentId))
      } catch {
        // Non-blocking — silently fail
      }
    },
    [invoiceId],
  )

  /* Don't render anything while loading */
  if (loading) return null

  /* Don't render the section at all if count is 0 */
  if ((attachments ?? []).length === 0) return null

  return (
    <div className="mt-4">
      <h3 className="text-sm font-semibold text-gray-700 mb-2">
        Attachments ({(attachments ?? []).length})
      </h3>

      <ul className="divide-y divide-gray-100 rounded-lg border border-gray-200 bg-white" role="list">
        {(attachments ?? []).map((attachment) => (
          <li key={attachment.id} className="flex items-center gap-3 px-3 py-2.5">
            {/* File type icon */}
            <FileTypeIcon mimeType={attachment.mime_type} />

            {/* Clickable filename + metadata */}
            <button
              type="button"
              className="flex min-w-0 flex-1 flex-col text-left rounded hover:bg-gray-50 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-blue-500 focus-visible:ring-offset-1 p-1 -m-1 transition-colors"
              onClick={() => handleOpen(attachment.id)}
              title={`Open ${attachment.file_name ?? 'attachment'}`}
              aria-label={`Open ${attachment.file_name ?? 'attachment'}`}
            >
              <span className="truncate text-sm font-medium text-blue-600 hover:text-blue-800">
                {attachment.file_name ?? 'Unnamed file'}
              </span>
              <span className="text-xs text-gray-500">
                {formatFileSize(attachment.file_size)} · {formatDate(attachment.created_at)}
              </span>
            </button>

            {/* Delete button — only for draft invoices */}
            {isDraft && (
              <button
                type="button"
                className="flex-shrink-0 rounded p-1.5 text-gray-400 hover:bg-red-50 hover:text-red-600 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-red-500 transition-colors"
                onClick={() => handleDelete(attachment.id)}
                title={`Delete ${attachment.file_name ?? 'attachment'}`}
                aria-label={`Delete ${attachment.file_name ?? 'attachment'}`}
              >
                <svg
                  className="h-4.5 w-4.5"
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
    </div>
  )
}
