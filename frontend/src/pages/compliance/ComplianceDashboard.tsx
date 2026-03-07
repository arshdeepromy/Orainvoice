import { useEffect, useState, useCallback } from 'react'
import apiClient from '@/api/client'

interface ComplianceDocument {
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
}

interface DashboardData {
  total_documents: number
  expiring_soon: number
  expired: number
  documents: ComplianceDocument[]
}

export default function ComplianceDashboard() {
  const [dashboard, setDashboard] = useState<DashboardData | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const [showUpload, setShowUpload] = useState(false)

  const fetchDashboard = useCallback(async () => {
    setLoading(true)
    try {
      const res = await apiClient.get('/api/v2/compliance-docs/dashboard')
      setDashboard(res.data)
      setError('')
    } catch {
      setError('Failed to load compliance dashboard')
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => { fetchDashboard() }, [fetchDashboard])

  if (loading) {
    return <div role="status" aria-label="Loading compliance dashboard">Loading…</div>
  }

  if (error) {
    return <div role="alert">{error}</div>
  }

  return (
    <div>
      <h1>Compliance Documents</h1>

      <div role="region" aria-label="Compliance summary" style={{ display: 'flex', gap: 24, marginBottom: 24 }}>
        <div data-testid="total-count">
          <strong>Total</strong>
          <p>{dashboard?.total_documents ?? 0}</p>
        </div>
        <div data-testid="expiring-count">
          <strong>Expiring Soon</strong>
          <p>{dashboard?.expiring_soon ?? 0}</p>
        </div>
        <div data-testid="expired-count">
          <strong>Expired</strong>
          <p>{dashboard?.expired ?? 0}</p>
        </div>
      </div>

      <button onClick={() => setShowUpload(true)} aria-label="Upload document">
        Upload Document
      </button>

      {showUpload && (
        <UploadForm
          onUploaded={() => { setShowUpload(false); fetchDashboard() }}
          onCancel={() => setShowUpload(false)}
        />
      )}

      {dashboard && dashboard.documents.length === 0 ? (
        <p>No compliance documents found</p>
      ) : (
        <table role="grid" aria-label="Compliance documents list">
          <thead>
            <tr>
              <th>Type</th>
              <th>File Name</th>
              <th>Expiry Date</th>
              <th>Description</th>
              <th>Uploaded</th>
            </tr>
          </thead>
          <tbody>
            {dashboard?.documents.map((doc) => (
              <tr key={doc.id}>
                <td>{doc.document_type}</td>
                <td>{doc.file_name}</td>
                <td>{doc.expiry_date ?? 'No expiry'}</td>
                <td>{doc.description ?? '—'}</td>
                <td>{new Date(doc.created_at).toLocaleDateString()}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </div>
  )
}

function UploadForm({
  onUploaded,
  onCancel,
}: {
  onUploaded: () => void
  onCancel: () => void
}) {
  const [documentType, setDocumentType] = useState('')
  const [fileName, setFileName] = useState('')
  const [fileKey, setFileKey] = useState('')
  const [expiryDate, setExpiryDate] = useState('')
  const [description, setDescription] = useState('')
  const [submitError, setSubmitError] = useState('')

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault()
    setSubmitError('')
    try {
      await apiClient.post('/api/v2/compliance-docs', {
        document_type: documentType,
        file_name: fileName,
        file_key: fileKey || `compliance/${Date.now()}.pdf`,
        expiry_date: expiryDate || null,
        description: description || null,
      })
      onUploaded()
    } catch (err: any) {
      setSubmitError(err?.response?.data?.detail ?? 'Upload failed')
    }
  }

  return (
    <form onSubmit={handleSubmit} aria-label="Upload compliance document">
      {submitError && <div role="alert">{submitError}</div>}
      <div>
        <label htmlFor="doc-type">Document Type</label>
        <input id="doc-type" value={documentType} onChange={(e) => setDocumentType(e.target.value)} required />
      </div>
      <div>
        <label htmlFor="doc-file-name">File Name</label>
        <input id="doc-file-name" value={fileName} onChange={(e) => setFileName(e.target.value)} required />
      </div>
      <div>
        <label htmlFor="doc-expiry">Expiry Date</label>
        <input id="doc-expiry" type="date" value={expiryDate} onChange={(e) => setExpiryDate(e.target.value)} />
      </div>
      <div>
        <label htmlFor="doc-description">Description</label>
        <textarea id="doc-description" value={description} onChange={(e) => setDescription(e.target.value)} />
      </div>
      <button type="submit" aria-label="Save document">Save</button>
      <button type="button" onClick={onCancel}>Cancel</button>
    </form>
  )
}
