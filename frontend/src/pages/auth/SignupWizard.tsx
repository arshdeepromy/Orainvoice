import { useState, useEffect, useMemo } from 'react'
import { loadStripe, type Stripe } from '@stripe/stripe-js'
import apiClient from '@/api/client'
import { AlertBanner } from '@/components/ui'
import { SignupForm } from './SignupForm'
import { PaymentStep } from './PaymentStep'
import { ConfirmationStep } from './ConfirmationStep'
import { usePlatformBranding } from '@/contexts/PlatformBrandingContext'
import type { SignupResponse, PublicPlan } from './signup-types'

export type WizardStep = 'form' | 'payment' | 'done'

interface StepIndicatorProps {
  currentStep: WizardStep
  totalSteps: number
}

function StepIndicator({ currentStep, totalSteps }: StepIndicatorProps) {
  const stepIndex = currentStep === 'form' ? 0 : currentStep === 'payment' ? 1 : totalSteps - 1

  const labels =
    totalSteps === 3
      ? ['Account details', 'Payment', 'Confirmation']
      : ['Account details', 'Confirmation']

  return (
    <div className="mb-8" role="navigation" aria-label="Signup progress">
      <div className="flex items-center justify-between">
        {labels.map((label, i) => {
          const isActive = i === stepIndex
          const isCompleted = i < stepIndex
          return (
            <div key={label} className="flex flex-1 items-center">
              <div className="flex flex-col items-center flex-1">
                <div
                  className={`flex h-8 w-8 items-center justify-center rounded-full text-sm font-medium transition-colors duration-200 ${
                    isActive
                      ? 'bg-blue-600 text-white'
                      : isCompleted
                        ? 'bg-blue-100 text-blue-600'
                        : 'bg-gray-200 text-gray-500'
                  }`}
                  aria-current={isActive ? 'step' : undefined}
                >
                  {isCompleted ? '✓' : i + 1}
                </div>
                <span
                  className={`mt-1 text-xs ${
                    isActive ? 'font-semibold text-blue-600' : 'text-gray-500'
                  }`}
                >
                  {label}
                </span>
              </div>
              {i < labels.length - 1 && (
                <div
                  className={`h-0.5 w-full mx-2 ${
                    i < stepIndex ? 'bg-blue-400' : 'bg-gray-200'
                  }`}
                />
              )}
            </div>
          )
        })}
      </div>
    </div>
  )
}

export function SignupWizard() {
  const { branding } = usePlatformBranding()
  const [step, setStep] = useState<WizardStep>('form')
  const [signupResult, setSignupResult] = useState<SignupResponse | null>(null)
  const [selectedPlan, setSelectedPlan] = useState<PublicPlan | null>(null)
  const [stripePromise, setStripePromise] = useState<Promise<Stripe | null> | null>(null)
  const [resetMessage, setResetMessage] = useState<string | null>(null)

  // Load Stripe publishable key from the backend on mount
  useEffect(() => {
    async function loadStripeKey() {
      try {
        const res = await apiClient.get<{ publishable_key: string }>('/auth/stripe-publishable-key')
        if (res.data.publishable_key) {
          setStripePromise(loadStripe(res.data.publishable_key))
        }
      } catch {
        // Stripe not configured — payment step will show a fallback
      }
    }
    loadStripeKey()
  }, [])

  // Determine total steps: 3 for paid plans (form → payment → done), 2 for trial (form → done)
  const totalSteps = useMemo(() => {
    if (signupResult?.requires_payment) return 3
    if (selectedPlan && selectedPlan.trial_duration > 0) return 2
    return 3 // default to 3 until we know
  }, [signupResult, selectedPlan])

  const slideOffset = step === 'form' ? 0 : step === 'payment' ? -100 : -200

  function handleSignupComplete(result: SignupResponse, plan: PublicPlan | null) {
    setSignupResult(result)
    setSelectedPlan(plan)
    setResetMessage(null)
    if (result.requires_payment && result.stripe_client_secret) {
      setStep('payment')
    } else {
      setStep('done')
    }
  }

  function handlePaymentComplete() {
    setStep('done')
  }

  function handleResetToForm(message?: string) {
    setStep('form')
    setSignupResult(null)
    setResetMessage(message ?? null)
  }

  return (
    <div className="mx-auto max-w-lg py-12 px-4">
      {branding.logo_url && (
        <img src={branding.logo_url} alt={branding.platform_name} className="mx-auto h-12 mb-4 object-contain" />
      )}
      <StepIndicator currentStep={step} totalSteps={totalSteps} />

      {/* Step 1: Signup Form */}
      {step === 'form' && (
        <div>
          {resetMessage && (
            <AlertBanner
              variant="warning"
              onDismiss={() => setResetMessage(null)}
              className="mb-4"
            >
              {resetMessage}
            </AlertBanner>
          )}
          <SignupForm onComplete={handleSignupComplete} />
        </div>
      )}

      {/* Step 2: Payment */}
      {step === 'payment' && (
        <div data-testid="payment-step">
          {signupResult?.stripe_client_secret && signupResult?.pending_signup_id && (
            <PaymentStep
              pendingSignupId={signupResult.pending_signup_id}
              clientSecret={signupResult.stripe_client_secret}
              planName={signupResult.plan_name ?? selectedPlan?.name ?? 'Selected'}
              paymentAmountCents={signupResult.payment_amount_cents}
              planAmountCents={signupResult.plan_amount_cents}
              gstAmountCents={signupResult.gst_amount_cents}
              gstPercentage={signupResult.gst_percentage}
              processingFeeCents={signupResult.processing_fee_cents}
              stripePromise={stripePromise}
              onComplete={handlePaymentComplete}
              onSessionExpired={(message) => handleResetToForm(message)}
            />
          )}
        </div>
      )}

      {/* Step 3: Confirmation */}
      {step === 'done' && (
        <div data-testid="confirmation-step">
          <ConfirmationStep email={signupResult?.admin_email ?? ''} />
        </div>
      )}
    </div>
  )
}
