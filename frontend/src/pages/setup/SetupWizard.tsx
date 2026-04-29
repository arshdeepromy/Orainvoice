import { useState, useEffect, useCallback } from 'react'
import { useNavigate } from 'react-router-dom'
import { Button } from '@/components/ui/Button'
import { Spinner } from '@/components/ui/Spinner'
import apiClient from '@/api/client'
import { StepIndicator, type StepInfo } from './components/StepIndicator'
import { BusinessStep } from './steps/BusinessStep'
import { BrandingStep } from './steps/BrandingStep'
import { CatalogueStep } from './steps/CatalogueStep'
import { ReadyStep } from './steps/ReadyStep'
import { INITIAL_WIZARD_DATA, type WizardData } from './types'

/**
 * The wizard UI has 5 steps (Business, Branding, Modules, Catalogue, Ready).
 * Country and Trade are captured during signup — no need to ask again.
 *
 * Backend step mapping:
 *   UI step 0 (Business)  → backend step 3
 *   UI step 1 (Branding)  → backend step 4
 *   UI step 2 (Modules)   → redirects to /setup-guide
 *   UI step 3 (Catalogue) → backend step 6
 *   UI step 4 (Ready)     → backend step 7
 */

const STEP_LABELS = ['Business Details', 'Branding', 'Modules', 'Catalogue', 'Ready'] as const
const TOTAL_STEPS = STEP_LABELS.length

/** Map UI step index to backend step number. */
function apiStepNumber(uiStep: number): number {
  // UI 0=Business→3, 1=Branding→4, 2=Modules→5, 3=Catalogue→6, 4=Ready→7
  return uiStep + 3
}

/** Map backend step key (step_3..step_7) to UI step index. */
function backendStepToUi(backendStep: number): number {
  return backendStep - 3
}

/** Build the step-specific payload for the backend. */
function buildStepPayload(uiStep: number, data: WizardData): Record<string, unknown> {
  switch (uiStep) {
    case 0: // Business Details → backend step 3
      return {
        business_name: data.businessName,
        trading_name: data.tradingName || null,
        registration_number: data.registrationNumber || null,
        tax_number: data.taxNumber || null,
        phone: data.phone || null,
        address_unit: data.addressUnit || null,
        address_street: data.addressStreet || null,
        address_city: data.addressCity || null,
        address_state: data.addressState || null,
        address_postcode: data.addressPostcode || null,
        website: data.website || null,
      }
    case 1: // Branding → backend step 4
      return {
        logo_url: data.logoUrl || null,
        primary_colour: data.primaryColour,
        secondary_colour: data.secondaryColour,
      }
    case 2: // Modules → backend step 5 (handled by setup guide redirect)
      return { enabled_modules: data.enabledModules }
    case 3: // Catalogue → backend step 6
      return {
        items: data.catalogueItems.map((item) => ({
          name: item.name,
          description: item.description || null,
          price: item.price,
          unit_of_measure: item.unit_of_measure,
          item_type: item.item_type,
        })),
      }
    case 4: // Ready → backend step 7
      return {}
    default:
      return {}
  }
}

export function SetupWizard() {
  const navigate = useNavigate()
  const [currentStep, setCurrentStep] = useState(0)
  const [wizardData, setWizardData] = useState<WizardData>({ ...INITIAL_WIZARD_DATA })
  const [stepStates, setStepStates] = useState<StepInfo[]>(
    STEP_LABELS.map((label) => ({ label, completed: false, skipped: false })),
  )
  const [saving, setSaving] = useState(false)
  const [loadingProgress, setLoadingProgress] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [businessErrors, setBusinessErrors] = useState<Record<string, string>>({})

  // Load existing progress on mount
  useEffect(() => {
    const loadProgress = async () => {
      try {
        const res = await apiClient.get('/api/v2/setup-wizard/progress')
        const progress = res.data
        if (progress?.steps) {
          const newStates = [...stepStates]
          // Map backend steps 3-7 to UI steps 0-4
          for (let uiIdx = 0; uiIdx < TOTAL_STEPS; uiIdx++) {
            const backendKey = `step_${uiIdx + 3}`
            if (progress.steps[backendKey]) {
              newStates[uiIdx] = { ...newStates[uiIdx], completed: true }
            }
          }
          setStepStates(newStates)
          // Resume from first incomplete step
          const firstIncomplete = newStates.findIndex((s) => !s.completed)
          if (firstIncomplete >= 0) {
            setCurrentStep(firstIncomplete)
          } else if (progress.wizard_completed) {
            setCurrentStep(TOTAL_STEPS - 1)
          }
        }
      } catch {
        // No progress yet — start from beginning
      } finally {
        setLoadingProgress(false)
      }
    }
    loadProgress()
  }, [])

  // Redirect to setup guide when wizard reaches Modules step (UI step 2)
  useEffect(() => {
    if (!loadingProgress && currentStep === 2) {
      navigate('/setup-guide')
    }
  }, [currentStep, loadingProgress, navigate])

  const updateWizardData = useCallback((updates: Partial<WizardData>) => {
    setWizardData((prev) => ({ ...prev, ...updates }))
  }, [])

  const validateBusinessStep = (): boolean => {
    const errors: Record<string, string> = {}
    if (!wizardData.businessName.trim()) {
      errors.businessName = 'Business name is required'
    }
    setBusinessErrors(errors)
    return Object.keys(errors).length === 0
  }

  const submitStep = async (skip: boolean) => {
    setSaving(true)
    setError(null)

    // Validate business step before submission
    if (currentStep === 0 && !skip && !validateBusinessStep()) {
      setSaving(false)
      return
    }

    try {
      // For branding step: upload logo file to server first (blob URLs don't persist)
      let stepData = skip ? {} : buildStepPayload(currentStep, wizardData)
      if (currentStep === 1 && !skip && wizardData.logoFile) {
        const formData = new FormData()
        formData.append('file', wizardData.logoFile)
        const uploadRes = await apiClient.post('/api/v2/setup-wizard/upload-logo', formData, {
          headers: { 'Content-Type': 'multipart/form-data' },
        })
        const serverUrl = uploadRes.data?.url ?? ''
        if (serverUrl) {
          stepData = { ...stepData, logo_url: serverUrl }
          updateWizardData({ logoUrl: serverUrl })
        }
      }

      await apiClient.post(`/api/v2/setup-wizard/step/${apiStepNumber(currentStep)}`, {
        data: stepData,
        skip,
      })

      // Update step state
      const newStates = [...stepStates]
      newStates[currentStep] = {
        ...newStates[currentStep],
        completed: !skip,
        skipped: skip,
      }
      setStepStates(newStates)

      // Navigate
      if (currentStep < TOTAL_STEPS - 1) {
        setCurrentStep((s) => s + 1)
      } else {
        // Wizard complete — redirect to dashboard
        window.location.href = '/dashboard'
      }
    } catch (err: unknown) {
      const detail = (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail
      const message = detail ?? (err instanceof Error ? err.message : 'Failed to save. Please try again.')
      setError(message)
    } finally {
      setSaving(false)
    }
  }

  const handleNext = () => submitStep(false)
  const handleSkip = () => submitStep(true)

  const handleBack = () => {
    setError(null)
    setBusinessErrors({})
    setCurrentStep((s) => Math.max(0, s - 1))
  }

  const goToStep = (step: number) => {
    setError(null)
    setBusinessErrors({})
    setCurrentStep(step)
  }

  if (loadingProgress) {
    return (
      <div className="bg-gray-50 flex items-center justify-center py-20">
        <Spinner label="Loading setup wizard" />
      </div>
    )
  }

  const isLastStep = currentStep === TOTAL_STEPS - 1

  const renderStep = () => {
    switch (currentStep) {
      case 0:
        return (
          <BusinessStep
            data={wizardData}
            onChange={updateWizardData}
            errors={businessErrors}
          />
        )
      case 1:
        return <BrandingStep data={wizardData} onChange={updateWizardData} />
      case 2:
        // Modules — handled by redirect to /setup-guide
        return null
      case 3:
        return <CatalogueStep data={wizardData} onChange={updateWizardData} />
      case 4:
        return <ReadyStep data={wizardData} onGoToStep={goToStep} />
      default:
        return null
    }
  }

  return (
    <div className="bg-gray-50 flex items-start justify-center px-4 py-12 sm:py-16">
      <div className="w-full max-w-2xl">
        <div className="text-center mb-8">
          <h1 className="text-2xl font-bold text-gray-900">Set Up Your Business</h1>
          <p className="mt-1 text-sm text-gray-500">
            Complete these steps to configure OraInvoice for your business. Skip any step to come back later.
          </p>
        </div>

        <StepIndicator steps={stepStates} currentStep={currentStep} />

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
              {!isLastStep && (
                <Button variant="secondary" size="sm" onClick={handleSkip} disabled={saving}>
                  Skip
                </Button>
              )}
              <Button
                variant="primary"
                size="sm"
                onClick={handleNext}
                loading={saving}
              >
                {isLastStep ? 'Complete Setup' : 'Next'}
              </Button>
            </div>
          </div>
        </div>
      </div>
    </div>
  )
}
