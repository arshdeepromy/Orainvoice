import { useCallback, useState } from 'react'
import apiClient from '@/api/client'
import { Button, Modal } from '@/components/ui'
import type { ComplianceDocumentResponse } from './ComplianceDashboard'

/* ------------------------------------------------------------------ */
/*  Props                                                              */
/* ------------------------------------------------------------------ */

interface DeleteConfirmationProps {
  open: boolean
  document: ComplianceDocumentResponse | null
  onClose: () => void
  onSuccess: (deletedId: string) => void
}

/* ------------------------------------------------------------------ */
/*  Component                                                          */
/* ------------------------------------------------------------------ */

export default function DeleteConfirmation({
  open,
  document: doc,
  onClose,
  onSuccess,
}: DeleteConfirmationProps) {
  const [deleting, setDeleting] = useState(false)
  const [error, setError] = useState('')

  const handleConfirm = useCallback(async () => {
    if (!doc) return

    setDeleting(true)
    setError('')

    try {
      await apiClient.delete(`/api/v2/compliance-docs/${doc.id}`)
      onSuccess(doc.id)
    } catch (err: unknown) {
      const detail =
        (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail ??
        'Failed to delete document. Please try again.'
      setError(detail)
    } finally {
      setDeleting(false)
    }
  }, [doc, onSuccess])

  const handleClose = useCallback(() => {
    setError('')
    setDeleting(false)
    onClose()
  }, [onClose])

  if (!doc) return null

  return (
    <Modal open={open} onClose={handleClose} title="Delete Document" className="max-w-md">
      <div className="space-y-4">
        {/* Error banner */}
        {error && (
          <div className="rounded-lg border border-red-200 bg-red-50 p-3" role="alert">
            <p className="text-sm text-red-700">{error}</p>
          </div>
        )}

        {/* Warning icon + message */}
        <div className="flex items-start gap-3">
          <div className="flex-shrink-0 mt-0.5">
            <svg
              className="h-6 w-6 text-red-500"
              fill="none"
              viewBox="0 0 24 24"
              stroke="currentColor"
              strokeWidth={2}
            >
              <path
                strokeLinecap="round"
                strokeLinejoin="round"
                d="M12 9v2m0 4h.01m-6.938 4h13.856c1.54 0 2.502-1.667 1.732-2.5L13.732 4.5c-.77-.833-2.694-.833-3.464 0L3.34 16.5c-.77.833.192 2.5 1.732 2.5z"
              />
            </svg>
          </div>
          <div>
            <p className="text-sm text-gray-700">
              Are you sure you want to delete{' '}
              <span className="font-medium text-gray-900">{doc.file_name}</span>?
            </p>
            <p className="text-sm text-gray-500 mt-1">
              This will permanently remove the document and its file. This action cannot be undone.
            </p>
          </div>
        </div>

        {/* Actions */}
        <div className="flex items-center justify-end gap-3 pt-2">
          <Button
            type="button"
            variant="secondary"
            size="sm"
            onClick={handleClose}
            disabled={deleting}
            style={{ minWidth: '44px', minHeight: '44px' }}
          >
            Cancel
          </Button>
          <Button
            type="button"
            variant="danger"
            size="sm"
            onClick={handleConfirm}
            loading={deleting}
            disabled={deleting}
            style={{ minWidth: '44px', minHeight: '44px' }}
          >
            Delete
          </Button>
        </div>
      </div>
    </Modal>
  )
}
