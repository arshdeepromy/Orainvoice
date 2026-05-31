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
 */

import React, { useEffect, useRef, useState } from 'react'
import apiClient from '@/api/client'

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

const MAX_BYTES = 10 * 1024 * 1024
const ACCEPTED_TYPES = '.pdf,.jpg,.jpeg,.png,application/pdf,image/jpeg,image/png'
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
      setError('File too large. Maximum size is 10 MB.')
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

  const onView = async () => {
    if (!recentUpload?.file_key) return
    try {
      const res = await apiClient.get(
        `/api/v2/uploads/${recentUpload.file_key}`,
        { responseType: 'blob' },
      )
      const blob = res.data as Blob
      const url = URL.createObjectURL(blob)
      window.open(url, '_blank', 'noopener,noreferrer')
    } catch {
      setError('Failed to open document.')
    }
  }

  if (isLoading) {
    return <div className="p-6 text-gray-500">Loading…</div>
  }
  if (loadError) {
    return (
      <div role="alert" className="p-6 text-red-600 dark:text-red-400">
        {loadError}
      </div>
    )
  }

  const hasUpload = !!staff?.employment_agreement_upload_id

  return (
    <div className="p-6 max-w-2xl">
      <h2 className="text-lg font-semibold mb-1 text-gray-900 dark:text-gray-100">
        Employment agreement
      </h2>
      <p className="text-sm text-gray-600 dark:text-gray-400 mb-4">
        Attach the staff member's signed employment agreement (PDF, JPG, or
        PNG, up to 10 MB).
      </p>

      {hasUpload ? (
        <div
          className="border border-gray-200 dark:border-gray-700 rounded p-4"
          data-testid="agreement-attached"
        >
          <div className="text-sm text-gray-900 dark:text-gray-100">
            {recentUpload?.file_name ? (
              <span data-testid="agreement-filename" className="font-medium">
                {recentUpload.file_name}
              </span>
            ) : (
              <span
                data-testid="agreement-upload-id"
                className="font-mono text-xs text-gray-700 dark:text-gray-300"
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
                className="text-sm text-blue-600 hover:underline min-h-[44px]"
              >
                View
              </button>
            )}
            <button
              type="button"
              onClick={() => fileInputRef.current?.click()}
              disabled={uploading}
              className="text-sm text-blue-600 hover:underline min-h-[44px] disabled:opacity-50"
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
          className={`border-2 border-dashed rounded p-8 text-center cursor-pointer min-h-[160px] flex flex-col items-center justify-center transition-colors ${
            dragActive
              ? 'border-blue-500 bg-blue-50 dark:bg-blue-900/20'
              : 'border-gray-300 dark:border-gray-600'
          } ${uploading ? 'opacity-50 cursor-wait' : ''}`}
        >
          <p className="text-sm text-gray-700 dark:text-gray-300">
            {uploading
              ? 'Uploading…'
              : 'Drag a PDF, JPG, or PNG here, or click to browse.'}
          </p>
          <p className="text-xs text-gray-500 dark:text-gray-500 mt-2">
            Maximum 10 MB.
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
          className="mt-4 text-sm text-red-600 dark:text-red-400"
        >
          {error}
        </div>
      )}
    </div>
  )
}
