import { useState, useCallback, useEffect } from 'react'
import { useNavigate } from 'react-router-dom'
import { useBiometric } from '@/contexts/BiometricContext'
import { MobileButton } from '@/components/ui/MobileButton'

const MAX_FAILURES = 3

/**
 * BiometricLockScreen — biometric prompt on app open with 3-failure
 * fallback to password login.
 *
 * Shown when biometric auth is enabled and the user opens the app
 * with a valid session. After 3 consecutive failures, falls back
 * to the standard login screen.
 *
 * Requirements: 4.2, 4.3
 */
export default function BiometricLockScreen() {
  const navigate = useNavigate()
  const { verify, isAvailable, isEnabled } = useBiometric()

  const [failureCount, setFailureCount] = useState(0)
  const [error, setError] = useState<string | null>(null)
  const [isVerifying, setIsVerifying] = useState(false)

  // Redirect to login if biometric is not available or not enabled
  useEffect(() => {
    if (!isAvailable || !isEnabled) {
      navigate('/login', { replace: true })
    }
  }, [isAvailable, isEnabled, navigate])

  // Auto-prompt on mount
  useEffect(() => {
    if (isAvailable && isEnabled && failureCount === 0) {
      handleVerify()
    }
    // Only run on mount
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  const handleVerify = useCallback(async () => {
    setError(null)
    setIsVerifying(true)

    try {
      const success = await verify()
      if (success) {
        navigate('/', { replace: true })
      } else {
        const newCount = failureCount + 1
        setFailureCount(newCount)
        if (newCount >= MAX_FAILURES) {
          navigate('/login', { replace: true })
        } else {
          setError(
            `Verification failed. ${MAX_FAILURES - newCount} attempt${MAX_FAILURES - newCount === 1 ? '' : 's'} remaining.`,
          )
        }
      }
    } catch {
      const newCount = failureCount + 1
      setFailureCount(newCount)
      if (newCount >= MAX_FAILURES) {
        navigate('/login', { replace: true })
      } else {
        setError(
          `Verification failed. ${MAX_FAILURES - newCount} attempt${MAX_FAILURES - newCount === 1 ? '' : 's'} remaining.`,
        )
      }
    } finally {
      setIsVerifying(false)
    }
  }, [verify, navigate, failureCount])

  const handleUsePassword = useCallback(() => {
    navigate('/login', { replace: true })
  }, [navigate])

  return (
    <div className="flex min-h-screen flex-col items-center justify-center bg-gray-50 px-6 dark:bg-gray-900">
      <div className="w-full max-w-sm text-center">
        {/* Biometric icon */}
        <div className="mx-auto mb-6 flex h-20 w-20 items-center justify-center rounded-full bg-blue-100 dark:bg-blue-900/30">
          <svg
            className="h-10 w-10 text-blue-600 dark:text-blue-400"
            viewBox="0 0 24 24"
            fill="none"
            stroke="currentColor"
            strokeWidth="1.5"
            strokeLinecap="round"
            strokeLinejoin="round"
            aria-hidden="true"
          >
            {/* Fingerprint icon */}
            <path d="M2 12C2 6.5 6.5 2 12 2a10 10 0 018 4" />
            <path d="M5 19.5C5.5 18 6 15 6 12c0-3.5 2.5-6 6-6 3 0 5.5 2 5.8 5" />
            <path d="M12 12v4c0 2.5-1 4-2.5 5.5" />
            <path d="M8.5 16.5c0 3-1 5.5-2 7" />
            <path d="M17.5 12c0 4-1 7-3 9.5" />
            <path d="M22 12c0 5.5-2.5 10-5 13" />
          </svg>
        </div>

        <h1 className="text-2xl font-bold text-gray-900 dark:text-white">
          Unlock OraInvoice
        </h1>
        <p className="mt-2 text-sm text-gray-500 dark:text-gray-400">
          Use your biometrics to unlock the app
        </p>

        {/* Error message */}
        {error && (
          <div
            role="alert"
            className="mt-4 rounded-lg bg-red-50 px-4 py-3 text-sm text-red-700 dark:bg-red-900/30 dark:text-red-400"
          >
            {error}
          </div>
        )}

        <div className="mt-8 flex flex-col gap-3">
          <MobileButton
            type="button"
            fullWidth
            isLoading={isVerifying}
            onClick={handleVerify}
          >
            Try Again
          </MobileButton>

          <MobileButton
            type="button"
            variant="ghost"
            fullWidth
            onClick={handleUsePassword}
          >
            Use Password Instead
          </MobileButton>
        </div>
      </div>
    </div>
  )
}
