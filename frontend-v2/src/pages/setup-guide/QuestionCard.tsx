import { useCallback, useEffect, useRef, useState } from 'react'

interface QuestionCardProps {
  question: {
    slug: string
    display_name: string
    setup_question: string
    setup_question_description: string | null
    category: string
    dependencies: string[]
  }
  currentIndex: number
  totalQuestions: number
  selectedAnswer: boolean | null
  onAnswer: (enabled: boolean) => void
  onBack: () => void
  dependencyWarning: string | null
}

export default function QuestionCard({
  question,
  currentIndex,
  totalQuestions,
  selectedAnswer,
  onAnswer,
  onBack,
  dependencyWarning,
}: QuestionCardProps) {
  const [pendingAnswer, setPendingAnswer] = useState<boolean | null>(null)
  const timerRef = useRef<ReturnType<typeof setTimeout> | null>(null)

  // Sync pending answer with parent's selectedAnswer when navigating back
  useEffect(() => {
    setPendingAnswer(selectedAnswer)
  }, [selectedAnswer, question.slug])

  // Clean up timer on unmount or when the question changes
  useEffect(() => {
    return () => {
      if (timerRef.current) {
        clearTimeout(timerRef.current)
        timerRef.current = null
      }
    }
  }, [question.slug])

  const handleSelect = useCallback(
    (value: boolean) => {
      // Clear any existing timer (e.g. user changes mind quickly)
      if (timerRef.current) {
        clearTimeout(timerRef.current)
        timerRef.current = null
      }

      // Show highlight immediately
      setPendingAnswer(value)

      // Auto-advance after 400ms
      timerRef.current = setTimeout(() => {
        onAnswer(value)
        timerRef.current = null
      }, 400)
    },
    [onAnswer],
  )

  const displayAnswer = pendingAnswer ?? selectedAnswer
  const progressPercent = totalQuestions > 0 ? ((currentIndex + 1) / totalQuestions) * 100 : 0

  return (
    <div className="bg-canvas flex items-start justify-center px-4 py-12 sm:py-16">
      <div className="w-full max-w-lg">
        <div className="bg-card rounded-card shadow-card border border-border p-6 sm:p-8 space-y-6">
          {/* Progress indicator */}
          <div className="space-y-2">
            <p className="text-xs text-muted text-center">
              Question {currentIndex + 1} of {totalQuestions}
            </p>
            <div
              className="w-full bg-border rounded-full h-2 overflow-hidden"
              role="progressbar"
              aria-valuenow={currentIndex + 1}
              aria-valuemin={1}
              aria-valuemax={totalQuestions}
              aria-label={`Question ${currentIndex + 1} of ${totalQuestions}`}
            >
              <div
                className="bg-accent h-2 rounded-full transition-all duration-300"
                style={{ width: `${progressPercent}%` }}
              />
            </div>
          </div>

          {/* Question heading */}
          <h2 className="text-xl font-bold text-text text-center">
            {question.setup_question}
          </h2>

          {/* Optional description */}
          {question.setup_question_description && (
            <p className="text-sm text-muted text-center leading-relaxed">
              {question.setup_question_description}
            </p>
          )}

          {/* Dependency warning */}
          {dependencyWarning && (
            <div className="flex items-start gap-2 rounded-card bg-warn-soft border border-warn/30 p-3">
              <svg
                className="h-5 w-5 text-warn mt-0.5 shrink-0"
                xmlns="http://www.w3.org/2000/svg"
                viewBox="0 0 20 20"
                fill="currentColor"
                aria-hidden="true"
              >
                <path
                  fillRule="evenodd"
                  d="M8.485 2.495c.673-1.167 2.357-1.167 3.03 0l6.28 10.875c.673 1.167-.17 2.625-1.516 2.625H3.72c-1.347 0-2.189-1.458-1.515-2.625L8.485 2.495zM10 6a.75.75 0 01.75.75v3.5a.75.75 0 01-1.5 0v-3.5A.75.75 0 0110 6zm0 9a1 1 0 100-2 1 1 0 000 2z"
                  clipRule="evenodd"
                />
              </svg>
              <p className="text-sm text-warn">{dependencyWarning}</p>
            </div>
          )}

          {/* Yes / No buttons */}
          <div className="flex gap-4">
            <button
              type="button"
              onClick={() => handleSelect(true)}
              className={`flex-1 py-3 rounded-ctl text-sm font-semibold transition-colors duration-200 border-2 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-offset-2 focus-visible:ring-ok ${
                displayAnswer === true
                  ? 'bg-ok border-ok text-white'
                  : 'bg-card border-border text-text hover:border-ok hover:text-ok'
              }`}
              aria-pressed={displayAnswer === true}
            >
              Yes
            </button>
            <button
              type="button"
              onClick={() => handleSelect(false)}
              className={`flex-1 py-3 rounded-ctl text-sm font-semibold transition-colors duration-200 border-2 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-offset-2 focus-visible:ring-muted-2 ${
                displayAnswer === false
                  ? 'bg-muted border-muted text-white'
                  : 'bg-card border-border text-text hover:border-border-strong'
              }`}
              aria-pressed={displayAnswer === false}
            >
              No
            </button>
          </div>

          {/* Back button */}
          <div className="flex justify-center">
            <button
              type="button"
              onClick={onBack}
              disabled={currentIndex === 0}
              className="text-sm text-muted hover:text-text disabled:opacity-40 disabled:cursor-not-allowed transition-colors"
              aria-label="Go back to previous question"
            >
              ← Back
            </button>
          </div>
        </div>
      </div>
    </div>
  )
}
