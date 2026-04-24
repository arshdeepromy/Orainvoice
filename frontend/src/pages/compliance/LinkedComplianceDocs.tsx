/**
 * LinkedComplianceDocs — Reusable section that displays compliance documents
 * linked to a specific invoice or job.
 *
 * Used on InvoiceDetail and JobDetail pages.
 *
 * Validates: Requirements 9.3, 9.4, 9.6
 */

import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import apiClient from '@/api/client'
import type { ComplianceDocumentResponse } from './ComplianceDashboard'

/* ------------------------------------------------------------------ */
/*  Types                                                              */
/* ------------------------------------------------------------------ */

interface DocumentListResponse {
  items: ComplianceDocumentResponse[]
  total: number
}

interface LinkedComplianceDocsProps {
  invoiceId?: string
  jobId?: string
}

/* ------------------------------------------------------------------ */
/*  Status badge helper                                                */
/* ------------------------------------------------------------------ */

const STATUS_STYLES: Record<string, string> = {
  valid: 'bg-green-50 text-green-700 ring-green-600/20',
  expiring_soon: 'bg-amber-50 text-amber-700 ring-amber-600/20',
  expired: 'bg-red-50 text-red-700 ring-red-600/20',
  no_expiry: 'bg-gray-50 text-gray-600 ring-gray-500/20',
}

const STATUS_LABELS: Record<string, string> = {
  valid: 'Valid',
  expiring_soon: 'Expiring Soon',
  expired: 'Expired',
  no_expiry: 'No Expiry',
}

function StatusBadge({ status }: { status: string }) {
  const style = STATUS_STYLES[status] ?? STATUS_STYLES.no_expiry
  const label = STATUS_LABELS[status] ?? status
  return (
    <span
      className={`inline-flex items-center rounded-full px-2 py-0.5 text-xs font-medium ring-1 ring-inset ${style}`}
    >
      {label}
    </span>
  )
}

/* ------------------------------------------------------------------ */
/*  Component                                                          */
/* ------------------------------------------------------------------ */

export default function LinkedComplianceDocs({ invoiceId, jobId }: LinkedComplianceDocsProps) {
  const [documents, setDocuments] = useState<ComplianceDocumentResponse[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')

  useEffect(() => {
    const controller = new AbortController()

    const fetchDocs = async () => {
      setLoading(true)
      setError('')
      try {
        const res = await apiClient.get<DocumentListResponse>(
          '/api/v2/compliance-docs',
          { signal: controller.signal },
        )
        const allDocs = res.data?.items ?? []

        // Filter client-side by the linked entity
        const filtered = allDocs.filter((doc) => {
          if (invoiceId && doc.invoice_id === invoiceId) return true
          if (jobId && doc.job_id === jobId) return true
          return false
        })

        setDocuments(filtered)
      } catch (err: unknown) {
        if (!controller.signal.aborted) {
          setError('Failed to load compliance documents.')
        }
      } finally {
        if (!controller.signal.aborted) {
          setLoading(false)
        }
      }
    }

    fetchDocs()
    return () => controller.abort()
  }, [invoiceId, jobId])

  /* ---- Download handler ---- */
  const handleDownload = async (doc: ComplianceDocumentResponse) => {
    try {
      const res = await apiClient.get(`/api/v2/compliance-docs/${doc.id}/download`, {
        responseType: 'blob',
      })
      const url = URL.createObjectURL(res.data as Blob)
      const a = document.createElement('a')
      a.href = url
      a.download = doc.file_name ?? 'download'
      a.click()
      URL.revokeObjectURL(url)
    } catch {
      // Silently fail — user can retry
    }
  }

  /* ---- Loading skeleton ---- */
  if (loading) {
    return (
      <section className="mt-6">
        <h2 className="text-sm font-medium text-gray-500 uppercase tracking-wider mb-3">
          Compliance Documents
        </h2>
        <div className="animate-pulse space-y-2">
          <div className="h-4 w-48 rounded bg-gray-200" />
          <div className="h-4 w-64 rounded bg-gray-200" />
        </div>
      </section>
    )
  }

  /* ---- Error state ---- */
  if (error) {
    return (
      <section className="mt-6">
        <h2 className="text-sm font-medium text-gray-500 uppercase tracking-wider mb-3">
          Compliance Documents
        </h2>
        <p className="text-sm text-red-600">{error}</p>
      </section>
    )
  }

  /* ---- Empty state ---- */
  if (documents.length === 0) {
    return (
      <section className="mt-6">
        <h2 className="text-sm font-medium text-gray-500 uppercase tracking-wider mb-3">
          Compliance Documents
        </h2>
        <p className="text-sm text-gray-500">No compliance documents linked.</p>
      </section>
    )
  }

  /* ---- Document list ---- */
  return (
    <section className="mt-6">
      <h2 className="text-sm font-medium text-gray-500 uppercase tracking-wider mb-3">
        Compliance Documents
      </h2>
      <div className="overflow-x-auto rounded-lg border border-gray-200">
        <table className="min-w-full divide-y divide-gray-200">
          <caption className="sr-only">Linked compliance documents</caption>
          <thead className="bg-gray-50">
            <tr>
              <th scope="col" className="px-4 py-3 text-left text-xs font-medium uppercase tracking-wider text-gray-500">
                File Name
              </th>
              <th scope="col" className="px-4 py-3 text-left text-xs font-medium uppercase tracking-wider text-gray-500">
                Type
              </th>
              <th scope="col" className="px-4 py-3 text-left text-xs font-medium uppercase tracking-wider text-gray-500">
                Status
              </th>
              <th scope="col" className="px-4 py-3 text-left text-xs font-medium uppercase tracking-wider text-gray-500">
                Expiry Date
              </th>
              <th scope="col" className="px-4 py-3 text-right text-xs font-medium uppercase tracking-wider text-gray-500">
                Actions
              </th>
            </tr>
          </thead>
          <tbody className="divide-y divide-gray-200 bg-white">
            {documents.map((doc) => (
              <tr key={doc.id}>
                <td className="whitespace-nowrap px-4 py-3 text-sm text-gray-900">
                  <Link
                    to="/compliance"
                    className="text-blue-600 hover:text-blue-800 hover:underline"
                  >
                    {doc.file_name ?? '—'}
                  </Link>
                </td>
                <td className="whitespace-nowrap px-4 py-3 text-sm text-gray-600">
                  {doc.document_type ?? '—'}
                </td>
                <td className="whitespace-nowrap px-4 py-3 text-sm">
                  <StatusBadge status={doc.status ?? 'no_expiry'} />
                </td>
                <td className="whitespace-nowrap px-4 py-3 text-sm text-gray-600">
                  {doc.expiry_date
                    ? new Intl.DateTimeFormat('en-NZ', {
                        day: '2-digit',
                        month: '2-digit',
                        year: 'numeric',
                      }).format(new Date(doc.expiry_date))
                    : '—'}
                </td>
                <td className="whitespace-nowrap px-4 py-3 text-sm text-right">
                  <button
                    type="button"
                    onClick={() => handleDownload(doc)}
                    className="inline-flex items-center rounded px-2 py-1 text-xs font-medium text-blue-600 hover:bg-blue-50 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-blue-500"
                  >
                    Download
                  </button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </section>
  )
}
