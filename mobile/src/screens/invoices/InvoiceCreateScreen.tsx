import { useState, useCallback, useEffect, useRef } from 'react'
import { useNavigate, useParams, useSearchParams } from 'react-router-dom'
import {
  Page,
  Block,
  BlockTitle,
  List,
  ListInput,
  Card,
  Button,
  Chip,
  Progressbar,
} from 'konsta/react'
import type { Customer } from '@shared/types/customer'
import type { Vehicle } from '@shared/types/vehicle'
import type { InventoryItem } from '@shared/types/inventory'
import type { InvoiceLineItemCreate } from '@shared/types/invoice'
import { KonstaNavbar } from '@/components/konsta/KonstaNavbar'
import HapticButton from '@/components/konsta/HapticButton'
import { CustomerPicker } from '@/components/common/CustomerPicker'
import { ItemPicker } from '@/components/common/ItemPicker'
import { useModules } from '@/contexts/ModuleContext'
import { useCamera } from '@/hooks/useCamera'
import apiClient from '@/api/client'

/* ------------------------------------------------------------------ */
/* Constants                                                           */
/* ------------------------------------------------------------------ */

const TOTAL_STEPS = 6
const MAX_ATTACHMENTS = 5
const MAX_FILE_SIZE_MB = 20
const MAX_FILE_SIZE_BYTES = MAX_FILE_SIZE_MB * 1024 * 1024

const PAYMENT_TERMS_OPTIONS = [
  { value: '', label: 'Select payment terms…' },
  { value: 'due_on_receipt', label: 'Due on Receipt' },
  { value: 'net_7', label: 'Net 7' },
  { value: 'net_15', label: 'Net 15' },
  { value: 'net_30', label: 'Net 30' },
  { value: 'net_60', label: 'Net 60' },
  { value: 'net_90', label: 'Net 90' },
  { value: 'custom', label: 'Custom' },
]

const TAX_MODE_OPTIONS = [
  { value: 'exclusive', label: 'Tax Exclusive' },
  { value: 'inclusive', label: 'Tax Inclusive' },
  { value: 'exempt', label: 'Tax Exempt' },
]

/* ------------------------------------------------------------------ */
/* Currency formatting — matches project convention (Requirement 56.4) */
/* ------------------------------------------------------------------ */

function formatNZD(value: number | null | undefined): string {
  return `NZD${Number(value ?? 0).toLocaleString('en-NZ', {
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  })}`
}

/* ------------------------------------------------------------------ */
/* Validation (exported for testing)                                   */
/* ------------------------------------------------------------------ */

export interface InvoiceFormErrors {
  customer?: string
  due_date?: string
  line_items?: string
}

export function validateInvoiceForm(form: {
  customer_id: string
  due_date: string
  line_items: InvoiceLineItemCreate[]
}): InvoiceFormErrors {
  const errors: InvoiceFormErrors = {}

  if (!form.customer_id) {
    errors.customer = 'Customer is required'
  }
  if (!form.due_date) {
    errors.due_date = 'Due date is required'
  }
  if (form.line_items.length === 0) {
    errors.line_items = 'At least one line item is required'
  }

  return errors
}

/* ------------------------------------------------------------------ */
/* Line item calculation — exact existing logic (Requirement 20.8)     */
/* ------------------------------------------------------------------ */

export interface LineItemTotals {
  subtotal: number
  discountAmount: number
  taxAmount: number
  shipping: number
  adjustment: number
  total: number
}

/**
 * Calculate invoice totals from line items, discount, shipping, and adjustment.
 *
 * - subtotal = sum of line amounts
 * - discountAmount = percentage of subtotal or fixed amount
 * - taxAmount handles inclusive/exclusive/exempt per line
 * - total = (subtotal - discountAmount) + taxAmount + shipping + adjustment
 *
 * **Validates: Requirements 20.8, 56.1**
 */
export function calculateInvoiceTotals(
  items: ReadonlyArray<{
    quantity: number
    unit_price: number
    tax_rate: number
    tax_mode?: string
    discount_percent?: number
  }>,
  discountType: 'percentage' | 'fixed',
  discountValue: number,
  shippingCharges: number,
  adjustment: number,
): LineItemTotals {
  let subtotal = 0
  let taxAmount = 0

  for (const item of items) {
    const qty = item.quantity ?? 0
    const price = item.unit_price ?? 0
    const rate = item.tax_rate ?? 0
    const mode = item.tax_mode ?? 'exclusive'
    const lineDiscount = item.discount_percent ?? 0

    let lineAmount = qty * price
    // Apply per-line discount
    if (lineDiscount > 0) {
      lineAmount = lineAmount * (1 - lineDiscount / 100)
    }

    if (mode === 'inclusive') {
      // Price includes tax — extract tax from the amount
      const taxPortion = lineAmount - lineAmount / (1 + rate)
      taxAmount += Math.round(taxPortion * 100) / 100
      subtotal += Math.round((lineAmount - taxPortion) * 100) / 100
    } else if (mode === 'exempt') {
      // No tax
      subtotal += Math.round(lineAmount * 100) / 100
    } else {
      // exclusive (default)
      subtotal += Math.round(lineAmount * 100) / 100
      taxAmount += Math.round(lineAmount * rate * 100) / 100
    }
  }

  const discountAmount =
    discountType === 'percentage'
      ? Math.round(subtotal * (discountValue / 100) * 100) / 100
      : Math.round((discountValue ?? 0) * 100) / 100

  const total =
    Math.round(
      (subtotal - discountAmount + taxAmount + shippingCharges + adjustment) *
        100,
    ) / 100

  return {
    subtotal: Math.round(subtotal * 100) / 100,
    discountAmount,
    taxAmount: Math.round(taxAmount * 100) / 100,
    shipping: Math.round(shippingCharges * 100) / 100,
    adjustment: Math.round(adjustment * 100) / 100,
    total,
  }
}

/* ------------------------------------------------------------------ */
/* Attachment type                                                     */
/* ------------------------------------------------------------------ */

interface AttachmentFile {
  id: string
  name: string
  size: number
  dataUrl: string
  type: string
}

/* ------------------------------------------------------------------ */
/* Step indicator component                                            */
/* ------------------------------------------------------------------ */

function StepIndicator({
  current,
  total,
  labels,
}: {
  current: number
  total: number
  labels: string[]
}) {
  return (
    <div className="px-4 pt-2 pb-1">
      <Progressbar progress={(current / total) * 100} />
      <div className="mt-2 flex items-center justify-between">
        <span className="text-xs font-medium text-primary">
          Step {current} of {total}
        </span>
        <span className="text-xs text-gray-500 dark:text-gray-400">
          {labels[current - 1]}
        </span>
      </div>
    </div>
  )
}

/* ------------------------------------------------------------------ */
/* Trash icon                                                          */
/* ------------------------------------------------------------------ */

function TrashIcon({ className }: { className?: string }) {
  return (
    <svg
      className={className}
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="2"
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
    >
      <path d="M3 6h18" />
      <path d="M19 6v14c0 1-1 2-2 2H7c-1 0-2-1-2-2V6" />
      <path d="M8 6V4c0-1 1-2 2-2h4c1 0 2 1 2 2v2" />
    </svg>
  )
}

/* ------------------------------------------------------------------ */
/* Camera icon                                                         */
/* ------------------------------------------------------------------ */

function CameraIcon({ className }: { className?: string }) {
  return (
    <svg
      className={className}
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="2"
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
    >
      <path d="M23 19a2 2 0 0 1-2 2H3a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2h4l2-3h6l2 3h4a2 2 0 0 1 2 2z" />
      <circle cx="12" cy="13" r="4" />
    </svg>
  )
}

/* ------------------------------------------------------------------ */
/* Main component                                                      */
/* ------------------------------------------------------------------ */

/**
 * Invoice creation/edit screen — multi-step form with Konsta UI components.
 *
 * Steps:
 * 1. Customer & Vehicle
 * 2. Dates & Meta
 * 3. Line Items
 * 4. Adjustments
 * 5. Notes & Attachments
 * 6. Review & Save
 *
 * Requirements: 20.1, 20.2, 20.3, 20.4, 20.5, 20.6, 20.7, 20.8, 20.9, 20.10, 56.1, 56.4
 */
export default function InvoiceCreateScreen() {
  const navigate = useNavigate()
  const { id: editId } = useParams<{ id: string }>()
  const [searchParams] = useSearchParams()
  const isEdit = Boolean(editId)

  const { isModuleEnabled, tradeFamily } = useModules()
  const { takePhoto } = useCamera()

  const showVehicles =
    isModuleEnabled('vehicles') && tradeFamily === 'automotive-transport'
  const showInventory = isModuleEnabled('inventory')

  // ---- Step state ----
  const [step, setStep] = useState(1)
  const stepLabels = [
    'Customer & Vehicle',
    'Dates & Meta',
    'Line Items',
    'Adjustments',
    'Notes & Attachments',
    'Review & Save',
  ]

  // ---- Step 1: Customer & Vehicle ----
  const [customerId, setCustomerId] = useState('')
  const [customerName, setCustomerName] = useState('')
  const [selectedVehicles, setSelectedVehicles] = useState<Vehicle[]>([])
  const [showCustomerPicker, setShowCustomerPicker] = useState(false)
  const [customerVehicles, setCustomerVehicles] = useState<Vehicle[]>([])

  // ---- Step 2: Dates & Meta ----
  const [issueDate, setIssueDate] = useState(
    new Date().toISOString().split('T')[0],
  )
  const [dueDate, setDueDate] = useState('')
  const [paymentTerms, setPaymentTerms] = useState('')
  const [salespersonId, setSalespersonId] = useState('')
  const [salespeople, setSalespeople] = useState<
    { id: string; name: string }[]
  >([])
  const [subject, setSubject] = useState('')
  const [orderNumber, setOrderNumber] = useState('')
  const [gstNumber, setGstNumber] = useState('')

  // ---- Step 3: Line Items ----
  const [lineItems, setLineItems] = useState<
    (InvoiceLineItemCreate & {
      tax_mode?: string
      discount_percent?: number
    })[]
  >([])
  const [showItemPicker, setShowItemPicker] = useState(false)

  // ---- Step 4: Adjustments ----
  const [discountType, setDiscountType] = useState<'percentage' | 'fixed'>(
    'percentage',
  )
  const [discountValue, setDiscountValue] = useState(0)
  const [shippingCharges, setShippingCharges] = useState(0)
  const [adjustment, setAdjustment] = useState(0)

  // ---- Step 5: Notes & Attachments ----
  const [customerNotes, setCustomerNotes] = useState('')
  const [internalNotes, setInternalNotes] = useState('')
  const [terms, setTerms] = useState('')
  const [attachments, setAttachments] = useState<AttachmentFile[]>([])

  // ---- Step 6: Review & Save ----
  const [makeRecurring, setMakeRecurring] = useState(false)
  const [paymentMethod, setPaymentMethod] = useState('')

  // ---- UI state ----
  const [errors, setErrors] = useState<InvoiceFormErrors>({})
  const [apiError, setApiError] = useState<string | null>(null)
  const [isSubmitting, setIsSubmitting] = useState(false)
  const [isLoadingEdit, setIsLoadingEdit] = useState(false)

  // ---- Computed totals ----
  const totals = calculateInvoiceTotals(
    lineItems,
    discountType,
    discountValue,
    shippingCharges,
    adjustment,
  )

  // ---- Load edit data ----
  useEffect(() => {
    if (!editId) return
    const controller = new AbortController()
    setIsLoadingEdit(true)

    apiClient
      .get(`/api/v1/invoices/${editId}`, { signal: controller.signal })
      .then((res) => {
        const inv = res.data
        if (!inv) return
        setCustomerId(inv.customer_id ?? '')
        setCustomerName(inv.customer_name ?? '')
        setDueDate(inv.due_date?.split('T')[0] ?? '')
        setIssueDate(inv.issue_date?.split('T')[0] ?? issueDate)
        setSubject(inv.subject ?? '')
        setOrderNumber(inv.order_number ?? '')
        setPaymentTerms(inv.payment_terms ?? '')
        setCustomerNotes(inv.notes ?? '')
        setInternalNotes(inv.internal_notes ?? '')
        setTerms(inv.terms ?? '')
        setDiscountType(inv.discount_type ?? 'percentage')
        setDiscountValue(inv.discount_value ?? inv.discount_amount ?? 0)
        setShippingCharges(inv.shipping_charges ?? 0)
        setAdjustment(inv.adjustment ?? 0)

        const items = (inv.line_items ?? []).map(
          (li: Record<string, unknown>) => ({
            description: (li.description as string) ?? '',
            quantity: (li.quantity as number) ?? 1,
            unit_price: (li.unit_price as number) ?? 0,
            tax_rate: (li.tax_rate as number) ?? 0.15,
            tax_mode: (li.tax_mode as string) ?? 'exclusive',
            discount_percent: (li.discount_percent as number) ?? 0,
          }),
        )
        setLineItems(items)

        if (inv.vehicles && Array.isArray(inv.vehicles)) {
          setSelectedVehicles(inv.vehicles)
        }
      })
      .catch((err: unknown) => {
        if ((err as { name?: string })?.name !== 'CanceledError') {
          setApiError('Failed to load invoice for editing')
        }
      })
      .finally(() => setIsLoadingEdit(false))

    return () => controller.abort()
  }, [editId])

  // ---- Load salespeople ----
  useEffect(() => {
    const controller = new AbortController()
    apiClient
      .get('/api/v1/org/salespeople', { signal: controller.signal })
      .then((res) => {
        setSalespeople(res.data?.items ?? res.data?.salespeople ?? [])
      })
      .catch(() => {})
    return () => controller.abort()
  }, [])

  // ---- Load GST number ----
  useEffect(() => {
    const controller = new AbortController()
    apiClient
      .get('/api/v1/org/settings', { signal: controller.signal })
      .then((res) => {
        setGstNumber(res.data?.gst_number ?? res.data?.tax_number ?? '')
      })
      .catch(() => {})
    return () => controller.abort()
  }, [])

  // ---- Pre-fill customer from query param ----
  useEffect(() => {
    const preCustomerId = searchParams.get('customer_id')
    if (preCustomerId && !customerId) {
      const controller = new AbortController()
      apiClient
        .get(`/api/v1/customers/${preCustomerId}`, {
          signal: controller.signal,
        })
        .then((res) => {
          const c = res.data
          if (c) {
            setCustomerId(c.id)
            const name = [c.first_name, c.last_name]
              .filter(Boolean)
              .join(' ')
            setCustomerName(name || 'Unnamed')
          }
        })
        .catch(() => {})
      return () => controller.abort()
    }
  }, [searchParams])

  // ---- Load customer vehicles when customer changes ----
  useEffect(() => {
    if (!customerId || !showVehicles) {
      setCustomerVehicles([])
      return
    }
    const controller = new AbortController()
    apiClient
      .get('/api/v1/vehicles', {
        params: { customer_id: customerId },
        signal: controller.signal,
      })
      .then((res) => {
        setCustomerVehicles(res.data?.items ?? res.data?.vehicles ?? [])
      })
      .catch(() => setCustomerVehicles([]))
    return () => controller.abort()
  }, [customerId, showVehicles])

  // ---- Handlers ----
  const handleCustomerSelect = useCallback((customer: Customer) => {
    setCustomerId(customer.id)
    const name = [customer.first_name, customer.last_name]
      .filter(Boolean)
      .join(' ')
    setCustomerName(name || 'Unnamed')
    setErrors((prev) => ({ ...prev, customer: undefined }))
  }, [])

  const handleItemSelect = useCallback(
    (item: InventoryItem) => {
      const newLineItem: InvoiceLineItemCreate & {
        tax_mode?: string
        discount_percent?: number
      } = {
        description: item.description ?? item.name ?? '',
        quantity: 1,
        unit_price: item.unit_price ?? 0,
        tax_rate: 0.15,
        tax_mode: 'exclusive',
        discount_percent: 0,
      }
      setLineItems((prev) => [...prev, newLineItem])
      setErrors((prev) => ({ ...prev, line_items: undefined }))
    },
    [],
  )

  const toggleVehicle = useCallback(
    (vehicle: Vehicle) => {
      setSelectedVehicles((prev) => {
        const exists = prev.find((v) => v.id === vehicle.id)
        if (exists) return prev.filter((v) => v.id !== vehicle.id)
        return [...prev, vehicle]
      })
    },
    [],
  )

  const updateLineItem = useCallback(
    (
      index: number,
      field: string,
      value: string | number,
    ) => {
      setLineItems((prev) => {
        const updated = [...prev]
        updated[index] = { ...updated[index], [field]: value }
        return updated
      })
    },
    [],
  )

  const removeLineItem = useCallback((index: number) => {
    setLineItems((prev) => prev.filter((_, i) => i !== index))
  }, [])

  const addEmptyLine = useCallback(() => {
    setLineItems((prev) => [
      ...prev,
      {
        description: '',
        quantity: 1,
        unit_price: 0,
        tax_rate: 0.15,
        tax_mode: 'exclusive',
        discount_percent: 0,
      },
    ])
  }, [])

  const handleFileUpload = useCallback(
    (e: React.ChangeEvent<HTMLInputElement>) => {
      const files = e.target.files
      if (!files) return
      const remaining = MAX_ATTACHMENTS - attachments.length
      const toAdd = Array.from(files).slice(0, remaining)

      for (const file of toAdd) {
        if (file.size > MAX_FILE_SIZE_BYTES) {
          setApiError(`File "${file.name}" exceeds ${MAX_FILE_SIZE_MB}MB limit`)
          continue
        }
        const reader = new FileReader()
        reader.onload = () => {
          setAttachments((prev) => {
            if (prev.length >= MAX_ATTACHMENTS) return prev
            return [
              ...prev,
              {
                id: `${Date.now()}-${Math.random()}`,
                name: file.name,
                size: file.size,
                dataUrl: reader.result as string,
                type: file.type,
              },
            ]
          })
        }
        reader.readAsDataURL(file)
      }
      // Reset input
      e.target.value = ''
    },
    [attachments.length],
  )

  const handleCameraCapture = useCallback(async () => {
    if (attachments.length >= MAX_ATTACHMENTS) {
      setApiError(`Maximum ${MAX_ATTACHMENTS} attachments allowed`)
      return
    }
    const photo = await takePhoto()
    if (photo) {
      setAttachments((prev) => [
        ...prev,
        {
          id: `${Date.now()}-${Math.random()}`,
          name: `photo-${Date.now()}.jpg`,
          size: 0,
          dataUrl: photo.dataUrl,
          type: photo.format,
        },
      ])
    }
  }, [attachments.length, takePhoto])

  const removeAttachment = useCallback((id: string) => {
    setAttachments((prev) => prev.filter((a) => a.id !== id))
  }, [])

  // ---- Navigation ----
  const goNext = useCallback(() => {
    // Validate current step before proceeding
    if (step === 1 && !customerId) {
      setErrors({ customer: 'Customer is required' })
      return
    }
    if (step === 2 && !dueDate) {
      setErrors({ due_date: 'Due date is required' })
      return
    }
    setErrors({})
    setStep((s) => Math.min(s + 1, TOTAL_STEPS))
  }, [step, customerId, dueDate])

  const goBack = useCallback(() => {
    setStep((s) => Math.max(s - 1, 1))
  }, [])

  // ---- Submit ----
  const handleSubmit = async (action: 'draft' | 'send' | 'paid') => {
    const formErrors = validateInvoiceForm({
      customer_id: customerId,
      due_date: dueDate,
      line_items: lineItems,
    })

    if (Object.keys(formErrors).length > 0) {
      setErrors(formErrors)
      setStep(1) // Go back to first step with errors
      return
    }

    setIsSubmitting(true)
    setApiError(null)

    try {
      const payload = {
        customer_id: customerId,
        vehicle_ids: selectedVehicles.map((v) => v.id),
        issue_date: issueDate,
        due_date: dueDate,
        payment_terms: paymentTerms || undefined,
        salesperson_id: salespersonId || undefined,
        subject: subject.trim() || undefined,
        order_number: orderNumber.trim() || undefined,
        line_items: lineItems.map((li) => ({
          description: li.description,
          quantity: li.quantity,
          unit_price: li.unit_price,
          tax_rate: li.tax_rate,
          tax_mode: li.tax_mode ?? 'exclusive',
          discount_percent: li.discount_percent ?? 0,
        })),
        discount_type: discountType,
        discount_value: discountValue > 0 ? discountValue : undefined,
        shipping_charges:
          shippingCharges > 0 ? shippingCharges : undefined,
        adjustment: adjustment !== 0 ? adjustment : undefined,
        notes: customerNotes.trim() || undefined,
        internal_notes: internalNotes.trim() || undefined,
        terms: terms.trim() || undefined,
        status: action === 'draft' ? 'draft' : 'issued',
        send_email: action === 'send' || action === 'paid',
        mark_paid: action === 'paid',
        make_recurring: makeRecurring,
        payment_method: paymentMethod || undefined,
      }

      let invoiceId: string
      if (isEdit && editId) {
        const res = await apiClient.put(
          `/api/v1/invoices/${editId}`,
          payload,
        )
        invoiceId = res.data?.id ?? editId
      } else {
        const res = await apiClient.post('/api/v1/invoices', payload)
        invoiceId = res.data?.id ?? ''
      }

      // Upload attachments if any
      for (const att of attachments) {
        if (!att.dataUrl) continue
        try {
          const blob = await fetch(att.dataUrl).then((r) => r.blob())
          const formData = new FormData()
          formData.append('file', blob, att.name)
          await apiClient.post(
            `/api/v1/invoices/${invoiceId}/attachments`,
            formData,
            { headers: { 'Content-Type': 'multipart/form-data' } },
          )
        } catch {
          // Attachment upload failure is non-blocking
        }
      }

      navigate(`/invoices/${invoiceId}`, { replace: true })
    } catch (err: unknown) {
      const detail =
        (err as { response?: { data?: { detail?: string } } })?.response
          ?.data?.detail ?? 'Failed to save invoice'
      setApiError(detail)
    } finally {
      setIsSubmitting(false)
    }
  }

  // ---- File input ref ----
  const fileInputRef = useRef<HTMLInputElement>(null)

  // ---- Render ----
  if (isLoadingEdit) {
    return (
      <Page>
        <KonstaNavbar title={isEdit ? 'Edit Invoice' : 'New Invoice'} showBack />
        <Block className="text-center">
          <p className="text-gray-500 dark:text-gray-400">Loading invoice…</p>
        </Block>
      </Page>
    )
  }

  return (
    <Page>
      <KonstaNavbar
        title={isEdit ? 'Edit Invoice' : 'New Invoice'}
        showBack
        onBack={() => {
          if (step > 1) {
            goBack()
          } else {
            navigate(-1)
          }
        }}
        rightActions={
          <Button
            onClick={() => navigate(-1)}
            clear
            small
            className="text-gray-500"
          >
            Cancel
          </Button>
        }
      />

      <StepIndicator current={step} total={TOTAL_STEPS} labels={stepLabels} />

      {/* API error banner */}
      {apiError && (
        <Block>
          <div
            className="rounded-lg bg-red-50 p-3 text-sm text-red-700 dark:bg-red-900/30 dark:text-red-300"
            role="alert"
          >
            {apiError}
            <button
              type="button"
              className="ml-2 text-xs underline"
              onClick={() => setApiError(null)}
            >
              Dismiss
            </button>
          </div>
        </Block>
      )}

      {/* ============================================================ */}
      {/* Step 1: Customer & Vehicle                                    */}
      {/* ============================================================ */}
      {step === 1 && (
        <>
          <BlockTitle>Customer</BlockTitle>
          <Block>
            <button
              type="button"
              onClick={() => setShowCustomerPicker(true)}
              className="flex min-h-[44px] w-full items-center rounded-lg border border-gray-300 px-3 py-2 text-left text-base dark:border-gray-600 dark:bg-gray-800"
            >
              {customerName ? (
                <span className="text-gray-900 dark:text-gray-100">
                  {customerName}
                </span>
              ) : (
                <span className="text-gray-400 dark:text-gray-500">
                  Select customer…
                </span>
              )}
            </button>
            {errors.customer && (
              <p
                className="mt-1 text-sm text-red-600 dark:text-red-400"
                role="alert"
              >
                {errors.customer}
              </p>
            )}
          </Block>

          {showVehicles && customerId && (
            <>
              <BlockTitle>Vehicles</BlockTitle>
              <Block>
                {customerVehicles.length === 0 ? (
                  <p className="text-sm text-gray-500 dark:text-gray-400">
                    No vehicles linked to this customer
                  </p>
                ) : (
                  <div className="flex flex-wrap gap-2">
                    {customerVehicles.map((v) => {
                      const isSelected = selectedVehicles.some(
                        (sv) => sv.id === v.id,
                      )
                      return (
                        <Chip
                          key={v.id}
                          className={`cursor-pointer ${
                            isSelected
                              ? 'bg-primary text-white'
                              : 'bg-gray-100 dark:bg-gray-700'
                          }`}
                          onClick={() => toggleVehicle(v)}
                        >
                          {v.registration}
                          {v.make ? ` — ${v.make}` : ''}
                          {v.model ? ` ${v.model}` : ''}
                        </Chip>
                      )
                    })}
                  </div>
                )}
              </Block>
            </>
          )}
        </>
      )}

      {/* ============================================================ */}
      {/* Step 2: Dates & Meta                                          */}
      {/* ============================================================ */}
      {step === 2 && (
        <>
          <BlockTitle>Dates</BlockTitle>
          <List strongIos outlineIos>
            <ListInput
              label="Issue Date"
              type="date"
              value={issueDate}
              onChange={(e: React.ChangeEvent<HTMLInputElement>) =>
                setIssueDate(e.target.value)
              }
            />
            <ListInput
              label="Due Date"
              type="date"
              value={dueDate}
              onChange={(e: React.ChangeEvent<HTMLInputElement>) => {
                setDueDate(e.target.value)
                setErrors((prev) => ({ ...prev, due_date: undefined }))
              }}
              info={errors.due_date}
              error={Boolean(errors.due_date)}
            />
            <ListInput
              label="Payment Terms"
              type="select"
              value={paymentTerms}
              onChange={(e: React.ChangeEvent<HTMLSelectElement>) =>
                setPaymentTerms(e.target.value)
              }
            >
              {PAYMENT_TERMS_OPTIONS.map((opt) => (
                <option key={opt.value} value={opt.value}>
                  {opt.label}
                </option>
              ))}
            </ListInput>
          </List>

          <BlockTitle>Details</BlockTitle>
          <List strongIos outlineIos>
            <ListInput
              label="Salesperson"
              type="select"
              value={salespersonId}
              onChange={(e: React.ChangeEvent<HTMLSelectElement>) => {
                setSalespersonId(e.target.value)
              }}
            >
              <option value="">Select salesperson…</option>
              {salespeople.map((sp) => (
                <option key={sp.id} value={sp.id}>
                  {sp.name}
                </option>
              ))}
            </ListInput>
            <ListInput
              label="Subject"
              type="text"
              value={subject}
              onChange={(e: React.ChangeEvent<HTMLInputElement>) =>
                setSubject(e.target.value)
              }
              placeholder="Invoice subject"
            />
            <ListInput
              label="Order Number"
              type="text"
              value={orderNumber}
              onChange={(e: React.ChangeEvent<HTMLInputElement>) =>
                setOrderNumber(e.target.value)
              }
              placeholder="PO / Order number"
            />
            <ListInput
              label="GST Number"
              type="text"
              value={gstNumber}
              readOnly
              disabled
            />
          </List>
        </>
      )}

      {/* ============================================================ */}
      {/* Step 3: Line Items                                            */}
      {/* ============================================================ */}
      {step === 3 && (
        <>
          <BlockTitle>
            Line Items ({lineItems.length})
          </BlockTitle>

          {errors.line_items && (
            <Block>
              <p
                className="text-sm text-red-600 dark:text-red-400"
                role="alert"
              >
                {errors.line_items}
              </p>
            </Block>
          )}

          {lineItems.map((item, index) => {
            const lineAmount =
              (item.quantity ?? 0) * (item.unit_price ?? 0) *
              (1 - (item.discount_percent ?? 0) / 100)
            return (
              <Card key={index} className="mb-3 mx-4">
                <div className="flex items-start justify-between mb-2">
                  <span className="text-xs font-medium text-gray-500 dark:text-gray-400">
                    Item {index + 1}
                  </span>
                  <button
                    type="button"
                    onClick={() => removeLineItem(index)}
                    className="flex min-h-[44px] min-w-[44px] items-center justify-center text-red-500 hover:text-red-700 dark:text-red-400"
                    aria-label={`Remove item ${index + 1}`}
                  >
                    <TrashIcon className="h-5 w-5" />
                  </button>
                </div>

                <List strongIos outlineIos className="-mx-4">
                  <ListInput
                    label="Description"
                    type="text"
                    value={item.description}
                    onChange={(e: React.ChangeEvent<HTMLInputElement>) =>
                      updateLineItem(index, 'description', e.target.value)
                    }
                    placeholder="Item description"
                  />
                  <ListInput
                    label="Quantity"
                    type="number"
                    value={String(item.quantity)}
                    onChange={(e: React.ChangeEvent<HTMLInputElement>) =>
                      updateLineItem(
                        index,
                        'quantity',
                        parseFloat(e.target.value) || 0,
                      )
                    }
                    min={0}
                    step={1}
                  />
                  <ListInput
                    label="Rate"
                    type="number"
                    value={String(item.unit_price)}
                    onChange={(e: React.ChangeEvent<HTMLInputElement>) =>
                      updateLineItem(
                        index,
                        'unit_price',
                        parseFloat(e.target.value) || 0,
                      )
                    }
                    min={0}
                    step={0.01}
                  />
                  <ListInput
                    label="Tax Mode"
                    type="select"
                    value={item.tax_mode ?? 'exclusive'}
                    onChange={(e: React.ChangeEvent<HTMLSelectElement>) =>
                      updateLineItem(index, 'tax_mode', e.target.value)
                    }
                  >
                    {TAX_MODE_OPTIONS.map((opt) => (
                      <option key={opt.value} value={opt.value}>
                        {opt.label}
                      </option>
                    ))}
                  </ListInput>
                  <ListInput
                    label="Discount %"
                    type="number"
                    value={String(item.discount_percent ?? 0)}
                    onChange={(e: React.ChangeEvent<HTMLInputElement>) =>
                      updateLineItem(
                        index,
                        'discount_percent',
                        parseFloat(e.target.value) || 0,
                      )
                    }
                    min={0}
                    max={100}
                    step={1}
                  />
                </List>

                <div className="mt-2 text-right">
                  <span className="text-sm font-medium text-gray-900 dark:text-gray-100">
                    Amount: {formatNZD(lineAmount)}
                  </span>
                </div>
              </Card>
            )
          })}

          <Block>
            <div className="flex flex-wrap gap-2">
              <Button
                small
                outline
                onClick={() => {
                  setShowItemPicker(true)
                }}
              >
                Add from Catalogue
              </Button>
              {showInventory && (
                <Button
                  small
                  outline
                  onClick={() => {
                    setShowItemPicker(true)
                  }}
                >
                  Add from Inventory
                </Button>
              )}
              <Button
                small
                outline
                onClick={() => {
                  setLineItems((prev) => [
                    ...prev,
                    {
                      description: 'Labour',
                      quantity: 1,
                      unit_price: 0,
                      tax_rate: 0.15,
                      tax_mode: 'exclusive',
                      discount_percent: 0,
                    },
                  ])
                }}
              >
                Add Labour
              </Button>
              <Button small outline onClick={addEmptyLine}>
                Add Empty Line
              </Button>
            </div>
          </Block>

          {/* Running totals */}
          <Block>
            <div
              className="rounded-lg bg-gray-50 p-3 dark:bg-gray-800"
              aria-label="Running totals"
            >
              <div className="flex justify-between text-sm">
                <span className="text-gray-500 dark:text-gray-400">
                  Subtotal
                </span>
                <span className="tabular-nums text-gray-900 dark:text-gray-100">
                  {formatNZD(totals.subtotal)}
                </span>
              </div>
              <div className="flex justify-between text-sm mt-1">
                <span className="text-gray-500 dark:text-gray-400">GST</span>
                <span className="tabular-nums text-gray-900 dark:text-gray-100">
                  {formatNZD(totals.taxAmount)}
                </span>
              </div>
              <div className="flex justify-between text-sm font-semibold mt-1 border-t border-gray-200 pt-1 dark:border-gray-600">
                <span className="text-gray-900 dark:text-gray-100">
                  Total
                </span>
                <span className="tabular-nums text-gray-900 dark:text-gray-100">
                  {formatNZD(totals.total)}
                </span>
              </div>
            </div>
          </Block>
        </>
      )}

      {/* ============================================================ */}
      {/* Step 4: Adjustments                                           */}
      {/* ============================================================ */}
      {step === 4 && (
        <>
          <BlockTitle>Discount</BlockTitle>
          <Block>
            <div className="flex items-center gap-2 mb-3">
              <Button
                small
                className={discountType === 'percentage' ? 'bg-primary text-white' : ''}
                outline={discountType !== 'percentage'}
                onClick={() => setDiscountType('percentage')}
              >
                %
              </Button>
              <Button
                small
                className={discountType === 'fixed' ? 'bg-primary text-white' : ''}
                outline={discountType !== 'fixed'}
                onClick={() => setDiscountType('fixed')}
              >
                $
              </Button>
            </div>
          </Block>
          <List strongIos outlineIos>
            <ListInput
              label={
                discountType === 'percentage'
                  ? 'Discount %'
                  : 'Discount Amount'
              }
              type="number"
              value={String(discountValue)}
              onChange={(e: React.ChangeEvent<HTMLInputElement>) =>
                setDiscountValue(parseFloat(e.target.value) || 0)
              }
              min={0}
              step={discountType === 'percentage' ? 1 : 0.01}
              max={discountType === 'percentage' ? 100 : undefined}
            />
          </List>

          <BlockTitle>Shipping & Adjustment</BlockTitle>
          <List strongIos outlineIos>
            <ListInput
              label="Shipping Charges"
              type="number"
              value={String(shippingCharges)}
              onChange={(e: React.ChangeEvent<HTMLInputElement>) =>
                setShippingCharges(parseFloat(e.target.value) || 0)
              }
              min={0}
              step={0.01}
            />
            <ListInput
              label="Adjustment"
              type="number"
              value={String(adjustment)}
              onChange={(e: React.ChangeEvent<HTMLInputElement>) =>
                setAdjustment(parseFloat(e.target.value) || 0)
              }
              step={0.01}
              info="Can be positive or negative"
            />
          </List>

          {/* Totals summary */}
          <Block>
            <div className="rounded-lg bg-gray-50 p-3 dark:bg-gray-800">
              <div className="flex justify-between text-sm">
                <span className="text-gray-500 dark:text-gray-400">
                  Subtotal
                </span>
                <span className="tabular-nums">{formatNZD(totals.subtotal)}</span>
              </div>
              {totals.discountAmount > 0 && (
                <div className="flex justify-between text-sm mt-1">
                  <span className="text-gray-500 dark:text-gray-400">
                    Discount
                  </span>
                  <span className="tabular-nums text-red-600 dark:text-red-400">
                    -{formatNZD(totals.discountAmount)}
                  </span>
                </div>
              )}
              <div className="flex justify-between text-sm mt-1">
                <span className="text-gray-500 dark:text-gray-400">GST</span>
                <span className="tabular-nums">{formatNZD(totals.taxAmount)}</span>
              </div>
              {totals.shipping > 0 && (
                <div className="flex justify-between text-sm mt-1">
                  <span className="text-gray-500 dark:text-gray-400">
                    Shipping
                  </span>
                  <span className="tabular-nums">
                    {formatNZD(totals.shipping)}
                  </span>
                </div>
              )}
              {totals.adjustment !== 0 && (
                <div className="flex justify-between text-sm mt-1">
                  <span className="text-gray-500 dark:text-gray-400">
                    Adjustment
                  </span>
                  <span className="tabular-nums">
                    {formatNZD(totals.adjustment)}
                  </span>
                </div>
              )}
              <div className="flex justify-between text-sm font-semibold mt-1 border-t border-gray-200 pt-1 dark:border-gray-600">
                <span>Total</span>
                <span className="tabular-nums">{formatNZD(totals.total)}</span>
              </div>
            </div>
          </Block>
        </>
      )}

      {/* ============================================================ */}
      {/* Step 5: Notes & Attachments                                   */}
      {/* ============================================================ */}
      {step === 5 && (
        <>
          <BlockTitle>Notes</BlockTitle>
          <List strongIos outlineIos>
            <ListInput
              label="Customer Notes"
              type="textarea"
              value={customerNotes}
              onChange={(e: React.ChangeEvent<HTMLTextAreaElement>) =>
                setCustomerNotes(e.target.value)
              }
              placeholder="Notes visible to the customer…"
              inputClassName="!h-24"
            />
            <ListInput
              label="Internal Notes"
              type="textarea"
              value={internalNotes}
              onChange={(e: React.ChangeEvent<HTMLTextAreaElement>) =>
                setInternalNotes(e.target.value)
              }
              placeholder="Internal notes (not visible to customer)…"
              inputClassName="!h-24"
            />
            <ListInput
              label="Terms & Conditions"
              type="textarea"
              value={terms}
              onChange={(e: React.ChangeEvent<HTMLTextAreaElement>) =>
                setTerms(e.target.value)
              }
              placeholder="Payment terms and conditions…"
              inputClassName="!h-24"
            />
          </List>

          <BlockTitle>
            Attachments ({attachments.length}/{MAX_ATTACHMENTS})
          </BlockTitle>
          <Block>
            {attachments.length > 0 && (
              <div className="flex flex-wrap gap-2 mb-3">
                {attachments.map((att) => (
                  <div
                    key={att.id}
                    className="relative rounded-lg border border-gray-200 p-2 dark:border-gray-700"
                  >
                    {att.dataUrl.startsWith('data:image') ? (
                      <img
                        src={att.dataUrl}
                        alt={att.name}
                        className="h-16 w-16 rounded object-cover"
                      />
                    ) : (
                      <div className="flex h-16 w-16 items-center justify-center rounded bg-gray-100 dark:bg-gray-700">
                        <span className="text-xs text-gray-500">
                          {att.name.split('.').pop()?.toUpperCase()}
                        </span>
                      </div>
                    )}
                    <button
                      type="button"
                      onClick={() => removeAttachment(att.id)}
                      className="absolute -top-1 -right-1 flex h-5 w-5 items-center justify-center rounded-full bg-red-500 text-white text-xs"
                      aria-label={`Remove ${att.name}`}
                    >
                      ×
                    </button>
                    <p className="mt-1 max-w-[64px] truncate text-xs text-gray-500">
                      {att.name}
                    </p>
                  </div>
                ))}
              </div>
            )}

            {attachments.length < MAX_ATTACHMENTS && (
              <div className="flex gap-2">
                <Button
                  small
                  outline
                  onClick={() => fileInputRef.current?.click()}
                >
                  Upload File
                </Button>
                <Button small outline onClick={handleCameraCapture}>
                  <CameraIcon className="h-4 w-4 mr-1 inline" />
                  Camera
                </Button>
              </div>
            )}

            <input
              ref={fileInputRef}
              type="file"
              multiple
              accept="image/*,.pdf,.doc,.docx,.xls,.xlsx"
              onChange={handleFileUpload}
              className="hidden"
            />

            <p className="mt-2 text-xs text-gray-400 dark:text-gray-500">
              Max {MAX_ATTACHMENTS} files, {MAX_FILE_SIZE_MB}MB each
            </p>
          </Block>
        </>
      )}

      {/* ============================================================ */}
      {/* Step 6: Review & Save                                         */}
      {/* ============================================================ */}
      {step === 6 && (
        <>
          <BlockTitle>Invoice Summary</BlockTitle>
          <Card className="mx-4">
            <div className="space-y-2 text-sm">
              <div className="flex justify-between">
                <span className="text-gray-500 dark:text-gray-400">
                  Customer
                </span>
                <span className="font-medium text-gray-900 dark:text-gray-100">
                  {customerName || '—'}
                </span>
              </div>
              {selectedVehicles.length > 0 && (
                <div className="flex justify-between">
                  <span className="text-gray-500 dark:text-gray-400">
                    Vehicles
                  </span>
                  <span className="font-medium text-gray-900 dark:text-gray-100">
                    {selectedVehicles
                      .map((v) => v.registration)
                      .join(', ')}
                  </span>
                </div>
              )}
              <div className="flex justify-between">
                <span className="text-gray-500 dark:text-gray-400">
                  Issue Date
                </span>
                <span>{issueDate}</span>
              </div>
              <div className="flex justify-between">
                <span className="text-gray-500 dark:text-gray-400">
                  Due Date
                </span>
                <span>{dueDate}</span>
              </div>
              {subject && (
                <div className="flex justify-between">
                  <span className="text-gray-500 dark:text-gray-400">
                    Subject
                  </span>
                  <span>{subject}</span>
                </div>
              )}
              <div className="flex justify-between">
                <span className="text-gray-500 dark:text-gray-400">
                  Line Items
                </span>
                <span>{lineItems.length}</span>
              </div>

              <div className="border-t border-gray-200 pt-2 dark:border-gray-600">
                <div className="flex justify-between">
                  <span className="text-gray-500 dark:text-gray-400">
                    Subtotal
                  </span>
                  <span className="tabular-nums">
                    {formatNZD(totals.subtotal)}
                  </span>
                </div>
                {totals.discountAmount > 0 && (
                  <div className="flex justify-between">
                    <span className="text-gray-500 dark:text-gray-400">
                      Discount
                    </span>
                    <span className="tabular-nums text-red-600 dark:text-red-400">
                      -{formatNZD(totals.discountAmount)}
                    </span>
                  </div>
                )}
                <div className="flex justify-between">
                  <span className="text-gray-500 dark:text-gray-400">
                    GST
                  </span>
                  <span className="tabular-nums">
                    {formatNZD(totals.taxAmount)}
                  </span>
                </div>
                {totals.shipping > 0 && (
                  <div className="flex justify-between">
                    <span className="text-gray-500 dark:text-gray-400">
                      Shipping
                    </span>
                    <span className="tabular-nums">
                      {formatNZD(totals.shipping)}
                    </span>
                  </div>
                )}
                {totals.adjustment !== 0 && (
                  <div className="flex justify-between">
                    <span className="text-gray-500 dark:text-gray-400">
                      Adjustment
                    </span>
                    <span className="tabular-nums">
                      {formatNZD(totals.adjustment)}
                    </span>
                  </div>
                )}
                <div className="flex justify-between font-semibold text-base mt-1 border-t border-gray-200 pt-1 dark:border-gray-600">
                  <span className="text-gray-900 dark:text-gray-100">
                    Total
                  </span>
                  <span className="tabular-nums text-gray-900 dark:text-gray-100">
                    {formatNZD(totals.total)}
                  </span>
                </div>
              </div>
            </div>
          </Card>

          <BlockTitle>Options</BlockTitle>
          <List strongIos outlineIos>
            <li className="flex items-center justify-between px-4 py-3">
              <span className="text-sm text-gray-900 dark:text-gray-100">
                Make Recurring
              </span>
              <label className="relative inline-flex cursor-pointer items-center">
                <input
                  type="checkbox"
                  checked={makeRecurring}
                  onChange={(e) => setMakeRecurring(e.target.checked)}
                  className="peer sr-only"
                />
                <div className="peer h-6 w-11 rounded-full bg-gray-200 after:absolute after:left-[2px] after:top-[2px] after:h-5 after:w-5 after:rounded-full after:border after:border-gray-300 after:bg-white after:transition-all after:content-[''] peer-checked:bg-primary peer-checked:after:translate-x-full peer-checked:after:border-white dark:bg-gray-700" />
              </label>
            </li>
            <ListInput
              label="Payment Method"
              type="select"
              value={paymentMethod}
              onChange={(e: React.ChangeEvent<HTMLSelectElement>) =>
                setPaymentMethod(e.target.value)
              }
            >
              <option value="">Select payment method…</option>
              <option value="bank_transfer">Bank Transfer</option>
              <option value="credit_card">Credit Card</option>
              <option value="cash">Cash</option>
              <option value="cheque">Cheque</option>
              <option value="stripe">Stripe</option>
            </ListInput>
          </List>

          <Block>
            <div className="flex flex-col gap-3">
              <HapticButton
                large
                onClick={() => handleSubmit('draft')}
                disabled={isSubmitting}
                className="w-full"
              >
                {isSubmitting ? 'Saving…' : 'Save as Draft'}
              </HapticButton>
              <HapticButton
                large
                onClick={() => handleSubmit('send')}
                disabled={isSubmitting}
                className="w-full bg-primary text-white"
              >
                {isSubmitting ? 'Saving…' : 'Save & Send'}
              </HapticButton>
              <HapticButton
                large
                outline
                onClick={() => handleSubmit('paid')}
                disabled={isSubmitting}
                className="w-full"
              >
                Mark Paid & Email
              </HapticButton>
            </div>
          </Block>
        </>
      )}

      {/* ============================================================ */}
      {/* Bottom navigation: Back / Next                                */}
      {/* ============================================================ */}
      {step < TOTAL_STEPS && (
        <Block>
          <div className="flex gap-3">
            {step > 1 && (
              <Button large outline onClick={goBack} className="flex-1">
                Back
              </Button>
            )}
            <HapticButton
              large
              onClick={goNext}
              className={`flex-1 ${step === 1 ? 'w-full' : ''}`}
            >
              Next
            </HapticButton>
          </div>
        </Block>
      )}

      {/* ============================================================ */}
      {/* Pickers                                                       */}
      {/* ============================================================ */}
      <CustomerPicker
        isOpen={showCustomerPicker}
        onClose={() => setShowCustomerPicker(false)}
        onSelect={handleCustomerSelect}
      />
      <ItemPicker
        isOpen={showItemPicker}
        onClose={() => setShowItemPicker(false)}
        onSelect={handleItemSelect}
      />
    </Page>
  )
}
