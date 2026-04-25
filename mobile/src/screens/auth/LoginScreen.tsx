import { useState, useCallback } from 'react'
import { useNavigate, Link } from 'react-router-dom'
import { useAuth } from '@/contexts/AuthContext'
import { MobileButton } from '@/components/ui/MobileButton'
import { MobileInput } from '@/components/ui/MobileInput'
import { MobileForm } from '@/components/ui/MobileForm'

/**
 * LoginScreen — email + password login with Remember Me, Google Sign-In,
 * and Forgot Password link.
 *
 * On submit: calls AuthContext.login(), stores JWT in memory,
 * refresh token as httpOnly cookie.
 * On MFA required: navigates to /mfa-verify.
 * On invalid credentials: displays backend error message.
 *
 * Requirements: 2.1, 2.2, 2.3, 2.8
 */
export default function LoginScreen() {
  const navigate = useNavigate()
  const { login, loginWithGoogle } = useAuth()

  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [remember, setRemember] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [isSubmitting, setIsSubmitting] = useState(false)
  const [isGoogleLoading, setIsGoogleLoading] = useState(false)

  // Client-side validation
  const emailError = email.length > 0 && !/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(email)
    ? 'Please enter a valid email address'
    : undefined
  const passwordError = password.length > 0 && password.length < 1
    ? 'Password is required'
    : undefined

  const canSubmit = email.length > 0 && password.length > 0 && !emailError && !isSubmitting

  const handleSubmit = useCallback(async () => {
    if (!canSubmit) return
    setError(null)
    setIsSubmitting(true)

    try {
      const result = await login({ email, password, remember })
      if (result.mfaRequired) {
        navigate('/mfa-verify')
      } else {
        navigate('/')
      }
    } catch (err: unknown) {
      const message = err instanceof Error ? err.message : 'Login failed. Please try again.'
      setError(message)
    } finally {
      setIsSubmitting(false)
    }
  }, [canSubmit, email, password, remember, login, navigate])

  const handleGoogleSignIn = useCallback(async () => {
    setError(null)
    setIsGoogleLoading(true)

    try {
      // In a real Capacitor app, this would use the Google Sign-In plugin
      // to get an ID token. For now, we use a placeholder flow.
      // The actual Google ID token would come from @capacitor/google-auth
      // or firebase.auth().signInWithPopup(googleProvider).
      const googleIdToken = await getGoogleIdToken()
      const result = await loginWithGoogle(googleIdToken)
      if (result.mfaRequired) {
        navigate('/mfa-verify')
      } else {
        navigate('/')
      }
    } catch (err: unknown) {
      const message = err instanceof Error ? err.message : 'Google sign-in failed.'
      setError(message)
    } finally {
      setIsGoogleLoading(false)
    }
  }, [loginWithGoogle, navigate])

  return (
    <div className="flex min-h-screen flex-col items-center justify-center bg-gray-50 px-6 dark:bg-gray-900">
      <div className="w-full max-w-sm">
        {/* Logo / Branding */}
        <div className="mb-8 text-center">
          <h1 className="text-2xl font-bold text-gray-900 dark:text-white">OraInvoice</h1>
          <p className="mt-1 text-sm text-gray-500 dark:text-gray-400">
            Sign in to your account
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

        <MobileForm onSubmit={handleSubmit}>
          <MobileInput
            label="Email"
            type="email"
            placeholder="you@example.com"
            value={email}
            onChange={(e) => setEmail(e.target.value)}
            error={emailError}
            required
            autoComplete="email"
            autoCapitalize="none"
            inputMode="email"
          />

          <MobileInput
            label="Password"
            type="password"
            placeholder="Enter your password"
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            error={passwordError}
            required
            autoComplete="current-password"
          />

          {/* Remember Me toggle */}
          <label className="flex min-h-[44px] items-center gap-3">
            <input
              type="checkbox"
              checked={remember}
              onChange={(e) => setRemember(e.target.checked)}
              className="h-5 w-5 rounded border-gray-300 text-blue-600 focus:ring-blue-500 dark:border-gray-600 dark:bg-gray-800"
            />
            <span className="text-sm text-gray-700 dark:text-gray-300">Remember me</span>
          </label>

          <MobileButton
            type="submit"
            fullWidth
            isLoading={isSubmitting}
            disabled={!canSubmit}
          >
            Sign In
          </MobileButton>
        </MobileForm>

        {/* Divider */}
        <div className="my-6 flex items-center gap-3">
          <div className="h-px flex-1 bg-gray-200 dark:bg-gray-700" />
          <span className="text-xs text-gray-400 dark:text-gray-500">or</span>
          <div className="h-px flex-1 bg-gray-200 dark:bg-gray-700" />
        </div>

        {/* Google Sign-In */}
        <MobileButton
          type="button"
          variant="secondary"
          fullWidth
          isLoading={isGoogleLoading}
          onClick={handleGoogleSignIn}
          icon={<GoogleIcon />}
        >
          Sign in with Google
        </MobileButton>

        {/* Forgot Password link */}
        <div className="mt-6 text-center">
          <Link
            to="/forgot-password"
            className="text-sm font-medium text-blue-600 active:text-blue-700 dark:text-blue-400 dark:active:text-blue-300"
          >
            Forgot your password?
          </Link>
        </div>
      </div>
    </div>
  )
}

/** Google "G" icon for the sign-in button */
function GoogleIcon() {
  return (
    <svg className="h-5 w-5" viewBox="0 0 24 24" aria-hidden="true">
      <path
        d="M22.56 12.25c0-.78-.07-1.53-.2-2.25H12v4.26h5.92a5.06 5.06 0 01-2.2 3.32v2.77h3.57c2.08-1.92 3.28-4.74 3.28-8.1z"
        fill="#4285F4"
      />
      <path
        d="M12 23c2.97 0 5.46-.98 7.28-2.66l-3.57-2.77c-.98.66-2.23 1.06-3.71 1.06-2.86 0-5.29-1.93-6.16-4.53H2.18v2.84C3.99 20.53 7.7 23 12 23z"
        fill="#34A853"
      />
      <path
        d="M5.84 14.09c-.22-.66-.35-1.36-.35-2.09s.13-1.43.35-2.09V7.07H2.18C1.43 8.55 1 10.22 1 12s.43 3.45 1.18 4.93l2.85-2.22.81-.62z"
        fill="#FBBC05"
      />
      <path
        d="M12 5.38c1.62 0 3.06.56 4.21 1.64l3.15-3.15C17.45 2.09 14.97 1 12 1 7.7 1 3.99 3.47 2.18 7.07l3.66 2.84c.87-2.6 3.3-4.53 6.16-4.53z"
        fill="#EA4335"
      />
    </svg>
  )
}

/**
 * Placeholder for Google ID token retrieval.
 * In production, this would use Firebase Auth or a Capacitor Google Sign-In plugin.
 */
async function getGoogleIdToken(): Promise<string> {
  // This would be replaced with actual Google Sign-In SDK integration:
  // - On web: firebase.auth().signInWithPopup(googleProvider)
  // - On native: @capacitor-firebase/authentication or @codetrix-studio/capacitor-google-auth
  throw new Error('Google Sign-In is not configured for this environment')
}
