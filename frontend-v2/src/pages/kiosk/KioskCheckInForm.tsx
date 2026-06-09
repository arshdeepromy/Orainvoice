import { useState, useEffect, useRef, useCallback, type FormEvent } from 'react'
import apiClient from '@/api/client'
import { lookupCustomer } from './api'
import type {
  KioskFormData,
  KioskSuccessData,
  KioskVehicleEntry,
  KioskReminderConsentBlock,
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
  /** Reminder-consent block captured on the consent step; included in the
   *  POST body only when non-null (master toggle on + ≥1 ticked entry). */
  reminderConsent?: KioskReminderConsentBlock | null
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

  // email: required, valid format, and confirmed
  if (!data.email.trim()) {
    errors.email = 'Email is required'
  } else if (!/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(data.email.trim())) {
    errors.email = 'Please enter a valid email address'
  } else if (confirmEmail !== undefined && data.email.trim().toLowerCase() !== confirmEmail.trim().toLowerCase()) {
    errors.confirm_email = 'Email addresses do not match'
  }

  return errors
}

/* ── Component ──
 * Design: the "FORM" screen in OraInvoice_Handoff/app/Kiosk.html. All behaviour
 * — debounced customer auto-fill, field validation, confirm-email matching, and
 * the /kiosk/check-in submission — is preserved exactly; only the markup is
 * restyled to the design's `.k-card` / `.k-field` / `.k-label` language. */

export function KioskCheckInForm({
  formData,
  onFormDataChange,
  onSuccess,
  onError,
  onBack,
  vehicles = [],
  reminderConsent = null,
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
        // Only include the consent block when the customer actually opted in
        // (master toggle on + ≥1 ticked entry). Omitted otherwise (Req 1.12).
        ...(reminderConsent ? { reminder_consent: reminderConsent } : {}),
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

  const emailMismatch =
    confirmEmail.trim().length > 0 &&
    formData.email.trim().toLowerCase() !== confirmEmail.trim().toLowerCase()
  const emailMatch =
    confirmEmail.trim().length > 0 &&
    formData.email.trim().toLowerCase() === confirmEmail.trim().toLowerCase()

  return (
    <>
      <button type="button" className="k-back" onClick={onBack} disabled={submitting}>
        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={2}>
          <path d="M15 18l-6-6 6-6" />
        </svg>
        Back
      </button>

      <form onSubmit={handleSubmit} noValidate className="k-card">
        <h1 style={{ fontSize: '28px' }}>Your details</h1>
        <p className="lead">So we can keep you updated on your service.</p>

        <div style={{ marginTop: '24px', display: 'flex', flexDirection: 'column', gap: '16px' }}>
          {/* Auto-fill suggestion — single match */}
          {showAutoFill && matches.length === 1 && (
            <button
              type="button"
              onClick={() => applyAutoFill(matches[0])}
              className="k-field"
              style={{ height: 'auto', padding: '12px 16px', textAlign: 'left', background: 'var(--accent-soft)', borderColor: 'var(--accent)', color: 'var(--accent)', cursor: 'pointer' }}
              aria-label="Auto-fill customer details"
            >
              <span style={{ fontWeight: 600 }}>We found your details — tap to auto-fill</span>
              <span style={{ display: 'block', fontSize: '14px', marginTop: '2px' }}>
                {matches[0].first_name} {matches[0].last_name}
              </span>
            </button>
          )}

          {/* Auto-fill suggestion — multiple matches */}
          {showAutoFill && matches.length > 1 && (
            <div style={{ background: 'var(--accent-soft)', borderRadius: '14px', padding: '12px' }}>
              <p style={{ fontSize: '14px', fontWeight: 600, color: 'var(--accent)', marginBottom: '8px' }}>
                We found your details — tap to auto-fill
              </p>
              <ul style={{ listStyle: 'none', margin: 0, padding: 0, display: 'flex', flexDirection: 'column', gap: '8px' }} aria-label="Customer matches">
                {matches.map((match) => (
                  <li key={match.id}>
                    <button
                      type="button"
                      onClick={() => applyAutoFill(match)}
                      className="k-field"
                      style={{ height: 'auto', padding: '10px 14px', textAlign: 'left', cursor: 'pointer' }}
                    >
                      <span style={{ fontWeight: 600 }}>
                        {match.first_name} {match.last_name}
                      </span>
                      {match.phone && <span style={{ marginLeft: '8px', fontSize: '14px', color: 'var(--muted)' }}>{match.phone}</span>}
                      {match.email && <span style={{ marginLeft: '8px', fontSize: '14px', color: 'var(--muted)' }}>{match.email}</span>}
                    </button>
                  </li>
                ))}
              </ul>
            </div>
          )}

          {/* First + last name */}
          <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '12px' }}>
            <div>
              <label className="k-label" htmlFor="kiosk-first-name">First name</label>
              <input
                id="kiosk-first-name"
                className={`k-field${errors.first_name ? ' error' : ''}`}
                type="text"
                autoComplete="given-name"
                placeholder="First name"
                value={formData.first_name}
                onChange={(e) => updateField('first_name', e.target.value)}
                aria-invalid={!!errors.first_name}
                aria-describedby={errors.first_name ? 'err-first-name' : undefined}
              />
              {errors.first_name && (
                <p id="err-first-name" style={{ marginTop: '6px', fontSize: '13px', color: 'var(--danger)' }}>{errors.first_name}</p>
              )}
            </div>
            <div>
              <label className="k-label" htmlFor="kiosk-last-name">Last name</label>
              <input
                id="kiosk-last-name"
                className={`k-field${errors.last_name ? ' error' : ''}`}
                type="text"
                autoComplete="family-name"
                placeholder="Last name"
                value={formData.last_name}
                onChange={(e) => updateField('last_name', e.target.value)}
                aria-invalid={!!errors.last_name}
                aria-describedby={errors.last_name ? 'err-last-name' : undefined}
              />
              {errors.last_name && (
                <p id="err-last-name" style={{ marginTop: '6px', fontSize: '13px', color: 'var(--danger)' }}>{errors.last_name}</p>
              )}
            </div>
          </div>

          {/* Mobile */}
          <div>
            <label className="k-label" htmlFor="kiosk-phone">Mobile</label>
            <input
              id="kiosk-phone"
              className={`k-field mono${errors.phone ? ' error' : ''}`}
              type="tel"
              autoComplete="tel"
              placeholder="021 000 0000"
              value={formData.phone}
              onChange={(e) => updateField('phone', e.target.value)}
              aria-invalid={!!errors.phone}
              aria-describedby={errors.phone ? 'err-phone' : undefined}
            />
            {errors.phone && (
              <p id="err-phone" style={{ marginTop: '6px', fontSize: '13px', color: 'var(--danger)' }}>{errors.phone}</p>
            )}
          </div>

          {/* Email (optional) */}
          <div>
            <label className="k-label" htmlFor="kiosk-email">Email</label>
            <input
              id="kiosk-email"
              className={`k-field${errors.email ? ' error' : ''}`}
              type="email"
              autoComplete="email"
              placeholder="you@email.co.nz"
              value={formData.email}
              onChange={(e) => updateField('email', e.target.value)}
              aria-invalid={!!errors.email}
              aria-describedby={errors.email ? 'err-email' : undefined}
            />
            {errors.email && (
              <p id="err-email" style={{ marginTop: '6px', fontSize: '13px', color: 'var(--danger)' }}>{errors.email}</p>
            )}
          </div>

          {/* Confirm email — only when an email is entered */}
          {formData.email.trim() && (
            <div>
              <label className="k-label" htmlFor="kiosk-confirm-email">Confirm email</label>
              <input
                id="kiosk-confirm-email"
                className={`k-field${emailMismatch ? ' error' : ''}`}
                style={emailMatch ? { borderColor: 'var(--ok)' } : undefined}
                type="email"
                autoComplete="email"
                placeholder="Re-enter your email"
                value={confirmEmail}
                onChange={(e) => {
                  setConfirmEmail(e.target.value)
                  if (errors.confirm_email) setErrors((prev) => ({ ...prev, confirm_email: undefined }))
                }}
                aria-invalid={emailMismatch}
                aria-describedby="confirm-email-feedback"
              />
              {emailMismatch && (
                <p id="confirm-email-feedback" style={{ marginTop: '6px', fontSize: '13px', fontWeight: 600, color: 'var(--danger)' }}>
                  Emails do not match
                </p>
              )}
              {emailMatch && (
                <p id="confirm-email-feedback" style={{ marginTop: '6px', fontSize: '13px', fontWeight: 600, color: 'var(--ok)' }}>
                  ✓ Emails match
                </p>
              )}
              {errors.confirm_email && !confirmEmail.trim() && (
                <p style={{ marginTop: '6px', fontSize: '13px', color: 'var(--danger)' }}>{errors.confirm_email}</p>
              )}
            </div>
          )}
        </div>

        <button type="submit" className="btn-kiosk primary" style={{ marginTop: '24px' }} disabled={submitting}>
          {submitting ? (
            'Submitting…'
          ) : (
            <>
              Complete check-in
              <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={2.4}>
                <path d="M20 6L9 17l-5-5" />
              </svg>
            </>
          )}
        </button>

        <div className="step-dots">
          <i />
          <i />
          <i className="on" />
        </div>
      </form>
    </>
  )
}

export default KioskCheckInForm
