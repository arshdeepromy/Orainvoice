import { useState, FormEvent } from 'react'
import axios from 'axios'
import { Modal } from '@/components/ui/Modal'
import { usePlatformBranding } from '@/contexts/PlatformBrandingContext'

interface DemoRequestModalProps {
  open: boolean
  onClose: () => void
}

interface FormData {
  full_name: string
  business_name: string
  email: string
  phone: string
  message: string
  website: string // honeypot field — hidden from real users
}

const INITIAL_FORM: FormData = {
  full_name: '',
  business_name: '',
  email: '',
  phone: '',
  message: '',
  website: '',
}

const EMAIL_REGEX = /^[^\s@]+@[^\s@]+\.[^\s@]+$/

export function DemoRequestModal({ open, onClose }: DemoRequestModalProps) {
  const { branding } = usePlatformBranding()
  const fallbackEmail = branding.support_email || 'support@oraflows.co.nz'
  const [form, setForm] = useState<FormData>(INITIAL_FORM)
  const [errors, setErrors] = useState<Partial<Record<keyof FormData, string>>>({})
  const [submitting, setSubmitting] = useState(false)
  const [submitState, setSubmitState] = useState<'idle' | 'success' | 'error'>('idle')
  const [errorMessage, setErrorMessage] = useState('')

  function handleChange(field: keyof FormData, value: string) {
    setForm((prev) => ({ ...prev, [field]: value }))
    // Clear field error on change
    if (errors[field]) {
      setErrors((prev) => {
        const next = { ...prev }
        delete next[field]
        return next
      })
    }
  }

  function validate(): boolean {
    const newErrors: Partial<Record<keyof FormData, string>> = {}

    if (!form.full_name.trim()) {
      newErrors.full_name = 'Full name is required.'
    }
    if (!form.business_name.trim()) {
      newErrors.business_name = 'Business name is required.'
    }
    if (!form.email.trim()) {
      newErrors.email = 'Email is required.'
    } else if (!EMAIL_REGEX.test(form.email.trim())) {
      newErrors.email = 'Please enter a valid email address.'
    }

    setErrors(newErrors)
    return Object.keys(newErrors).length === 0
  }

  async function handleSubmit(e: FormEvent) {
    e.preventDefault()
    if (!validate()) return

    setSubmitting(true)
    setSubmitState('idle')
    setErrorMessage('')

    try {
      const res = await axios.post<{ success?: boolean; message?: string }>(
        '/api/v1/public/demo-request',
        {
          full_name: form.full_name.trim(),
          business_name: form.business_name.trim(),
          email: form.email.trim(),
          phone: form.phone.trim() || null,
          message: form.message.trim() || null,
          website: form.website, // honeypot — should be empty for real users
        },
      )

      if (res.data?.success) {
        setSubmitState('success')
        setForm(INITIAL_FORM)
      } else {
        setSubmitState('error')
        setErrorMessage(
          res.data?.message ??
            `Something went wrong. Please email us directly at ${fallbackEmail}`,
        )
      }
    } catch (err) {
      setSubmitState('error')

      if (axios.isAxiosError(err) && err.response?.status === 429) {
        setErrorMessage('Too many requests. Please try again later.')
      } else {
        setErrorMessage(
          `Something went wrong. Please email us directly at ${fallbackEmail}`,
        )
      }
    } finally {
      setSubmitting(false)
    }
  }

  function handleClose() {
    // Reset state when closing
    setForm(INITIAL_FORM)
    setErrors({})
    setSubmitState('idle')
    setErrorMessage('')
    setSubmitting(false)
    onClose()
  }

  return (
    <Modal open={open} onClose={handleClose} title="Request a Free Demo">
      {submitState === 'success' ? (
        <div className="py-4 text-center">
          <div className="mx-auto mb-4 flex h-12 w-12 items-center justify-center rounded-full bg-green-100">
            <svg
              className="h-6 w-6 text-green-600"
              fill="none"
              viewBox="0 0 24 24"
              stroke="currentColor"
              aria-hidden="true"
            >
              <path
                strokeLinecap="round"
                strokeLinejoin="round"
                strokeWidth={2}
                d="M5 13l4 4L19 7"
              />
            </svg>
          </div>
          <h3 className="text-lg font-semibold text-gray-900">Demo Request Sent</h3>
          <p className="mt-2 text-sm text-gray-600">
            Thank you! Our team will be in touch within 24 hours to schedule your demo.
          </p>
          <button
            type="button"
            onClick={handleClose}
            className="mt-6 rounded-md bg-blue-600 px-4 py-2 text-sm font-medium text-white transition-colors hover:bg-blue-500 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-blue-500 focus-visible:ring-offset-2"
          >
            Close
          </button>
        </div>
      ) : (
        <form onSubmit={handleSubmit} noValidate>
          {/* Description */}
          <p className="mb-5 text-sm text-gray-600">
            Request a free demo — someone from the Oraflows team will set up a dedicated session to
            walk you through the app. Feel free to share feedback on features you'd like, and we can
            work around that at no additional cost.
          </p>

          {/* Error banner */}
          {submitState === 'error' && errorMessage && (
            <div
              className="mb-4 rounded-md border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700"
              role="alert"
            >
              {errorMessage}
            </div>
          )}

          {/* Honeypot field — hidden from real users via CSS positioning */}
          <div
            aria-hidden="true"
            style={{ position: 'absolute', left: '-9999px' }}
          >
            <label htmlFor="demo-website">Website</label>
            <input
              type="text"
              id="demo-website"
              name="website"
              tabIndex={-1}
              autoComplete="off"
              value={form.website}
              onChange={(e) => handleChange('website', e.target.value)}
            />
          </div>

          {/* Full Name */}
          <div className="mb-4">
            <label htmlFor="demo-full-name" className="mb-1 block text-sm font-medium text-gray-700">
              Full Name <span className="text-red-500">*</span>
            </label>
            <input
              type="text"
              id="demo-full-name"
              value={form.full_name}
              onChange={(e) => handleChange('full_name', e.target.value)}
              className={`w-full rounded-md border px-3 py-2 text-sm shadow-sm transition-colors focus:outline-none focus:ring-2 focus:ring-blue-500 ${
                errors.full_name ? 'border-red-300 bg-red-50' : 'border-gray-300'
              }`}
              placeholder="John Smith"
              required
              maxLength={200}
            />
            {errors.full_name && (
              <p className="mt-1 text-xs text-red-600">{errors.full_name}</p>
            )}
          </div>

          {/* Business Name */}
          <div className="mb-4">
            <label htmlFor="demo-business-name" className="mb-1 block text-sm font-medium text-gray-700">
              Business Name <span className="text-red-500">*</span>
            </label>
            <input
              type="text"
              id="demo-business-name"
              value={form.business_name}
              onChange={(e) => handleChange('business_name', e.target.value)}
              className={`w-full rounded-md border px-3 py-2 text-sm shadow-sm transition-colors focus:outline-none focus:ring-2 focus:ring-blue-500 ${
                errors.business_name ? 'border-red-300 bg-red-50' : 'border-gray-300'
              }`}
              placeholder="Smith Auto Workshop"
              required
              maxLength={200}
            />
            {errors.business_name && (
              <p className="mt-1 text-xs text-red-600">{errors.business_name}</p>
            )}
          </div>

          {/* Email */}
          <div className="mb-4">
            <label htmlFor="demo-email" className="mb-1 block text-sm font-medium text-gray-700">
              Email Address <span className="text-red-500">*</span>
            </label>
            <input
              type="email"
              id="demo-email"
              value={form.email}
              onChange={(e) => handleChange('email', e.target.value)}
              className={`w-full rounded-md border px-3 py-2 text-sm shadow-sm transition-colors focus:outline-none focus:ring-2 focus:ring-blue-500 ${
                errors.email ? 'border-red-300 bg-red-50' : 'border-gray-300'
              }`}
              placeholder="john@smithauto.co.nz"
              required
            />
            {errors.email && (
              <p className="mt-1 text-xs text-red-600">{errors.email}</p>
            )}
          </div>

          {/* Phone (optional) */}
          <div className="mb-4">
            <label htmlFor="demo-phone" className="mb-1 block text-sm font-medium text-gray-700">
              Phone Number <span className="text-gray-400">(optional)</span>
            </label>
            <input
              type="tel"
              id="demo-phone"
              value={form.phone}
              onChange={(e) => handleChange('phone', e.target.value)}
              className="w-full rounded-md border border-gray-300 px-3 py-2 text-sm shadow-sm transition-colors focus:outline-none focus:ring-2 focus:ring-blue-500"
              placeholder="021 123 4567"
              maxLength={50}
            />
          </div>

          {/* Message (optional) */}
          <div className="mb-5">
            <label htmlFor="demo-message" className="mb-1 block text-sm font-medium text-gray-700">
              Message / Additional Notes <span className="text-gray-400">(optional)</span>
            </label>
            <textarea
              id="demo-message"
              value={form.message}
              onChange={(e) => handleChange('message', e.target.value)}
              className="w-full rounded-md border border-gray-300 px-3 py-2 text-sm shadow-sm transition-colors focus:outline-none focus:ring-2 focus:ring-blue-500"
              placeholder="Tell us about your business or any features you're interested in..."
              rows={3}
              maxLength={2000}
            />
          </div>

          {/* Actions */}
          <div className="flex items-center justify-end gap-3 border-t border-gray-200 pt-4">
            <button
              type="button"
              onClick={handleClose}
              className="rounded-md px-4 py-2 text-sm font-medium text-gray-700 transition-colors hover:bg-gray-100 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-blue-500 focus-visible:ring-offset-2"
              disabled={submitting}
            >
              Cancel
            </button>
            <button
              type="submit"
              disabled={submitting}
              className="rounded-md bg-blue-600 px-4 py-2 text-sm font-medium text-white transition-colors hover:bg-blue-500 disabled:opacity-50 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-blue-500 focus-visible:ring-offset-2"
            >
              {submitting ? 'Sending...' : 'Submit Request'}
            </button>
          </div>
        </form>
      )}
    </Modal>
  )
}
