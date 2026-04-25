import { useState, useCallback } from 'react'
import { useNavigate } from 'react-router-dom'
import { MobileForm, MobileInput, MobileSelect, MobileButton } from '@/components/ui'
import { CameraCapture } from '@/components/common/CameraCapture'
import type { CameraPhoto } from '@/hooks/useCamera'
import apiClient from '@/api/client'

/* ------------------------------------------------------------------ */
/* Document type options                                               */
/* ------------------------------------------------------------------ */

const DOCUMENT_TYPES = [
  { value: 'license', label: 'License' },
  { value: 'insurance', label: 'Insurance' },
  { value: 'certification', label: 'Certification' },
  { value: 'permit', label: 'Permit' },
  { value: 'registration', label: 'Registration' },
  { value: 'safety', label: 'Safety Certificate' },
  { value: 'training', label: 'Training Record' },
  { value: 'other', label: 'Other' },
]

/**
 * Compliance upload screen — camera capture or file selection, form for
 * document type, description, expiry date, upload to backend.
 * Uses CameraCapture component.
 *
 * Requirements: 27.2, 27.3
 */
export default function ComplianceUploadScreen() {
  const navigate = useNavigate()

  const [name, setName] = useState('')
  const [documentType, setDocumentType] = useState('')
  const [description, setDescription] = useState('')
  const [expiryDate, setExpiryDate] = useState('')
  const [photo, setPhoto] = useState<CameraPhoto | null>(null)
  const [isSubmitting, setIsSubmitting] = useState(false)
  const [errors, setErrors] = useState<Record<string, string>>({})

  const validate = useCallback((): boolean => {
    const newErrors: Record<string, string> = {}
    if (!name.trim()) newErrors.name = 'Document name is required'
    if (!documentType) newErrors.documentType = 'Select a document type'
    setErrors(newErrors)
    return Object.keys(newErrors).length === 0
  }, [name, documentType])

  const handleSubmit = useCallback(async () => {
    if (!validate()) return

    setIsSubmitting(true)
    try {
      const body: Record<string, unknown> = {
        name: name.trim(),
        document_type: documentType,
        description: description.trim() || null,
        expiry_date: expiryDate || null,
      }

      if (photo) {
        body.file_data = photo.dataUrl
      }

      await apiClient.post('/api/v2/compliance-docs', body)
      navigate('/compliance', { replace: true })
    } catch {
      setErrors({ submit: 'Failed to upload document' })
    } finally {
      setIsSubmitting(false)
    }
  }, [validate, name, documentType, description, expiryDate, photo, navigate])

  return (
    <div className="flex flex-col gap-4 p-4">
      {/* Back button */}
      <button
        type="button"
        onClick={() => navigate(-1)}
        className="flex min-h-[44px] items-center gap-1 self-start text-blue-600 dark:text-blue-400"
        aria-label="Back"
      >
        <svg
          className="h-5 w-5"
          viewBox="0 0 24 24"
          fill="none"
          stroke="currentColor"
          strokeWidth="2"
          strokeLinecap="round"
          strokeLinejoin="round"
          aria-hidden="true"
        >
          <path d="m15 18-6-6 6-6" />
        </svg>
        Back
      </button>

      <h1 className="text-xl font-semibold text-gray-900 dark:text-gray-100">
        Upload Document
      </h1>

      <MobileForm onSubmit={handleSubmit}>
        <MobileInput
          label="Document Name"
          value={name}
          onChange={(e) => {
            setName(e.target.value)
            setErrors((prev) => ({ ...prev, name: '' }))
          }}
          error={errors.name}
          placeholder="e.g. Electrical License 2025"
          required
        />

        <MobileSelect
          label="Document Type"
          value={documentType}
          onChange={(e) => {
            setDocumentType(e.target.value)
            setErrors((prev) => ({ ...prev, documentType: '' }))
          }}
          options={DOCUMENT_TYPES}
          placeholder="Select type"
          error={errors.documentType}
          required
        />

        <MobileInput
          label="Description"
          value={description}
          onChange={(e) => setDescription(e.target.value)}
          placeholder="Optional description…"
        />

        <MobileInput
          label="Expiry Date"
          type="date"
          value={expiryDate}
          onChange={(e) => setExpiryDate(e.target.value)}
          helperText="Leave blank if no expiry"
        />

        {/* Document photo/scan */}
        <CameraCapture
          label="Document Photo"
          onCapture={(captured) => setPhoto(captured)}
        />

        {photo && (
          <div className="flex items-center gap-2">
            <img
              src={photo.dataUrl}
              alt="Document"
              className="h-16 w-16 rounded-lg object-cover"
            />
            <MobileButton
              variant="ghost"
              size="sm"
              onClick={() => setPhoto(null)}
            >
              Remove
            </MobileButton>
          </div>
        )}

        {errors.submit && (
          <p className="text-sm text-red-600 dark:text-red-400" role="alert">
            {errors.submit}
          </p>
        )}

        <MobileButton
          variant="primary"
          fullWidth
          type="submit"
          isLoading={isSubmitting}
        >
          Upload Document
        </MobileButton>
      </MobileForm>
    </div>
  )
}
