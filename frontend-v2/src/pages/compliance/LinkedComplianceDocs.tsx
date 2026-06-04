/**
 * LinkedComplianceDocs — Task 20 port of
 * frontend/src/pages/compliance/LinkedComplianceDocs.tsx.
 *
 * Reusable section that displays compliance documents linked to a specific
 * invoice or job. All logic (fetch /api/v2/compliance-docs with AbortController,
 * client-side filter by invoice/job id, download via blob, loading / error /
 * empty states) is copied VERBATIM. The `ComplianceDocumentResponse` type is
 * inlined here (Task 65 owns the full Compliance module). Styling is remapped
 * onto the design-system tokens (FR-2b) — cards, borders, status pills.
 *
 * Validates: Requirements 9.3, 9.4, 9.6
 */

import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import apiClient from '@/api/client'

/* ------------------------------------------------------------------ */
/*  Types (inlined from compliance/ComplianceDashboard — Task 65)      */
/* ------------------------------------------------------------------ */

interface ComplianceDocumentResponse {
  id: string
  org_id: string
  document_type: string
  description: string | null
  file_key: string
  file_name: string
  expiry_date: string | null
  invoice_id: string | null
  job_id: string | null
  uploaded_by: string | null
  created_at: string
  status: string // 'valid' | 'expiring_soon' | 'expired' | 'no_expiry'
}

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
  valid: 'bg-ok-soft text-ok ring-ok/20',
  expiring_soon: 'bg-warn-soft text-warn ring-warn/20',
  expired: 'bg-danger-soft text-danger ring-danger/20',
  no_expiry: 'bg-canvas text-muted ring-border-strong',
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
      } catch {
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
        <h2 className="text-sm font-medium text-muted uppercase tracking-wider mb-3">
          Compliance Documents
        </h2>
        <div className="animate-pulse space-y-2">
          <div className="h-4 w-48 rounded bg-border" />
          <div className="h-4 w-64 rounded bg-border" />
        </div>
      </section>
    )
  }

  /* ---- Error state ---- */
  if (error) {
    return (
      <section className="mt-6">
        <h2 className="text-sm font-medium text-muted uppercase tracking-wider mb-3">
          Compliance Documents
        </h2>
        <p className="text-sm text-danger">{error}</p>
      </section>
    )
  }

  /* ---- Empty state ---- */
  if (documents.length === 0) {
    return (
      <section className="mt-6">
        <h2 className="text-sm font-medium text-muted uppercase tracking-wider mb-3">
          Compliance Documents
        </h2>
        <p className="text-sm text-muted">No compliance documents linked.</p>
      </section>
    )
  }

  /* ---- Document list ---- */
  return (
    <section className="mt-6">
      <h2 className="text-sm font-medium text-muted uppercase tracking-wider mb-3">
        Compliance Documents
      </h2>
      <div className="overflow-x-auto rounded-card border border-border">
        <table className="min-w-full divide-y divide-border">
          <caption className="sr-only">Linked compliance documents</caption>
          <thead className="bg-canvas">
            <tr>
              <th scope="col" className="px-4 py-3 text-left text-xs font-medium uppercase tracking-wider text-muted">
                File Name
              </th>
              <th scope="col" className="px-4 py-3 text-left text-xs font-medium uppercase tracking-wider text-muted">
                Type
              </th>
              <th scope="col" className="px-4 py-3 text-left text-xs font-medium uppercase tracking-wider text-muted">
                Status
              </th>
              <th scope="col" className="px-4 py-3 text-left text-xs font-medium uppercase tracking-wider text-muted">
                Expiry Date
              </th>
              <th scope="col" className="px-4 py-3 text-right text-xs font-medium uppercase tracking-wider text-muted">
                Actions
              </th>
            </tr>
          </thead>
          <tbody className="divide-y divide-border bg-card">
            {documents.map((doc) => (
              <tr key={doc.id}>
                <td className="whitespace-nowrap px-4 py-3 text-sm text-text">
                  <Link
                    to="/compliance"
                    className="text-accent hover:text-accent-press hover:underline"
                  >
                    {doc.file_name ?? '—'}
                  </Link>
                </td>
                <td className="whitespace-nowrap px-4 py-3 text-sm text-muted">
                  {doc.document_type ?? '—'}
                </td>
                <td className="whitespace-nowrap px-4 py-3 text-sm">
                  <StatusBadge status={doc.status ?? 'no_expiry'} />
                </td>
                <td className="whitespace-nowrap px-4 py-3 text-sm text-muted mono">
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
                    className="inline-flex items-center rounded-ctl px-2 py-1 text-xs font-medium text-accent hover:bg-accent-soft focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent"
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
