import { useMemo } from 'react'
import { Button, Modal } from '@/components/ui'
import type { ComplianceDocumentResponse } from './ComplianceDashboard'

/* ------------------------------------------------------------------ */
/*  Props                                                              */
/* ------------------------------------------------------------------ */

interface FilePreviewProps {
  open: boolean
  document: ComplianceDocumentResponse | null
  onClose: () => void
  onDownload: (doc: ComplianceDocumentResponse) => void
}

/* ------------------------------------------------------------------ */
/*  Helpers                                                            */
/* ------------------------------------------------------------------ */

type PreviewType = 'pdf' | 'image' | 'none'

function getPreviewType(fileName: string | null | undefined): PreviewType {
  const name = (fileName ?? '').toLowerCase()
  if (name.endsWith('.pdf')) return 'pdf'
  if (/\.(jpe?g|png|gif)$/.test(name)) return 'image'
  return 'none'
}

/* ------------------------------------------------------------------ */
/*  Component                                                          */
/* ------------------------------------------------------------------ */

export default function FilePreview({
  open,
  document: doc,
  onClose,
  onDownload,
}: FilePreviewProps) {
  const previewType = useMemo(
    () => getPreviewType(doc?.file_name),
    [doc?.file_name],
  )

  const downloadUrl = doc ? `/api/v2/compliance-docs/${doc.id}/download` : ''

  if (!doc) return null

  return (
    <Modal open={open} onClose={onClose} title={doc.file_name ?? 'File Preview'} className="max-w-4xl">
      <div className="space-y-4">
        {/* PDF preview */}
        {previewType === 'pdf' && (
          <div className="w-full" style={{ height: '70vh' }}>
            <iframe
              src={downloadUrl}
              title={`Preview of ${doc.file_name}`}
              className="h-full w-full rounded border border-gray-200"
              style={{ minHeight: '400px' }}
            />
          </div>
        )}

        {/* Image preview */}
        {previewType === 'image' && (
          <div className="flex items-center justify-center">
            <img
              src={downloadUrl}
              alt={doc.file_name ?? 'Document preview'}
              className="max-h-[70vh] max-w-full rounded border border-gray-200 object-contain"
            />
          </div>
        )}

        {/* Non-previewable (Word docs) — should not normally reach here */}
        {previewType === 'none' && (
          <div className="py-8 text-center">
            <svg
              className="mx-auto h-12 w-12 text-gray-400 mb-3"
              fill="none"
              viewBox="0 0 24 24"
              stroke="currentColor"
              strokeWidth={1.5}
            >
              <path
                strokeLinecap="round"
                strokeLinejoin="round"
                d="M9 12h6m-6 4h6m2 5H7a2 2 0 01-2-2V5a2 2 0 012-2h5.586a1 1 0 01.707.293l5.414 5.414a1 1 0 01.293.707V19a2 2 0 01-2 2z"
              />
            </svg>
            <p className="text-sm text-gray-600 mb-1">
              Preview is not available for this file type.
            </p>
            <p className="text-xs text-gray-400">
              Download the file to view its contents.
            </p>
          </div>
        )}

        {/* Actions */}
        <div className="flex items-center justify-end gap-3 pt-2">
          <Button
            type="button"
            variant="secondary"
            size="sm"
            onClick={() => onDownload(doc)}
            style={{ minWidth: '44px', minHeight: '44px' }}
          >
            <span className="flex items-center gap-1.5">
              <svg className="h-4 w-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                <path strokeLinecap="round" strokeLinejoin="round" d="M4 16v2a2 2 0 002 2h12a2 2 0 002-2v-2M7 10l5 5m0 0l5-5m-5 5V3" />
              </svg>
              Download
            </span>
          </Button>
          <Button
            type="button"
            size="sm"
            onClick={onClose}
            style={{ minWidth: '44px', minHeight: '44px' }}
          >
            Close
          </Button>
        </div>
      </div>
    </Modal>
  )
}
