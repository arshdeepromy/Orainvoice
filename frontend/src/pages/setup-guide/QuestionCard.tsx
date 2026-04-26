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
    <div className="bg-gray-50 flex items-start justify-center px-4 py-12 sm:py-16">
      <div className="w-full max-w-lg">
        <div className="bg-white rounded-xl shadow-sm border border-gray-200 p-6 sm:p-8 space-y-6">
          {/* Progress indicator */}
          <div className="space-y-2">
            <p className="text-xs text-gray-500 text-center">
              Question {currentIndex + 1} of {totalQuestions}
            </p>
            <div
              className="w-full bg-gray-200 rounded-full h-2 overflow-hidden"
              role="progressbar"
              aria-valuenow={currentIndex + 1}
              aria-valuemin={1}
              aria-valuemax={totalQuestions}
              aria-label={`Question ${currentIndex + 1} of ${totalQuestions}`}
            >
              <div
                className="bg-blue-600 h-2 rounded-full transition-all duration-300"
                style={{ width: `${progressPercent}%` }}
              />
            </div>
          </div>

          {/* Question heading */}
          <h2 className="text-xl font-bold text-gray-900 text-center">
            {question.setup_question}
          </h2>

          {/* Optional description */}
          {question.setup_question_description && (
            <p className="text-sm text-gray-600 text-center leading-relaxed">
              {question.setup_question_description}
            </p>
          )}

          {/* Dependency warning */}
          {dependencyWarning && (
            <div className="flex items-start gap-2 rounded-lg bg-amber-50 border border-amber-200 p-3">
              <svg
                className="h-5 w-5 text-amber-500 mt-0.5 shrink-0"
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
              <p className="text-sm text-amber-800">{dependencyWarning}</p>
            </div>
          )}

          {/* Yes / No buttons */}
          <div className="flex gap-4">
            <button
              type="button"
              onClick={() => handleSelect(true)}
              className={`flex-1 py-3 rounded-xl text-sm font-semibold transition-colors duration-200 border-2 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-offset-2 focus-visible:ring-green-500 ${
                displayAnswer === true
                  ? 'bg-green-600 border-green-600 text-white'
                  : 'bg-white border-gray-300 text-gray-700 hover:border-green-400 hover:text-green-700'
              }`}
              aria-pressed={displayAnswer === true}
            >
              Yes
            </button>
            <button
              type="button"
              onClick={() => handleSelect(false)}
              className={`flex-1 py-3 rounded-xl text-sm font-semibold transition-colors duration-200 border-2 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-offset-2 focus-visible:ring-gray-400 ${
                displayAnswer === false
                  ? 'bg-gray-600 border-gray-600 text-white'
                  : 'bg-white border-gray-300 text-gray-700 hover:border-gray-400'
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
              className="text-sm text-gray-500 hover:text-gray-700 disabled:opacity-40 disabled:cursor-not-allowed transition-colors"
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
