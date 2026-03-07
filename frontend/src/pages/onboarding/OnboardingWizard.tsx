import React, { useState } from 'react'
import { Button } from '../../components/ui/Button'
import { Input } from '../../components/ui/Input'
import { Select } from '../../components/ui/Select'
import apiClient from '../../api/client'

/* ------------------------------------------------------------------ */
/*  Types                                                              */
/* ------------------------------------------------------------------ */

interface OrgContactData {
  name: string
  address: string
  phone: string
  email: string
}

interface BrandingData {
  logoFile: File | null
  primaryColour: string
  secondaryColour: string
}

interface GstData {
  gstNumber: string
  gstPercentage: string
  gstInclusive: boolean
}

interface InvoiceData {
  invoicePrefix: string
  startingNumber: string
}

interface PaymentTermsData {
  defaultDueDays: string
  paymentTermsText: string
}

interface ServiceTypeData {
  serviceName: string
  servicePrice: string
  serviceCategory: string
}

type StepData =
  | OrgContactData
  | BrandingData
  | GstData
  | InvoiceData
  | PaymentTermsData
  | ServiceTypeData

const STEP_LABELS = [
  'Organisation Details',
  'Branding',
  'GST Settings',
  'Invoice Numbering',
  'Payment Terms',
  'First Service',
] as const

const TOTAL_STEPS = STEP_LABELS.length

const SERVICE_CATEGORIES = [
  { value: 'warrant', label: 'Warrant' },
  { value: 'service', label: 'Service' },
  { value: 'repair', label: 'Repair' },
  { value: 'diagnostic', label: 'Diagnostic' },
]

/* ------------------------------------------------------------------ */
/*  Progress Indicator                                                 */
/* ------------------------------------------------------------------ */

function ProgressIndicator({ current, total }: { current: number; total: number }) {
  return (
    <div className="mb-8">
      <div className="flex items-center justify-between mb-2">
        <span className="text-sm font-medium text-gray-700">
          Step {current + 1} of {total}
        </span>
        <span className="text-sm text-gray-500">{STEP_LABELS[current]}</span>
      </div>
      <div className="flex gap-1.5" role="progressbar" aria-valuenow={current + 1} aria-valuemin={1} aria-valuemax={total}>
        {Array.from({ length: total }, (_, i) => (
          <div
            key={i}
            className={`h-2 flex-1 rounded-full transition-colors ${
              i <= current ? 'bg-blue-600' : 'bg-gray-200'
            }`}
          />
        ))}
      </div>
    </div>
  )
}

/* ------------------------------------------------------------------ */
/*  Step Components                                                    */
/* ------------------------------------------------------------------ */

function StepOrgContact({
  data,
  onChange,
}: {
  data: OrgContactData
  onChange: (d: OrgContactData) => void
}) {
  return (
    <div className="space-y-4">
      <h2 className="text-xl font-semibold text-gray-900">Organisation Details</h2>
      <p className="text-sm text-gray-500">Enter your workshop's contact information.</p>
      <Input
        label="Organisation Name"
        value={data.name}
        onChange={(e) => onChange({ ...data, name: e.target.value })}
        placeholder="e.g. Smith's Auto Workshop"
      />
      <Input
        label="Address"
        value={data.address}
        onChange={(e) => onChange({ ...data, address: e.target.value })}
        placeholder="123 Main Street, Auckland"
      />
      <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
        <Input
          label="Phone"
          type="tel"
          value={data.phone}
          onChange={(e) => onChange({ ...data, phone: e.target.value })}
          placeholder="+64 9 123 4567"
        />
        <Input
          label="Email"
          type="email"
          value={data.email}
          onChange={(e) => onChange({ ...data, email: e.target.value })}
          placeholder="info@workshop.co.nz"
        />
      </div>
    </div>
  )
}

function StepBranding({
  data,
  onChange,
}: {
  data: BrandingData
  onChange: (d: BrandingData) => void
}) {
  const handleFileChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0] ?? null
    onChange({ ...data, logoFile: file })
  }

  return (
    <div className="space-y-4">
      <h2 className="text-xl font-semibold text-gray-900">Branding</h2>
      <p className="text-sm text-gray-500">Upload your logo and choose brand colours.</p>
      <div className="flex flex-col gap-1">
        <label htmlFor="logo-upload" className="text-sm font-medium text-gray-700">
          Logo (PNG or SVG)
        </label>
        <input
          id="logo-upload"
          type="file"
          accept=".png,.svg,image/png,image/svg+xml"
          onChange={handleFileChange}
          className="block w-full text-sm text-gray-500 file:mr-4 file:py-2 file:px-4
            file:rounded-md file:border-0 file:text-sm file:font-medium
            file:bg-blue-50 file:text-blue-700 hover:file:bg-blue-100"
        />
        {data.logoFile && (
          <p className="text-xs text-gray-500">Selected: {data.logoFile.name}</p>
        )}
      </div>
      <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
        <div className="flex flex-col gap-1">
          <label htmlFor="primary-colour" className="text-sm font-medium text-gray-700">
            Primary Colour
          </label>
          <div className="flex items-center gap-3">
            <input
              id="primary-colour"
              type="color"
              value={data.primaryColour}
              onChange={(e) => onChange({ ...data, primaryColour: e.target.value })}
              className="h-10 w-14 cursor-pointer rounded border border-gray-300"
            />
            <span className="text-sm text-gray-500">{data.primaryColour}</span>
          </div>
        </div>
        <div className="flex flex-col gap-1">
          <label htmlFor="secondary-colour" className="text-sm font-medium text-gray-700">
            Secondary Colour
          </label>
          <div className="flex items-center gap-3">
            <input
              id="secondary-colour"
              type="color"
              value={data.secondaryColour}
              onChange={(e) => onChange({ ...data, secondaryColour: e.target.value })}
              className="h-10 w-14 cursor-pointer rounded border border-gray-300"
            />
            <span className="text-sm text-gray-500">{data.secondaryColour}</span>
          </div>
        </div>
      </div>
    </div>
  )
}

function StepGst({
  data,
  onChange,
}: {
  data: GstData
  onChange: (d: GstData) => void
}) {
  return (
    <div className="space-y-4">
      <h2 className="text-xl font-semibold text-gray-900">GST Settings</h2>
      <p className="text-sm text-gray-500">Configure your GST details for NZ tax compliance.</p>
      <Input
        label="GST Number (IRD format)"
        value={data.gstNumber}
        onChange={(e) => onChange({ ...data, gstNumber: e.target.value })}
        placeholder="123-456-789"
        helperText="8 or 9 digit IRD number, e.g. 12-345-678 or 123-456-789"
      />
      <Input
        label="GST Percentage"
        type="number"
        value={data.gstPercentage}
        onChange={(e) => onChange({ ...data, gstPercentage: e.target.value })}
        placeholder="15"
        helperText="Default NZ GST rate is 15%"
      />
      <div className="flex items-center gap-3">
        <button
          type="button"
          role="switch"
          aria-checked={data.gstInclusive}
          onClick={() => onChange({ ...data, gstInclusive: !data.gstInclusive })}
          className={`relative inline-flex h-6 w-11 shrink-0 cursor-pointer rounded-full border-2 border-transparent transition-colors ${
            data.gstInclusive ? 'bg-blue-600' : 'bg-gray-200'
          }`}
        >
          <span
            className={`pointer-events-none inline-block h-5 w-5 rounded-full bg-white shadow ring-0 transition-transform ${
              data.gstInclusive ? 'translate-x-5' : 'translate-x-0'
            }`}
          />
        </button>
        <span className="text-sm font-medium text-gray-700">
          {data.gstInclusive ? 'GST Inclusive' : 'GST Exclusive'}
        </span>
      </div>
    </div>
  )
}

function StepInvoice({
  data,
  onChange,
}: {
  data: InvoiceData
  onChange: (d: InvoiceData) => void
}) {
  return (
    <div className="space-y-4">
      <h2 className="text-xl font-semibold text-gray-900">Invoice Numbering</h2>
      <p className="text-sm text-gray-500">Set up your invoice number format.</p>
      <Input
        label="Invoice Prefix"
        value={data.invoicePrefix}
        onChange={(e) => onChange({ ...data, invoicePrefix: e.target.value })}
        placeholder="INV-"
        helperText='e.g. "INV-", "WS-"'
      />
      <Input
        label="Starting Number"
        type="number"
        value={data.startingNumber}
        onChange={(e) => onChange({ ...data, startingNumber: e.target.value })}
        placeholder="1"
        helperText="First invoice will use this number"
      />
      {data.invoicePrefix && data.startingNumber && (
        <p className="text-sm text-gray-500">
          Preview: <span className="font-mono font-medium text-gray-900">{data.invoicePrefix}{data.startingNumber}</span>
        </p>
      )}
    </div>
  )
}

function StepPaymentTerms({
  data,
  onChange,
}: {
  data: PaymentTermsData
  onChange: (d: PaymentTermsData) => void
}) {
  return (
    <div className="space-y-4">
      <h2 className="text-xl font-semibold text-gray-900">Payment Terms</h2>
      <p className="text-sm text-gray-500">Configure default payment terms for your invoices.</p>
      <Input
        label="Default Due Days"
        type="number"
        value={data.defaultDueDays}
        onChange={(e) => onChange({ ...data, defaultDueDays: e.target.value })}
        placeholder="14"
        helperText="Number of days from issue date until payment is due"
      />
      <div className="flex flex-col gap-1">
        <label htmlFor="payment-terms-text" className="text-sm font-medium text-gray-700">
          Payment Terms Text
        </label>
        <textarea
          id="payment-terms-text"
          value={data.paymentTermsText}
          onChange={(e) => onChange({ ...data, paymentTermsText: e.target.value })}
          placeholder="Payment is due within 14 days of invoice date. Late payments may incur additional charges."
          rows={3}
          className="rounded-md border border-gray-300 px-3 py-2 text-gray-900 shadow-sm
            placeholder:text-gray-400 focus:outline-none focus:ring-2 focus:ring-blue-500 focus:border-blue-500"
        />
        <p className="text-sm text-gray-500">This text appears on your invoice PDFs.</p>
      </div>
    </div>
  )
}

function StepServiceType({
  data,
  onChange,
}: {
  data: ServiceTypeData
  onChange: (d: ServiceTypeData) => void
}) {
  return (
    <div className="space-y-4">
      <h2 className="text-xl font-semibold text-gray-900">First Service Type</h2>
      <p className="text-sm text-gray-500">Add your first service to the catalogue. You can add more later.</p>
      <Input
        label="Service Name"
        value={data.serviceName}
        onChange={(e) => onChange({ ...data, serviceName: e.target.value })}
        placeholder="e.g. WOF Inspection"
      />
      <Input
        label="Price (ex-GST, NZD)"
        type="number"
        value={data.servicePrice}
        onChange={(e) => onChange({ ...data, servicePrice: e.target.value })}
        placeholder="55.00"
      />
      <Select
        label="Category"
        options={SERVICE_CATEGORIES}
        value={data.serviceCategory}
        onChange={(e) => onChange({ ...data, serviceCategory: e.target.value })}
        placeholder="Select a category"
      />
    </div>
  )
}

/* ------------------------------------------------------------------ */
/*  API helpers                                                        */
/* ------------------------------------------------------------------ */

async function saveStep(step: number, data: StepData): Promise<void> {
  const payloads: Record<number, { step: string; payload: Record<string, unknown> }> = {
    0: {
      step: 'org_contact',
      payload: data as unknown as Record<string, unknown>,
    },
    1: {
      step: 'branding',
      payload: (() => {
        const d = data as BrandingData
        return { primaryColour: d.primaryColour, secondaryColour: d.secondaryColour }
      })(),
    },
    2: {
      step: 'gst',
      payload: data as unknown as Record<string, unknown>,
    },
    3: {
      step: 'invoice_numbering',
      payload: data as unknown as Record<string, unknown>,
    },
    4: {
      step: 'payment_terms',
      payload: data as unknown as Record<string, unknown>,
    },
    5: {
      step: 'first_service',
      payload: data as unknown as Record<string, unknown>,
    },
  }

  const { step: stepName, payload } = payloads[step]

  // Logo upload needs FormData
  if (step === 1) {
    const d = data as BrandingData
    if (d.logoFile) {
      const formData = new FormData()
      formData.append('logo', d.logoFile)
      formData.append('primaryColour', d.primaryColour)
      formData.append('secondaryColour', d.secondaryColour)
      await apiClient.post('/org/onboarding', formData, {
        headers: { 'Content-Type': 'multipart/form-data' },
        params: { step: stepName },
      })
      return
    }
  }

  await apiClient.post('/org/onboarding', { step: stepName, ...payload })
}

/* ------------------------------------------------------------------ */
/*  Main Wizard Component                                              */
/* ------------------------------------------------------------------ */

export function OnboardingWizard() {
  const [currentStep, setCurrentStep] = useState(0)
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState<string | null>(null)

  // Step state
  const [orgContact, setOrgContact] = useState<OrgContactData>({
    name: '',
    address: '',
    phone: '',
    email: '',
  })
  const [branding, setBranding] = useState<BrandingData>({
    logoFile: null,
    primaryColour: '#2563eb',
    secondaryColour: '#1e40af',
  })
  const [gst, setGst] = useState<GstData>({
    gstNumber: '',
    gstPercentage: '15',
    gstInclusive: true,
  })
  const [invoice, setInvoice] = useState<InvoiceData>({
    invoicePrefix: 'INV-',
    startingNumber: '1',
  })
  const [paymentTerms, setPaymentTerms] = useState<PaymentTermsData>({
    defaultDueDays: '14',
    paymentTermsText: '',
  })
  const [serviceType, setServiceType] = useState<ServiceTypeData>({
    serviceName: '',
    servicePrice: '',
    serviceCategory: '',
  })

  const stepDataMap: StepData[] = [orgContact, branding, gst, invoice, paymentTerms, serviceType]

  const isLastStep = currentStep === TOTAL_STEPS - 1

  const handleSaveAndNext = async () => {
    setSaving(true)
    setError(null)
    try {
      await saveStep(currentStep, stepDataMap[currentStep])
      if (isLastStep) {
        // Redirect to dashboard after completing wizard
        window.location.href = '/dashboard'
      } else {
        setCurrentStep((s) => s + 1)
      }
    } catch {
      setError('Failed to save. Please try again.')
    } finally {
      setSaving(false)
    }
  }

  const handleSkip = () => {
    if (isLastStep) {
      window.location.href = '/dashboard'
    } else {
      setCurrentStep((s) => s + 1)
    }
  }

  const handleBack = () => {
    setError(null)
    setCurrentStep((s) => Math.max(0, s - 1))
  }

  const renderStep = () => {
    switch (currentStep) {
      case 0:
        return <StepOrgContact data={orgContact} onChange={setOrgContact} />
      case 1:
        return <StepBranding data={branding} onChange={setBranding} />
      case 2:
        return <StepGst data={gst} onChange={setGst} />
      case 3:
        return <StepInvoice data={invoice} onChange={setInvoice} />
      case 4:
        return <StepPaymentTerms data={paymentTerms} onChange={setPaymentTerms} />
      case 5:
        return <StepServiceType data={serviceType} onChange={setServiceType} />
      default:
        return null
    }
  }

  return (
    <div className="min-h-screen bg-gray-50 flex items-start justify-center px-4 py-12 sm:py-16">
      <div className="w-full max-w-lg">
        <div className="text-center mb-8">
          <h1 className="text-2xl font-bold text-gray-900">Set Up Your Workshop</h1>
          <p className="mt-1 text-sm text-gray-500">
            Complete these steps to get started. You can skip any step and come back later from Settings.
          </p>
        </div>

        <ProgressIndicator current={currentStep} total={TOTAL_STEPS} />

        <div className="bg-white rounded-xl shadow-sm border border-gray-200 p-6 sm:p-8">
          {renderStep()}

          {error && (
            <p className="mt-4 text-sm text-red-600" role="alert">
              {error}
            </p>
          )}

          <div className="mt-8 flex items-center justify-between">
            <div>
              {currentStep > 0 && (
                <Button variant="secondary" size="sm" onClick={handleBack} disabled={saving}>
                  Back
                </Button>
              )}
            </div>
            <div className="flex items-center gap-3">
              <Button variant="secondary" size="sm" onClick={handleSkip} disabled={saving}>
                Skip
              </Button>
              <Button
                variant="primary"
                size="sm"
                onClick={handleSaveAndNext}
                loading={saving}
              >
                {isLastStep ? 'Complete' : 'Next'}
              </Button>
            </div>
          </div>
        </div>
      </div>
    </div>
  )
}
