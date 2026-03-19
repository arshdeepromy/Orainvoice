import { useState, useEffect } from 'react'

/* ── Types ── */

export interface StripeSetupProgress {
  /** Whether publishable + secret keys have been saved */
  apiKeysSaved: boolean
  /** Whether API keys have been tested successfully */
  apiKeysTested: boolean
  /** Whether the webhook endpoint URL is configured */
  webhookEndpointSet: boolean
  /** Whether the webhook signing secret has been saved */
  signingSecretSaved: boolean
  /** Whether the platform/webhook config has been saved and tested */
  connectionTested: boolean
}

interface StripeSetupGuideProps {
  progress: StripeSetupProgress
}

const STORAGE_KEY = 'stripe-setup-guide-dismissed'

const WEBHOOK_EVENTS = [
  'invoice.created',
  'invoice.payment_succeeded',
  'invoice.payment_failed',
  'customer.subscription.updated',
  'customer.subscription.deleted',
  'customer.updated',
  'setup_intent.succeeded',
]

interface Step {
  number: number
  title: string
  explanation: string
  content?: React.ReactNode
  isComplete: (progress: StripeSetupProgress) => boolean
}

const STEPS: Step[] = [
  {
    number: 1,
    title: 'Create a Stripe account',
    explanation:
      'You need a Stripe account to process payments. If you already have one, skip to the next step.',
    content: (
      <a
        href="https://dashboard.stripe.com/register"
        target="_blank"
        rel="noopener noreferrer"
        className="inline-flex items-center gap-1 text-sm text-blue-600 hover:text-blue-800 underline"
      >
        Open Stripe Dashboard
        <svg className="h-4 w-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" aria-hidden="true">
          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M10 6H6a2 2 0 00-2 2v10a2 2 0 002 2h10a2 2 0 002-2v-4M14 4h6m0 0v6m0-6L10 14" />
        </svg>
      </a>
    ),
    isComplete: () => false, // Manual step — never auto-checked
  },
  {
    number: 2,
    title: 'Add your API keys',
    explanation:
      'Copy the Publishable key and Secret key from Stripe Dashboard → Developers → API keys, then paste them into the API Keys section below.',
    isComplete: (p) => p.apiKeysSaved,
  },
  {
    number: 3,
    title: 'Test the API keys',
    explanation:
      'Click "Test API keys" to verify the keys are valid. A successful test confirms the backend can communicate with Stripe.',
    isComplete: (p) => p.apiKeysTested,
  },
  {
    number: 4,
    title: 'Set up the webhook endpoint',
    explanation:
      'In Stripe Dashboard → Developers → Webhooks → Add endpoint, paste the Webhook endpoint URL shown in the Platform & Webhooks section below. This lets Stripe notify your app about payment events.',
    isComplete: (p) => p.webhookEndpointSet,
  },
  {
    number: 5,
    title: 'Add the webhook signing secret',
    explanation:
      'Copy the Webhook signing secret (whsec_...) from Stripe and paste it into the Signing secret field. The signing secret lets us verify that webhook calls are genuinely from Stripe.',
    isComplete: (p) => p.signingSecretSaved,
  },
  {
    number: 6,
    title: 'Subscribe to webhook events',
    explanation:
      'In the Stripe webhook settings, subscribe to the following events so your app receives the notifications it needs:',
    content: (
      <ul className="mt-1 space-y-0.5">
        {WEBHOOK_EVENTS.map((evt) => (
          <li key={evt} className="text-sm text-gray-600 font-mono">
            {evt}
          </li>
        ))}
      </ul>
    ),
    isComplete: () => false, // Manual step — never auto-checked
  },
  {
    number: 7,
    title: 'Save and test the connection',
    explanation:
      'Save the Platform & Webhooks configuration and click "Test connection" to verify everything is wired up correctly.',
    isComplete: (p) => p.connectionTested,
  },
]

export function StripeSetupGuide({ progress }: StripeSetupGuideProps) {
  const [dismissed, setDismissed] = useState(() => {
    try {
      return localStorage.getItem(STORAGE_KEY) === 'true'
    } catch {
      return false
    }
  })

  const [collapsed, setCollapsed] = useState(false)

  // Persist dismissed state
  useEffect(() => {
    try {
      localStorage.setItem(STORAGE_KEY, String(dismissed))
    } catch {
      // localStorage unavailable — ignore
    }
  }, [dismissed])

  if (dismissed) return null

  const completedCount = STEPS.filter((s) => s.isComplete(progress)).length
  const totalCheckable = STEPS.filter((s) => {
    // Steps that can be auto-checked (not always-false manual steps)
    // We test with a "fully complete" progress to see if the step can ever be true
    const allTrue: StripeSetupProgress = {
      apiKeysSaved: true,
      apiKeysTested: true,
      webhookEndpointSet: true,
      signingSecretSaved: true,
      connectionTested: true,
    }
    return s.isComplete(allTrue)
  }).length

  return (
    <div className="rounded-lg border border-blue-200 bg-blue-50 mb-5" role="region" aria-label="Stripe setup guide">
      {/* Header */}
      <div className="flex items-center justify-between px-5 py-3">
        <button
          type="button"
          onClick={() => setCollapsed((c) => !c)}
          className="flex items-center gap-2 text-left focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-blue-500 focus-visible:ring-offset-2 rounded"
          aria-expanded={!collapsed}
        >
          <svg
            className={`h-5 w-5 text-blue-500 transition-transform ${collapsed ? '' : 'rotate-180'}`}
            xmlns="http://www.w3.org/2000/svg"
            viewBox="0 0 20 20"
            fill="currentColor"
            aria-hidden="true"
          >
            <path
              fillRule="evenodd"
              d="M5.23 7.21a.75.75 0 011.06.02L10 11.168l3.71-3.938a.75.75 0 111.08 1.04l-4.25 4.5a.75.75 0 01-1.08 0l-4.25-4.5a.75.75 0 01.02-1.06z"
              clipRule="evenodd"
            />
          </svg>
          <h3 className="text-md font-semibold text-blue-900">Setup Guide</h3>
          <span className="text-xs text-blue-700">
            {completedCount} of {totalCheckable} steps completed
          </span>
        </button>

        <button
          type="button"
          onClick={() => setDismissed(true)}
          className="text-blue-400 hover:text-blue-600 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-blue-500 rounded p-1"
          aria-label="Dismiss setup guide"
        >
          <svg className="h-5 w-5" fill="none" viewBox="0 0 24 24" stroke="currentColor" aria-hidden="true">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M6 18L18 6M6 6l12 12" />
          </svg>
        </button>
      </div>

      {/* Steps */}
      {!collapsed && (
        <ol className="px-5 pb-4 space-y-3" aria-label="Setup steps">
          {STEPS.map((step) => {
            const done = step.isComplete(progress)
            return (
              <li key={step.number} className="flex gap-3">
                {/* Step indicator */}
                <div className="flex-shrink-0 mt-0.5">
                  {done ? (
                    <span
                      className="flex h-6 w-6 items-center justify-center rounded-full bg-green-500 text-white"
                      aria-label={`Step ${step.number} complete`}
                    >
                      <svg className="h-4 w-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" aria-hidden="true">
                        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2.5} d="M5 13l4 4L19 7" />
                      </svg>
                    </span>
                  ) : (
                    <span
                      className="flex h-6 w-6 items-center justify-center rounded-full border-2 border-blue-300 text-xs font-semibold text-blue-700"
                      aria-label={`Step ${step.number}`}
                    >
                      {step.number}
                    </span>
                  )}
                </div>

                {/* Step content */}
                <div className="min-w-0">
                  <p className={`text-sm font-medium ${done ? 'text-green-800 line-through' : 'text-gray-900'}`}>
                    {step.title}
                  </p>
                  <p className="text-sm text-gray-600 mt-0.5">{step.explanation}</p>
                  {step.content && <div className="mt-1">{step.content}</div>}
                </div>
              </li>
            )
          })}
        </ol>
      )}
    </div>
  )
}
