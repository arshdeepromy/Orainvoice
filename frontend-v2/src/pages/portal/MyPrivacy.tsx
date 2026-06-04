import { useState } from 'react'
import apiClient from '@/api/client'

interface MyPrivacyProps {
  token: string
}

interface DSARResponse {
  request_type: string
  message: string
}

export function MyPrivacy({ token }: MyPrivacyProps) {
  const [submitting, setSubmitting] = useState(false)
  const [confirmType, setConfirmType] = useState<'export' | 'deletion' | null>(null)
  const [success, setSuccess] = useState('')
  const [error, setError] = useState('')

  const handleSubmit = async (requestType: 'export' | 'deletion') => {
    setSubmitting(true)
    setError('')
    setSuccess('')
    try {
      const res = await apiClient.post<DSARResponse>(
        `/portal/${token}/dsar`,
        { request_type: requestType },
      )
      setSuccess(res.data?.message ?? 'Your request has been submitted.')
      setConfirmType(null)
    } catch (err: unknown) {
      const axiosErr = err as { response?: { data?: { detail?: string } } }
      setError(
        axiosErr?.response?.data?.detail ?? 'Failed to submit request. Please try again.',
      )
    } finally {
      setSubmitting(false)
    }
  }

  return (
    <div className="mb-6 rounded-card border border-border bg-card shadow-card p-4">
      <h2 className="text-lg font-medium text-text">My Privacy</h2>
      <p className="mt-1 text-sm text-muted">
        You can request a copy of your data or request deletion of your account.
        These requests will be reviewed by the organisation.
      </p>

      {success && (
        <div className="mt-3 rounded-ctl bg-ok-soft p-3">
          <p className="text-sm text-ok">{success}</p>
        </div>
      )}
      {error && (
        <div className="mt-3 rounded-ctl bg-danger-soft p-3">
          <p className="text-sm text-danger">{error}</p>
        </div>
      )}

      {/* Confirmation dialog for export */}
      {confirmType === 'export' && (
        <div className="mt-3 rounded-ctl border border-accent bg-accent-soft p-4">
          <p className="text-sm font-medium text-accent">
            Request Data Export?
          </p>
          <p className="mt-1 text-sm text-accent">
            The organisation will be notified and will provide a copy of your
            personal data. This may take a few business days.
          </p>
          <div className="mt-3 flex gap-2">
            <button
              type="button"
              onClick={() => handleSubmit('export')}
              disabled={submitting}
              className="rounded-ctl bg-accent px-3 py-2 text-sm font-medium text-white hover:bg-accent-press disabled:opacity-50 min-h-[44px]"
            >
              {submitting ? 'Submitting…' : 'Confirm Request'}
            </button>
            <button
              type="button"
              onClick={() => setConfirmType(null)}
              disabled={submitting}
              className="rounded-ctl border border-border bg-card px-3 py-2 text-sm font-medium text-text hover:bg-canvas disabled:opacity-50 min-h-[44px]"
            >
              Cancel
            </button>
          </div>
        </div>
      )}

      {/* Confirmation dialog for deletion */}
      {confirmType === 'deletion' && (
        <div className="mt-3 rounded-ctl border border-danger bg-danger-soft p-4">
          <p className="text-sm font-medium text-danger">
            Request Account Deletion?
          </p>
          <p className="mt-1 text-sm text-danger">
            The organisation will be notified and will review your deletion
            request. This action cannot be undone once processed.
          </p>
          <div className="mt-3 flex gap-2">
            <button
              type="button"
              onClick={() => handleSubmit('deletion')}
              disabled={submitting}
              className="rounded-ctl bg-danger px-3 py-2 text-sm font-medium text-white hover:brightness-95 disabled:opacity-50 min-h-[44px]"
            >
              {submitting ? 'Submitting…' : 'Confirm Deletion Request'}
            </button>
            <button
              type="button"
              onClick={() => setConfirmType(null)}
              disabled={submitting}
              className="rounded-ctl border border-border bg-card px-3 py-2 text-sm font-medium text-text hover:bg-canvas disabled:opacity-50 min-h-[44px]"
            >
              Cancel
            </button>
          </div>
        </div>
      )}

      {/* Action buttons — hidden when a confirmation dialog is showing */}
      {!confirmType && (
        <div className="mt-4 flex flex-wrap gap-3">
          <button
            type="button"
            onClick={() => {
              setError('')
              setSuccess('')
              setConfirmType('export')
            }}
            disabled={submitting}
            className="inline-flex items-center gap-1.5 rounded-ctl border border-border bg-card px-4 py-2 text-sm font-medium text-text shadow-card hover:bg-canvas focus:outline-none focus:ring-2 focus:ring-accent focus:ring-offset-2 disabled:opacity-50 min-h-[44px]"
          >
            <svg xmlns="http://www.w3.org/2000/svg" className="h-4 w-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
              <path strokeLinecap="round" strokeLinejoin="round" d="M12 10v6m0 0l-3-3m3 3l3-3m2 8H7a2 2 0 01-2-2V5a2 2 0 012-2h5.586a1 1 0 01.707.293l5.414 5.414a1 1 0 01.293.707V19a2 2 0 01-2 2z" />
            </svg>
            Request Data Export
          </button>
          <button
            type="button"
            onClick={() => {
              setError('')
              setSuccess('')
              setConfirmType('deletion')
            }}
            disabled={submitting}
            className="inline-flex items-center gap-1.5 rounded-ctl border border-danger bg-card px-4 py-2 text-sm font-medium text-danger shadow-card hover:bg-danger-soft focus:outline-none focus:ring-2 focus:ring-danger focus:ring-offset-2 disabled:opacity-50 min-h-[44px]"
          >
            <svg xmlns="http://www.w3.org/2000/svg" className="h-4 w-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
              <path strokeLinecap="round" strokeLinejoin="round" d="M19 7l-.867 12.142A2 2 0 0116.138 21H7.862a2 2 0 01-1.995-1.858L5 7m5 4v6m4-6v6m1-10V4a1 1 0 00-1-1h-4a1 1 0 00-1 1v3M4 7h16" />
            </svg>
            Request Account Deletion
          </button>
        </div>
      )}
    </div>
  )
}
