import { useCallback, useMemo, useRef, useState } from 'react'
import apiClient from '@/api/client'
import { Button, Modal } from '@/components/ui'
import type { CategoryResponse, ComplianceDocumentResponse } from './ComplianceDashboard'

/* ------------------------------------------------------------------ */
/*  Props                                                              */
/* ------------------------------------------------------------------ */

interface EditModalProps {
  open: boolean
  document: ComplianceDocumentResponse | null
  categories: CategoryResponse[]
  onClose: () => void
  onSuccess: (updated: ComplianceDocumentResponse) => void
  onCategoriesChange: (categories: CategoryResponse[]) => void
}

/* ------------------------------------------------------------------ */
/*  Component                                                          */
/* ------------------------------------------------------------------ */

export default function EditModal({
  open,
  document: doc,
  categories,
  onClose,
  onSuccess,
  onCategoriesChange,
}: EditModalProps) {
  /* --- form state, initialised from the document --- */
  const [categoryQuery, setCategoryQuery] = useState('')
  const [selectedCategory, setSelectedCategory] = useState('')
  const [showCategoryDropdown, setShowCategoryDropdown] = useState(false)
  const [description, setDescription] = useState('')
  const [expiryDate, setExpiryDate] = useState('')
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState('')

  const dropdownRef = useRef<HTMLDivElement>(null)

  /* --- sync form state when the document changes --- */
  const lastDocId = useRef<string | null>(null)
  if (doc && doc.id !== lastDocId.current) {
    lastDocId.current = doc.id
    setCategoryQuery(doc.document_type ?? '')
    setSelectedCategory(doc.document_type ?? '')
    setDescription(doc.description ?? '')
    setExpiryDate(doc.expiry_date ?? '')
    setError('')
    setSaving(false)
    setShowCategoryDropdown(false)
  }

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
          onCategoriesChange([...(categories ?? []), newCat])
        }
        setSelectedCategory(name)
        setCategoryQuery(name)
        setShowCategoryDropdown(false)
      } catch (err: unknown) {
        const status = (err as { response?: { status?: number } })?.response?.status
        if (status === 409) {
          setSelectedCategory(name)
          setCategoryQuery(name)
          setShowCategoryDropdown(false)
        } else {
          setError('Failed to create custom category')
        }
      }
    },
    [categories, onCategoriesChange],
  )

  /* --- form submission --- */
  const handleSubmit = useCallback(
    async (e: React.FormEvent) => {
      e.preventDefault()
      if (!doc) return

      const categoryName = selectedCategory.trim() || categoryQuery.trim()
      if (!categoryName) {
        setError('Please select or enter a document category')
        return
      }

      // Create custom category if needed
      const existingCat = (categories ?? []).find(
        (cat) => cat.name.toLowerCase() === categoryName.toLowerCase(),
      )
      if (!existingCat) {
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
            setError('Failed to create custom category')
            return
          }
        }
      }

      setSaving(true)
      setError('')

      try {
        const payload: Record<string, string | null> = {
          document_type: categoryName,
          description: description.trim() || null,
          expiry_date: expiryDate || null,
        }

        const res = await apiClient.put<ComplianceDocumentResponse>(
          `/api/v2/compliance-docs/${doc.id}`,
          payload,
        )

        onSuccess(res.data)
      } catch (err: unknown) {
        const detail =
          (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail ??
          'Failed to update document. Please try again.'
        setError(detail)
      } finally {
        setSaving(false)
      }
    },
    [doc, selectedCategory, categoryQuery, categories, description, expiryDate, onSuccess, onCategoriesChange],
  )

  /* --- close handler resets tracking --- */
  const handleClose = useCallback(() => {
    lastDocId.current = null
    onClose()
  }, [onClose])

  if (!doc) return null

  return (
    <Modal open={open} onClose={handleClose} title="Edit Document" className="max-w-lg">
      <form onSubmit={handleSubmit} noValidate>
        {/* Error banner */}
        {error && (
          <div className="mb-4 rounded-lg border border-red-200 bg-red-50 p-3" role="alert">
            <p className="text-sm text-red-700">{error}</p>
          </div>
        )}

        {/* File name (read-only) */}
        <div className="mb-4">
          <p className="text-sm text-gray-500">
            File: <span className="font-medium text-gray-900">{doc.file_name}</span>
          </p>
        </div>

        {/* Category searchable dropdown */}
        <div className="mb-4 relative" ref={dropdownRef}>
          <label htmlFor="edit-category" className="text-sm font-medium text-gray-700 mb-1 block">
            Category <span className="text-red-500">*</span>
          </label>
          <input
            id="edit-category"
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
          <label htmlFor="edit-description" className="text-sm font-medium text-gray-700 mb-1 block">
            Description
          </label>
          <textarea
            id="edit-description"
            rows={2}
            placeholder="Optional description…"
            value={description}
            onChange={(e) => setDescription(e.target.value)}
            className="w-full rounded-md border border-gray-300 px-3 py-2 text-gray-900 shadow-sm placeholder:text-gray-400 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-blue-500 focus-visible:ring-offset-2 focus-visible:border-blue-500"
          />
        </div>

        {/* Expiry date */}
        <div className="mb-4">
          <label htmlFor="edit-expiry" className="text-sm font-medium text-gray-700 mb-1 block">
            Expiry Date
          </label>
          <input
            id="edit-expiry"
            type="date"
            value={expiryDate}
            onChange={(e) => setExpiryDate(e.target.value)}
            className="h-[44px] w-full sm:w-64 rounded-md border border-gray-300 px-3 py-2 text-gray-900 shadow-sm focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-blue-500 focus-visible:ring-offset-2 focus-visible:border-blue-500"
          />
        </div>

        {/* Actions */}
        <div className="flex items-center justify-end gap-3 pt-2">
          <Button
            type="button"
            variant="secondary"
            size="sm"
            onClick={handleClose}
            disabled={saving}
            style={{ minWidth: '44px', minHeight: '44px' }}
          >
            Cancel
          </Button>
          <Button
            type="submit"
            size="sm"
            loading={saving}
            disabled={saving}
            style={{ minWidth: '44px', minHeight: '44px' }}
          >
            Save Changes
          </Button>
        </div>
      </form>
    </Modal>
  )
}
