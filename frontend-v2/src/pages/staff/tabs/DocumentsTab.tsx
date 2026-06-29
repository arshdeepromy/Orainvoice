/**
 * DocumentsTab — Staff Detail tabbed shell (task E5).
 *
 * Single section "Employment agreement". Drag-drop or file picker →
 * `POST /api/v2/uploads/attachments` (existing endpoint, returns
 * `{file_key, file_name, file_size}`) → `POST /api/v2/staff/:id/employment-agreement`
 * with `{ upload_id }` (the UUID extracted from the file_key hex segment) →
 * refresh local staff state. Shows current filename + View + Replace once
 * an attachment is on file.
 *
 * The /uploads endpoint stores `file_key = "attachments/{org_id}/{uuid.hex}{ext}"`.
 * We extract the hex segment and convert it to a UUID before posting to
 * /staff/:id/employment-agreement (whose Pydantic body is `{ upload_id: UUID }`).
 *
 * After a fresh upload we keep the `file_key` and `file_name` in component
 * state so the "View" button can fetch the binary via
 * `GET /api/v2/uploads/{file_key}` (responseType=blob) and open it in a
 * new tab. After a page reload we only have the upload_id (the staff
 * GET response does not currently surface the file_key); the row still
 * shows "Replace" so the user can swap the file.
 *
 * Refs: Staff Management Phase 1 — R5.
 *
 * Logic copied verbatim; presentation remapped onto the design-system tokens.
 */

import React, { useEffect, useRef, useState } from 'react'
import apiClient from '@/api/client'
import { Modal } from '@/components/ui'
import { useModules } from '@/contexts/ModuleContext'
import { SendForSignatureModal } from '@/components/esign/SendForSignatureModal'
import {
  STAFF_DOC_TYPES,
  docTypeConfig,
  documentTypeLabel,
  detailOptionLabel,
} from '@/utils/staffDocumentTypes'

interface DocumentsTabProps {
  staffId: string
}

/**
 * Subset of the staff response we care about on this tab. The full
 * shape lives in `app/modules/staff/schemas.py::StaffMemberResponse`.
 */
interface StaffSummary {
  id: string
  employment_agreement_upload_id: string | null
}

interface UploadResponse {
  file_key: string
  file_name: string
  file_size: number
}

/** A document linked to this staff member (onboarding uploads, manual uploads). */
interface StaffDocument {
  id: string
  document_type: string
  description: string | null
  file_name: string
  file_size: number | null
  created_at: string
  expiry_date: string | null
}

interface StaffDocumentListResponse {
  items: StaffDocument[]
  total: number
}

/** Uppercase file-type label derived from the filename extension. */
function fileTypeLabel(fileName: string): string {
  const ext = fileName.toLowerCase().split('.').pop() ?? ''
  const map: Record<string, string> = {
    pdf: 'PDF',
    jpg: 'JPEG',
    jpeg: 'JPEG',
    png: 'PNG',
    gif: 'GIF',
    webp: 'WebP',
    doc: 'DOC',
    docx: 'DOCX',
  }
  return map[ext] ?? (ext ? ext.toUpperCase() : '—')
}

/** Format a byte count as a compact human-readable size. */
function formatFileSize(bytes: number | null | undefined): string {
  if (bytes === null || bytes === undefined) return '—'
  if (bytes < 1024) return `${bytes} B`
  const kb = bytes / 1024
  if (kb < 1024) return `${kb.toFixed(kb < 10 ? 1 : 0)} KB`
  const mb = kb / 1024
  return `${mb.toFixed(mb < 10 ? 1 : 0)} MB`
}

/** Best-effort content-type for preview rendering: prefer the blob's own type,
 *  fall back to the filename extension. */
function inferPreviewMime(blob: Blob, fileName: string): string {
  if (blob.type && blob.type !== 'application/octet-stream') return blob.type
  const ext = fileName.toLowerCase().split('.').pop() ?? ''
  const map: Record<string, string> = {
    pdf: 'application/pdf',
    jpg: 'image/jpeg',
    jpeg: 'image/jpeg',
    png: 'image/png',
    gif: 'image/gif',
    webp: 'image/webp',
  }
  return map[ext] ?? 'application/octet-stream'
}

const MAX_BYTES = 20 * 1024 * 1024
const ACCEPTED_TYPES = '.pdf,.jpg,.jpeg,.png,application/pdf,image/jpeg,image/png'
const ACCEPTED_DOC_UPLOAD_TYPES =
  '.pdf,.jpg,.jpeg,.png,.gif,.doc,.docx,application/pdf,image/jpeg,image/png,image/gif,application/msword,application/vnd.openxmlformats-officedocument.wordprocessingml.document'
const HEX32_RE = /^[a-f0-9]{32}$/i

/**
 * Convert a 32-character hex string (the bare uuid hex form) into the
 * canonical 8-4-4-4-12 dashed UUID form expected by the FastAPI
 * `UUID` body validator on `/staff/:id/employment-agreement`.
 */
function hexToUuid(hex: string): string {
  return (
    hex.slice(0, 8) +
    '-' +
    hex.slice(8, 12) +
    '-' +
    hex.slice(12, 16) +
    '-' +
    hex.slice(16, 20) +
    '-' +
    hex.slice(20, 32)
  )
}

/**
 * Pull the uuid.hex portion out of a `file_key` of the form
 * `attachments/{org_id}/{uuid.hex}{ext}`. Returns `null` if the shape
 * doesn't match (defensive — the backend always emits this shape today
 * but a future change shouldn't crash the UI).
 */
function extractHexFromFileKey(fileKey: string): string | null {
  const filename = fileKey.split('/').pop() ?? ''
  const dot = filename.lastIndexOf('.')
  const hex = dot > 0 ? filename.slice(0, dot) : filename
  return HEX32_RE.test(hex) ? hex.toLowerCase() : null
}

export default function DocumentsTab({ staffId }: DocumentsTabProps) {
  const { isEnabled } = useModules()
  const esignEnabled = isEnabled('esignatures')
  const [staff, setStaff] = useState<StaffSummary | null>(null)
  const [isLoading, setIsLoading] = useState(true)
  const [loadError, setLoadError] = useState<string | null>(null)
  const [uploading, setUploading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [dragActive, setDragActive] = useState(false)
  // Local cache of the most-recent upload so we can render the filename +
  // construct the View URL. After a hard refresh this is null and we fall
  // back to showing the upload_id only.
  const [recentUpload, setRecentUpload] = useState<UploadResponse | null>(null)
  const fileInputRef = useRef<HTMLInputElement | null>(null)

  // Compliance documents linked to this staff member (onboarding uploads,
  // working-rights docs, etc.) — surfaced so admins can see what the staff
  // member submitted during onboarding.
  const [docs, setDocs] = useState<StaffDocument[]>([])
  const [docsLoading, setDocsLoading] = useState(true)
  const [docsError, setDocsError] = useState<string | null>(null)
  const [docUploading, setDocUploading] = useState(false)
  const [deletingId, setDeletingId] = useState<string | null>(null)
  const [downloadingId, setDownloadingId] = useState<string | null>(null)
  const docInputRef = useRef<HTMLInputElement | null>(null)
  const backInputRef = useRef<HTMLInputElement | null>(null)

  // Manual upload modal (document type + detail + optional expiry + file).
  const [uploadModalOpen, setUploadModalOpen] = useState(false)
  // Send for signature (e-signature) modal — shown only when the
  // `esignatures` module is enabled (R10.2/R10.5).
  const [sendForSignatureOpen, setSendForSignatureOpen] = useState(false)
  const [uploadType, setUploadType] = useState('working_rights')
  const [uploadDetailSelect, setUploadDetailSelect] = useState('')
  const [uploadDetailText, setUploadDetailText] = useState('')
  const [uploadExpiry, setUploadExpiry] = useState('')
  const [pendingFile, setPendingFile] = useState<File | null>(null)
  // Driver's-licence extras: back-of-card file + licence class.
  const [backFile, setBackFile] = useState<File | null>(null)
  const [licenceClass, setLicenceClass] = useState('')
  const [uploadError, setUploadError] = useState<string | null>(null)

  // In-app preview modal state. We fetch the file as a blob (the endpoints are
  // auth-gated so a plain <img src> / new tab won't carry the token), turn it
  // into an object URL, and render it inside a Modal instead of opening a raw
  // blob: URL in a new tab.
  const [preview, setPreview] = useState<{
    url: string
    name: string
    mime: string
  } | null>(null)
  const [previewLoadingId, setPreviewLoadingId] = useState<string | null>(null)
  const previewUrlRef = useRef<string | null>(null)

  const closePreview = () => {
    setPreview(null)
    if (previewUrlRef.current) {
      URL.revokeObjectURL(previewUrlRef.current)
      previewUrlRef.current = null
    }
  }

  // Fetch a file (auth-gated) and open it in the preview modal.
  const openPreview = async (key: string, fetchPath: string, fileName: string) => {
    setPreviewLoadingId(key)
    setError(null)
    setDocsError(null)
    try {
      const res = await apiClient.get(fetchPath, { responseType: 'blob' })
      const blob = res.data as Blob
      const mime = inferPreviewMime(blob, fileName)
      // Re-type the blob so the <img>/<iframe> renders correctly even when the
      // server sent application/octet-stream.
      const typed = blob.type === mime ? blob : new Blob([blob], { type: mime })
      const url = URL.createObjectURL(typed)
      if (previewUrlRef.current) URL.revokeObjectURL(previewUrlRef.current)
      previewUrlRef.current = url
      setPreview({ url, name: fileName, mime })
    } catch {
      setDocsError('Failed to open document.')
    } finally {
      setPreviewLoadingId(null)
    }
  }

  const loadDocs = useRef<(signal?: AbortSignal) => Promise<void>>(async () => {})
  loadDocs.current = async (signal?: AbortSignal) => {
    setDocsLoading(true)
    setDocsError(null)
    try {
      const res = await apiClient.get<StaffDocumentListResponse>(
        `/api/v2/staff/${staffId}/documents`,
        { signal },
      )
      if (signal?.aborted) return
      setDocs(res.data?.items ?? [])
    } catch (err) {
      if (signal?.aborted) return
      setDocsError('Failed to load documents.')
    } finally {
      if (!signal?.aborted) setDocsLoading(false)
    }
  }

  useEffect(() => {
    const controller = new AbortController()
    void loadDocs.current(controller.signal)
    return () => controller.abort()
  }, [staffId])

  // Release the preview object-URL when the tab unmounts.
  useEffect(() => {
    return () => {
      if (previewUrlRef.current) URL.revokeObjectURL(previewUrlRef.current)
    }
  }, [])

  const onDownloadDoc = (doc: StaffDocument) =>
    openPreview(
      doc.id,
      `/api/v2/staff/${staffId}/documents/${doc.id}/download`,
      doc.file_name,
    )

  /** Save a document to disk (true download, distinct from the preview). */
  const onSaveDoc = async (doc: StaffDocument) => {
    setDownloadingId(doc.id)
    setDocsError(null)
    try {
      const res = await apiClient.get(
        `/api/v2/staff/${staffId}/documents/${doc.id}/download`,
        { responseType: 'blob' },
      )
      const url = URL.createObjectURL(res.data as Blob)
      const a = document.createElement('a')
      a.href = url
      a.download = doc.file_name
      document.body.appendChild(a)
      a.click()
      a.remove()
      setTimeout(() => URL.revokeObjectURL(url), 10_000)
    } catch {
      setDocsError('Failed to download document.')
    } finally {
      setDownloadingId(null)
    }
  }

  /** Delete a document (with confirmation), then refresh the list. */
  const onDeleteDoc = async (doc: StaffDocument) => {
    if (
      typeof window !== 'undefined' &&
      !window.confirm(`Delete "${doc.file_name}"? This cannot be undone.`)
    ) {
      return
    }
    setDeletingId(doc.id)
    setDocsError(null)
    try {
      await apiClient.delete(`/api/v2/staff/${staffId}/documents/${doc.id}`)
      setDocs((prev) => prev.filter((d) => d.id !== doc.id))
    } catch {
      setDocsError('Failed to delete document.')
    } finally {
      setDeletingId(null)
    }
  }

  /** Open the upload modal with a clean form. */
  const openUploadModal = () => {
    setUploadType('working_rights')
    setUploadDetailSelect('')
    setUploadDetailText('')
    setUploadExpiry('')
    setPendingFile(null)
    setBackFile(null)
    setLicenceClass('')
    setUploadError(null)
    setUploadModalOpen(true)
  }

  /** Switch document type → reset the dependent detail inputs. */
  const onChangeUploadType = (next: string) => {
    setUploadType(next)
    setUploadDetailSelect('')
    setUploadDetailText('')
    setBackFile(null)
    setLicenceClass('')
    setUploadError(null)
  }

  /** Resolve the human-readable detail string for the chosen type. */
  const resolveUploadDescription = (): string => {
    const cfg = docTypeConfig(uploadType)
    if (!cfg?.detail) return ''
    if (cfg.detail.options) {
      if (!uploadDetailSelect) return ''
      if (uploadDetailSelect === 'other') return uploadDetailText.trim()
      return detailOptionLabel(uploadType, uploadDetailSelect)
    }
    return uploadDetailText.trim()
  }

  /** True when the chosen document is a driver's licence (front/back + class). */
  const isDriversLicence =
    uploadType === 'identity' && uploadDetailSelect === 'drivers_licence'

  /** Submit the manual upload (document type + detail + optional expiry + file). */
  const submitUpload = async () => {
    setUploadError(null)
    const cfg = docTypeConfig(uploadType)
    const baseDescription = resolveUploadDescription()
    if (cfg?.detail?.required && !baseDescription) {
      setUploadError(`Please provide ${cfg.detail.label.toLowerCase()}.`)
      return
    }
    if (!pendingFile) {
      setUploadError(
        isDriversLicence
          ? 'Choose the front of the licence.'
          : 'Choose a file to upload.',
      )
      return
    }
    const oversized = [pendingFile, backFile].find(
      (f): f is File => !!f && f.size > MAX_BYTES,
    )
    if (oversized) {
      setUploadError('File too large. Maximum size is 20 MB.')
      return
    }

    // Fold the licence class into the description for driver's licences.
    let description = baseDescription
    if (isDriversLicence) {
      const cls = licenceClass.trim()
      description = cls ? `${baseDescription} — Class ${cls}` : baseDescription
    }

    const uploadOne = async (file: File, suffix: string) => {
      const formData = new FormData()
      formData.append('file', file)
      formData.append('document_type', uploadType || 'staff_document')
      const desc = suffix ? `${description}${suffix}` : description
      if (desc) formData.append('description', desc)
      if (uploadExpiry) formData.append('expiry_date', uploadExpiry)
      await apiClient.post(`/api/v2/staff/${staffId}/documents`, formData, {
        headers: { 'Content-Type': 'multipart/form-data' },
      })
    }

    setDocUploading(true)
    try {
      if (isDriversLicence) {
        // Front + (optional) back are stored as two linked documents.
        await uploadOne(pendingFile, backFile ? ' (Front)' : '')
        if (backFile) await uploadOne(backFile, ' (Back)')
      } else {
        await uploadOne(pendingFile, '')
      }
      setUploadModalOpen(false)
      setPendingFile(null)
      setBackFile(null)
      setLicenceClass('')
      setUploadExpiry('')
      const controller = new AbortController()
      await loadDocs.current(controller.signal)
    } catch (err) {
      const detail = (err as { response?: { data?: { detail?: unknown } } })
        .response?.data?.detail
      setUploadError(
        typeof detail === 'string' && detail.length > 0
          ? detail
          : 'Failed to upload document. Use a PDF, image, or Word file up to 20 MB.',
      )
    } finally {
      setDocUploading(false)
    }
  }

  useEffect(() => {
    const controller = new AbortController()
    const load = async () => {
      setIsLoading(true)
      setLoadError(null)
      try {
        const res = await apiClient.get<StaffSummary>(
          `/api/v2/staff/${staffId}`,
          { signal: controller.signal },
        )
        if (controller.signal.aborted) return
        setStaff((res.data as StaffSummary | undefined) ?? null)
      } catch (err) {
        if (controller.signal.aborted) return
        setLoadError('Failed to load staff record.')
      } finally {
        if (!controller.signal.aborted) setIsLoading(false)
      }
    }
    load()
    return () => controller.abort()
  }, [staffId])

  const uploadFile = async (file: File) => {
    setError(null)
    if (file.size > MAX_BYTES) {
      setError('File too large. Maximum size is 20 MB.')
      return
    }
    setUploading(true)
    try {
      // Step 1 — push the binary to the existing uploads pipeline.
      const formData = new FormData()
      formData.append('file', file)
      const uploadRes = await apiClient.post<UploadResponse>(
        '/api/v2/uploads/attachments',
        formData,
        { headers: { 'Content-Type': 'multipart/form-data' } },
      )
      const fileKey = uploadRes.data?.file_key
      const fileName = uploadRes.data?.file_name
      const fileSize = uploadRes.data?.file_size ?? file.size
      if (!fileKey) {
        setError('Upload did not return a file key.')
        return
      }
      const hex = extractHexFromFileKey(fileKey)
      if (!hex) {
        setError('Upload returned an unexpected file key shape.')
        return
      }
      const uploadId = hexToUuid(hex)

      // Step 2 — attach to the staff record.
      const attachRes = await apiClient.post<StaffSummary>(
        `/api/v2/staff/${staffId}/employment-agreement`,
        { upload_id: uploadId },
      )
      setStaff((attachRes.data as StaffSummary | undefined) ?? null)
      setRecentUpload({
        file_key: fileKey,
        file_name: fileName ?? file.name,
        file_size: fileSize,
      })
    } catch (err) {
      const detail =
        (err as { response?: { data?: { detail?: unknown } } }).response?.data
          ?.detail
      setError(
        typeof detail === 'string' && detail.length > 0
          ? detail
          : 'Upload failed. Please try again.',
      )
    } finally {
      setUploading(false)
    }
  }

  const onPickFile = (e: React.ChangeEvent<HTMLInputElement>) => {
    const f = e.target.files?.[0]
    if (f) void uploadFile(f)
    // Reset so the same filename can be picked twice in a row.
    e.target.value = ''
  }

  const onDragOver = (e: React.DragEvent<HTMLDivElement>) => {
    e.preventDefault()
    setDragActive(true)
  }
  const onDragLeave = (e: React.DragEvent<HTMLDivElement>) => {
    e.preventDefault()
    setDragActive(false)
  }
  const onDrop = (e: React.DragEvent<HTMLDivElement>) => {
    e.preventDefault()
    setDragActive(false)
    const f = e.dataTransfer.files?.[0]
    if (f) void uploadFile(f)
  }

  const onView = () => {
    if (!recentUpload?.file_key) return
    void openPreview(
      'agreement',
      `/api/v2/uploads/${recentUpload.file_key}`,
      recentUpload.file_name || 'document',
    )
  }

  if (isLoading) {
    return <div className="p-6 text-muted">Loading…</div>
  }
  if (loadError) {
    return (
      <div role="alert" className="p-6 text-danger">
        {loadError}
      </div>
    )
  }

  const hasUpload = !!staff?.employment_agreement_upload_id

  return (
    <div className="mx-auto max-w-[1280px] p-6" data-testid="documents-tab">
      <h2 className="text-lg font-semibold mb-1 text-text">
        Employment agreement
      </h2>
      <p className="text-sm text-muted mb-4">
        Attach the staff member's signed employment agreement (PDF, JPG, or
        PNG, up to 20 MB).
      </p>

      {hasUpload ? (
        <div
          className="max-w-2xl border border-border rounded-card p-4"
          data-testid="agreement-attached"
        >
          <div className="text-sm text-text">
            {recentUpload?.file_name ? (
              <span data-testid="agreement-filename" className="font-medium">
                {recentUpload.file_name}
              </span>
            ) : (
              <span
                data-testid="agreement-upload-id"
                className="mono text-xs text-muted"
              >
                {staff?.employment_agreement_upload_id}
              </span>
            )}
          </div>
          <div className="mt-3 flex flex-wrap gap-4">
            {recentUpload?.file_key && (
              <button
                type="button"
                onClick={onView}
                disabled={previewLoadingId === 'agreement'}
                className="text-sm text-accent hover:underline min-h-[44px] disabled:opacity-50"
              >
                {previewLoadingId === 'agreement' ? 'Opening…' : 'View'}
              </button>
            )}
            <button
              type="button"
              onClick={() => fileInputRef.current?.click()}
              disabled={uploading}
              className="text-sm text-accent hover:underline min-h-[44px] disabled:opacity-50"
            >
              {uploading ? 'Uploading…' : 'Replace'}
            </button>
          </div>
        </div>
      ) : (
        <div
          role="button"
          tabIndex={0}
          aria-label="Upload employment agreement"
          aria-disabled={uploading}
          onDragOver={onDragOver}
          onDragLeave={onDragLeave}
          onDrop={onDrop}
          onClick={() => {
            if (!uploading) fileInputRef.current?.click()
          }}
          onKeyDown={(e) => {
            if (uploading) return
            if (e.key === 'Enter' || e.key === ' ') {
              e.preventDefault()
              fileInputRef.current?.click()
            }
          }}
          data-testid="dropzone"
          className={`max-w-2xl border-2 border-dashed rounded-card p-8 text-center cursor-pointer min-h-[160px] flex flex-col items-center justify-center transition-colors ${
            dragActive
              ? 'border-accent bg-accent-soft'
              : 'border-border'
          } ${uploading ? 'opacity-50 cursor-wait' : ''}`}
        >
          <p className="text-sm text-text">
            {uploading
              ? 'Uploading…'
              : 'Drag a PDF, JPG, or PNG here, or click to browse.'}
          </p>
          <p className="text-xs text-muted-2 mt-2">
            Maximum 20 MB.
          </p>
        </div>
      )}

      <input
        ref={fileInputRef}
        type="file"
        accept={ACCEPTED_TYPES}
        className="hidden"
        onChange={onPickFile}
        data-testid="file-input"
      />

      {error && (
        <div
          role="alert"
          className="mt-4 text-sm text-danger"
        >
          {error}
        </div>
      )}

      {/* Submitted / compliance documents (onboarding uploads, working rights) */}
      <div className="mt-10">
        <div className="mb-4 flex items-start justify-between gap-3">
          <div>
            <h2 className="text-lg font-semibold mb-1 text-text">
              Submitted documents
            </h2>
            <p className="text-sm text-muted">
              Documents this staff member uploaded (e.g. during onboarding), such
              as working-rights or identity documents. You can also upload more here.
            </p>
          </div>
          <div className="flex shrink-0 items-center gap-2">
            {esignEnabled && (
              <button
                type="button"
                onClick={() => setSendForSignatureOpen(true)}
                className="inline-flex items-center gap-1.5 rounded-ctl border border-border bg-card px-3 py-2 text-sm font-medium text-text hover:bg-canvas focus:outline-none focus:ring-2 focus:ring-accent min-h-[44px]"
              >
                <svg className="h-4 w-4" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={2}>
                  <path strokeLinecap="round" strokeLinejoin="round" d="M15.232 5.232l3.536 3.536m-2.036-5.036a2.5 2.5 0 113.536 3.536L6.5 21.036H3v-3.572L16.732 3.732z" />
                </svg>
                Send for signature
              </button>
            )}
            <button
              type="button"
              onClick={openUploadModal}
              disabled={docUploading}
              className="inline-flex items-center gap-1.5 rounded-ctl bg-accent px-3 py-2 text-sm font-medium text-white hover:bg-accent-press focus:outline-none focus:ring-2 focus:ring-accent min-h-[44px] disabled:opacity-50"
            >
              <svg className="h-4 w-4" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={2}>
                <path strokeLinecap="round" strokeLinejoin="round" d="M12 5v14M5 12h14" />
              </svg>
              Upload document
            </button>
          </div>
          <input
            ref={docInputRef}
            type="file"
            accept={ACCEPTED_DOC_UPLOAD_TYPES}
            className="hidden"
            data-testid="doc-upload-input"
            onChange={(e) => {
              const f = e.target.files?.[0]
              if (f) {
                setPendingFile(f)
                setUploadError(null)
              }
              e.target.value = ''
            }}
          />
        </div>

        {docsError && (
          <div role="alert" className="mb-3 text-sm text-danger">
            {docsError}
          </div>
        )}

        {docsLoading ? (
          <div className="text-sm text-muted">Loading documents…</div>
        ) : docs.length === 0 ? (
          <div className="border border-border rounded-card p-4 text-sm text-muted">
            No documents have been uploaded yet.
          </div>
        ) : (
          <div className="overflow-hidden rounded-card border border-border">
            <div className="overflow-x-auto">
              <table className="w-full border-collapse text-sm">
                <thead>
                  <tr className="bg-canvas text-left text-[11px] font-medium uppercase tracking-wide text-muted-2">
                    <th className="px-4 py-2.5">Document type</th>
                    <th className="px-4 py-2.5">Details</th>
                    <th className="px-4 py-2.5">File type</th>
                    <th className="px-4 py-2.5">File name</th>
                    <th className="px-4 py-2.5">Size</th>
                    <th className="px-4 py-2.5">Expiry</th>
                    <th className="px-4 py-2.5 text-right">Actions</th>
                  </tr>
                </thead>
                <tbody>
                  {docs.map((doc) => (
                    <tr
                      key={doc.id}
                      className="border-t border-border"
                      data-testid={`staff-document-${doc.id}`}
                    >
                      <td className="px-4 py-3">
                        <span className="inline-flex items-center rounded bg-canvas px-1.5 py-0.5 text-xs font-medium text-text">
                          {documentTypeLabel(doc.document_type)}
                        </span>
                      </td>
                      <td className="px-4 py-3 text-text">
                        {doc.description ? (
                          <span className="block max-w-[220px] truncate" title={doc.description}>
                            {doc.description}
                          </span>
                        ) : (
                          <span className="text-muted-2">—</span>
                        )}
                      </td>
                      <td className="px-4 py-3 text-muted">{fileTypeLabel(doc.file_name)}</td>
                      <td className="px-4 py-3 text-text">
                        <span className="block max-w-[260px] truncate" title={doc.file_name}>
                          {doc.file_name}
                        </span>
                      </td>
                      <td className="px-4 py-3 text-muted whitespace-nowrap">
                        {formatFileSize(doc.file_size)}
                      </td>
                      <td className="px-4 py-3 whitespace-nowrap">
                        {doc.expiry_date ? (
                          (() => {
                            const days = Math.ceil(
                              (new Date(doc.expiry_date).getTime() - Date.now()) / 86400000,
                            )
                            const cls =
                              days < 0 ? 'text-danger' : days <= 30 ? 'text-warn' : 'text-muted'
                            return (
                              <span className={cls}>
                                {new Date(doc.expiry_date).toLocaleDateString('en-NZ', {
                                  day: 'numeric',
                                  month: 'short',
                                  year: 'numeric',
                                })}
                              </span>
                            )
                          })()
                        ) : (
                          <span className="text-muted-2">—</span>
                        )}
                      </td>
                      <td className="px-4 py-3">
                        <div className="flex items-center justify-end gap-3 whitespace-nowrap">
                          <button
                            type="button"
                            onClick={() => void onDownloadDoc(doc)}
                            disabled={previewLoadingId === doc.id}
                            className="text-accent hover:underline disabled:opacity-50"
                          >
                            {previewLoadingId === doc.id ? 'Opening…' : 'View'}
                          </button>
                          <button
                            type="button"
                            onClick={() => void onSaveDoc(doc)}
                            disabled={downloadingId === doc.id}
                            className="text-accent hover:underline disabled:opacity-50"
                          >
                            {downloadingId === doc.id ? 'Saving…' : 'Download'}
                          </button>
                          <button
                            type="button"
                            onClick={() => void onDeleteDoc(doc)}
                            disabled={deletingId === doc.id}
                            className="text-danger hover:underline disabled:opacity-50"
                          >
                            {deletingId === doc.id ? 'Deleting…' : 'Delete'}
                          </button>
                        </div>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>
        )}
      </div>

      {/* Manual upload modal — document type + optional expiry + file */}
      <Modal
        open={uploadModalOpen}
        onClose={() => {
          if (!docUploading) setUploadModalOpen(false)
        }}
        title="Upload document"
        className="w-full max-w-md"
      >
        <div className="space-y-4 p-1">
          <div>
            <label htmlFor="doc-type" className="mb-1 block text-sm font-medium text-text">
              Document type
            </label>
            <select
              id="doc-type"
              value={uploadType}
              onChange={(e) => onChangeUploadType(e.target.value)}
              className="h-10 w-full rounded-ctl border border-border bg-card px-3 text-sm text-text focus:border-accent focus:outline-none focus:ring-2 focus:ring-accent/20"
            >
              {STAFF_DOC_TYPES.map((o) => (
                <option key={o.value} value={o.value}>
                  {o.label}
                </option>
              ))}
            </select>
          </div>

          {/* Type-dependent detail field */}
          {(() => {
            const cfg = docTypeConfig(uploadType)
            if (!cfg?.detail) return null
            const detail = cfg.detail
            return (
              <div>
                <label htmlFor="doc-detail" className="mb-1 block text-sm font-medium text-text">
                  {detail.label}
                  {detail.required && <span className="text-danger"> *</span>}
                </label>
                {detail.options ? (
                  <>
                    <select
                      id="doc-detail"
                      value={uploadDetailSelect}
                      onChange={(e) => {
                        setUploadDetailSelect(e.target.value)
                        if (e.target.value !== 'drivers_licence') {
                          setBackFile(null)
                          setLicenceClass('')
                        }
                      }}
                      className="h-10 w-full rounded-ctl border border-border bg-card px-3 text-sm text-text focus:border-accent focus:outline-none focus:ring-2 focus:ring-accent/20"
                    >
                      <option value="">Select…</option>
                      {detail.options.map((o) => (
                        <option key={o.value} value={o.value}>
                          {o.label}
                        </option>
                      ))}
                      {detail.allowOther && <option value="other">Other…</option>}
                    </select>
                    {uploadDetailSelect === 'other' && (
                      <input
                        type="text"
                        value={uploadDetailText}
                        onChange={(e) => setUploadDetailText(e.target.value)}
                        placeholder="Describe the document"
                        className="mt-2 h-10 w-full rounded-ctl border border-border bg-card px-3 text-sm text-text focus:border-accent focus:outline-none focus:ring-2 focus:ring-accent/20"
                      />
                    )}
                  </>
                ) : (
                  <input
                    id="doc-detail"
                    type="text"
                    value={uploadDetailText}
                    onChange={(e) => setUploadDetailText(e.target.value)}
                    placeholder={detail.placeholder ?? ''}
                    className="h-10 w-full rounded-ctl border border-border bg-card px-3 text-sm text-text focus:border-accent focus:outline-none focus:ring-2 focus:ring-accent/20"
                  />
                )}
                {uploadType === 'identity' && uploadDetailSelect === 'passport' && (
                  <p className="mt-1 text-xs text-muted">
                    Tip: an NZ/Australian passport also proves the right to work — no
                    separate working-rights document is needed.
                  </p>
                )}
              </div>
            )
          })()}

          {/* Licence class — driver's licence only */}
          {isDriversLicence && (
            <div>
              <label htmlFor="licence-class" className="mb-1 block text-sm font-medium text-text">
                Licence class <span className="text-muted-2">(optional)</span>
              </label>
              <input
                id="licence-class"
                type="text"
                value={licenceClass}
                onChange={(e) => setLicenceClass(e.target.value)}
                placeholder="e.g. 1, 2, 4, 6, DI, F, R, T, W"
                className="h-10 w-full rounded-ctl border border-border bg-card px-3 text-sm text-text focus:border-accent focus:outline-none focus:ring-2 focus:ring-accent/20"
              />
              <p className="mt-1 text-xs text-muted">
                The class(es) endorsed on the licence (e.g. Class 1, Class 2 + endorsement DI).
              </p>
            </div>
          )}

          <div>
            <label htmlFor="doc-expiry" className="mb-1 block text-sm font-medium text-text">
              Expiry date <span className="text-muted-2">(optional)</span>
            </label>
            <input
              id="doc-expiry"
              type="date"
              value={uploadExpiry}
              onChange={(e) => setUploadExpiry(e.target.value)}
              className="h-10 w-full rounded-ctl border border-border bg-card px-3 text-sm text-text focus:border-accent focus:outline-none focus:ring-2 focus:ring-accent/20"
            />
            <p className="mt-1 text-xs text-muted">
              Set an expiry to be reminded before the document lapses (e.g. a visa or licence).
            </p>
          </div>

          <div>
            <label className="mb-1 block text-sm font-medium text-text">
              {isDriversLicence ? 'Front of licence' : 'File'}
              {isDriversLicence && <span className="text-danger"> *</span>}
            </label>
            <div className="flex items-center gap-3">
              <button
                type="button"
                onClick={() => docInputRef.current?.click()}
                className="rounded-ctl border border-border bg-card px-3 py-2 text-sm font-medium text-text hover:bg-canvas min-h-[40px]"
              >
                Choose file
              </button>
              <span className="min-w-0 flex-1 truncate text-sm text-muted" title={pendingFile?.name}>
                {pendingFile ? pendingFile.name : 'No file selected'}
              </span>
            </div>

            {isDriversLicence && (
              <div className="mt-3">
                <label className="mb-1 block text-sm font-medium text-text">
                  Back of licence <span className="text-muted-2">(optional)</span>
                </label>
                <div className="flex items-center gap-3">
                  <button
                    type="button"
                    onClick={() => backInputRef.current?.click()}
                    className="rounded-ctl border border-border bg-card px-3 py-2 text-sm font-medium text-text hover:bg-canvas min-h-[40px]"
                  >
                    Choose file
                  </button>
                  <span className="min-w-0 flex-1 truncate text-sm text-muted" title={backFile?.name}>
                    {backFile ? backFile.name : 'No file selected'}
                  </span>
                  {backFile && (
                    <button
                      type="button"
                      onClick={() => setBackFile(null)}
                      className="text-xs text-danger hover:underline"
                    >
                      Remove
                    </button>
                  )}
                </div>
                <input
                  ref={backInputRef}
                  type="file"
                  accept={ACCEPTED_DOC_UPLOAD_TYPES}
                  className="hidden"
                  data-testid="doc-upload-back-input"
                  onChange={(e) => {
                    const f = e.target.files?.[0]
                    if (f) {
                      setBackFile(f)
                      setUploadError(null)
                    }
                    e.target.value = ''
                  }}
                />
              </div>
            )}

            <p className="mt-1 text-xs text-muted">
              PDF, image, or Word file, up to 20 MB.
            </p>
          </div>

          {uploadError && (
            <p role="alert" className="text-sm text-danger">
              {uploadError}
            </p>
          )}

          <div className="flex items-center justify-end gap-3 border-t border-border pt-3">
            <button
              type="button"
              onClick={() => setUploadModalOpen(false)}
              disabled={docUploading}
              className="rounded-ctl border border-border px-3.5 py-2 text-sm font-medium text-text hover:bg-canvas min-h-[40px] disabled:opacity-50"
            >
              Cancel
            </button>
            <button
              type="button"
              onClick={() => void submitUpload()}
              disabled={docUploading || !pendingFile}
              className="rounded-ctl bg-accent px-3.5 py-2 text-sm font-medium text-white hover:bg-accent-press min-h-[40px] disabled:opacity-50"
            >
              {docUploading ? 'Uploading…' : 'Upload'}
            </button>
          </div>
        </div>
      </Modal>

      {/* In-app document/image preview modal */}
      <Modal
        open={preview !== null}
        onClose={closePreview}
        title={preview?.name ?? 'Preview'}
        className="w-full max-w-3xl"
      >
        {preview && (
          <div className="flex flex-col">
            <div className="flex max-h-[70vh] items-center justify-center overflow-auto bg-canvas p-2">
              {preview.mime.startsWith('image/') ? (
                <img
                  src={preview.url}
                  alt={preview.name}
                  className="max-h-[68vh] max-w-full object-contain"
                />
              ) : preview.mime === 'application/pdf' ? (
                <iframe
                  src={preview.url}
                  title={preview.name}
                  className="h-[68vh] w-full"
                />
              ) : (
                <div className="p-8 text-center text-sm text-muted">
                  This file type can't be previewed. Use Download to open it.
                </div>
              )}
            </div>
            <div className="flex items-center justify-end gap-3 border-t border-border px-4 py-3">
              <a
                href={preview.url}
                download={preview.name}
                className="text-sm text-accent hover:underline min-h-[44px] inline-flex items-center"
              >
                Download
              </a>
              <button
                type="button"
                onClick={closePreview}
                className="text-sm text-text hover:underline min-h-[44px]"
              >
                Close
              </button>
            </div>
          </div>
        )}
      </Modal>

      {/* Send for signature (e-signature) modal — module-gated (R10.2/R10.5) */}
      {esignEnabled && (
        <SendForSignatureModal
          open={sendForSignatureOpen}
          onClose={() => setSendForSignatureOpen(false)}
          originatingEntityType="staff"
          originatingEntityId={staffId}
          onSent={() => {
            const controller = new AbortController()
            void loadDocs.current(controller.signal)
          }}
        />
      )}
    </div>
  )
}
