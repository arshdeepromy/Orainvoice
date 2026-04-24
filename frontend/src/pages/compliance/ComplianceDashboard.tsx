import { useEffect, useState } from 'react'
import apiClient from '@/api/client'
import { Button } from '@/components/ui'
import SummaryCards from './SummaryCards'
import DocumentTable from './DocumentTable'
import UploadForm from './UploadForm'
import EditModal from './EditModal'
import DeleteConfirmation from './DeleteConfirmation'
import FilePreview from './FilePreview'

/* ------------------------------------------------------------------ */
/*  Types — matching backend Pydantic schemas exactly                  */
/* ------------------------------------------------------------------ */

export interface ComplianceDocumentResponse {
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

export interface DashboardSummary {
  total_documents: number
  valid_documents: number
  expiring_soon: number
  expired: number
  documents: ComplianceDocumentResponse[]
}

export interface CategoryResponse {
  id: string
  name: string
  is_predefined: boolean
}

interface CategoriesListResponse {
  items: CategoryResponse[]
  total: number
}

/* ------------------------------------------------------------------ */
/*  Component                                                          */
/* ------------------------------------------------------------------ */

export default function ComplianceDashboard() {
  const [documents, setDocuments] = useState<ComplianceDocumentResponse[]>([])
  const [summary, setSummary] = useState<DashboardSummary | null>(null)
  const [categories, setCategories] = useState<CategoryResponse[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const [showUpload, setShowUpload] = useState(false)

  /* Modal state */
  const [editDoc, setEditDoc] = useState<ComplianceDocumentResponse | null>(null)
  const [deleteDoc, setDeleteDoc] = useState<ComplianceDocumentResponse | null>(null)
  const [previewDoc, setPreviewDoc] = useState<ComplianceDocumentResponse | null>(null)

  useEffect(() => {
    const controller = new AbortController()

    const fetchAll = async () => {
      setLoading(true)
      setError('')
      try {
        const [dashboardRes, categoriesRes] = await Promise.all([
          apiClient.get<DashboardSummary>('/api/v2/compliance-docs/dashboard', {
            signal: controller.signal,
          }),
          apiClient.get<CategoriesListResponse>('/api/v2/compliance-docs/categories', {
            signal: controller.signal,
          }),
        ])

        const dashData = dashboardRes.data
        setSummary(dashData ?? null)
        setDocuments(dashData?.documents ?? [])
        setCategories(categoriesRes.data?.items ?? [])
      } catch (err: unknown) {
        if (!controller.signal.aborted) {
          setError('Failed to load compliance dashboard')
        }
      } finally {
        if (!controller.signal.aborted) {
          setLoading(false)
        }
      }
    }

    fetchAll()
    return () => controller.abort()
  }, [])

  const handleRefresh = () => {
    // Re-trigger the effect by forcing a re-mount isn't ideal,
    // so we duplicate the fetch logic in a callback for manual refresh.
    const controller = new AbortController()

    const refresh = async () => {
      setLoading(true)
      setError('')
      try {
        const [dashboardRes, categoriesRes] = await Promise.all([
          apiClient.get<DashboardSummary>('/api/v2/compliance-docs/dashboard', {
            signal: controller.signal,
          }),
          apiClient.get<CategoriesListResponse>('/api/v2/compliance-docs/categories', {
            signal: controller.signal,
          }),
        ])

        const dashData = dashboardRes.data
        setSummary(dashData ?? null)
        setDocuments(dashData?.documents ?? [])
        setCategories(categoriesRes.data?.items ?? [])
      } catch (err: unknown) {
        if (!controller.signal.aborted) {
          setError('Failed to load compliance dashboard')
        }
      } finally {
        if (!controller.signal.aborted) {
          setLoading(false)
        }
      }
    }

    refresh()
  }

  /* ---- Action handlers for DocumentTable ---- */

  const handleDownload = async (doc: ComplianceDocumentResponse) => {
    try {
      const res = await apiClient.get(`/api/v2/compliance-docs/${doc.id}/download`, {
        responseType: 'blob',
      })
      const blob = new Blob([res.data])
      const url = window.URL.createObjectURL(blob)
      const a = document.createElement('a')
      a.href = url
      a.download = doc.file_name ?? 'download'
      document.body.appendChild(a)
      a.click()
      document.body.removeChild(a)
      window.URL.revokeObjectURL(url)
    } catch {
      setError('Failed to download file')
    }
  }

  const handlePreview = (doc: ComplianceDocumentResponse) => {
    setPreviewDoc(doc)
  }

  const handleEdit = (doc: ComplianceDocumentResponse) => {
    setEditDoc(doc)
  }

  const handleDelete = (doc: ComplianceDocumentResponse) => {
    setDeleteDoc(doc)
  }

  return (
    <div className="px-4 py-6 sm:px-6 lg:px-8">
      {/* Page header */}
      <div className="flex flex-col gap-4 sm:flex-row sm:items-center sm:justify-between mb-6">
        <div>
          <h1 className="text-2xl font-semibold text-gray-900">Compliance Documents</h1>
          <p className="text-sm text-gray-500 mt-1">
            {(summary?.total_documents ?? 0)} document{(summary?.total_documents ?? 0) !== 1 ? 's' : ''} on file
          </p>
        </div>
        <Button onClick={() => setShowUpload(true)} aria-label="Upload document">
          Upload Document
        </Button>
      </div>

      {/* Error banner */}
      {error && (
        <div className="mb-6 rounded-lg border border-red-200 bg-red-50 p-4" role="alert">
          <div className="flex items-center justify-between">
            <p className="text-sm text-red-700">{error}</p>
            <Button variant="secondary" size="sm" onClick={handleRefresh}>
              Retry
            </Button>
          </div>
        </div>
      )}

      {/* Summary cards */}
      <SummaryCards summary={summary} loading={loading} />

      {/* Upload form */}
      {showUpload && (
        <UploadForm
          categories={categories}
          onSuccess={() => {
            setShowUpload(false)
            handleRefresh()
          }}
          onCancel={() => setShowUpload(false)}
          onCategoriesChange={(updatedCategories) => setCategories(updatedCategories)}
        />
      )}

      {/* Document table */}
      <DocumentTable
        documents={documents}
        categories={categories}
        loading={loading}
        onDownload={handleDownload}
        onPreview={handlePreview}
        onEdit={handleEdit}
        onDelete={handleDelete}
      />

      {/* Edit modal */}
      <EditModal
        open={editDoc !== null}
        document={editDoc}
        categories={categories}
        onClose={() => setEditDoc(null)}
        onSuccess={() => {
          setEditDoc(null)
          handleRefresh()
        }}
        onCategoriesChange={(updatedCategories) => setCategories(updatedCategories)}
      />

      {/* Delete confirmation dialog */}
      <DeleteConfirmation
        open={deleteDoc !== null}
        document={deleteDoc}
        onClose={() => setDeleteDoc(null)}
        onSuccess={() => {
          setDeleteDoc(null)
          handleRefresh()
        }}
      />

      {/* File preview modal */}
      <FilePreview
        open={previewDoc !== null}
        document={previewDoc}
        onClose={() => setPreviewDoc(null)}
        onDownload={(doc) => {
          setPreviewDoc(null)
          handleDownload(doc)
        }}
      />
    </div>
  )
}

/* ------------------------------------------------------------------ */
/*  Helper components — StatusBadge moved to DocumentTable.tsx         */
/* ------------------------------------------------------------------ */
