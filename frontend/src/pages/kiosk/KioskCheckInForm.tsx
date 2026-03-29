import { useState, type FormEvent } from 'react'
import apiClient from '@/api/client'
import type { KioskFormData, KioskSuccessData } from './KioskPage'

/* ── Types ── */

interface KioskCheckInFormProps {
  formData: KioskFormData
  onFormDataChange: (data: KioskFormData) => void
  onSuccess: (data: KioskSuccessData) => void
  onError: () => void
  onBack: () => void
}

interface FieldErrors {
  first_name?: string
  last_name?: string
  phone?: string
  email?: string
}

interface CheckInResponse {
  customer_first_name: string
  is_new_customer: boolean
  vehicle_linked: boolean
}

/* ── Validation helpers (match backend rules) ── */

function stripPhoneFormatting(phone: string): string {
  return phone.replace(/[\s\-+()]/g, '')
}

export function validateKioskForm(data: KioskFormData): FieldErrors {
  const errors: FieldErrors = {}

  // first_name: 1-100 chars, required
  if (!data.first_name.trim()) {
    errors.first_name = 'First name is required'
  } else if (data.first_name.length > 100) {
    errors.first_name = 'First name must be 100 characters or less'
  }

  // last_name: 1-100 chars, required
  if (!data.last_name.trim()) {
    errors.last_name = 'Last name is required'
  } else if (data.last_name.length > 100) {
    errors.last_name = 'Last name must be 100 characters or less'
  }

  // phone: ≥7 digits after stripping formatting
  const digits = stripPhoneFormatting(data.phone)
  if (!digits) {
    errors.phone = 'Phone number is required'
  } else if (!/^\d+$/.test(digits) || digits.length < 7) {
    errors.phone = 'Phone must contain at least 7 digits'
  }

  // email: optional, must match standard format if provided
  if (data.email.trim()) {
    if (!/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(data.email.trim())) {
      errors.email = 'Please enter a valid email address'
    }
  }

  return errors
}

/* ── Input styling constants ── */

const INPUT_CLASS =
  'w-full rounded-lg border border-gray-300 px-4 py-3 text-gray-900 placeholder-gray-400 ' +
  'focus:border-blue-500 focus:outline-none focus:ring-2 focus:ring-blue-500'

const INPUT_STYLE = { minHeight: '48px', fontSize: '18px' } as const

/* ── Component ── */

export function KioskCheckInForm({
  formData,
  onFormDataChange,
  onSuccess,
  onError,
  onBack,
}: KioskCheckInFormProps) {
  const [errors, setErrors] = useState<FieldErrors>({})
  const [submitting, setSubmitting] = useState(false)

  /** Update a single field in the form data. */
  const updateField = (field: keyof KioskFormData, value: string) => {
    onFormDataChange({ ...formData, [field]: value })
    // Clear field error on change
    if (errors[field as keyof FieldErrors]) {
      setErrors((prev) => {
        const next = { ...prev }
        delete next[field as keyof FieldErrors]
        return next
      })
    }
  }

  /** Handle form submission. */
  const handleSubmit = async (e: FormEvent) => {
    e.preventDefault()

    // Client-side validation
    const validationErrors = validateKioskForm(formData)
    if (Object.keys(validationErrors).length > 0) {
      setErrors(validationErrors)
      return
    }

    setSubmitting(true)
    setErrors({})

    try {
      const res = await apiClient.post<CheckInResponse>('/kiosk/check-in', {
        first_name: formData.first_name.trim(),
        last_name: formData.last_name.trim(),
        phone: formData.phone.trim(),
        email: formData.email.trim() || null,
        vehicle_rego: formData.vehicle_rego.trim() || null,
      })

      onSuccess({
        customer_first_name: res.data?.customer_first_name ?? formData.first_name.trim(),
      })
    } catch {
      onError()
    } finally {
      setSubmitting(false)
    }
  }

  return (
    <form
      onSubmit={handleSubmit}
      noValidate
      className="w-full max-w-md space-y-5 rounded-xl bg-white p-8 shadow-lg"
    >
      <h2 className="text-xl font-semibold text-gray-900" style={{ fontSize: '22px' }}>
        Check In
      </h2>

      {/* First Name */}
      <div>
        <label htmlFor="kiosk-first-name" className="mb-1 block text-sm font-medium text-gray-700">
          First Name <span className="text-red-500">*</span>
        </label>
        <input
          id="kiosk-first-name"
          type="text"
          required
          autoComplete="given-name"
          placeholder="First name"
          value={formData.first_name}
          onChange={(e) => updateField('first_name', e.target.value)}
          className={`${INPUT_CLASS} ${errors.first_name ? 'border-red-500' : ''}`}
          style={INPUT_STYLE}
          aria-invalid={!!errors.first_name}
          aria-describedby={errors.first_name ? 'err-first-name' : undefined}
        />
        {errors.first_name && (
          <p id="err-first-name" className="mt-1 text-sm text-red-600">{errors.first_name}</p>
        )}
      </div>

      {/* Last Name */}
      <div>
        <label htmlFor="kiosk-last-name" className="mb-1 block text-sm font-medium text-gray-700">
          Last Name <span className="text-red-500">*</span>
        </label>
        <input
          id="kiosk-last-name"
          type="text"
          required
          autoComplete="family-name"
          placeholder="Last name"
          value={formData.last_name}
          onChange={(e) => updateField('last_name', e.target.value)}
          className={`${INPUT_CLASS} ${errors.last_name ? 'border-red-500' : ''}`}
          style={INPUT_STYLE}
          aria-invalid={!!errors.last_name}
          aria-describedby={errors.last_name ? 'err-last-name' : undefined}
        />
        {errors.last_name && (
          <p id="err-last-name" className="mt-1 text-sm text-red-600">{errors.last_name}</p>
        )}
      </div>

      {/* Phone */}
      <div>
        <label htmlFor="kiosk-phone" className="mb-1 block text-sm font-medium text-gray-700">
          Phone <span className="text-red-500">*</span>
        </label>
        <input
          id="kiosk-phone"
          type="tel"
          required
          autoComplete="tel"
          placeholder="Phone number"
          value={formData.phone}
          onChange={(e) => updateField('phone', e.target.value)}
          className={`${INPUT_CLASS} ${errors.phone ? 'border-red-500' : ''}`}
          style={INPUT_STYLE}
          aria-invalid={!!errors.phone}
          aria-describedby={errors.phone ? 'err-phone' : undefined}
        />
        {errors.phone && (
          <p id="err-phone" className="mt-1 text-sm text-red-600">{errors.phone}</p>
        )}
      </div>

      {/* Email (optional) */}
      <div>
        <label htmlFor="kiosk-email" className="mb-1 block text-sm font-medium text-gray-700">
          Email
        </label>
        <input
          id="kiosk-email"
          type="email"
          autoComplete="email"
          placeholder="Email (optional)"
          value={formData.email}
          onChange={(e) => updateField('email', e.target.value)}
          className={`${INPUT_CLASS} ${errors.email ? 'border-red-500' : ''}`}
          style={INPUT_STYLE}
          aria-invalid={!!errors.email}
          aria-describedby={errors.email ? 'err-email' : undefined}
        />
        {errors.email && (
          <p id="err-email" className="mt-1 text-sm text-red-600">{errors.email}</p>
        )}
      </div>

      {/* Vehicle Rego (optional) */}
      <div>
        <label htmlFor="kiosk-rego" className="mb-1 block text-sm font-medium text-gray-700">
          Vehicle Registration
        </label>
        <input
          id="kiosk-rego"
          type="text"
          autoComplete="off"
          placeholder="Rego (optional)"
          value={formData.vehicle_rego}
          onChange={(e) => updateField('vehicle_rego', e.target.value)}
          className={INPUT_CLASS}
          style={INPUT_STYLE}
        />
      </div>

      {/* Buttons */}
      <div className="flex gap-3 pt-2">
        <button
          type="button"
          onClick={onBack}
          disabled={submitting}
          className="min-h-[48px] rounded-lg border border-gray-300 px-6 py-3 font-medium text-gray-700 hover:bg-gray-50 focus:outline-none focus:ring-2 focus:ring-gray-400 focus:ring-offset-2 disabled:opacity-50"
          style={{ fontSize: '18px' }}
        >
          Back
        </button>
        <button
          type="submit"
          disabled={submitting}
          className="flex min-h-[48px] flex-1 items-center justify-center rounded-lg bg-blue-600 px-6 py-3 font-medium text-white shadow-sm hover:bg-blue-700 focus:outline-none focus:ring-2 focus:ring-blue-500 focus:ring-offset-2 disabled:opacity-50"
          style={{ fontSize: '18px' }}
        >
          {submitting ? (
            <>
              <svg
                className="mr-2 h-5 w-5 animate-spin text-white"
                xmlns="http://www.w3.org/2000/svg"
                fill="none"
                viewBox="0 0 24 24"
                aria-hidden="true"
              >
                <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
                <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z" />
              </svg>
              Submitting…
            </>
          ) : (
            'Submit'
          )}
        </button>
      </div>
    </form>
  )
}

export default KioskCheckInForm
