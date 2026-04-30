import { useState, useCallback, useEffect } from 'react'
import { useNavigate } from 'react-router-dom'
import {
  Page,
  Block,
  List,
  ListInput,
  Segmented,
  SegmentedButton,
  Button,
} from 'konsta/react'
import { useAuth } from '@/contexts/AuthContext'

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
 * MfaScreen — Konsta UI redesign with Segmented method selector, ListInput
 * for code entry, and primary Verify button.
 *
 * Business logic is preserved unchanged:
 * - Redirects to /login if no MFA pending
 * - Sets default method from AuthContext
 * - On valid code: calls completeMfa/completeFirebaseMfa, navigates to /
 * - On invalid code: displays error, clears code for retry
 * - Supports TOTP, SMS, backup codes, and Firebase MFA
 *
 * Requirements: 12.1, 12.2, 12.3, 12.4, 12.5
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
      const message =
        err instanceof Error
          ? err.message
          : 'Invalid verification code. Please try again.'
      setError(message)
      setCode('')
    } finally {
      setIsSubmitting(false)
    }
  }, [
    canSubmit,
    isFirebase,
    code,
    selectedMethod,
    completeMfa,
    completeFirebaseMfa,
    navigate,
  ])

  const handleMethodChange = useCallback((method: string) => {
    setSelectedMethod(method)
    setCode('')
    setError(null)
  }, [])

  const handleFormSubmit = useCallback(
    (e: React.FormEvent) => {
      e.preventDefault()
      void handleSubmit()
    },
    [handleSubmit],
  )

  if (!mfaPending) return null

  return (
    <Page className="bg-white dark:bg-gray-900">
      {/* Hero gradient header */}
      <div className="bg-gradient-to-b from-slate-900 to-indigo-900 px-6 pb-10 pt-16 text-center">
        <div className="mx-auto mb-3 flex h-16 w-16 items-center justify-center rounded-2xl bg-white/10 backdrop-blur-sm">
          <svg
            className="h-8 w-8 text-white"
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
        <h1 className="text-2xl font-bold text-white">Verify Your Identity</h1>
        <p className="mt-1 text-sm text-indigo-200">
          {METHOD_DESCRIPTIONS[selectedMethod as MfaMethodType] ??
            'Enter your verification code'}
        </p>
      </div>

      <Block className="-mt-4 rounded-t-2xl bg-white pt-6 dark:bg-gray-900">
        {/* Error banner */}
        {error && (
          <div
            role="alert"
            className="mb-4 rounded-lg bg-red-50 px-4 py-3 text-sm text-red-700 dark:bg-red-900/30 dark:text-red-400"
          >
            {error}
          </div>
        )}

        {/* Method selector — Segmented control when multiple methods available */}
        {mfaMethods.length > 1 && (
          <div className="mb-6">
            <p className="mb-2 text-sm font-medium text-gray-700 dark:text-gray-300">
              Verification method
            </p>
            <Segmented strong>
              {mfaMethods.map((method) => (
                <SegmentedButton
                  key={method}
                  active={selectedMethod === method}
                  onClick={() => handleMethodChange(method)}
                >
                  {METHOD_LABELS[method as MfaMethodType] ?? method}
                </SegmentedButton>
              ))}
            </Segmented>
          </div>
        )}

        {/* Code input and submit */}
        <form onSubmit={handleFormSubmit} noValidate>
          <List strongIos outlineIos className="-mx-4 mb-4">
            <ListInput
              label="Verification Code"
              type="text"
              inputMode={isFirebase ? 'text' : 'numeric'}
              placeholder={isFirebase ? 'Paste Firebase token' : 'Enter 6-digit code'}
              value={code}
              maxLength={isFirebase ? undefined : 6}
              onInput={(e: React.ChangeEvent<HTMLInputElement>) =>
                setCode(e.target.value)
              }
              autoComplete="one-time-code"
              autoFocus
            />
          </List>

          {/* Verify primary button */}
          <Button
            type="submit"
            large
            className="mb-3"
            disabled={!canSubmit}
          >
            {isSubmitting ? 'Verifying…' : 'Verify'}
          </Button>
        </form>

        {/* Back to login link */}
        <div className="mt-4 text-center">
          <button
            type="button"
            onClick={() => navigate('/login', { replace: true })}
            className="text-sm font-medium text-blue-600 active:text-blue-700 dark:text-blue-400 dark:active:text-blue-300"
          >
            Back to login
          </button>
        </div>
      </Block>
    </Page>
  )
}
