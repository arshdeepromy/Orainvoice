import { useCallback, useEffect, useRef, useState } from 'react'
import apiClient from '@/api/client'

/* ------------------------------------------------------------------ */
/*  Types                                                              */
/* ------------------------------------------------------------------ */

export interface Attachment {
  id: string
  job_card_id: string
  file_key: string
  file_name: string
  file_size: number
  mime_type: string
  uploaded_by: string
  uploaded_at: string
}

interface AttachmentUploaderProps {
  jobCardId: string
  onUploadComplete: (attachment: Attachment) => void
  onError: (error: string) => void
  disabled?: boolean
}

/* ------------------------------------------------------------------ */
/*  Constants                                                          */
/* ------------------------------------------------------------------ */

const MAX_FILE_SIZE = 50 * 1024 * 1024 // 50 MB

const ACCEPTED_MIME_TYPES = new Set([
  'image/jpeg',
  'image/png',
  'image/webp',
  'image/gif',
  'application/pdf',
])

/** File-input accept string for the native file picker. */
const ACCEPT_STRING =
  '.jpg,.jpeg,.png,.webp,.gif,.pdf,image/jpeg,image/png,image/webp,image/gif,application/pdf'

/* ------------------------------------------------------------------ */
/*  Helpers                                                            */
/* ------------------------------------------------------------------ */

function formatFileSize(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`
  if (bytes < 1_048_576) return `${(bytes / 1024).toFixed(1)} KB`
  return `${(bytes / 1_048_576).toFixed(1)} MB`
}

function validateFile(file: File): string | null {
  if (!ACCEPTED_MIME_TYPES.has(file.type)) {
    return `File type "${file.type || 'unknown'}" is not accepted. Allowed: JPEG, PNG, WebP, GIF, PDF`
  }
  if (file.size > MAX_FILE_SIZE) {
    return `File size (${formatFileSize(file.size)}) exceeds the 50 MB limit`
  }
  if (file.size === 0) {
    return 'File is empty'
  }
  return null
}

/* ------------------------------------------------------------------ */
/*  Component                                                          */
/* ------------------------------------------------------------------ */

export default function AttachmentUploader({
  jobCardId,
  onUploadComplete,
  onError,
  disabled = false,
}: AttachmentUploaderProps) {
  const [dragActive, setDragActive] = useState(false)
  const [uploading, setUploading] = useState(false)
  const [uploadProgress, setUploadProgress] = useState(0)
  const [fileError, setFileError] = useState('')

  const fileInputRef = useRef<HTMLInputElement>(null)
  const abortControllerRef = useRef<AbortController | null>(null)

  /* Cleanup any in-flight upload on unmount */
  useEffect(() => {
    return () => {
      abortControllerRef.current?.abort()
    }
  }, [])

  /* --- file selection & validation --- */
  const handleFileSelect = useCallback(
    (file: File) => {
      setFileError('')

      const error = validateFile(file)
      if (error) {
        setFileError(error)
        onError(error)
        return
      }

      // Start upload
      uploadFile(file)
    },
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [jobCardId],
  )

  /* --- upload logic --- */
  const uploadFile = useCallback(
    async (file: File) => {
      // Abort any previous in-flight upload
      abortControllerRef.current?.abort()
      const controller = new AbortController()
      abortControllerRef.current = controller

      setUploading(true)
      setUploadProgress(0)
      setFileError('')

      const formData = new FormData()
      formData.append('file', file)

      try {
        const res = await apiClient.post<Attachment>(
          `/job-cards/${jobCardId}/attachments`,
          formData,
          {
            headers: { 'Content-Type': 'multipart/form-data' },
            signal: controller.signal,
            onUploadProgress: (progressEvent) => {
              const total = progressEvent.total ?? 0
              if (total > 0) {
                setUploadProgress(Math.round((progressEvent.loaded * 100) / total))
              }
            },
          },
        )

        if (res.data) {
          onUploadComplete(res.data)
        }
      } catch (err: unknown) {
        // Don't report errors from intentional aborts
        if (controller.signal.aborted) return

        const detail =
          (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail ??
          'Upload failed. Please try again.'
        const status = (err as { response?: { status?: number } })?.response?.status

        let message = detail
        if (status === 413) {
          message = 'File too large. Maximum size is 50 MB.'
        } else if (status === 507) {
          message = 'Storage quota exceeded. Please contact your administrator.'
        }

        setFileError(message)
        onError(message)
      } finally {
        if (!controller.signal.aborted) {
          setUploading(false)
          setUploadProgress(0)
        }
        // Clear the file input so the same file can be re-selected
        if (fileInputRef.current) {
          fileInputRef.current.value = ''
        }
      }
    },
    [jobCardId, onUploadComplete, onError],
  )

  /* --- input change handler --- */
  const handleInputChange = useCallback(
    (e: React.ChangeEvent<HTMLInputElement>) => {
      const file = e.target.files?.[0]
      if (file) handleFileSelect(file)
    },
    [handleFileSelect],
  )

  /* --- drag-and-drop handlers --- */
  const handleDrag = useCallback((e: React.DragEvent) => {
    e.preventDefault()
    e.stopPropagation()
    if (e.type === 'dragenter' || e.type === 'dragover') {
      setDragActive(true)
    } else if (e.type === 'dragleave') {
      setDragActive(false)
    }
  }, [])

  const handleDrop = useCallback(
    (e: React.DragEvent) => {
      e.preventDefault()
      e.stopPropagation()
      setDragActive(false)

      if (disabled || uploading) return

      const file = e.dataTransfer.files?.[0]
      if (file) handleFileSelect(file)
    },
    [disabled, uploading, handleFileSelect],
  )

  const isDisabled = disabled || uploading

  return (
    <div>
      {/* Drop zone */}
      <div
        role="button"
        tabIndex={isDisabled ? -1 : 0}
        aria-label="Drop a file here or click to browse"
        aria-disabled={isDisabled}
        className={`relative flex flex-col items-center justify-center rounded-lg border-2 border-dashed p-6 transition-colors min-h-[120px] ${
          isDisabled
            ? 'cursor-not-allowed border-gray-200 bg-gray-100 opacity-60'
            : dragActive
              ? 'cursor-pointer border-blue-400 bg-blue-50'
              : fileError
                ? 'cursor-pointer border-red-300 bg-red-50'
                : 'cursor-pointer border-gray-300 bg-gray-50 hover:border-gray-400 hover:bg-gray-100'
        }`}
        onDragEnter={isDisabled ? undefined : handleDrag}
        onDragOver={isDisabled ? undefined : handleDrag}
        onDragLeave={isDisabled ? undefined : handleDrag}
        onDrop={isDisabled ? undefined : handleDrop}
        onClick={() => {
          if (!isDisabled) fileInputRef.current?.click()
        }}
        onKeyDown={(e) => {
          if (!isDisabled && (e.key === 'Enter' || e.key === ' ')) {
            e.preventDefault()
            fileInputRef.current?.click()
          }
        }}
      >
        <input
          ref={fileInputRef}
          type="file"
          accept={ACCEPT_STRING}
          onChange={handleInputChange}
          className="sr-only"
          aria-label="Select file to upload"
          disabled={isDisabled}
        />

        {uploading ? (
          /* Upload in progress */
          <div className="w-full max-w-xs text-center">
            <svg
              className="mx-auto mb-2 h-8 w-8 animate-spin"
              style={{ color: 'var(--color-primary, #3b82f6)' }}
              xmlns="http://www.w3.org/2000/svg"
              fill="none"
              viewBox="0 0 24 24"
              aria-hidden="true"
            >
              <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
              <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z" />
            </svg>
            <div className="flex items-center justify-between text-sm text-gray-600 mb-1">
              <span>Uploading…</span>
              <span>{uploadProgress}%</span>
            </div>
            <div className="h-2 w-full rounded-full bg-gray-200 overflow-hidden">
              <div
                className="h-full rounded-full bg-blue-500 transition-all duration-300"
                style={{ width: `${uploadProgress}%` }}
                role="progressbar"
                aria-valuenow={uploadProgress}
                aria-valuemin={0}
                aria-valuemax={100}
                aria-label="Upload progress"
              />
            </div>
          </div>
        ) : (
          /* Default idle state */
          <>
            <svg
              className="h-10 w-10 text-gray-400 mb-2"
              fill="none"
              viewBox="0 0 24 24"
              stroke="currentColor"
              strokeWidth={1.5}
              aria-hidden="true"
            >
              <path
                strokeLinecap="round"
                strokeLinejoin="round"
                d="M7 16a4 4 0 01-.88-7.903A5 5 0 1115.9 6L16 6a5 5 0 011 9.9M15 13l-3-3m0 0l-3 3m3-3v12"
              />
            </svg>
            <p className="text-sm text-gray-600">
              <span className="font-medium text-blue-600">Click to browse</span> or drag and drop
            </p>
            <p className="text-xs text-gray-400 mt-1">
              Images (JPEG, PNG, WebP, GIF) and PDFs up to 50MB
            </p>
          </>
        )}
      </div>

      {/* Error message */}
      {fileError && (
        <p className="mt-1 text-sm text-red-600" role="alert">
          {fileError}
        </p>
      )}
    </div>
  )
}
