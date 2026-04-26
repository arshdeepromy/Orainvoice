import { useState, useCallback, useEffect, useRef } from 'react'
import { useParams, useNavigate } from 'react-router-dom'
import apiClient from '@/api/client'
import {
  MobileForm,
  MobileInput,
  MobileSelect,
  MobileButton,
  MobileSpinner,
} from '@/components/ui'

/* ------------------------------------------------------------------ */
/* Types                                                              */
/* ------------------------------------------------------------------ */

interface CustomerData {
  id: string
  customer_type: string
  salutation?: string | null
  first_name: string
  last_name: string
  company_name?: string | null
  display_name?: string | null
  email?: string | null
  phone?: string | null
  mobile_phone?: string | null
  currency: string
  payment_terms: string
}

interface EditFormState {
  customer_type: string
  salutation: string
  first_name: string
  last_name: string
  company_name: string
  display_name: string
  email: string
  phone: string
  mobile_phone: string
  currency: string
  payment_terms: string
}

/* ------------------------------------------------------------------ */
/* Constants                                                          */
/* ------------------------------------------------------------------ */

const SALUTATION_OPTIONS = [
  { value: '', label: 'None' },
  { value: 'Mr', label: 'Mr' },
  { value: 'Mrs', label: 'Mrs' },
  { value: 'Ms', label: 'Ms' },
  { value: 'Miss', label: 'Miss' },
  { value: 'Dr', label: 'Dr' },
  { value: 'Prof', label: 'Prof' },
]

const PAYMENT_TERMS_OPTIONS = [
  { value: 'due_on_receipt', label: 'Due on Receipt' },
  { value: 'net_7', label: 'Net 7' },
  { value: 'net_15', label: 'Net 15' },
  { value: 'net_30', label: 'Net 30' },
  { value: 'net_45', label: 'Net 45' },
  { value: 'net_60', label: 'Net 60' },
  { value: 'net_90', label: 'Net 90' },
]

/* ------------------------------------------------------------------ */
/* CustomerEditScreen                                                 */
/* ------------------------------------------------------------------ */

/**
 * Customer edit screen — Zoho Invoice-style edit form with
 * customer type toggle, salutation, name fields, contact info,
 * and payment terms.
 */
export default function CustomerEditScreen() {
  const { id } = useParams<{ id: string }>()
  const navigate = useNavigate()
  const abortRef = useRef<AbortController | null>(null)

  const [isLoadingCustomer, setIsLoadingCustomer] = useState(true)
  const [loadError, setLoadError] = useState<string | null>(null)
  const [isSaving, setIsSaving] = useState(false)
  const [apiError, setApiError] = useState<string | null>(null)
  const [errors, setErrors] = useState<Record<string, string>>({})

  const [form, setForm] = useState<EditFormState>({
    customer_type: 'individual',
    salutation: '',
    first_name: '',
    last_name: '',
    company_name: '',
    display_name: '',
    email: '',
    phone: '',
    mobile_phone: '',
    currency: 'NZD',
    payment_terms: 'due_on_receipt',
  })

  // Track original values to send only changed fields
  const [original, setOriginal] = useState<EditFormState | null>(null)

  // Load customer data
  useEffect(() => {
    if (!id) return

    abortRef.current?.abort()
    const controller = new AbortController()
    abortRef.current = controller

    setIsLoadingCustomer(true)
    setLoadError(null)

    apiClient
      .get<CustomerData>(`/api/v1/customers/${id}`, { signal: controller.signal })
      .then((res) => {
        const c = res.data
        if (!c) {
          setLoadError('Customer not found')
          return
        }
        const state: EditFormState = {
          customer_type: c.customer_type ?? 'individual',
          salutation: c.salutation ?? '',
          first_name: c.first_name ?? '',
          last_name: c.last_name ?? '',
          company_name: c.company_name ?? '',
          display_name: c.display_name ?? '',
          email: c.email ?? '',
          phone: c.phone ?? '',
          mobile_phone: c.mobile_phone ?? '',
          currency: c.currency ?? 'NZD',
          payment_terms: c.payment_terms ?? 'due_on_receipt',
        }
        setForm(state)
        setOriginal(state)
      })
      .catch((err: unknown) => {
        if ((err as { name?: string })?.name !== 'CanceledError') {
          setLoadError('Failed to load customer')
        }
      })
      .finally(() => {
        setIsLoadingCustomer(false)
      })

    return () => controller.abort()
  }, [id])

  const updateField = useCallback(
    (field: keyof EditFormState, value: string) => {
      setForm((prev) => ({ ...prev, [field]: value }))
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

    // Validate
    const validationErrors: Record<string, string> = {}
    if (!form.first_name.trim()) {
      validationErrors.first_name = 'First name is required'
    }
    if (form.email && !/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(form.email)) {
      validationErrors.email = 'Invalid email address'
    }
    if (Object.keys(validationErrors).length > 0) {
      setErrors(validationErrors)
      return
    }

    // Build payload with only changed fields
    const payload: Record<string, string> = {}
    if (!original) return

    for (const key of Object.keys(form) as (keyof EditFormState)[]) {
      const currentVal = form[key].trim()
      const originalVal = original[key].trim()
      if (currentVal !== originalVal) {
        payload[key] = currentVal
      }
    }

    if (Object.keys(payload).length === 0) {
      // Nothing changed — just go back
      navigate(-1)
      return
    }

    setIsSaving(true)
    try {
      await apiClient.put(`/api/v1/customers/${id}`, payload)
      navigate(`/customers/${id}`, { replace: true })
    } catch (err: unknown) {
      const message =
        (err as { response?: { data?: { detail?: string } } })?.response?.data
          ?.detail ?? 'Failed to save changes'
      setApiError(message)
    } finally {
      setIsSaving(false)
    }
  }, [form, original, id, navigate])

  if (isLoadingCustomer) {
    return (
      <div className="flex flex-1 items-center justify-center p-8">
        <MobileSpinner size="lg" />
      </div>
    )
  }

  if (loadError) {
    return (
      <div className="flex flex-col items-center gap-4 p-8">
        <p className="text-gray-500 dark:text-gray-400">{loadError}</p>
        <MobileButton variant="secondary" onClick={() => navigate(-1)}>
          Go Back
        </MobileButton>
      </div>
    )
  }

  const isBusiness = form.customer_type === 'business'

  return (
    <div className="flex min-h-screen flex-col bg-white dark:bg-gray-900">
      {/* Header */}
      <div className="sticky top-0 z-20 flex items-center justify-between border-b border-gray-200 bg-white px-2 py-2 dark:border-gray-700 dark:bg-gray-800">
        <button
          type="button"
          onClick={() => navigate(-1)}
          className="flex min-h-[44px] items-center justify-center rounded-lg px-3 text-sm font-medium text-gray-600 active:bg-gray-100 dark:text-gray-300 dark:active:bg-gray-700"
        >
          Cancel
        </button>
        <h1 className="text-base font-semibold text-gray-900 dark:text-gray-100">
          Edit Customer
        </h1>
        <button
          type="button"
          onClick={handleSubmit}
          disabled={isSaving}
          className="flex min-h-[44px] items-center justify-center rounded-lg px-3 text-sm font-medium text-blue-600 active:bg-blue-50 disabled:text-blue-300 dark:text-blue-400 dark:active:bg-gray-700 dark:disabled:text-blue-800"
        >
          {isSaving ? 'Saving…' : 'Save'}
        </button>
      </div>

      {/* Form */}
      <div className="flex-1 overflow-y-auto p-4">
        {apiError && (
          <div
            role="alert"
            className="mb-4 rounded-lg bg-red-50 p-3 text-sm text-red-700 dark:bg-red-900/30 dark:text-red-300"
          >
            {apiError}
          </div>
        )}

        <MobileForm onSubmit={handleSubmit}>
          {/* Customer Type */}
          <div className="flex flex-col gap-1">
            <label className="text-sm font-medium text-gray-700 dark:text-gray-300">
              Customer Type
            </label>
            <div className="flex gap-2">
              <button
                type="button"
                onClick={() => updateField('customer_type', 'business')}
                className={`flex-1 min-h-[44px] rounded-lg border px-4 py-2 text-sm font-medium transition-colors ${
                  isBusiness
                    ? 'border-blue-600 bg-blue-50 text-blue-600 dark:border-blue-400 dark:bg-blue-900/30 dark:text-blue-400'
                    : 'border-gray-300 text-gray-600 dark:border-gray-600 dark:text-gray-400'
                }`}
              >
                Business
              </button>
              <button
                type="button"
                onClick={() => updateField('customer_type', 'individual')}
                className={`flex-1 min-h-[44px] rounded-lg border px-4 py-2 text-sm font-medium transition-colors ${
                  !isBusiness
                    ? 'border-blue-600 bg-blue-50 text-blue-600 dark:border-blue-400 dark:bg-blue-900/30 dark:text-blue-400'
                    : 'border-gray-300 text-gray-600 dark:border-gray-600 dark:text-gray-400'
                }`}
              >
                Individual
              </button>
            </div>
          </div>

          {/* Salutation */}
          <MobileSelect
            label="Salutation"
            options={SALUTATION_OPTIONS}
            value={form.salutation}
            onChange={(e) => updateField('salutation', e.target.value)}
          />

          {/* First Name */}
          <MobileInput
            label="First Name"
            required
            value={form.first_name}
            onChange={(e) => updateField('first_name', e.target.value)}
            error={errors.first_name}
            placeholder="First name"
          />

          {/* Last Name */}
          <MobileInput
            label="Last Name"
            value={form.last_name}
            onChange={(e) => updateField('last_name', e.target.value)}
            placeholder="Last name"
          />

          {/* Company Name — shown for business type */}
          {isBusiness && (
            <MobileInput
              label="Company Name"
              value={form.company_name}
              onChange={(e) => updateField('company_name', e.target.value)}
              placeholder="Company name"
            />
          )}

          {/* Display Name */}
          <MobileInput
            label="Display Name"
            value={form.display_name}
            onChange={(e) => updateField('display_name', e.target.value)}
            placeholder="Display name for invoices"
            helperText="Used on invoices and statements"
          />

          {/* Email */}
          <MobileInput
            label="Email"
            type="email"
            value={form.email}
            onChange={(e) => updateField('email', e.target.value)}
            error={errors.email}
            placeholder="email@example.com"
          />

          {/* Phone */}
          <MobileInput
            label="Phone"
            type="tel"
            value={form.phone}
            onChange={(e) => updateField('phone', e.target.value)}
            placeholder="Phone number"
          />

          {/* Mobile */}
          <MobileInput
            label="Mobile"
            type="tel"
            value={form.mobile_phone}
            onChange={(e) => updateField('mobile_phone', e.target.value)}
            placeholder="Mobile number"
          />

          {/* Other Details section header */}
          <div className="mt-4 border-t border-gray-200 pt-4 dark:border-gray-700">
            <h2 className="text-sm font-semibold uppercase text-gray-400 dark:text-gray-500">
              Other Details
            </h2>
          </div>

          {/* Currency */}
          <MobileInput
            label="Currency"
            value={form.currency}
            disabled
            onChange={() => {}}
            helperText="Currency cannot be changed"
          />

          {/* Payment Terms */}
          <MobileSelect
            label="Payment Terms"
            options={PAYMENT_TERMS_OPTIONS}
            value={form.payment_terms}
            onChange={(e) => updateField('payment_terms', e.target.value)}
          />

          {/* Bottom spacer for safe area */}
          <div className="h-8" />
        </MobileForm>
      </div>
    </div>
  )
}
