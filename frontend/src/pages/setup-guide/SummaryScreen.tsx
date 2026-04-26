import { useMemo } from 'react'
import { Button } from '@/components/ui/Button'

interface SummaryQuestion {
  slug: string
  display_name: string
  setup_question: string
  setup_question_description: string | null
  category: string
  dependencies: string[]
}

interface SummaryScreenProps {
  questions: SummaryQuestion[]
  answers: Record<string, boolean>
  autoEnabled: string[]
  onConfirm: () => void
  onGoBack: () => void
  isSubmitting: boolean
  error: string | null
}

export default function SummaryScreen({
  questions,
  answers,
  autoEnabled,
  onConfirm,
  onGoBack,
  isSubmitting,
  error,
}: SummaryScreenProps) {
  const safeQuestions = questions ?? []
  const safeAutoEnabled = autoEnabled ?? []

  // Group modules by category
  const grouped = useMemo(() => {
    const groups: Record<string, SummaryQuestion[]> = {}
    for (const q of safeQuestions) {
      const cat = q.category ?? 'Other'
      if (!groups[cat]) {
        groups[cat] = []
      }
      groups[cat].push(q)
    }
    return groups
  }, [safeQuestions])

  const enabledCount = safeQuestions.filter((q) => answers[q.slug] === true).length
  const skippedCount = safeQuestions.filter((q) => answers[q.slug] !== true).length

  return (
    <div className="bg-gray-50 flex items-start justify-center px-4 py-12 sm:py-16">
      <div className="w-full max-w-lg">
        <div className="bg-white rounded-xl shadow-sm border border-gray-200 p-6 sm:p-8 space-y-6">
          {/* Heading */}
          <div className="text-center space-y-2">
            <h2 className="text-2xl font-bold text-gray-900">Review Your Choices</h2>
            <p className="text-sm text-gray-600">
              {enabledCount} module{enabledCount !== 1 ? 's' : ''} enabled,{' '}
              {skippedCount} skipped
            </p>
          </div>

          {/* Grouped module list */}
          <div className="space-y-5">
            {Object.entries(grouped).map(([category, modules]) => (
              <div key={category}>
                <h3 className="text-xs font-semibold text-gray-500 uppercase tracking-wider mb-2">
                  {category}
                </h3>
                <ul className="space-y-1" role="list">
                  {(modules ?? []).map((mod) => {
                    const enabled = answers[mod.slug] === true
                    const isAutoEnabled = safeAutoEnabled.includes(mod.slug)

                    return (
                      <li
                        key={mod.slug}
                        className="flex items-center gap-2 py-1.5 text-sm"
                      >
                        {enabled ? (
                          <span
                            className="text-green-600 font-bold text-base leading-none"
                            aria-hidden="true"
                          >
                            ✓
                          </span>
                        ) : (
                          <span
                            className="text-gray-400 font-bold text-base leading-none"
                            aria-hidden="true"
                          >
                            —
                          </span>
                        )}
                        <span
                          className={
                            enabled ? 'text-gray-900' : 'text-gray-500'
                          }
                        >
                          {mod.display_name}
                        </span>
                        {isAutoEnabled && (
                          <span className="inline-flex items-center rounded-full bg-blue-50 px-2 py-0.5 text-xs font-medium text-blue-700">
                            auto-enabled
                          </span>
                        )}
                        <span className="sr-only">
                          {enabled ? 'Enabled' : 'Skipped'}
                          {isAutoEnabled ? ', auto-enabled as a dependency' : ''}
                        </span>
                      </li>
                    )
                  })}
                </ul>
              </div>
            ))}
          </div>

          {/* Error message */}
          {error && (
            <div
              className="flex items-start gap-2 rounded-lg bg-red-50 border border-red-200 p-3"
              role="alert"
            >
              <svg
                className="h-5 w-5 text-red-500 mt-0.5 shrink-0"
                xmlns="http://www.w3.org/2000/svg"
                viewBox="0 0 20 20"
                fill="currentColor"
                aria-hidden="true"
              >
                <path
                  fillRule="evenodd"
                  d="M10 18a8 8 0 100-16 8 8 0 000 16zM8.28 7.22a.75.75 0 00-1.06 1.06L8.94 10l-1.72 1.72a.75.75 0 101.06 1.06L10 11.06l1.72 1.72a.75.75 0 101.06-1.06L11.06 10l1.72-1.72a.75.75 0 00-1.06-1.06L10 8.94 8.28 7.22z"
                  clipRule="evenodd"
                />
              </svg>
              <p className="text-sm text-red-800">
                {error} — click Confirm to retry.
              </p>
            </div>
          )}

          {/* Action buttons */}
          <div className="flex gap-3">
            <Button
              variant="secondary"
              size="lg"
              onClick={onGoBack}
              disabled={isSubmitting}
              className="flex-1"
            >
              Go Back
            </Button>
            <Button
              variant="primary"
              size="lg"
              onClick={onConfirm}
              loading={isSubmitting}
              className="flex-1"
            >
              Confirm
            </Button>
          </div>
        </div>
      </div>
    </div>
  )
}
