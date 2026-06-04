import { useState, useEffect, useRef, useCallback, type FormEvent } from 'react'
import apiClient from '@/api/client'
import { lookupCustomer } from './api'
import type {
  KioskFormData,
  KioskSuccessData,
  KioskVehicleEntry,
  AutoFillMatch,
  CheckInPayload,
  CheckInResponse,
} from './types'

/* ── Types ── */

interface KioskCheckInFormProps {
  formData: KioskFormData
  onFormDataChange: (data: KioskFormData) => void
  onSuccess: (data: KioskSuccessData) => void
  onError: () => void
  onBack: () => void
  vehicles?: KioskVehicleEntry[]
}

interface FieldErrors {
  first_name?: string
  last_name?: string
  phone?: string
  email?: string
  confirm_email?: string
}

/* ── Validation helpers (match backend rules) ── */

function stripPhoneFormatting(phone: string): string {
  return phone.replace(/[\s\-+()]/g, '')
}

export function validateKioskForm(data: KioskFormData, confirmEmail?: string): FieldErrors {
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
    } else if (confirmEmail !== undefined && data.email.trim().toLowerCase() !== confirmEmail.trim().toLowerCase()) {
      errors.confirm_email = 'Email addresses do not match'
    }
  }

  return errors
}

/* ── Input styling constants ── */

const INPUT_CLASS =
  'w-full rounded-ctl border border-border-strong px-4 py-3 text-text placeholder-muted-2 ' +
  'focus:border-accent focus:outline-none focus:ring-2 focus:ring-accent'

const INPUT_STYLE = { minHeight: '48px', fontSize: '18px' } as const

/* ── Component ── */

export function KioskCheckInForm({
  formData,
  onFormDataChange,
  onSuccess,
  onError,
  onBack,
  vehicles = [],
}: KioskCheckInFormProps) {
  const [errors, setErrors] = useState<FieldErrors>({})
  const [submitting, setSubmitting] = useState(false)
  const [confirmEmail, setConfirmEmail] = useState('')

  // Auto-fill state
  const [matches, setMatches] = useState<AutoFillMatch[]>([])
  const [showAutoFill, setShowAutoFill] = useState(false)
  const [existingCustomerId, setExistingCustomerId] = useState<string | null>(null)

  // Refs for debounce and abort
  const debounceTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null)
  const abortControllerRef = useRef<AbortController | null>(null)

  /** Perform debounced customer lookup when phone or email changes. */
  const triggerLookup = useCallback((phone: string, email: string) => {
    // Clear previous debounce timer
    if (debounceTimerRef.current) {
      clearTimeout(debounceTimerRef.current)
    }

    // Abort previous in-flight request
    if (abortControllerRef.current) {
      abortControllerRef.current.abort()
    }

    // Determine if we have enough data to look up
    const trimmedPhone = phone.trim()
    const trimmedEmail = email.trim()
    const phoneDigits = stripPhoneFormatting(trimmedPhone)
    const hasValidPhone = phoneDigits.length >= 7 && /^\d+$/.test(phoneDigits)
    const hasValidEmail = /^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(trimmedEmail)

    if (!hasValidPhone && !hasValidEmail) {
      setMatches([])
      setShowAutoFill(false)
      return
    }

    debounceTimerRef.current = setTimeout(async () => {
      const controller = new AbortController()
      abortControllerRef.current = controller

      try {
        const params: { phone?: string; email?: string } = {}
        if (hasValidPhone) params.phone = trimmedPhone
        if (hasValidEmail) params.email = trimmedEmail

        const result = await lookupCustomer(params, controller.signal)
        const items = result?.items ?? []

        if (!controller.signal.aborted) {
          setMatches(items)
          setShowAutoFill(items.length > 0)
        }
      } catch {
        // Silently ignore auto-fill lookup failures (form continues normally)
        if (!controller.signal.aborted) {
          setMatches([])
          setShowAutoFill(false)
        }
      }
    }, 500)
  }, [])

  /** Cleanup on unmount. */
  useEffect(() => {
    return () => {
      if (debounceTimerRef.current) {
        clearTimeout(debounceTimerRef.current)
      }
      if (abortControllerRef.current) {
        abortControllerRef.current.abort()
      }
    }
  }, [])

  /** Update a single field in the form data. */
  const updateField = (field: keyof KioskFormData, value: string) => {
    const newFormData = { ...formData, [field]: value }
    onFormDataChange(newFormData)

    // Clear field error on change
    if (errors[field as keyof FieldErrors]) {
      setErrors((prev) => {
        const next = { ...prev }
        delete next[field as keyof FieldErrors]
        return next
      })
    }

    // Clear existing_customer_id when user edits key fields after auto-fill
    if (existingCustomerId && (field === 'phone' || field === 'email')) {
      setExistingCustomerId(null)
    }

    // Trigger lookup on phone or email change
    if (field === 'phone' || field === 'email') {
      const phone = field === 'phone' ? value : formData.phone
      const email = field === 'email' ? value : formData.email
      triggerLookup(phone, email)
    }
  }

  /** Apply auto-fill from a matched customer record. */
  const applyAutoFill = (match: AutoFillMatch) => {
    const updated: KioskFormData = {
      first_name: match.first_name ?? formData.first_name,
      last_name: match.last_name ?? formData.last_name,
      phone: match.phone ?? formData.phone,
      email: match.email ?? formData.email,
    }
    onFormDataChange(updated)
    setExistingCustomerId(match.id)
    setShowAutoFill(false)
    setMatches([])
    setErrors({})
    // Pre-fill confirm email when auto-filling from existing customer
    setConfirmEmail(match.email ?? '')
  }

  /** Handle form submission. */
  const handleSubmit = async (e: FormEvent) => {
    e.preventDefault()

    // Client-side validation
    const validationErrors = validateKioskForm(formData, confirmEmail)
    if (Object.keys(validationErrors).length > 0) {
      setErrors(validationErrors)
      return
    }

    setSubmitting(true)
    setErrors({})

    try {
      const payload: CheckInPayload = {
        first_name: formData.first_name.trim(),
        last_name: formData.last_name.trim(),
        phone: formData.phone.trim(),
        email: formData.email.trim() || null,
        vehicles: vehicles.map((v) => ({
          global_vehicle_id: v.global_vehicle_id,
          odometer_km: v.odometer_km ?? null,
        })),
        existing_customer_id: existingCustomerId,
      }

      const res = await apiClient.post<CheckInResponse>('/kiosk/check-in', payload)

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
      className="w-full max-w-md space-y-5 rounded-card bg-card p-8 shadow-pop"
    >
      <h2 className="text-xl font-semibold text-text" style={{ fontSize: '22px' }}>
        Check In
      </h2>

      {/* Auto-fill suggestion banner */}
      {showAutoFill && matches.length === 1 && (
        <button
          type="button"
          onClick={() => applyAutoFill(matches[0])}
          className="w-full rounded-ctl border border-accent/30 bg-accent-soft px-4 py-3 text-left text-accent hover:bg-accent-soft/70 focus:outline-none focus:ring-2 focus:ring-accent"
          style={{ minHeight: '48px' }}
          aria-label="Auto-fill customer details"
        >
          <span className="font-medium">We found your details — tap to auto-fill</span>
          <span className="mt-1 block text-sm text-accent">
            {matches[0].first_name} {matches[0].last_name}
          </span>
        </button>
      )}

      {/* Multiple matches — selectable list */}
      {showAutoFill && matches.length > 1 && (
        <div className="rounded-ctl border border-accent/30 bg-accent-soft p-3">
          <p className="mb-2 text-sm font-medium text-accent">
            We found your details — tap to auto-fill
          </p>
          <ul className="space-y-2" role="list" aria-label="Customer matches">
            {matches.map((match) => (
              <li key={match.id}>
                <button
                  type="button"
                  onClick={() => applyAutoFill(match)}
                  className="w-full rounded-chip border border-accent/20 bg-card px-3 py-2 text-left text-text hover:bg-accent-soft focus:outline-none focus:ring-2 focus:ring-accent"
                  style={{ minHeight: '44px' }}
                >
                  <span className="font-medium">
                    {match.first_name} {match.last_name}
                  </span>
                  {match.phone && (
                    <span className="ml-2 text-sm text-muted">{match.phone}</span>
                  )}
                  {match.email && (
                    <span className="ml-2 text-sm text-muted">{match.email}</span>
                  )}
                </button>
              </li>
            ))}
          </ul>
        </div>
      )}

      {/* First Name */}
      <div>
        <label htmlFor="kiosk-first-name" className="mb-1 block text-sm font-medium text-text">
          First Name <span className="text-danger">*</span>
        </label>
        <input
          id="kiosk-first-name"
          type="text"
          required
          autoComplete="given-name"
          placeholder="First name"
          value={formData.first_name}
          onChange={(e) => updateField('first_name', e.target.value)}
          className={`${INPUT_CLASS} ${errors.first_name ? 'border-danger' : ''}`}
          style={INPUT_STYLE}
          aria-invalid={!!errors.first_name}
          aria-describedby={errors.first_name ? 'err-first-name' : undefined}
        />
        {errors.first_name && (
          <p id="err-first-name" className="mt-1 text-sm text-danger">{errors.first_name}</p>
        )}
      </div>

      {/* Last Name */}
      <div>
        <label htmlFor="kiosk-last-name" className="mb-1 block text-sm font-medium text-text">
          Last Name <span className="text-danger">*</span>
        </label>
        <input
          id="kiosk-last-name"
          type="text"
          required
          autoComplete="family-name"
          placeholder="Last name"
          value={formData.last_name}
          onChange={(e) => updateField('last_name', e.target.value)}
          className={`${INPUT_CLASS} ${errors.last_name ? 'border-danger' : ''}`}
          style={INPUT_STYLE}
          aria-invalid={!!errors.last_name}
          aria-describedby={errors.last_name ? 'err-last-name' : undefined}
        />
        {errors.last_name && (
          <p id="err-last-name" className="mt-1 text-sm text-danger">{errors.last_name}</p>
        )}
      </div>

      {/* Phone */}
      <div>
        <label htmlFor="kiosk-phone" className="mb-1 block text-sm font-medium text-text">
          Phone <span className="text-danger">*</span>
        </label>
        <input
          id="kiosk-phone"
          type="tel"
          required
          autoComplete="tel"
          placeholder="Phone number"
          value={formData.phone}
          onChange={(e) => updateField('phone', e.target.value)}
          className={`${INPUT_CLASS} ${errors.phone ? 'border-danger' : ''}`}
          style={INPUT_STYLE}
          aria-invalid={!!errors.phone}
          aria-describedby={errors.phone ? 'err-phone' : undefined}
        />
        {errors.phone && (
          <p id="err-phone" className="mt-1 text-sm text-danger">{errors.phone}</p>
        )}
      </div>

      {/* Email (optional) */}
      <div>
        <label htmlFor="kiosk-email" className="mb-1 block text-sm font-medium text-text">
          Email
        </label>
        <input
          id="kiosk-email"
          type="email"
          autoComplete="email"
          placeholder="Email (optional)"
          value={formData.email}
          onChange={(e) => updateField('email', e.target.value)}
          className={`${INPUT_CLASS} ${errors.email ? 'border-danger' : ''}`}
          style={INPUT_STYLE}
          aria-invalid={!!errors.email}
          aria-describedby={errors.email ? 'err-email' : undefined}
        />
        {errors.email && (
          <p id="err-email" className="mt-1 text-sm text-danger">{errors.email}</p>
        )}
      </div>

      {/* Confirm Email — only shown when email is entered */}
      {formData.email.trim() && (
        <div>
          <label htmlFor="kiosk-confirm-email" className="mb-1 block text-sm font-medium text-text">
            Confirm Email <span className="text-danger">*</span>
          </label>
          <input
            id="kiosk-confirm-email"
            type="email"
            autoComplete="email"
            placeholder="Re-enter your email"
            value={confirmEmail}
            onChange={(e) => {
              setConfirmEmail(e.target.value)
              if (errors.confirm_email) setErrors((prev) => ({ ...prev, confirm_email: undefined }))
            }}
            className={`${INPUT_CLASS} ${
              confirmEmail.trim() && formData.email.trim().toLowerCase() !== confirmEmail.trim().toLowerCase()
                ? 'border-danger'
                : confirmEmail.trim() && formData.email.trim().toLowerCase() === confirmEmail.trim().toLowerCase()
                  ? 'border-ok'
                  : ''
            }`}
            style={INPUT_STYLE}
            aria-invalid={!!(confirmEmail.trim() && formData.email.trim().toLowerCase() !== confirmEmail.trim().toLowerCase())}
            aria-describedby="confirm-email-feedback"
          />
          {/* Real-time mismatch feedback */}
          {confirmEmail.trim() && formData.email.trim().toLowerCase() !== confirmEmail.trim().toLowerCase() && (
            <p id="confirm-email-feedback" className="mt-1 text-sm text-danger font-medium">
              Emails do not match
            </p>
          )}
          {/* Match confirmation */}
          {confirmEmail.trim() && formData.email.trim().toLowerCase() === confirmEmail.trim().toLowerCase() && (
            <p id="confirm-email-feedback" className="mt-1 text-sm text-ok font-medium">
              ✓ Emails match
            </p>
          )}
          {/* Submit-time validation error (fallback) */}
          {errors.confirm_email && !confirmEmail.trim() && (
            <p className="mt-1 text-sm text-danger">{errors.confirm_email}</p>
          )}
        </div>
      )}

      {/* Buttons */}
      <div className="flex gap-3 pt-2">
        <button
          type="button"
          onClick={onBack}
          disabled={submitting}
          className="min-h-[48px] rounded-ctl border border-border-strong px-6 py-3 font-medium text-text hover:bg-canvas focus:outline-none focus:ring-2 focus:ring-border-strong focus:ring-offset-2 disabled:opacity-50"
          style={{ fontSize: '18px' }}
        >
          Back
        </button>
        <button
          type="submit"
          disabled={submitting}
          className="flex min-h-[48px] flex-1 items-center justify-center rounded-ctl bg-accent px-6 py-3 font-medium text-white shadow-card hover:bg-accent-press focus:outline-none focus:ring-2 focus:ring-accent focus:ring-offset-2 disabled:opacity-50"
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
