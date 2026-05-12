/**
 * DemoRequestForm — inline demo-request form that submits to the
 * existing public endpoint `POST /api/v1/public/demo-request` (see
 * `app/modules/landing/router.py`).
 *
 * This component does NOT expose a new unauthenticated mutation
 * endpoint (Requirement 1.7); it posts the same payload shape as
 * `DemoRequestModal` and inherits the same honeypot + rate-limit
 * protection on the server.
 */
import type { ComponentConfig } from '@puckeditor/core'
import { useState, type FormEvent } from 'react'
import axios from 'axios'

export interface DemoRequestFormProps {
  heading: string
  subheading: string
  submitLabel: string
  successMessage: string
  fallbackEmail: string
}

interface FormData {
  full_name: string
  business_name: string
  email: string
  phone: string
  message: string
  website: string // honeypot
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

function DemoRequestFormRenderer(props: DemoRequestFormProps) {
  const [form, setForm] = useState<FormData>(INITIAL_FORM)
  const [errors, setErrors] = useState<Partial<Record<keyof FormData, string>>>({})
  const [submitting, setSubmitting] = useState(false)
  const [submitState, setSubmitState] = useState<'idle' | 'success' | 'error'>('idle')
  const [errorMessage, setErrorMessage] = useState('')

  function handleChange(field: keyof FormData, value: string) {
    setForm((prev) => ({ ...prev, [field]: value }))
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
    if (!form.full_name.trim()) newErrors.full_name = 'Full name is required.'
    if (!form.business_name.trim()) newErrors.business_name = 'Business name is required.'
    if (!form.email.trim()) newErrors.email = 'Email is required.'
    else if (!EMAIL_REGEX.test(form.email.trim()))
      newErrors.email = 'Please enter a valid email address.'
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
          website: form.website,
        },
      )
      if (res.data?.success) {
        setSubmitState('success')
        setForm(INITIAL_FORM)
      } else {
        setSubmitState('error')
        setErrorMessage(
          res.data?.message ??
            `Something went wrong. Please email us directly at ${props.fallbackEmail}`,
        )
      }
    } catch (err) {
      setSubmitState('error')
      if (axios.isAxiosError(err) && err.response?.status === 429) {
        setErrorMessage('Too many requests. Please try again later.')
      } else {
        setErrorMessage(
          `Something went wrong. Please email us directly at ${props.fallbackEmail}`,
        )
      }
    } finally {
      setSubmitting(false)
    }
  }

  if (submitState === 'success') {
    return (
      <div className="mx-auto max-w-xl rounded-xl border border-green-200 bg-green-50 p-8 text-center">
        <div className="mx-auto mb-4 flex h-12 w-12 items-center justify-center rounded-full bg-green-100">
          <svg
            className="h-6 w-6 text-green-600"
            fill="none"
            viewBox="0 0 24 24"
            stroke="currentColor"
            aria-hidden="true"
          >
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M5 13l4 4L19 7" />
          </svg>
        </div>
        <h3 className="text-lg font-semibold text-gray-900">Demo Request Sent</h3>
        <p className="mt-2 text-sm text-gray-600">{props.successMessage}</p>
      </div>
    )
  }

  return (
    <form
      onSubmit={handleSubmit}
      noValidate
      className="mx-auto max-w-xl rounded-xl border border-gray-200 bg-white p-6 shadow-sm"
    >
      {props.heading ? (
        <h2 className="text-2xl font-bold text-gray-900">{props.heading}</h2>
      ) : null}
      {props.subheading ? (
        <p className="mt-2 text-sm text-gray-600">{props.subheading}</p>
      ) : null}

      {submitState === 'error' && errorMessage ? (
        <div
          className="mt-4 rounded-md border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700"
          role="alert"
        >
          {errorMessage}
        </div>
      ) : null}

      {/* Honeypot */}
      <div aria-hidden="true" style={{ position: 'absolute', left: '-9999px' }}>
        <label htmlFor="demo-form-website">Website</label>
        <input
          type="text"
          id="demo-form-website"
          name="website"
          tabIndex={-1}
          autoComplete="off"
          value={form.website}
          onChange={(e) => handleChange('website', e.target.value)}
        />
      </div>

      <div className="mt-5 space-y-4">
        <div>
          <label
            htmlFor="demo-form-full-name"
            className="mb-1 block text-sm font-medium text-gray-700"
          >
            Full Name <span className="text-red-500">*</span>
          </label>
          <input
            type="text"
            id="demo-form-full-name"
            value={form.full_name}
            onChange={(e) => handleChange('full_name', e.target.value)}
            className={`w-full rounded-md border px-3 py-2 text-sm shadow-sm transition-colors focus:outline-none focus:ring-2 focus:ring-blue-500 ${
              errors.full_name ? 'border-red-300 bg-red-50' : 'border-gray-300'
            }`}
            required
            maxLength={200}
          />
          {errors.full_name ? (
            <p className="mt-1 text-xs text-red-600">{errors.full_name}</p>
          ) : null}
        </div>

        <div>
          <label
            htmlFor="demo-form-business"
            className="mb-1 block text-sm font-medium text-gray-700"
          >
            Business Name <span className="text-red-500">*</span>
          </label>
          <input
            type="text"
            id="demo-form-business"
            value={form.business_name}
            onChange={(e) => handleChange('business_name', e.target.value)}
            className={`w-full rounded-md border px-3 py-2 text-sm shadow-sm transition-colors focus:outline-none focus:ring-2 focus:ring-blue-500 ${
              errors.business_name ? 'border-red-300 bg-red-50' : 'border-gray-300'
            }`}
            required
            maxLength={200}
          />
          {errors.business_name ? (
            <p className="mt-1 text-xs text-red-600">{errors.business_name}</p>
          ) : null}
        </div>

        <div>
          <label
            htmlFor="demo-form-email"
            className="mb-1 block text-sm font-medium text-gray-700"
          >
            Email <span className="text-red-500">*</span>
          </label>
          <input
            type="email"
            id="demo-form-email"
            value={form.email}
            onChange={(e) => handleChange('email', e.target.value)}
            className={`w-full rounded-md border px-3 py-2 text-sm shadow-sm transition-colors focus:outline-none focus:ring-2 focus:ring-blue-500 ${
              errors.email ? 'border-red-300 bg-red-50' : 'border-gray-300'
            }`}
            required
          />
          {errors.email ? (
            <p className="mt-1 text-xs text-red-600">{errors.email}</p>
          ) : null}
        </div>

        <div>
          <label
            htmlFor="demo-form-phone"
            className="mb-1 block text-sm font-medium text-gray-700"
          >
            Phone <span className="text-gray-400">(optional)</span>
          </label>
          <input
            type="tel"
            id="demo-form-phone"
            value={form.phone}
            onChange={(e) => handleChange('phone', e.target.value)}
            className="w-full rounded-md border border-gray-300 px-3 py-2 text-sm shadow-sm transition-colors focus:outline-none focus:ring-2 focus:ring-blue-500"
            maxLength={50}
          />
        </div>

        <div>
          <label
            htmlFor="demo-form-message"
            className="mb-1 block text-sm font-medium text-gray-700"
          >
            Message <span className="text-gray-400">(optional)</span>
          </label>
          <textarea
            id="demo-form-message"
            rows={3}
            value={form.message}
            onChange={(e) => handleChange('message', e.target.value)}
            className="w-full rounded-md border border-gray-300 px-3 py-2 text-sm shadow-sm transition-colors focus:outline-none focus:ring-2 focus:ring-blue-500"
            maxLength={2000}
          />
        </div>
      </div>

      <button
        type="submit"
        disabled={submitting}
        className="mt-6 inline-flex w-full items-center justify-center rounded-md bg-blue-600 px-4 py-2.5 text-sm font-semibold text-white transition-colors hover:bg-blue-500 disabled:opacity-50 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-blue-500 focus-visible:ring-offset-2"
      >
        {submitting ? 'Sending...' : props.submitLabel || 'Request Demo'}
      </button>
    </form>
  )
}

export const DemoRequestFormComponent: ComponentConfig<DemoRequestFormProps> = {
  label: 'Demo Request Form',
  fields: {
    heading: { type: 'text', label: 'Heading' },
    subheading: { type: 'textarea', label: 'Sub-heading' },
    submitLabel: { type: 'text', label: 'Submit button label' },
    successMessage: { type: 'textarea', label: 'Success message' },
    fallbackEmail: { type: 'text', label: 'Fallback email (shown on error)' },
  },
  defaultProps: {
    heading: 'Request a Free Demo',
    subheading:
      'Our team will set up a dedicated session to walk you through the app.',
    submitLabel: 'Request Demo',
    successMessage:
      'Thank you! Our team will be in touch within 24 hours to schedule your demo.',
    fallbackEmail: 'support@oraflows.co.nz',
  },
  render: (props) => <DemoRequestFormRenderer {...props} />,
}
