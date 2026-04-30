import { useState, useCallback } from 'react'
import { useNavigate } from 'react-router-dom'
import { Page, List, ListInput, Button, Block } from 'konsta/react'
import type { CustomerCreate } from '@shared/types/customer'
import apiClient from '@/api/client'
import { KonstaNavbar } from '@/components/konsta/KonstaNavbar'

/* ------------------------------------------------------------------ */
/* Validation                                                         */
/* ------------------------------------------------------------------ */

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

/* ------------------------------------------------------------------ */
/* CustomerCreateScreen                                               */
/* ------------------------------------------------------------------ */

/**
 * Customer creation screen — Konsta UI single-page form.
 *
 * Fields: First Name (required), Last Name, Company Name, Email,
 * Phone, Mobile Phone, Work Phone, Address (textarea).
 *
 * Buttons: "Save" navigates to the new customer profile,
 * "Save & Add Another" resets the form for another entry.
 *
 * Validates First Name before submission.
 * Calls POST /api/v1/customers unchanged.
 *
 * Requirements: 22.1, 22.2, 22.3, 22.4, 22.5
 */
export default function CustomerCreateScreen() {
  const navigate = useNavigate()

  const emptyForm: CustomerCreate = {
    first_name: '',
    last_name: '',
    email: '',
    phone: '',
    mobile_phone: '',
    work_phone: '',
    company: '',
    address: '',
  }

  const [form, setForm] = useState<CustomerCreate>({ ...emptyForm })
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

  /** Build the API payload — only include non-empty optional fields */
  const buildPayload = useCallback((f: CustomerCreate): CustomerCreate => {
    const payload: CustomerCreate = {
      first_name: f.first_name.trim(),
    }
    if (f.last_name?.trim()) payload.last_name = f.last_name.trim()
    if (f.email?.trim()) payload.email = f.email.trim()
    if (f.phone?.trim()) payload.phone = f.phone.trim()
    if (f.mobile_phone?.trim()) payload.mobile_phone = f.mobile_phone.trim()
    if (f.work_phone?.trim()) payload.work_phone = f.work_phone.trim()
    if (f.company?.trim()) payload.company = f.company.trim()
    if (f.address?.trim()) payload.address = f.address.trim()
    return payload
  }, [])

  const handleSubmit = useCallback(
    async (addAnother: boolean) => {
      setApiError(null)

      const validationErrors = validateCustomerForm(form)
      if (Object.keys(validationErrors).length > 0) {
        setErrors(validationErrors)
        return
      }

      setIsSubmitting(true)

      try {
        const payload = buildPayload(form)
        const res = await apiClient.post<{ id: string }>('/api/v1/customers', payload)
        const newId = res.data?.id

        if (addAnother) {
          // Reset form for another entry
          setForm({ ...emptyForm })
          setErrors({})
          setApiError(null)
        } else {
          if (newId) {
            navigate(`/customers/${newId}`, { replace: true })
          } else {
            navigate('/customers', { replace: true })
          }
        }
      } catch (err: unknown) {
        const message =
          (err as { response?: { data?: { detail?: string } } })?.response?.data
            ?.detail ?? 'Failed to create customer'
        setApiError(message)
      } finally {
        setIsSubmitting(false)
      }
    },
    [form, navigate, buildPayload, emptyForm],
  )

  return (
    <Page>
      <KonstaNavbar title="New Customer" showBack />

      {/* ── API Error Banner ──────────────────────────────────────── */}
      {apiError && (
        <Block>
          <div
            role="alert"
            className="rounded-lg bg-red-50 p-3 text-sm text-red-700 dark:bg-red-900/30 dark:text-red-300"
          >
            {apiError}
          </div>
        </Block>
      )}

      {/* ── Form Fields ───────────────────────────────────────────── */}
      <List strongIos outlineIos dividersIos>
        <ListInput
          label="First Name"
          type="text"
          placeholder="First name"
          value={form.first_name}
          onChange={(e: React.ChangeEvent<HTMLInputElement>) =>
            updateField('first_name', e.target.value)
          }
          error={errors.first_name || undefined}
          inputClassName="min-h-[44px]"
          required
          autoFocus
        />

        <ListInput
          label="Last Name"
          type="text"
          placeholder="Last name"
          value={form.last_name ?? ''}
          onChange={(e: React.ChangeEvent<HTMLInputElement>) =>
            updateField('last_name', e.target.value)
          }
          inputClassName="min-h-[44px]"
        />

        <ListInput
          label="Company Name"
          type="text"
          placeholder="Company name"
          value={form.company ?? ''}
          onChange={(e: React.ChangeEvent<HTMLInputElement>) =>
            updateField('company', e.target.value)
          }
          inputClassName="min-h-[44px]"
        />

        <ListInput
          label="Email"
          type="email"
          placeholder="email@example.com"
          value={form.email ?? ''}
          onChange={(e: React.ChangeEvent<HTMLInputElement>) =>
            updateField('email', e.target.value)
          }
          error={errors.email || undefined}
          inputClassName="min-h-[44px]"
        />

        <ListInput
          label="Phone"
          type="tel"
          placeholder="Phone number"
          value={form.phone ?? ''}
          onChange={(e: React.ChangeEvent<HTMLInputElement>) =>
            updateField('phone', e.target.value)
          }
          inputClassName="min-h-[44px]"
        />

        <ListInput
          label="Mobile Phone"
          type="tel"
          placeholder="Mobile phone"
          value={form.mobile_phone ?? ''}
          onChange={(e: React.ChangeEvent<HTMLInputElement>) =>
            updateField('mobile_phone', e.target.value)
          }
          inputClassName="min-h-[44px]"
        />

        <ListInput
          label="Work Phone"
          type="tel"
          placeholder="Work phone"
          value={form.work_phone ?? ''}
          onChange={(e: React.ChangeEvent<HTMLInputElement>) =>
            updateField('work_phone', e.target.value)
          }
          inputClassName="min-h-[44px]"
        />

        <ListInput
          label="Address"
          type="textarea"
          placeholder="Street address"
          value={form.address ?? ''}
          onChange={(e: React.ChangeEvent<HTMLTextAreaElement>) =>
            updateField('address', e.target.value)
          }
          inputClassName="min-h-[88px]"
        />
      </List>

      {/* ── Action Buttons ────────────────────────────────────────── */}
      <Block className="flex flex-col gap-3">
        <Button
          large
          onClick={() => handleSubmit(false)}
          disabled={isSubmitting}
        >
          {isSubmitting ? 'Saving…' : 'Create Customer'}
        </Button>

        <Button
          large
          outline
          onClick={() => handleSubmit(true)}
          disabled={isSubmitting}
        >
          Save &amp; Add Another
        </Button>

        <Button
          large
          outline
          onClick={() => navigate(-1)}
        >
          Cancel
        </Button>
      </Block>
    </Page>
  )
}
