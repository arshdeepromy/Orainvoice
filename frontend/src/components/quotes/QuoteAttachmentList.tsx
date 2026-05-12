/**
 * QuoteAttachmentList — displays attachments for a quote with download and delete.
 * Mirrors the invoice attachment list pattern.
 * Task 17.1
 */

import { useEffect, useState } from 'react'
import apiClient from '../../api/client'

interface QuoteAttachment {
  id: string
  file_name: string
  file_size: number
  mime_type: string
  created_at: string
}

interface QuoteAttachmentListProps {
  quoteId: string
  isDraft: boolean
}

function formatFileSize(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`
}

function fileTypeIcon(mimeType: string): string {
  if (mimeType === 'application/pdf') return '📄'
  if (mimeType.startsWith('image/')) return '🖼️'
  return '📎'
}

export default function QuoteAttachmentList({ quoteId, isDraft }: QuoteAttachmentListProps) {
  const [attachments, setAttachments] = useState<QuoteAttachment[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [deleting, setDeleting] = useState<string | null>(null)

  useEffect(() => {
    const controller = new AbortController()
    async function fetchAttachments() {
      try {
        const res = await apiClient.get<{ attachments: QuoteAttachment[]; total: number }>(
          `/quotes/${quoteId}/attachments`,
          { signal: controller.signal }
        )
        setAttachments(res.data?.attachments ?? [])
      } catch (err) {
        if (!controller.signal.aborted) {
          setError('Failed to load attachments')
        }
      } finally {
        if (!controller.signal.aborted) setLoading(false)
      }
    }
    fetchAttachments()
    return () => controller.abort()
  }, [quoteId])

  const handleDelete = async (attachmentId: string) => {
    setDeleting(attachmentId)
    try {
      await apiClient.delete(`/quotes/${quoteId}/attachments/${attachmentId}`)
      setAttachments(prev => prev.filter(a => a.id !== attachmentId))
    } catch (err: unknown) {
      const detail = (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail
      setError(detail ?? 'Failed to delete attachment')
    } finally {
      setDeleting(null)
    }
  }

  if (loading) return null
  if (error) return <p className="text-sm text-red-600">{error}</p>
  if (attachments.length === 0) return null

  return (
    <div className="border-t border-gray-200 p-6">
      <h3 className="text-sm font-semibold text-gray-900 mb-3">
        Attachments <span className="text-xs text-gray-400 font-normal">({attachments.length})</span>
      </h3>
      <ul className="space-y-2">
        {attachments.map(att => (
          <li key={att.id} className="flex items-center justify-between rounded-md border border-gray-100 px-3 py-2">
            <a
              href={`/api/v1/quotes/${quoteId}/attachments/${att.id}`}
              target="_blank"
              rel="noopener noreferrer"
              className="flex items-center gap-2 text-sm text-blue-600 hover:text-blue-800 min-w-0"
            >
              <span>{fileTypeIcon(att.mime_type)}</span>
              <span className="truncate">{att.file_name}</span>
              <span className="text-xs text-gray-400 flex-shrink-0">{formatFileSize(att.file_size)}</span>
            </a>
            {isDraft && (
              <button
                onClick={() => handleDelete(att.id)}
                disabled={deleting === att.id}
                className="ml-2 rounded px-2 py-1 text-xs text-red-500 hover:bg-red-50 disabled:opacity-50"
                title="Delete attachment"
              >
                {deleting === att.id ? '…' : '×'}
              </button>
            )}
          </li>
        ))}
      </ul>
    </div>
  )
}
