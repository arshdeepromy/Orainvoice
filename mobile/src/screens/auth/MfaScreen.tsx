import { useState, useCallback, useEffect } from 'react'
import { useNavigate } from 'react-router-dom'
import { useAuth } from '@/contexts/AuthContext'
import { MobileButton } from '@/components/ui/MobileButton'
import { MobileInput } from '@/components/ui/MobileInput'
import { MobileForm } from '@/components/ui/MobileForm'

type MfaMethodType = 'totp' | 'sms' | 'backup_codes' | 'firebase'

const METHOD_LABELS: Record<MfaMethodType, string> = {
  totp: 'Authenticator App',
  sms: 'SMS Code',
  backup_codes: 'Backup Code',
  firebase: 'Firebase MFA',
}

const METHOD_DESCRIPTIONS: Record<MfaMethodType, string> = {
  totp: 'Enter the 6-digit code from your authenticator app',
  sms: 'Enter the code sent to your phone',
  backup_codes: 'Enter one of your backup codes',
  firebase: 'Complete verification via Firebase',
}

/**
 * MfaScreen — MFA method selection, code input, submit, error handling.
 *
 * Navigated to when backend returns MFA challenge after login.
 * On valid code: completes auth, navigates to Dashboard.
 * On invalid code: displays error, allows retry.
 * Supports TOTP, SMS, backup codes, and Firebase MFA.
 *
 * Requirements: 3.1, 3.2, 3.3, 3.4, 3.5
 */
export default function MfaScreen() {
  const navigate = useNavigate()
  const {
    mfaPending,
    mfaMethods,
    mfaDefaultMethod,
    completeMfa,
    completeFirebaseMfa,
  } = useAuth()

  const [selectedMethod, setSelectedMethod] = useState<string>('')
  const [code, setCode] = useState('')
  const [error, setError] = useState<string | null>(null)
  const [isSubmitting, setIsSubmitting] = useState(false)

  // Redirect to login if no MFA is pending
  useEffect(() => {
    if (!mfaPending) {
      navigate('/login', { replace: true })
    }
  }, [mfaPending, navigate])

  // Set default method on mount
  useEffect(() => {
    if (mfaDefaultMethod) {
      setSelectedMethod(mfaDefaultMethod)
    } else if (mfaMethods.length > 0) {
      setSelectedMethod(mfaMethods[0])
    }
  }, [mfaDefaultMethod, mfaMethods])

  const isFirebase = selectedMethod === 'firebase'
  const canSubmit = code.length > 0 && !isSubmitting

  const handleSubmit = useCallback(async () => {
    if (!canSubmit) return
    setError(null)
    setIsSubmitting(true)

    try {
      if (isFirebase) {
        // Firebase MFA flow — the code here is the Firebase ID token
        await completeFirebaseMfa(code)
      } else {
        await completeMfa(code, selectedMethod)
      }
      navigate('/', { replace: true })
    } catch (err: unknown) {
      const message = err instanceof Error
        ? err.message
        : 'Invalid verification code. Please try again.'
      setError(message)
      setCode('')
    } finally {
      setIsSubmitting(false)
    }
  }, [canSubmit, isFirebase, code, selectedMethod, completeMfa, completeFirebaseMfa, navigate])

  const handleMethodChange = useCallback((method: string) => {
    setSelectedMethod(method)
    setCode('')
    setError(null)
  }, [])

  if (!mfaPending) return null

  return (
    <div className="flex min-h-screen flex-col items-center justify-center bg-gray-50 px-6 dark:bg-gray-900">
      <div className="w-full max-w-sm">
        {/* Header */}
        <div className="mb-8 text-center">
          <div className="mx-auto mb-4 flex h-16 w-16 items-center justify-center rounded-full bg-blue-100 dark:bg-blue-900/30">
            <svg
              className="h-8 w-8 text-blue-600 dark:text-blue-400"
              viewBox="0 0 24 24"
              fill="none"
              stroke="currentColor"
              strokeWidth="2"
              strokeLinecap="round"
              strokeLinejoin="round"
              aria-hidden="true"
            >
              <rect x="3" y="11" width="18" height="11" rx="2" ry="2" />
              <path d="M7 11V7a5 5 0 0110 0v4" />
            </svg>
          </div>
          <h1 className="text-2xl font-bold text-gray-900 dark:text-white">
            Verify Your Identity
          </h1>
          <p className="mt-1 text-sm text-gray-500 dark:text-gray-400">
            {METHOD_DESCRIPTIONS[selectedMethod as MfaMethodType] ??
              'Enter your verification code'}
          </p>
        </div>

        {/* Error banner */}
        {error && (
          <div
            role="alert"
            className="mb-4 rounded-lg bg-red-50 px-4 py-3 text-sm text-red-700 dark:bg-red-900/30 dark:text-red-400"
          >
            {error}
          </div>
        )}

        {/* Method selector — only show if multiple methods available */}
        {mfaMethods.length > 1 && (
          <div className="mb-6">
            <p className="mb-2 text-sm font-medium text-gray-700 dark:text-gray-300">
              Verification method
            </p>
            <div className="flex flex-col gap-2">
              {mfaMethods.map((method) => (
                <button
                  key={method}
                  type="button"
                  onClick={() => handleMethodChange(method)}
                  className={`flex min-h-[44px] items-center gap-3 rounded-lg border px-4 py-3 text-left text-sm transition-colors ${
                    selectedMethod === method
                      ? 'border-blue-500 bg-blue-50 text-blue-700 dark:border-blue-400 dark:bg-blue-900/20 dark:text-blue-300'
                      : 'border-gray-200 bg-white text-gray-700 active:bg-gray-50 dark:border-gray-700 dark:bg-gray-800 dark:text-gray-300 dark:active:bg-gray-700'
                  }`}
                >
                  <MethodIcon method={method as MfaMethodType} />
                  <span className="font-medium">
                    {METHOD_LABELS[method as MfaMethodType] ?? method}
                  </span>
                </button>
              ))}
            </div>
          </div>
        )}

        {/* Code input */}
        <MobileForm onSubmit={handleSubmit}>
          <MobileInput
            label={isFirebase ? 'Firebase Token' : 'Verification Code'}
            type="text"
            inputMode={isFirebase ? 'text' : 'numeric'}
            placeholder={isFirebase ? 'Paste Firebase token' : 'Enter code'}
            value={code}
            onChange={(e) => setCode(e.target.value)}
            required
            autoComplete="one-time-code"
            autoFocus
          />

          <MobileButton
            type="submit"
            fullWidth
            isLoading={isSubmitting}
            disabled={!canSubmit}
          >
            Verify
          </MobileButton>
        </MobileForm>

        {/* Back to login */}
        <div className="mt-6 text-center">
          <button
            type="button"
            onClick={() => navigate('/login', { replace: true })}
            className="text-sm font-medium text-blue-600 active:text-blue-700 dark:text-blue-400 dark:active:text-blue-300"
          >
            Back to login
          </button>
        </div>
      </div>
    </div>
  )
}

/** Icon for each MFA method */
function MethodIcon({ method }: { method: MfaMethodType }) {
  const className = 'h-5 w-5 flex-shrink-0'

  switch (method) {
    case 'totp':
      return (
        <svg className={className} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
          <circle cx="12" cy="12" r="10" />
          <polyline points="12 6 12 12 16 14" />
        </svg>
      )
    case 'sms':
      return (
        <svg className={className} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
          <path d="M21 15a2 2 0 01-2 2H7l-4 4V5a2 2 0 012-2h14a2 2 0 012 2z" />
        </svg>
      )
    case 'backup_codes':
      return (
        <svg className={className} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
          <rect x="3" y="3" width="18" height="18" rx="2" />
          <path d="M7 7h.01M7 12h.01M7 17h.01M12 7h5M12 12h5M12 17h5" />
        </svg>
      )
    case 'firebase':
      return (
        <svg className={className} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
          <path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z" />
        </svg>
      )
    default:
      return null
  }
}
