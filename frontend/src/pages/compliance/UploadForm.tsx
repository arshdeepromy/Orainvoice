import { useCallback, useRef, useState, useMemo } from 'react'
import apiClient from '@/api/client'
import { Button } from '@/components/ui'
import type { CategoryResponse, ComplianceDocumentResponse } from './ComplianceDashboard'

/* ------------------------------------------------------------------ */
/*  Constants                                                          */
/* ------------------------------------------------------------------ */

const MAX_FILE_SIZE = 10_485_760 // 10 MB

/** MIME types accepted by the backend (Requirement 3.2). */
const ACCEPTED_MIME_TYPES = new Set([
  'application/pdf',
  'image/jpeg',
  'image/png',
  'image/gif',
  'application/msword',
  'application/vnd.openxmlformats-officedocument.wordprocessingml.document',
])

/** File-input accept string for the native file picker. */
const ACCEPT_STRING =
  '.pdf,.jpg,.jpeg,.png,.gif,.doc,.docx,application/pdf,image/jpeg,image/png,image/gif,application/msword,application/vnd.openxmlformats-officedocument.wordprocessingml.document'

/* ------------------------------------------------------------------ */
/*  Props                                                              */
/* ------------------------------------------------------------------ */

interface UploadFormProps {
  categories: CategoryResponse[]
  onSuccess: () => void
  onCancel: () => void
  onCategoriesChange: (categories: CategoryResponse[]) => void
}

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
    return 'File type not accepted. Allowed types: PDF, JPEG, PNG, GIF, Word (.doc, .docx)'
  }
  if (file.size > MAX_FILE_SIZE) {
    return `File size (${formatFileSize(file.size)}) exceeds maximum of 10 MB`
  }
  return null
}

/* ------------------------------------------------------------------ */
/*  Component                                                          */
/* ------------------------------------------------------------------ */

export default function UploadForm({
  categories,
  onSuccess,
  onCancel,
  onCategoriesChange,
}: UploadFormProps) {
  /* --- state --- */
  const [selectedFile, setSelectedFile] = useState<File | null>(null)
  const [fileError, setFileError] = useState('')
  const [categoryQuery, setCategoryQuery] = useState('')
  const [selectedCategory, setSelectedCategory] = useState('')
  const [showCategoryDropdown, setShowCategoryDropdown] = useState(false)
  const [description, setDescription] = useState('')
  const [expiryDate, setExpiryDate] = useState('')
  const [invoiceId, setInvoiceId] = useState('')
  const [jobId, setJobId] = useState('')
  const [uploading, setUploading] = useState(false)
  const [uploadProgress, setUploadProgress] = useState(0)
  const [submitError, setSubmitError] = useState('')
  const [dragActive, setDragActive] = useState(false)

  const fileInputRef = useRef<HTMLInputElement>(null)
  const categoryInputRef = useRef<HTMLInputElement>(null)
  const dropdownRef = useRef<HTMLDivElement>(null)

  /* --- category filtering --- */
  const filteredCategories = useMemo(() => {
    const q = categoryQuery.toLowerCase().trim()
    if (!q) return categories ?? []
    return (categories ?? []).filter((cat) =>
      cat.name.toLowerCase().includes(q),
    )
  }, [categories, categoryQuery])

  const showCreateOption =
    categoryQuery.trim().length > 0 &&
    !(categories ?? []).some(
      (cat) => cat.name.toLowerCase() === categoryQuery.trim().toLowerCase(),
    )

  /* --- file selection --- */
  const handleFileSelect = useCallback((file: File) => {
    setFileError('')
    setSubmitError('')
    const error = validateFile(file)
    if (error) {
      setFileError(error)
      setSelectedFile(null)
      return
    }
    setSelectedFile(file)
  }, [])

  const handleInputChange = useCallback(
    (e: React.ChangeEvent<HTMLInputElement>) => {
      const file = e.target.files?.[0]
      if (file) handleFileSelect(file)
    },
    [handleFileSelect],
  )

  /* --- drag-and-drop --- */
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
      const file = e.dataTransfer.files?.[0]
      if (file) handleFileSelect(file)
    },
    [handleFileSelect],
  )

  /* --- category selection --- */
  const handleCategorySelect = useCallback((name: string) => {
    setSelectedCategory(name)
    setCategoryQuery(name)
    setShowCategoryDropdown(false)
  }, [])

  const handleCreateCategory = useCallback(
    async (name: string) => {
      try {
        const res = await apiClient.post<CategoryResponse>(
          '/api/v2/compliance-docs/categories',
          { name },
        )
        const newCat = res.data
        if (newCat) {
          // Update parent's category list
          onCategoriesChange([...(categories ?? []), newCat])
        }
        setSelectedCategory(name)
        setCategoryQuery(name)
        setShowCategoryDropdown(false)
      } catch (err: unknown) {
        // If 409 (duplicate), just select the existing one
        const status = (err as { response?: { status?: number } })?.response?.status
        if (status === 409) {
          setSelectedCategory(name)
          setCategoryQuery(name)
          setShowCategoryDropdown(false)
        } else {
          setSubmitError('Failed to create custom category')
        }
      }
    },
    [categories, onCategoriesChange],
  )

  /* --- form submission --- */
  const handleSubmit = useCallback(
    async (e: React.FormEvent) => {
      e.preventDefault()
      setSubmitError('')

      if (!selectedFile) {
        setFileError('Please select a file to upload')
        return
      }

      const categoryName = selectedCategory.trim() || categoryQuery.trim()
      if (!categoryName) {
        setSubmitError('Please select or enter a document category')
        return
      }

      // If the user typed a custom category that doesn't exist yet, create it first
      const existingCat = (categories ?? []).find(
        (cat) => cat.name.toLowerCase() === categoryName.toLowerCase(),
      )
      if (!existingCat) {
        // Create the custom category before uploading
        try {
          const res = await apiClient.post<CategoryResponse>(
            '/api/v2/compliance-docs/categories',
            { name: categoryName },
          )
          const newCat = res.data
          if (newCat) {
            onCategoriesChange([...(categories ?? []), newCat])
          }
        } catch (err: unknown) {
          const status = (err as { response?: { status?: number } })?.response?.status
          if (status !== 409) {
            setSubmitError('Failed to create custom category')
            return
          }
          // 409 means it already exists — proceed with upload
        }
      }

      const formData = new FormData()
      formData.append('file', selectedFile)
      formData.append('document_type', categoryName)
      if (description.trim()) formData.append('description', description.trim())
      if (expiryDate) formData.append('expiry_date', expiryDate)
      if (invoiceId.trim()) formData.append('invoice_id', invoiceId.trim())
      if (jobId.trim()) formData.append('job_id', jobId.trim())

      setUploading(true)
      setUploadProgress(0)

      try {
        await apiClient.post<ComplianceDocumentResponse>(
          '/api/v2/compliance-docs/upload',
          formData,
          {
            headers: { 'Content-Type': 'multipart/form-data' },
            onUploadProgress: (progressEvent) => {
              const total = progressEvent.total ?? 0
              if (total > 0) {
                setUploadProgress(Math.round((progressEvent.loaded * 100) / total))
              }
            },
          },
        )
        onSuccess()
      } catch (err: unknown) {
        const detail =
          (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail ??
          'Upload failed. Please try again.'
        setSubmitError(detail)
      } finally {
        setUploading(false)
      }
    },
    [
      selectedFile,
      selectedCategory,
      categoryQuery,
      categories,
      description,
      expiryDate,
      invoiceId,
      jobId,
      onSuccess,
      onCategoriesChange,
    ],
  )

  /* --- clear file --- */
  const handleClearFile = useCallback(() => {
    setSelectedFile(null)
    setFileError('')
    if (fileInputRef.current) {
      fileInputRef.current.value = ''
    }
  }, [])

  return (
    <div className="mb-6 rounded-lg border border-gray-200 bg-white p-6 shadow-sm">
      <div className="flex items-center justify-between mb-4">
        <h2 className="text-lg font-medium text-gray-900">Upload Document</h2>
        <Button variant="secondary" size="sm" onClick={onCancel} disabled={uploading}>
          Cancel
        </Button>
      </div>

      <form onSubmit={handleSubmit} noValidate>
        {/* Error banner */}
        {submitError && (
          <div className="mb-4 rounded-lg border border-red-200 bg-red-50 p-3" role="alert">
            <p className="text-sm text-red-700">{submitError}</p>
          </div>
        )}

        {/* Drag-and-drop zone */}
        <div className="mb-4">
          <label className="text-sm font-medium text-gray-700 mb-1 block">
            File <span className="text-red-500">*</span>
          </label>
          <div
            role="button"
            tabIndex={0}
            aria-label="Drop a file here or click to select"
            className={`relative flex flex-col items-center justify-center rounded-lg border-2 border-dashed p-6 transition-colors cursor-pointer min-h-[120px] ${
              dragActive
                ? 'border-blue-400 bg-blue-50'
                : fileError
                  ? 'border-red-300 bg-red-50'
                  : 'border-gray-300 bg-gray-50 hover:border-gray-400 hover:bg-gray-100'
            }`}
            onDragEnter={handleDrag}
            onDragOver={handleDrag}
            onDragLeave={handleDrag}
            onDrop={handleDrop}
            onClick={() => fileInputRef.current?.click()}
            onKeyDown={(e) => {
              if (e.key === 'Enter' || e.key === ' ') {
                e.preventDefault()
                fileInputRef.current?.click()
              }
            }}
            style={{ minHeight: '44px' }}
          >
            <input
              ref={fileInputRef}
              type="file"
              accept={ACCEPT_STRING}
              onChange={handleInputChange}
              className="sr-only"
              aria-label="Select file to upload"
            />

            {selectedFile ? (
              <div className="flex items-center gap-3 text-sm">
                <svg
                  className="h-8 w-8 text-blue-500 flex-shrink-0"
                  fill="none"
                  viewBox="0 0 24 24"
                  stroke="currentColor"
                  strokeWidth={1.5}
                >
                  <path
                    strokeLinecap="round"
                    strokeLinejoin="round"
                    d="M9 12h6m-6 4h6m2 5H7a2 2 0 01-2-2V5a2 2 0 012-2h5.586a1 1 0 01.707.293l5.414 5.414a1 1 0 01.293.707V19a2 2 0 01-2 2z"
                  />
                </svg>
                <div>
                  <p className="font-medium text-gray-900">{selectedFile.name}</p>
                  <p className="text-gray-500">{formatFileSize(selectedFile.size)}</p>
                </div>
                <button
                  type="button"
                  onClick={(e) => {
                    e.stopPropagation()
                    handleClearFile()
                  }}
                  className="ml-2 rounded p-1 text-gray-400 hover:bg-gray-200 hover:text-gray-600"
                  aria-label="Remove selected file"
                  style={{ minWidth: '44px', minHeight: '44px' }}
                >
                  <svg className="h-4 w-4 mx-auto" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                    <path strokeLinecap="round" strokeLinejoin="round" d="M6 18L18 6M6 6l12 12" />
                  </svg>
                </button>
              </div>
            ) : (
              <>
                <svg
                  className="h-10 w-10 text-gray-400 mb-2"
                  fill="none"
                  viewBox="0 0 24 24"
                  stroke="currentColor"
                  strokeWidth={1.5}
                >
                  <path
                    strokeLinecap="round"
                    strokeLinejoin="round"
                    d="M7 16a4 4 0 01-.88-7.903A5 5 0 1115.9 6L16 6a5 5 0 011 9.9M15 13l-3-3m0 0l-3 3m3-3v12"
                  />
                </svg>
                <p className="text-sm text-gray-600">
                  <span className="font-medium text-blue-600">Click to select</span> or drag and
                  drop
                </p>
                <p className="text-xs text-gray-400 mt-1">
                  PDF, JPEG, PNG, GIF, Word (.doc, .docx) — max 10 MB
                </p>
              </>
            )}
          </div>
          {fileError && (
            <p className="mt-1 text-sm text-red-600" role="alert">
              {fileError}
            </p>
          )}
        </div>

        {/* Category searchable dropdown */}
        <div className="mb-4 relative" ref={dropdownRef}>
          <label htmlFor="upload-category" className="text-sm font-medium text-gray-700 mb-1 block">
            Category <span className="text-red-500">*</span>
          </label>
          <input
            ref={categoryInputRef}
            id="upload-category"
            type="text"
            role="combobox"
            aria-expanded={showCategoryDropdown}
            aria-haspopup="listbox"
            aria-autocomplete="list"
            autoComplete="off"
            placeholder="Search or enter a category…"
            value={categoryQuery}
            onChange={(e) => {
              setCategoryQuery(e.target.value)
              setSelectedCategory('')
              setShowCategoryDropdown(true)
            }}
            onFocus={() => setShowCategoryDropdown(true)}
            onBlur={() => {
              // Delay to allow click on dropdown items
              setTimeout(() => setShowCategoryDropdown(false), 200)
            }}
            className="h-[44px] w-full rounded-md border border-gray-300 px-3 py-2 text-gray-900 shadow-sm placeholder:text-gray-400 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-blue-500 focus-visible:ring-offset-2 focus-visible:border-blue-500"
          />
          {showCategoryDropdown && (filteredCategories.length > 0 || showCreateOption) && (
            <ul
              role="listbox"
              className="absolute z-10 mt-1 max-h-60 w-full overflow-auto rounded-md border border-gray-200 bg-white py-1 shadow-lg"
            >
              {(filteredCategories ?? []).map((cat) => (
                <li
                  key={cat.id}
                  role="option"
                  aria-selected={selectedCategory === cat.name}
                  className={`cursor-pointer px-3 py-2 text-sm hover:bg-blue-50 hover:text-blue-700 ${
                    selectedCategory === cat.name ? 'bg-blue-50 text-blue-700 font-medium' : 'text-gray-900'
                  }`}
                  style={{ minHeight: '44px', display: 'flex', alignItems: 'center' }}
                  onMouseDown={(e) => {
                    e.preventDefault()
                    handleCategorySelect(cat.name)
                  }}
                >
                  <span className="flex-1">{cat.name}</span>
                  {cat.is_predefined && (
                    <span className="ml-2 text-xs text-gray-400">Predefined</span>
                  )}
                </li>
              ))}
              {showCreateOption && (
                <li
                  role="option"
                  aria-selected={false}
                  className="cursor-pointer px-3 py-2 text-sm text-blue-600 hover:bg-blue-50 font-medium border-t border-gray-100"
                  style={{ minHeight: '44px', display: 'flex', alignItems: 'center' }}
                  onMouseDown={(e) => {
                    e.preventDefault()
                    handleCreateCategory(categoryQuery.trim())
                  }}
                >
                  <svg className="h-4 w-4 mr-2 flex-shrink-0" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                    <path strokeLinecap="round" strokeLinejoin="round" d="M12 4v16m8-8H4" />
                  </svg>
                  Create &ldquo;{categoryQuery.trim()}&rdquo;
                </li>
              )}
            </ul>
          )}
        </div>

        {/* Description */}
        <div className="mb-4">
          <label htmlFor="upload-description" className="text-sm font-medium text-gray-700 mb-1 block">
            Description
          </label>
          <textarea
            id="upload-description"
            rows={2}
            placeholder="Optional description…"
            value={description}
            onChange={(e) => setDescription(e.target.value)}
            className="w-full rounded-md border border-gray-300 px-3 py-2 text-gray-900 shadow-sm placeholder:text-gray-400 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-blue-500 focus-visible:ring-offset-2 focus-visible:border-blue-500"
          />
        </div>

        {/* Expiry date */}
        <div className="mb-4">
          <label htmlFor="upload-expiry" className="text-sm font-medium text-gray-700 mb-1 block">
            Expiry Date
          </label>
          <input
            id="upload-expiry"
            type="date"
            value={expiryDate}
            onChange={(e) => setExpiryDate(e.target.value)}
            className="h-[44px] w-full sm:w-64 rounded-md border border-gray-300 px-3 py-2 text-gray-900 shadow-sm focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-blue-500 focus-visible:ring-offset-2 focus-visible:border-blue-500"
          />
        </div>

        {/* Optional linking fields */}
        <div className="grid grid-cols-1 sm:grid-cols-2 gap-4 mb-4">
          <div>
            <label htmlFor="upload-invoice" className="text-sm font-medium text-gray-700 mb-1 block">
              Link to Invoice (ID)
            </label>
            <input
              id="upload-invoice"
              type="text"
              placeholder="Invoice UUID (optional)"
              value={invoiceId}
              onChange={(e) => setInvoiceId(e.target.value)}
              className="h-[44px] w-full rounded-md border border-gray-300 px-3 py-2 text-gray-900 shadow-sm placeholder:text-gray-400 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-blue-500 focus-visible:ring-offset-2 focus-visible:border-blue-500"
            />
          </div>
          <div>
            <label htmlFor="upload-job" className="text-sm font-medium text-gray-700 mb-1 block">
              Link to Job (ID)
            </label>
            <input
              id="upload-job"
              type="text"
              placeholder="Job UUID (optional)"
              value={jobId}
              onChange={(e) => setJobId(e.target.value)}
              className="h-[44px] w-full rounded-md border border-gray-300 px-3 py-2 text-gray-900 shadow-sm placeholder:text-gray-400 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-blue-500 focus-visible:ring-offset-2 focus-visible:border-blue-500"
            />
          </div>
        </div>

        {/* Upload progress */}
        {uploading && (
          <div className="mb-4">
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
        )}

        {/* Actions */}
        <div className="flex items-center justify-end gap-3 pt-2">
          <Button
            type="button"
            variant="secondary"
            onClick={onCancel}
            disabled={uploading}
            style={{ minWidth: '44px', minHeight: '44px' }}
          >
            Cancel
          </Button>
          <Button
            type="submit"
            loading={uploading}
            disabled={uploading || !selectedFile}
            style={{ minWidth: '44px', minHeight: '44px' }}
          >
            Upload
          </Button>
        </div>
      </form>
    </div>
  )
}
