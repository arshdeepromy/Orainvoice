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
    <div className="mb-6 rounded-card border border-border bg-card p-6 shadow-card">
      <div className="mb-4 flex items-center justify-between">
        <h2 className="text-lg font-medium text-text">Upload Document</h2>
        <Button variant="ghost" size="sm" onClick={onCancel} disabled={uploading}>
          Cancel
        </Button>
      </div>

      <form onSubmit={handleSubmit} noValidate>
        {/* Error banner */}
        {submitError && (
          <div className="mb-4 rounded-card border border-danger/30 bg-danger-soft p-3" role="alert">
            <p className="text-sm text-danger">{submitError}</p>
          </div>
        )}

        {/* Drag-and-drop zone */}
        <div className="mb-4">
          <label className="mb-1 block text-sm font-medium text-text">
            File <span className="text-danger">*</span>
          </label>
          <div
            role="button"
            tabIndex={0}
            aria-label="Drop a file here or click to select"
            className={`relative flex min-h-[120px] cursor-pointer flex-col items-center justify-center rounded-card border-2 border-dashed p-6 transition-colors ${
              dragActive
                ? 'border-accent bg-accent-soft'
                : fileError
                  ? 'border-danger/40 bg-danger-soft'
                  : 'border-border-strong bg-canvas hover:border-border-strong hover:bg-canvas'
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
                  className="h-8 w-8 flex-shrink-0 text-accent"
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
                  <p className="font-medium text-text">{selectedFile.name}</p>
                  <p className="text-muted">{formatFileSize(selectedFile.size)}</p>
                </div>
                <button
                  type="button"
                  onClick={(e) => {
                    e.stopPropagation()
                    handleClearFile()
                  }}
                  className="ml-2 rounded-ctl p-1 text-muted-2 hover:bg-canvas hover:text-muted"
                  aria-label="Remove selected file"
                  style={{ minWidth: '44px', minHeight: '44px' }}
                >
                  <svg className="mx-auto h-4 w-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                    <path strokeLinecap="round" strokeLinejoin="round" d="M6 18L18 6M6 6l12 12" />
                  </svg>
                </button>
              </div>
            ) : (
              <>
                <svg
                  className="mb-2 h-10 w-10 text-muted-2"
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
                <p className="text-sm text-muted">
                  <span className="font-medium text-accent">Click to select</span> or drag and
                  drop
                </p>
                <p className="mt-1 text-xs text-muted-2">
                  PDF, JPEG, PNG, GIF, Word (.doc, .docx) — max 10 MB
                </p>
              </>
            )}
          </div>
          {fileError && (
            <p className="mt-1 text-sm text-danger" role="alert">
              {fileError}
            </p>
          )}
        </div>

        {/* Category searchable dropdown */}
        <div className="relative mb-4" ref={dropdownRef}>
          <label htmlFor="upload-category" className="mb-1 block text-sm font-medium text-text">
            Category <span className="text-danger">*</span>
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
            className="h-[44px] w-full rounded-ctl border border-border bg-card px-3 py-2 text-text shadow-sm placeholder:text-muted-2 focus-visible:border-accent focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent"
          />
          {showCategoryDropdown && (filteredCategories.length > 0 || showCreateOption) && (
            <ul
              role="listbox"
              className="absolute z-10 mt-1 max-h-60 w-full overflow-auto rounded-ctl border border-border bg-card py-1 shadow-pop"
            >
              {(filteredCategories ?? []).map((cat) => (
                <li
                  key={cat.id}
                  role="option"
                  aria-selected={selectedCategory === cat.name}
                  className={`cursor-pointer px-3 py-2 text-sm hover:bg-accent-soft hover:text-accent ${
                    selectedCategory === cat.name ? 'bg-accent-soft font-medium text-accent' : 'text-text'
                  }`}
                  style={{ minHeight: '44px', display: 'flex', alignItems: 'center' }}
                  onMouseDown={(e) => {
                    e.preventDefault()
                    handleCategorySelect(cat.name)
                  }}
                >
                  <span className="flex-1">{cat.name}</span>
                  {cat.is_predefined && (
                    <span className="ml-2 text-xs text-muted-2">Predefined</span>
                  )}
                </li>
              ))}
              {showCreateOption && (
                <li
                  role="option"
                  aria-selected={false}
                  className="cursor-pointer border-t border-border px-3 py-2 text-sm font-medium text-accent hover:bg-accent-soft"
                  style={{ minHeight: '44px', display: 'flex', alignItems: 'center' }}
                  onMouseDown={(e) => {
                    e.preventDefault()
                    handleCreateCategory(categoryQuery.trim())
                  }}
                >
                  <svg className="mr-2 h-4 w-4 flex-shrink-0" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
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
          <label htmlFor="upload-description" className="mb-1 block text-sm font-medium text-text">
            Description
          </label>
          <textarea
            id="upload-description"
            rows={2}
            placeholder="Optional description…"
            value={description}
            onChange={(e) => setDescription(e.target.value)}
            className="w-full rounded-ctl border border-border bg-card px-3 py-2 text-text shadow-sm placeholder:text-muted-2 focus-visible:border-accent focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent"
          />
        </div>

        {/* Expiry date */}
        <div className="mb-4">
          <label htmlFor="upload-expiry" className="mb-1 block text-sm font-medium text-text">
            Expiry Date
          </label>
          <input
            id="upload-expiry"
            type="date"
            value={expiryDate}
            onChange={(e) => setExpiryDate(e.target.value)}
            className="h-[44px] w-full rounded-ctl border border-border bg-card px-3 py-2 text-text shadow-sm focus-visible:border-accent focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent sm:w-64"
          />
        </div>

        {/* Upload progress */}
        {uploading && (
          <div className="mb-4">
            <div className="mb-1 flex items-center justify-between text-sm text-muted">
              <span>Uploading…</span>
              <span>{uploadProgress}%</span>
            </div>
            <div className="h-2 w-full overflow-hidden rounded-full bg-canvas">
              <div
                className="h-full rounded-full bg-accent transition-all duration-300"
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
            variant="ghost"
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
