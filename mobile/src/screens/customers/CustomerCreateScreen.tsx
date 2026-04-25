import { useState, useCallback } from 'react'
import { useNavigate } from 'react-router-dom'
import type { CustomerCreate } from '@shared/types/customer'
import apiClient from '@/api/client'
import { MobileForm, MobileInput, MobileButton } from '@/components/ui'

/**
 * Validate the customer creation form.
 * Only first_name is required — all other fields are optional.
 */
export function validateCustomerForm(form: CustomerCreate): Record<string, string> {
  const errors: Record<string, string> = {}

  if (!form.first_name.trim()) {
    errors.first_name = 'First name is required'
  }

  if (form.email && !/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(form.email)) {
    errors.email = 'Invalid email address'
  }

  return errors
}

/**
 * Customer creation screen — form with first name required,
 * all other fields optional. POSTs to /api/v1/customers and
 * navigates to the new customer's profile on success.
 *
 * Requirements: 7.5
 */
export default function CustomerCreateScreen() {
  const navigate = useNavigate()

  const [form, setForm] = useState<CustomerCreate>({
    first_name: '',
    last_name: '',
    email: '',
    phone: '',
    company: '',
    address: '',
  })

  const [errors, setErrors] = useState<Record<string, string>>({})
  const [isSubmitting, setIsSubmitting] = useState(false)
  const [apiError, setApiError] = useState<string | null>(null)

  const updateField = useCallback(
    (field: keyof CustomerCreate, value: string) => {
      setForm((prev) => ({ ...prev, [field]: value }))
      // Clear field error on change
      setErrors((prev) => {
        if (!prev[field]) return prev
        const next = { ...prev }
        delete next[field]
        return next
      })
    },
    [],
  )

  const handleSubmit = useCallback(async () => {
    setApiError(null)

    const validationErrors = validateCustomerForm(form)
    if (Object.keys(validationErrors).length > 0) {
      setErrors(validationErrors)
      return
    }

    setIsSubmitting(true)

    try {
      // Build payload — only include non-empty optional fields
      const payload: CustomerCreate = {
        first_name: form.first_name.trim(),
      }
      if (form.last_name?.trim()) payload.last_name = form.last_name.trim()
      if (form.email?.trim()) payload.email = form.email.trim()
      if (form.phone?.trim()) payload.phone = form.phone.trim()
      if (form.company?.trim()) payload.company = form.company.trim()
      if (form.address?.trim()) payload.address = form.address.trim()

      const res = await apiClient.post<{ id: string }>('/api/v1/customers', payload)
      const newId = res.data?.id
      if (newId) {
        navigate(`/customers/${newId}`, { replace: true })
      } else {
        navigate('/customers', { replace: true })
      }
    } catch (err: unknown) {
      const message =
        (err as { response?: { data?: { detail?: string } } })?.response?.data
          ?.detail ?? 'Failed to create customer'
      setApiError(message)
    } finally {
      setIsSubmitting(false)
    }
  }, [form, navigate])

  return (
    <div className="flex flex-col p-4">
      <h1 className="mb-4 text-xl font-semibold text-gray-900 dark:text-gray-100">
        New Customer
      </h1>

      {apiError && (
        <div
          role="alert"
          className="mb-4 rounded-lg bg-red-50 p-3 text-sm text-red-700 dark:bg-red-900/30 dark:text-red-300"
        >
          {apiError}
        </div>
      )}

      <MobileForm onSubmit={handleSubmit}>
        <MobileInput
          label="First Name"
          required
          value={form.first_name}
          onChange={(e) => updateField('first_name', e.target.value)}
          error={errors.first_name}
          placeholder="First name"
          autoFocus
        />

        <MobileInput
          label="Last Name"
          value={form.last_name ?? ''}
          onChange={(e) => updateField('last_name', e.target.value)}
          placeholder="Last name"
        />

        <MobileInput
          label="Email"
          type="email"
          value={form.email ?? ''}
          onChange={(e) => updateField('email', e.target.value)}
          error={errors.email}
          placeholder="email@example.com"
        />

        <MobileInput
          label="Phone"
          type="tel"
          value={form.phone ?? ''}
          onChange={(e) => updateField('phone', e.target.value)}
          placeholder="Phone number"
        />

        <MobileInput
          label="Company"
          value={form.company ?? ''}
          onChange={(e) => updateField('company', e.target.value)}
          placeholder="Company name"
        />

        <MobileInput
          label="Address"
          value={form.address ?? ''}
          onChange={(e) => updateField('address', e.target.value)}
          placeholder="Street address"
        />

        <div className="mt-2 flex gap-3">
          <MobileButton
            variant="secondary"
            type="button"
            fullWidth
            onClick={() => navigate(-1)}
          >
            Cancel
          </MobileButton>
          <MobileButton
            variant="primary"
            type="submit"
            fullWidth
            isLoading={isSubmitting}
          >
            Create Customer
          </MobileButton>
        </div>
      </MobileForm>
    </div>
  )
}
