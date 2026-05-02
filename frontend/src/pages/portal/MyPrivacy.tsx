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
    <div className="mb-6 rounded-lg border border-gray-200 bg-white p-4">
      <h2 className="text-lg font-medium text-gray-900">My Privacy</h2>
      <p className="mt-1 text-sm text-gray-500">
        You can request a copy of your data or request deletion of your account.
        These requests will be reviewed by the organisation.
      </p>

      {success && (
        <div className="mt-3 rounded-md bg-green-50 p-3">
          <p className="text-sm text-green-700">{success}</p>
        </div>
      )}
      {error && (
        <div className="mt-3 rounded-md bg-red-50 p-3">
          <p className="text-sm text-red-700">{error}</p>
        </div>
      )}

      {/* Confirmation dialog for export */}
      {confirmType === 'export' && (
        <div className="mt-3 rounded-md border border-blue-200 bg-blue-50 p-4">
          <p className="text-sm font-medium text-blue-800">
            Request Data Export?
          </p>
          <p className="mt-1 text-sm text-blue-700">
            The organisation will be notified and will provide a copy of your
            personal data. This may take a few business days.
          </p>
          <div className="mt-3 flex gap-2">
            <button
              type="button"
              onClick={() => handleSubmit('export')}
              disabled={submitting}
              className="rounded-md bg-blue-600 px-3 py-2 text-sm font-medium text-white hover:bg-blue-700 disabled:opacity-50 min-h-[44px]"
            >
              {submitting ? 'Submitting…' : 'Confirm Request'}
            </button>
            <button
              type="button"
              onClick={() => setConfirmType(null)}
              disabled={submitting}
              className="rounded-md border border-gray-300 bg-white px-3 py-2 text-sm font-medium text-gray-700 hover:bg-gray-50 disabled:opacity-50 min-h-[44px]"
            >
              Cancel
            </button>
          </div>
        </div>
      )}

      {/* Confirmation dialog for deletion */}
      {confirmType === 'deletion' && (
        <div className="mt-3 rounded-md border border-red-200 bg-red-50 p-4">
          <p className="text-sm font-medium text-red-800">
            Request Account Deletion?
          </p>
          <p className="mt-1 text-sm text-red-700">
            The organisation will be notified and will review your deletion
            request. This action cannot be undone once processed.
          </p>
          <div className="mt-3 flex gap-2">
            <button
              type="button"
              onClick={() => handleSubmit('deletion')}
              disabled={submitting}
              className="rounded-md bg-red-600 px-3 py-2 text-sm font-medium text-white hover:bg-red-700 disabled:opacity-50 min-h-[44px]"
            >
              {submitting ? 'Submitting…' : 'Confirm Deletion Request'}
            </button>
            <button
              type="button"
              onClick={() => setConfirmType(null)}
              disabled={submitting}
              className="rounded-md border border-gray-300 bg-white px-3 py-2 text-sm font-medium text-gray-700 hover:bg-gray-50 disabled:opacity-50 min-h-[44px]"
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
            className="inline-flex items-center gap-1.5 rounded-md border border-gray-300 bg-white px-4 py-2 text-sm font-medium text-gray-700 shadow-sm hover:bg-gray-50 focus:outline-none focus:ring-2 focus:ring-blue-500 focus:ring-offset-2 disabled:opacity-50 min-h-[44px]"
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
            className="inline-flex items-center gap-1.5 rounded-md border border-red-300 bg-white px-4 py-2 text-sm font-medium text-red-700 shadow-sm hover:bg-red-50 focus:outline-none focus:ring-2 focus:ring-red-500 focus:ring-offset-2 disabled:opacity-50 min-h-[44px]"
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
