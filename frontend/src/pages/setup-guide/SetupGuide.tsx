import { useState, useEffect, useCallback, useMemo } from 'react'
import { useSearchParams, useNavigate } from 'react-router-dom'
import apiClient from '@/api/client'
import { useModules } from '@/contexts/ModuleContext'
import { Spinner } from '@/components/ui/Spinner'
import { Button } from '@/components/ui/Button'
import WelcomeScreen from './WelcomeScreen'
import QuestionCard from './QuestionCard'
import SummaryScreen from './SummaryScreen'

/* ── Types ── */

interface SetupQuestion {
  slug: string
  display_name: string
  setup_question: string
  setup_question_description: string | null
  category: string
  dependencies: string[]
}

interface QuestionsResponse {
  questions: SetupQuestion[]
  total: number
}

interface SubmitResponse {
  completed: boolean
  auto_enabled: string[]
  message: string
}

type GuideState = 'loading' | 'welcome' | 'questions' | 'summary' | 'submitting' | 'success'

/* ── Component ── */

export default function SetupGuide() {
  const [searchParams] = useSearchParams()
  const navigate = useNavigate()
  const { refetch } = useModules()

  const isRerun = searchParams.get('rerun') === 'true'

  /* ── State ── */
  const [state, setState] = useState<GuideState>('loading')
  const [questions, setQuestions] = useState<SetupQuestion[]>([])
  const [answers, setAnswers] = useState<Record<string, boolean>>({})
  const [currentIndex, setCurrentIndex] = useState(0)
  const [autoEnabled, setAutoEnabled] = useState<string[]>([])
  const [error, setError] = useState<string | null>(null)
  const [fetchError, setFetchError] = useState<string | null>(null)

  /* ── Fetch questions ── */
  useEffect(() => {
    const controller = new AbortController()

    const fetchQuestions = async () => {
      setState('loading')
      setFetchError(null)
      try {
        const res = await apiClient.get<QuestionsResponse>('/setup-guide/questions', {
          baseURL: '/api/v2',
          params: isRerun ? { rerun: true } : undefined,
          signal: controller.signal,
        })
        const fetched = res.data?.questions ?? []
        setQuestions(fetched)

        // If rerun and no questions, stay on welcome to show "all enabled" message
        setState('welcome')
      } catch (err: unknown) {
        if (!controller.signal.aborted) {
          setFetchError('Failed to load setup guide questions. Please try again.')
          setState('welcome')
        }
      }
    }

    fetchQuestions()
    return () => controller.abort()
  }, [isRerun])

  /* ── Handlers ── */

  const handleStart = useCallback(() => {
    if (questions.length === 0) return
    setCurrentIndex(0)
    setState('questions')
  }, [questions.length])

  const handleAnswer = useCallback(
    (enabled: boolean) => {
      const q = questions[currentIndex]
      if (!q) return

      setAnswers((prev) => ({ ...prev, [q.slug]: enabled }))

      // Auto-advance to next question or summary
      if (currentIndex < questions.length - 1) {
        setCurrentIndex((i) => i + 1)
      } else {
        setState('summary')
      }
    },
    [currentIndex, questions],
  )

  const handleBack = useCallback(() => {
    if (currentIndex > 0) {
      setCurrentIndex((i) => i - 1)
    }
  }, [currentIndex])

  const handleGoBackFromSummary = useCallback(() => {
    setCurrentIndex(questions.length - 1)
    setState('questions')
  }, [questions.length])

  /* ── Submit ── */
  const handleConfirm = useCallback(async () => {
    setState('submitting')
    setError(null)

    const payload = {
      answers: questions.map((q) => ({
        slug: q.slug,
        enabled: answers[q.slug] === true,
      })),
    }

    try {
      const res = await apiClient.post<SubmitResponse>('/setup-guide/submit', payload, {
        baseURL: '/api/v2',
      })
      setAutoEnabled(res.data?.auto_enabled ?? [])
      setState('success')

      // Refresh sidebar modules
      try {
        await refetch()
      } catch {
        // Non-blocking — modules will refresh on next page load
      }
    } catch {
      setError('Something went wrong while saving your choices. Please try again.')
      setState('summary')
    }
  }, [questions, answers, refetch])

  /* ── Dependency warning computation ── */
  const dependencyWarning = useMemo(() => {
    if (state !== 'questions') return null
    const currentQuestion = questions[currentIndex]
    if (!currentQuestion) return null

    const deps = currentQuestion.dependencies ?? []
    const skippedDeps = deps.filter((depSlug) => answers[depSlug] === false)

    if (skippedDeps.length === 0) return null

    // Look up display names for skipped dependencies
    const depNames = skippedDeps
      .map((slug) => {
        const depQ = questions.find((q) => q.slug === slug)
        return depQ?.display_name ?? slug
      })
      .join(', ')

    return `This module requires ${depNames} which you chose to skip. It will be auto-enabled if you select Yes.`
  }, [state, questions, currentIndex, answers])

  /* ── Retry fetch ── */
  const handleRetryFetch = useCallback(() => {
    // Trigger re-fetch by toggling a dummy state — the useEffect depends on isRerun
    // which hasn't changed, so we force a re-mount by resetting state
    setFetchError(null)
    setState('loading')
    // Re-run the fetch
    const controller = new AbortController()
    const fetchQuestions = async () => {
      try {
        const res = await apiClient.get<QuestionsResponse>('/setup-guide/questions', {
          baseURL: '/api/v2',
          params: isRerun ? { rerun: true } : undefined,
          signal: controller.signal,
        })
        const fetched = res.data?.questions ?? []
        setQuestions(fetched)
        setState('welcome')
      } catch (err: unknown) {
        if (!controller.signal.aborted) {
          setFetchError('Failed to load setup guide questions. Please try again.')
          setState('welcome')
        }
      }
    }
    fetchQuestions()
  }, [isRerun])

  /* ── Render ── */

  // Loading state
  if (state === 'loading') {
    return (
      <div className="bg-gray-50 flex items-center justify-center py-20">
        <Spinner label="Loading setup guide" />
      </div>
    )
  }

  // Fetch error
  if (fetchError) {
    return (
      <div className="bg-gray-50 flex items-start justify-center px-4 py-12 sm:py-16">
        <div className="w-full max-w-lg">
          <div className="bg-white rounded-xl shadow-sm border border-gray-200 p-6 sm:p-8 text-center space-y-4">
            <p className="text-sm text-red-600" role="alert">
              {fetchError}
            </p>
            <Button variant="primary" size="md" onClick={handleRetryFetch}>
              Retry
            </Button>
          </div>
        </div>
      </div>
    )
  }

  // Welcome — empty questions for rerun
  if (state === 'welcome' && isRerun && questions.length === 0) {
    return (
      <div className="bg-gray-50 flex items-start justify-center px-4 py-12 sm:py-16">
        <div className="w-full max-w-lg">
          <div className="bg-white rounded-xl shadow-sm border border-gray-200 p-6 sm:p-8 text-center space-y-6">
            <h1 className="text-2xl font-bold text-gray-900">All Modules Enabled</h1>
            <p className="text-sm text-gray-600 leading-relaxed">
              All available modules for your plan are already enabled. There's nothing to
              configure right now.
            </p>
            <Button variant="primary" size="lg" onClick={() => navigate('/settings?tab=modules')}>
              Back to Settings
            </Button>
          </div>
        </div>
      </div>
    )
  }

  // Welcome screen
  if (state === 'welcome') {
    return <WelcomeScreen isRerun={isRerun} onStart={handleStart} />
  }

  // Questions
  if (state === 'questions') {
    const currentQuestion = questions[currentIndex]
    if (!currentQuestion) {
      // Safety fallback — shouldn't happen
      setState('summary')
      return null
    }

    return (
      <QuestionCard
        question={currentQuestion}
        currentIndex={currentIndex}
        totalQuestions={questions.length ?? 0}
        selectedAnswer={answers[currentQuestion.slug] ?? null}
        onAnswer={handleAnswer}
        onBack={handleBack}
        dependencyWarning={dependencyWarning}
      />
    )
  }

  // Summary / Submitting
  if (state === 'summary' || state === 'submitting') {
    return (
      <SummaryScreen
        questions={questions}
        answers={answers}
        autoEnabled={autoEnabled}
        onConfirm={handleConfirm}
        onGoBack={handleGoBackFromSummary}
        isSubmitting={state === 'submitting'}
        error={error}
      />
    )
  }

  // Success
  if (state === 'success') {
    const enabledCount = (questions ?? []).filter((q) => answers[q.slug] === true).length

    return (
      <div className="bg-gray-50 flex items-start justify-center px-4 py-12 sm:py-16">
        <div className="w-full max-w-lg">
          <div className="bg-white rounded-xl shadow-sm border border-gray-200 p-6 sm:p-8 text-center space-y-6">
            <div
              className="mx-auto flex h-12 w-12 items-center justify-center rounded-full bg-green-100"
              aria-hidden="true"
            >
              <svg
                className="h-6 w-6 text-green-600"
                xmlns="http://www.w3.org/2000/svg"
                viewBox="0 0 20 20"
                fill="currentColor"
              >
                <path
                  fillRule="evenodd"
                  d="M16.704 4.153a.75.75 0 01.143 1.052l-8 10.5a.75.75 0 01-1.127.075l-4.5-4.5a.75.75 0 011.06-1.06l3.894 3.893 7.48-9.817a.75.75 0 011.05-.143z"
                  clipRule="evenodd"
                />
              </svg>
            </div>
            <h2 className="text-2xl font-bold text-gray-900">You're All Set!</h2>
            <p className="text-sm text-gray-600 leading-relaxed">
              {enabledCount} module{enabledCount !== 1 ? 's' : ''} enabled.
              {(autoEnabled ?? []).length > 0 && (
                <> {(autoEnabled ?? []).length} additional module{(autoEnabled ?? []).length !== 1 ? 's were' : ' was'} auto-enabled as dependencies.</>
              )}
            </p>
            <Button
              variant="primary"
              size="lg"
              onClick={() => navigate(isRerun ? '/settings?tab=modules' : '/setup')}
            >
              {isRerun ? 'Back to Settings' : 'Continue Setup'}
            </Button>
          </div>
        </div>
      </div>
    )
  }

  return null
}
