import { useState, useCallback } from 'react'
import { useNavigate } from 'react-router-dom'
import type { Customer } from '@shared/types/customer'
import { MobileButton, MobileInput, MobileFormField } from '@/components/ui'
import { CustomerPicker } from '@/components/common/CustomerPicker'
import apiClient from '@/api/client'

/* ------------------------------------------------------------------ */
/* Validation (exported for testing)                                   */
/* ------------------------------------------------------------------ */

export interface JobCardFormErrors {
  customer?: string
  description?: string
}

export function validateJobCardForm(form: {
  customer_id: string
  description: string
}): JobCardFormErrors {
  const errors: JobCardFormErrors = {}

  if (!form.customer_id) {
    errors.customer = 'Customer is required'
  }
  if (!form.description.trim()) {
    errors.description = 'Service description is required'
  }

  return errors
}

/**
 * Job card creation form — customer selection, vehicle selection,
 * service description fields.
 *
 * Requirements: 11.3
 */
export default function JobCardCreateScreen() {
  const navigate = useNavigate()

  // Form state
  const [customerId, setCustomerId] = useState('')
  const [customerName, setCustomerName] = useState('')
  const [vehicleRegistration, setVehicleRegistration] = useState('')
  const [description, setDescription] = useState('')

  // UI state
  const [showCustomerPicker, setShowCustomerPicker] = useState(false)
  const [errors, setErrors] = useState<JobCardFormErrors>({})
  const [apiError, setApiError] = useState<string | null>(null)
  const [isSubmitting, setIsSubmitting] = useState(false)

  const handleCustomerSelect = useCallback((customer: Customer) => {
    setCustomerId(customer.id)
    const name = [customer.first_name, customer.last_name].filter(Boolean).join(' ')
    setCustomerName(name || 'Unnamed')
    setErrors((prev) => ({ ...prev, customer: undefined }))
  }, [])

  const handleSubmit = async () => {
    const formErrors = validateJobCardForm({
      customer_id: customerId,
      description,
    })

    if (Object.keys(formErrors).length > 0) {
      setErrors(formErrors)
      return
    }

    setIsSubmitting(true)
    setApiError(null)

    try {
      const res = await apiClient.post('/api/v1/job-cards', {
        customer_id: customerId,
        vehicle_registration: vehicleRegistration.trim() || undefined,
        description: description.trim(),
      })
      const newId = res.data?.id ?? ''
      navigate(`/job-cards/${newId}`, { replace: true })
    } catch (err: unknown) {
      const detail =
        (err as { response?: { data?: { detail?: string } } })?.response?.data
          ?.detail ?? 'Failed to create job card'
      setApiError(detail)
    } finally {
      setIsSubmitting(false)
    }
  }

  return (
    <div className="flex flex-col gap-4 p-4">
      {/* Header */}
      <div className="flex items-center justify-between">
        <h1 className="text-xl font-semibold text-gray-900 dark:text-gray-100">
          New Job Card
        </h1>
        <MobileButton
          variant="ghost"
          size="sm"
          onClick={() => navigate(-1)}
        >
          Cancel
        </MobileButton>
      </div>

      {/* API error */}
      {apiError && (
        <div
          className="rounded-lg bg-red-50 p-3 text-sm text-red-700 dark:bg-red-900/30 dark:text-red-300"
          role="alert"
        >
          {apiError}
        </div>
      )}

      {/* Customer selection */}
      <MobileFormField label="Customer" required error={errors.customer}>
        <button
          type="button"
          onClick={() => setShowCustomerPicker(true)}
          className="flex min-h-[44px] w-full items-center rounded-lg border border-gray-300 px-3 py-2 text-left text-base dark:border-gray-600 dark:bg-gray-800"
        >
          {customerName ? (
            <span className="text-gray-900 dark:text-gray-100">{customerName}</span>
          ) : (
            <span className="text-gray-400 dark:text-gray-500">Select customer…</span>
          )}
        </button>
      </MobileFormField>

      {/* Vehicle registration */}
      <MobileInput
        label="Vehicle Registration"
        value={vehicleRegistration}
        onChange={(e) => setVehicleRegistration(e.target.value)}
        placeholder="e.g. ABC123"
      />

      {/* Service description */}
      <MobileFormField label="Service Description" required error={errors.description}>
        <textarea
          value={description}
          onChange={(e) => {
            setDescription(e.target.value)
            setErrors((prev) => ({ ...prev, description: undefined }))
          }}
          placeholder="Describe the service required…"
          rows={4}
          className="min-h-[44px] w-full rounded-lg border border-gray-300 px-3 py-2 text-base text-gray-900 placeholder-gray-400 focus:outline-none focus:ring-2 focus:ring-blue-500 dark:border-gray-600 dark:bg-gray-800 dark:text-gray-100 dark:placeholder-gray-500"
        />
      </MobileFormField>

      {/* Submit */}
      <MobileButton
        variant="primary"
        fullWidth
        onClick={handleSubmit}
        isLoading={isSubmitting}
      >
        Create Job Card
      </MobileButton>

      {/* Customer picker */}
      <CustomerPicker
        isOpen={showCustomerPicker}
        onClose={() => setShowCustomerPicker(false)}
        onSelect={handleCustomerSelect}
      />
    </div>
  )
}
