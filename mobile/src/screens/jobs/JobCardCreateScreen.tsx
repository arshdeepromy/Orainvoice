import { useState, useCallback, useEffect } from 'react'
import { useNavigate } from 'react-router-dom'
import {
  Page,
  Block,
  BlockTitle,
  List,
  ListInput,
  Card,
  Button,
  Progressbar,
} from 'konsta/react'
import type { Customer } from '@shared/types/customer'
import { KonstaNavbar } from '@/components/konsta/KonstaNavbar'
import HapticButton from '@/components/konsta/HapticButton'
import { CustomerPicker } from '@/components/common/CustomerPicker'
import { ModuleGate } from '@/components/common/ModuleGate'
import { useModules } from '@/contexts/ModuleContext'
import apiClient from '@/api/client'

/* ------------------------------------------------------------------ */
/* Constants                                                           */
/* ------------------------------------------------------------------ */

const TOTAL_STEPS = 5
const STEP_LABELS = [
  'Customer & Vehicle',
  'Service Details',
  'Parts',
  'Labour',
  'Review & Save',
]

/* ------------------------------------------------------------------ */
/* Currency formatting                                                 */
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

export interface JobCardFormErrors {
  customer?: string
  description?: string
}

export function validateJobCardForm(form: {
  customer_id: string
  description: string
}): JobCardFormErrors {
  const errors: JobCardFormErrors = {}
  if (!form.customer_id) errors.customer = 'Customer is required'
  if (!form.description.trim()) errors.description = 'Service description is required'
  return errors
}

/* ------------------------------------------------------------------ */
/* Step indicator                                                      */
/* ------------------------------------------------------------------ */

function StepIndicator({ current, total }: { current: number; total: number }) {
  return (
    <div className="px-4 pt-2 pb-1">
      <Progressbar progress={(current / total) * 100} />
      <div className="mt-2 flex items-center justify-between">
        <span className="text-xs font-medium text-primary">
          Step {current} of {total}
        </span>
        <span className="text-xs text-gray-500 dark:text-gray-400">
          {STEP_LABELS[current - 1]}
        </span>
      </div>
    </div>
  )
}

/* ------------------------------------------------------------------ */
/* Types                                                               */
/* ------------------------------------------------------------------ */

interface PartEntry {
  name: string
  quantity: number
  unit_price: number
}

interface LabourEntry {
  description: string
  hours: number
  rate: number
}

interface StaffMember {
  id: string
  name: string
}

/* ------------------------------------------------------------------ */
/* Main component                                                      */
/* ------------------------------------------------------------------ */

/**
 * Job card creation screen — multi-step form with Konsta UI.
 *
 * Steps:
 * 1. Customer & Vehicle
 * 2. Description, service type, assigned staff
 * 3. Parts from inventory (if inventory enabled)
 * 4. Labour entries
 * 5. Review & Save
 *
 * Requirements: 26.1, 26.2, 26.3
 */
export default function JobCardCreateScreen() {
  const navigate = useNavigate()
  const { isModuleEnabled } = useModules()
  const showInventory = isModuleEnabled('inventory')

  // ---- Step state ----
  const [step, setStep] = useState(1)

  // ---- Step 1: Customer & Vehicle ----
  const [customerId, setCustomerId] = useState('')
  const [customerName, setCustomerName] = useState('')
  const [vehicleRegistration, setVehicleRegistration] = useState('')
  const [showCustomerPicker, setShowCustomerPicker] = useState(false)

  // ---- Step 2: Service Details ----
  const [description, setDescription] = useState('')
  const [serviceType, setServiceType] = useState('')
  const [assignedStaffId, setAssignedStaffId] = useState('')
  const [staffList, setStaffList] = useState<StaffMember[]>([])

  // ---- Step 3: Parts ----
  const [parts, setParts] = useState<PartEntry[]>([])

  // ---- Step 4: Labour ----
  const [labourEntries, setLabourEntries] = useState<LabourEntry[]>([])

  // ---- UI state ----
  const [errors, setErrors] = useState<JobCardFormErrors>({})
  const [apiError, setApiError] = useState<string | null>(null)
  const [isSubmitting, setIsSubmitting] = useState(false)

  // ---- Load staff list ----
  useEffect(() => {
    const controller = new AbortController()
    apiClient
      .get('/api/v2/staff', { signal: controller.signal })
      .then((res) => {
        setStaffList(res.data?.items ?? res.data?.staff ?? [])
      })
      .catch(() => {})
    return () => controller.abort()
  }, [])

  // ---- Handlers ----
  const handleCustomerSelect = useCallback((customer: Customer) => {
    setCustomerId(customer.id)
    const name = [customer.first_name, customer.last_name].filter(Boolean).join(' ')
    setCustomerName(name || 'Unnamed')
    setErrors((prev) => ({ ...prev, customer: undefined }))
  }, [])

  const addPart = useCallback(() => {
    setParts((prev) => [...prev, { name: '', quantity: 1, unit_price: 0 }])
  }, [])

  const updatePart = useCallback((index: number, field: string, value: string | number) => {
    setParts((prev) => {
      const updated = [...prev]
      updated[index] = { ...updated[index], [field]: value }
      return updated
    })
  }, [])

  const removePart = useCallback((index: number) => {
    setParts((prev) => prev.filter((_, i) => i !== index))
  }, [])

  const addLabour = useCallback(() => {
    setLabourEntries((prev) => [...prev, { description: '', hours: 0, rate: 0 }])
  }, [])

  const updateLabour = useCallback((index: number, field: string, value: string | number) => {
    setLabourEntries((prev) => {
      const updated = [...prev]
      updated[index] = { ...updated[index], [field]: value }
      return updated
    })
  }, [])

  const removeLabour = useCallback((index: number) => {
    setLabourEntries((prev) => prev.filter((_, i) => i !== index))
  }, [])

  // ---- Navigation ----
  const goNext = useCallback(() => {
    if (step === 1 && !customerId) {
      setErrors({ customer: 'Customer is required' })
      return
    }
    if (step === 2 && !description.trim()) {
      setErrors({ description: 'Service description is required' })
      return
    }
    // Skip parts step if inventory not enabled
    if (step === 3 && !showInventory) {
      setStep(4)
      return
    }
    setErrors({})
    setStep((s) => Math.min(s + 1, TOTAL_STEPS))
  }, [step, customerId, description, showInventory])

  const goBack = useCallback(() => {
    // Skip parts step going back if inventory not enabled
    if (step === 4 && !showInventory) {
      setStep(2)
      return
    }
    setStep((s) => Math.max(s - 1, 1))
  }, [step, showInventory])

  // ---- Submit ----
  const handleSubmit = async () => {
    const formErrors = validateJobCardForm({
      customer_id: customerId,
      description,
    })

    if (Object.keys(formErrors).length > 0) {
      setErrors(formErrors)
      if (formErrors.customer) setStep(1)
      else if (formErrors.description) setStep(2)
      return
    }

    setIsSubmitting(true)
    setApiError(null)

    try {
      const res = await apiClient.post('/api/v1/job-cards', {
        customer_id: customerId,
        vehicle_registration: vehicleRegistration.trim() || undefined,
        description: description.trim(),
        service_type: serviceType.trim() || undefined,
        assigned_staff_id: assignedStaffId || undefined,
        parts: parts.length > 0 ? parts : undefined,
        labour_entries: labourEntries.length > 0 ? labourEntries : undefined,
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

  // ---- Computed totals ----
  const partsTotal = parts.reduce((sum, p) => sum + (p.quantity ?? 0) * (p.unit_price ?? 0), 0)
  const labourTotal = labourEntries.reduce((sum, l) => sum + (l.hours ?? 0) * (l.rate ?? 0), 0)

  return (
    <ModuleGate moduleSlug="jobs">
      <Page data-testid="job-card-create-page">
        <KonstaNavbar
          title="New Job Card"
          showBack
          onBack={() => {
            if (step > 1) goBack()
            else navigate(-1)
          }}
          rightActions={
            <Button onClick={() => navigate(-1)} clear small className="text-gray-500">
              Cancel
            </Button>
          }
        />

        <StepIndicator current={step} total={TOTAL_STEPS} />

        {/* API error banner */}
        {apiError && (
          <Block>
            <div
              className="rounded-lg bg-red-50 p-3 text-sm text-red-700 dark:bg-red-900/30 dark:text-red-300"
              role="alert"
            >
              {apiError}
              <button type="button" className="ml-2 text-xs underline" onClick={() => setApiError(null)}>
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
                  <span className="text-gray-900 dark:text-gray-100">{customerName}</span>
                ) : (
                  <span className="text-gray-400 dark:text-gray-500">Select customer…</span>
                )}
              </button>
              {errors.customer && (
                <p className="mt-1 text-sm text-red-600 dark:text-red-400" role="alert">
                  {errors.customer}
                </p>
              )}
            </Block>

            <BlockTitle>Vehicle</BlockTitle>
            <List strongIos outlineIos>
              <ListInput
                label="Registration"
                type="text"
                value={vehicleRegistration}
                onChange={(e: React.ChangeEvent<HTMLInputElement>) =>
                  setVehicleRegistration(e.target.value)
                }
                placeholder="e.g. ABC123"
              />
            </List>
          </>
        )}

        {/* ============================================================ */}
        {/* Step 2: Service Details                                       */}
        {/* ============================================================ */}
        {step === 2 && (
          <>
            <BlockTitle>Service Details</BlockTitle>
            <List strongIos outlineIos>
              <ListInput
                label="Description"
                type="textarea"
                value={description}
                onChange={(e: React.ChangeEvent<HTMLTextAreaElement>) => {
                  setDescription(e.target.value)
                  setErrors((prev) => ({ ...prev, description: undefined }))
                }}
                placeholder="Describe the service required…"
                info={errors.description}
                error={Boolean(errors.description)}
              />
              <ListInput
                label="Service Type"
                type="text"
                value={serviceType}
                onChange={(e: React.ChangeEvent<HTMLInputElement>) =>
                  setServiceType(e.target.value)
                }
                placeholder="e.g. Full Service, WOF"
              />
              <ListInput
                label="Assigned Staff"
                type="select"
                value={assignedStaffId}
                onChange={(e: React.ChangeEvent<HTMLSelectElement>) =>
                  setAssignedStaffId(e.target.value)
                }
              >
                <option value="">Select staff…</option>
                {staffList.map((s) => (
                  <option key={s.id} value={s.id}>
                    {s.name}
                  </option>
                ))}
              </ListInput>
            </List>
          </>
        )}

        {/* ============================================================ */}
        {/* Step 3: Parts (only if inventory enabled)                     */}
        {/* ============================================================ */}
        {step === 3 && showInventory && (
          <>
            <BlockTitle>Parts ({parts.length})</BlockTitle>

            {parts.map((part, idx) => (
              <Card key={idx} className="mx-4 mb-3">
                <div className="flex items-start justify-between">
                  <span className="text-xs font-medium text-gray-400">Part {idx + 1}</span>
                  <button
                    type="button"
                    onClick={() => removePart(idx)}
                    className="text-xs text-red-500"
                  >
                    Remove
                  </button>
                </div>
                <List strongIos outlineIos className="-mx-4 -mb-4 mt-1">
                  <ListInput
                    label="Name"
                    type="text"
                    value={part.name}
                    onChange={(e: React.ChangeEvent<HTMLInputElement>) =>
                      updatePart(idx, 'name', e.target.value)
                    }
                    placeholder="Part name"
                  />
                  <ListInput
                    label="Quantity"
                    type="number"
                    value={String(part.quantity)}
                    onChange={(e: React.ChangeEvent<HTMLInputElement>) =>
                      updatePart(idx, 'quantity', Number(e.target.value) || 0)
                    }
                  />
                  <ListInput
                    label="Unit Price"
                    type="number"
                    value={String(part.unit_price)}
                    onChange={(e: React.ChangeEvent<HTMLInputElement>) =>
                      updatePart(idx, 'unit_price', Number(e.target.value) || 0)
                    }
                  />
                </List>
              </Card>
            ))}

            <Block>
              <Button onClick={addPart} outline small>
                + Add Part
              </Button>
            </Block>
          </>
        )}

        {/* ============================================================ */}
        {/* Step 4: Labour                                                */}
        {/* ============================================================ */}
        {step === 4 && (
          <>
            <BlockTitle>Labour Entries ({labourEntries.length})</BlockTitle>

            {labourEntries.map((entry, idx) => (
              <Card key={idx} className="mx-4 mb-3">
                <div className="flex items-start justify-between">
                  <span className="text-xs font-medium text-gray-400">Labour {idx + 1}</span>
                  <button
                    type="button"
                    onClick={() => removeLabour(idx)}
                    className="text-xs text-red-500"
                  >
                    Remove
                  </button>
                </div>
                <List strongIos outlineIos className="-mx-4 -mb-4 mt-1">
                  <ListInput
                    label="Description"
                    type="text"
                    value={entry.description}
                    onChange={(e: React.ChangeEvent<HTMLInputElement>) =>
                      updateLabour(idx, 'description', e.target.value)
                    }
                    placeholder="Labour description"
                  />
                  <ListInput
                    label="Hours"
                    type="number"
                    value={String(entry.hours)}
                    onChange={(e: React.ChangeEvent<HTMLInputElement>) =>
                      updateLabour(idx, 'hours', Number(e.target.value) || 0)
                    }
                  />
                  <ListInput
                    label="Rate ($/hr)"
                    type="number"
                    value={String(entry.rate)}
                    onChange={(e: React.ChangeEvent<HTMLInputElement>) =>
                      updateLabour(idx, 'rate', Number(e.target.value) || 0)
                    }
                  />
                </List>
              </Card>
            ))}

            <Block>
              <Button onClick={addLabour} outline small>
                + Add Labour Entry
              </Button>
            </Block>
          </>
        )}

        {/* ============================================================ */}
        {/* Step 5: Review & Save                                         */}
        {/* ============================================================ */}
        {step === 5 && (
          <>
            <BlockTitle>Review Job Card</BlockTitle>
            <Card className="mx-4">
              <div className="flex flex-col gap-2 text-sm">
                <div className="flex justify-between">
                  <span className="text-gray-500 dark:text-gray-400">Customer</span>
                  <span className="font-medium text-gray-900 dark:text-gray-100">{customerName}</span>
                </div>
                {vehicleRegistration && (
                  <div className="flex justify-between">
                    <span className="text-gray-500 dark:text-gray-400">Vehicle</span>
                    <span className="font-mono font-medium text-gray-900 dark:text-gray-100">
                      {vehicleRegistration}
                    </span>
                  </div>
                )}
                <div className="flex justify-between">
                  <span className="text-gray-500 dark:text-gray-400">Service</span>
                  <span className="font-medium text-gray-900 dark:text-gray-100">
                    {serviceType || description.slice(0, 30)}
                  </span>
                </div>
                {parts.length > 0 && (
                  <div className="flex justify-between">
                    <span className="text-gray-500 dark:text-gray-400">Parts ({parts.length})</span>
                    <span className="font-medium text-gray-900 dark:text-gray-100">
                      {formatNZD(partsTotal)}
                    </span>
                  </div>
                )}
                {labourEntries.length > 0 && (
                  <div className="flex justify-between">
                    <span className="text-gray-500 dark:text-gray-400">
                      Labour ({labourEntries.length})
                    </span>
                    <span className="font-medium text-gray-900 dark:text-gray-100">
                      {formatNZD(labourTotal)}
                    </span>
                  </div>
                )}
                <div className="flex justify-between border-t border-gray-200 pt-2 dark:border-gray-600">
                  <span className="font-semibold text-gray-900 dark:text-gray-100">Estimated Total</span>
                  <span className="font-semibold text-gray-900 dark:text-gray-100">
                    {formatNZD(partsTotal + labourTotal)}
                  </span>
                </div>
              </div>
            </Card>

            <Block>
              <HapticButton
                large
                onClick={handleSubmit}
                disabled={isSubmitting}
                className="w-full"
              >
                {isSubmitting ? 'Creating…' : 'Create Job Card'}
              </HapticButton>
            </Block>
          </>
        )}

        {/* ============================================================ */}
        {/* Step navigation footer                                        */}
        {/* ============================================================ */}
        {step < TOTAL_STEPS && (
          <Block>
            <div className="flex gap-3">
              {step > 1 && (
                <Button onClick={goBack} outline className="flex-1">
                  Back
                </Button>
              )}
              <HapticButton onClick={goNext} large className="flex-1">
                Next
              </HapticButton>
            </div>
          </Block>
        )}

        {/* Customer picker */}
        <CustomerPicker
          isOpen={showCustomerPicker}
          onClose={() => setShowCustomerPicker(false)}
          onSelect={handleCustomerSelect}
        />
      </Page>
    </ModuleGate>
  )
}
