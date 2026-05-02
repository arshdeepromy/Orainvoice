import { useState, useEffect } from 'react'
import apiClient from '@/api/client'
import { Badge } from '@/components/ui/Badge'
import { Spinner } from '@/components/ui/Spinner'
import { AlertBanner } from '@/components/ui/AlertBanner'

export interface PortalDocument {
  id: string
  document_type: string
  description: string | null
  linked_invoice_number: string | null
  download_url: string
}

interface DocumentsTabProps {
  token: string
}

const DOC_TYPE_LABELS: Record<string, string> = {
  safety_certificate: 'Safety Certificate',
  inspection_report: 'Inspection Report',
  warranty_certificate: 'Warranty Certificate',
  compliance_certificate: 'Compliance Certificate',
  test_report: 'Test Report',
  calibration_certificate: 'Calibration Certificate',
  electrical_certificate: 'Electrical Certificate',
  gas_certificate: 'Gas Certificate',
  plumbing_certificate: 'Plumbing Certificate',
  building_consent: 'Building Consent',
}

export function DocumentsTab({ token }: DocumentsTabProps) {
  const [documents, setDocuments] = useState<PortalDocument[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')

  useEffect(() => {
    const controller = new AbortController()
    const fetchDocuments = async () => {
      setLoading(true)
      setError('')
      try {
        const res = await apiClient.get(`/portal/${token}/documents`, { signal: controller.signal })
        setDocuments(res.data?.documents ?? [])
      } catch (err) {
        if (!controller.signal.aborted) setError('Failed to load documents.')
      } finally {
        if (!controller.signal.aborted) setLoading(false)
      }
    }
    fetchDocuments()
    return () => controller.abort()
  }, [token])

  if (loading) return <div className="py-8"><Spinner label="Loading documents" /></div>
  if (error) return <AlertBanner variant="error">{error}</AlertBanner>
  if (documents.length === 0) return <p className="py-8 text-center text-sm text-gray-500">No compliance documents found.</p>

  return (
    <div className="space-y-4">
      {documents.map((doc) => {
        const typeLabel = DOC_TYPE_LABELS[doc.document_type] ?? formatDocType(doc.document_type)

        return (
          <div key={doc.id} className="rounded-lg border border-gray-200 bg-white p-4">
            <div className="flex items-center justify-between mb-2">
              <div className="flex items-center gap-2">
                <Badge variant="info">{typeLabel}</Badge>
                {doc.linked_invoice_number && (
                  <span className="text-xs text-gray-400">Invoice: {doc.linked_invoice_number}</span>
                )}
              </div>
              <a
                href={doc.download_url}
                target="_blank"
                rel="noopener noreferrer"
                className="inline-flex items-center gap-1 rounded-md bg-blue-50 px-3 py-1.5 text-xs font-medium text-blue-700 hover:bg-blue-100 transition-colors"
              >
                <DownloadIcon />
                Download
              </a>
            </div>

            {doc.description && (
              <p className="text-sm text-gray-700">{doc.description}</p>
            )}
          </div>
        )
      })}
    </div>
  )
}

function formatDocType(docType: string): string {
  return docType
    .replace(/_/g, ' ')
    .replace(/\b\w/g, (c) => c.toUpperCase())
}

function DownloadIcon() {
  return (
    <svg xmlns="http://www.w3.org/2000/svg" className="h-3.5 w-3.5" viewBox="0 0 20 20" fill="currentColor">
      <path
        fillRule="evenodd"
        d="M3 17a1 1 0 011-1h12a1 1 0 110 2H4a1 1 0 01-1-1zm3.293-7.707a1 1 0 011.414 0L9 10.586V3a1 1 0 112 0v7.586l1.293-1.293a1 1 0 111.414 1.414l-3 3a1 1 0 01-1.414 0l-3-3a1 1 0 010-1.414z"
        clipRule="evenodd"
      />
    </svg>
  )
}
