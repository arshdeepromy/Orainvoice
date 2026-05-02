import { useState, useCallback } from 'react'
import { useNavigate, Link } from 'react-router-dom'
import { Page, Block, List, ListInput, Button } from 'konsta/react'
import { useAuth } from '@/contexts/AuthContext'

/**
 * LoginScreen — Konsta UI redesign with hero gradient header, email/password
 * ListInputs, primary Sign In button, Google and Passkey secondary buttons,
 * and footer links.
 *
 * Business logic is preserved unchanged:
 * - On submit: calls AuthContext.login(), stores JWT in memory,
 *   refresh token as httpOnly cookie.
 * - On MFA required: navigates to /mfa-verify.
 * - On invalid credentials: displays backend error message.
 *
 * Requirements: 11.1, 11.2, 11.3, 11.4, 11.5, 11.6, 11.7, 11.8
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
  const emailError =
    email.length > 0 && !/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(email)
      ? 'Please enter a valid email address'
      : undefined
  const passwordError =
    password.length > 0 && password.length < 1
      ? 'Password is required'
      : undefined

  const canSubmit =
    email.length > 0 && password.length > 0 && !emailError && !isSubmitting

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
      const message =
        err instanceof Error ? err.message : 'Login failed. Please try again.'
      setError(message)
    } finally {
      setIsSubmitting(false)
    }
  }, [canSubmit, email, password, remember, login, navigate])

  const handleGoogleSignIn = useCallback(async () => {
    setError(null)
    setIsGoogleLoading(true)

    try {
      const googleIdToken = await getGoogleIdToken()
      const result = await loginWithGoogle(googleIdToken)
      if (result.mfaRequired) {
        navigate('/mfa-verify')
      } else {
        navigate('/')
      }
    } catch (err: unknown) {
      const message =
        err instanceof Error ? err.message : 'Google sign-in failed.'
      setError(message)
    } finally {
      setIsGoogleLoading(false)
    }
  }, [loginWithGoogle, navigate])

  const handlePasskeySignIn = useCallback(async () => {
    setError(null)
    try {
      // Passkey login is not yet implemented in AuthContext.
      // This placeholder will be replaced when the passkey flow is wired up.
      throw new Error('Passkey sign-in is not configured for this environment')
    } catch (err: unknown) {
      const message =
        err instanceof Error ? err.message : 'Passkey sign-in failed.'
      setError(message)
    }
  }, [])

  const handleFormSubmit = useCallback(
    (e: React.FormEvent) => {
      e.preventDefault()
      void handleSubmit()
    },
    [handleSubmit],
  )

  return (
    <Page className="bg-white dark:bg-gray-900">
      {/* Hero gradient header with OraInvoice logo */}
      <div className="bg-gradient-to-b from-slate-900 to-indigo-900 px-6 pb-10 pt-16 text-center">
        <div className="mx-auto mb-3 flex h-16 w-16 items-center justify-center rounded-2xl bg-white/10 backdrop-blur-sm">
          <OraInvoiceLogo />
        </div>
        <h1 className="text-2xl font-bold text-white">OraInvoice</h1>
        <p className="mt-1 text-sm text-indigo-200">
          Sign in to your account
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

        {/* Email and password form */}
        <form onSubmit={handleFormSubmit} noValidate>
          <List strongIos outlineIos className="-mx-4 mb-4">
            <ListInput
              type="email"
              label="Email"
              placeholder="you@example.com"
              value={email}
              onChange={(e: React.ChangeEvent<HTMLInputElement>) =>
                setEmail(e.target.value)
              }
              onInput={(e: React.ChangeEvent<HTMLInputElement>) =>
                setEmail(e.target.value)
              }
              error={emailError}
              inputMode="email"
              autoComplete="email"
              autoCapitalize="none"
            />
            <ListInput
              type="password"
              label="Password"
              placeholder="Enter your password"
              value={password}
              onChange={(e: React.ChangeEvent<HTMLInputElement>) =>
                setPassword(e.target.value)
              }
              onInput={(e: React.ChangeEvent<HTMLInputElement>) =>
                setPassword(e.target.value)
              }
              error={passwordError}
              autoComplete="current-password"
            />
          </List>

          {/* Remember Me toggle */}
          <label className="mb-6 flex min-h-[44px] items-center gap-3">
            <input
              type="checkbox"
              checked={remember}
              onChange={(e) => setRemember(e.target.checked)}
              className="h-5 w-5 rounded border-gray-300 text-blue-600 focus:ring-blue-500 dark:border-gray-600 dark:bg-gray-800"
            />
            <span className="text-sm text-gray-700 dark:text-gray-300">
              Remember me
            </span>
          </label>

          {/* Primary Sign In button */}
          <Button
            type="submit"
            large
            className="mb-3"
            disabled={!canSubmit}
            colors={{
              fillBgIos: 'bg-blue-600',
              fillBgMaterial: 'bg-blue-600',
              fillTextIos: 'text-white',
              fillTextMaterial: 'text-white',
            }}
          >
            {isSubmitting ? 'Signing in…' : 'Sign In'}
          </Button>
        </form>

        {/* Divider */}
        <div className="my-5 flex items-center gap-3">
          <div className="h-px flex-1 bg-gray-200 dark:bg-gray-700" />
          <span className="text-xs text-gray-400 dark:text-gray-500">or</span>
          <div className="h-px flex-1 bg-gray-200 dark:bg-gray-700" />
        </div>

        {/* Secondary buttons: Google and Passkey */}
        <Button
          large
          outline
          className="mb-3"
          disabled={isGoogleLoading}
          onClick={handleGoogleSignIn}
          colors={{
            textIos: 'text-blue-600',
            textMaterial: 'text-blue-600',
            outlineBorderIos: 'border-blue-600',
            outlineBorderMaterial: 'border-blue-600',
          }}
        >
          <span className="flex items-center justify-center gap-2">
            <GoogleIcon />
            {isGoogleLoading ? 'Connecting…' : 'Continue with Google'}
          </span>
        </Button>

        <Button
          large
          outline
          className="mb-6"
          onClick={handlePasskeySignIn}
          colors={{
            textIos: 'text-blue-600',
            textMaterial: 'text-blue-600',
            outlineBorderIos: 'border-blue-600',
            outlineBorderMaterial: 'border-blue-600',
          }}
        >
          <span className="flex items-center justify-center gap-2">
            <PasskeyIcon />
            Sign in with Passkey
          </span>
        </Button>

        {/* Footer links */}
        <div className="flex flex-col items-center gap-3 pb-8">
          <Link
            to="/forgot-password"
            className="text-sm font-medium text-blue-600 active:text-blue-700 dark:text-blue-400 dark:active:text-blue-300"
          >
            Forgot password?
          </Link>
          <Link
            to="/signup"
            className="text-sm font-medium text-blue-600 active:text-blue-700 dark:text-blue-400 dark:active:text-blue-300"
          >
            Create account
          </Link>
        </div>
      </Block>
    </Page>
  )
}

/** OraInvoice logo icon for the hero section */
function OraInvoiceLogo() {
  return (
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
      <path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z" />
      <polyline points="14 2 14 8 20 8" />
      <line x1="16" y1="13" x2="8" y2="13" />
      <line x1="16" y1="17" x2="8" y2="17" />
      <polyline points="10 9 9 9 8 9" />
    </svg>
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

/** Passkey (key) icon for the sign-in button */
function PasskeyIcon() {
  return (
    <svg
      className="h-5 w-5 text-gray-600 dark:text-gray-400"
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="2"
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
    >
      <path d="M21 2l-2 2m-7.61 7.61a5.5 5.5 0 1 1-7.778 7.778 5.5 5.5 0 0 1 7.777-7.777zm0 0L15.5 7.5m0 0l3 3L22 7l-3-3m-3.5 3.5L19 4" />
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
