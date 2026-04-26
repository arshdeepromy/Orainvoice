import { useState, useEffect, useCallback } from 'react'
import { useNavigate } from 'react-router-dom'
import { Button } from '@/components/ui/Button'
import { Spinner } from '@/components/ui/Spinner'
import apiClient from '@/api/client'
import { StepIndicator, type StepInfo } from './components/StepIndicator'
import { CountryStep } from './steps/CountryStep'
import { TradeStep } from './steps/TradeStep'
import { BusinessStep } from './steps/BusinessStep'
import { BrandingStep } from './steps/BrandingStep'
import { ModulesStep } from './steps/ModulesStep'
import { CatalogueStep } from './steps/CatalogueStep'
import { ReadyStep } from './steps/ReadyStep'
import { STEP_LABELS, INITIAL_WIZARD_DATA, type WizardData } from './types'

const TOTAL_STEPS = STEP_LABELS.length

/** Map step index to the API step number (1-based). */
function apiStepNumber(index: number): number {
  return index + 1
}

/** Build the step-specific payload for the backend. */
function buildStepPayload(step: number, data: WizardData): Record<string, unknown> {
  switch (step) {
    case 0:
      return { country_code: data.countryCode }
    case 1:
      return { trade_category_slug: data.tradeCategorySlug }
    case 2:
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
    case 3:
      return {
        logo_url: data.logoUrl || null,
        primary_colour: data.primaryColour,
        secondary_colour: data.secondaryColour,
      }
    case 4:
      return { enabled_modules: data.enabledModules }
    case 5:
      return {
        items: data.catalogueItems.map((item) => ({
          name: item.name,
          description: item.description || null,
          price: item.price,
          unit_of_measure: item.unit_of_measure,
          item_type: item.item_type,
        })),
      }
    case 6:
      return {} // Ready step — no data to submit
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
          for (let i = 0; i < TOTAL_STEPS; i++) {
            const key = `step_${i + 1}`
            if (progress.steps[key]) {
              newStates[i] = { ...newStates[i], completed: true }
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

  // Redirect to setup guide when wizard reaches Step 5 (Modules)
  useEffect(() => {
    if (!loadingProgress && currentStep === 4) {
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
    if (currentStep === 2 && !skip && !validateBusinessStep()) {
      setSaving(false)
      return
    }

    try {
      await apiClient.post(`/api/v2/setup-wizard/step/${apiStepNumber(currentStep)}`, {
        data: skip ? {} : buildStepPayload(currentStep, wizardData),
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
      const message =
        err instanceof Error ? err.message : 'Failed to save. Please try again.'
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
        return <CountryStep data={wizardData} onChange={updateWizardData} />
      case 1:
        return <TradeStep data={wizardData} onChange={updateWizardData} />
      case 2:
        return (
          <BusinessStep
            data={wizardData}
            onChange={updateWizardData}
            errors={businessErrors}
          />
        )
      case 3:
        return <BrandingStep data={wizardData} onChange={updateWizardData} />
      case 4:
        return <ModulesStep data={wizardData} onChange={updateWizardData} />
      case 5:
        return <CatalogueStep data={wizardData} onChange={updateWizardData} />
      case 6:
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
