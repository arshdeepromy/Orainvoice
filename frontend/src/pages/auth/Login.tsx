import { useState } from 'react'
import type { FormEvent } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import { useAuth } from '@/contexts/AuthContext'
import { Button, Input, AlertBanner, Spinner } from '@/components/ui'

export function Login() {
  const { login, loginWithGoogle, loginWithPasskey, mfaPending, isLoading } =
    useAuth()
  const navigate = useNavigate()

  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [remember, setRemember] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [submitting, setSubmitting] = useState(false)

  if (isLoading) {
    return (
      <div className="flex min-h-screen items-center justify-center">
        <Spinner size="lg" label="Loading session" />
      </div>
    )
  }

  async function handleSubmit(e: FormEvent) {
    e.preventDefault()
    setError(null)
    setSubmitting(true)
    try {
      await login({ email, password, remember })
      if (!mfaPending) navigate('/')
      else navigate('/auth/mfa-verify')
    } catch (err: unknown) {
      const msg =
        err instanceof Error ? err.message : 'Invalid email or password'
      setError(msg)
    } finally {
      setSubmitting(false)
    }
  }

  async function handleGoogle() {
    setError(null)
    try {
      // In production, this would use the Google Identity Services SDK
      // to obtain an id_token before calling loginWithGoogle
      await loginWithGoogle('')
    } catch {
      setError('Google sign-in failed. Please try again.')
    }
  }

  async function handlePasskey() {
    setError(null)
    try {
      await loginWithPasskey()
      navigate('/')
    } catch {
      setError('Passkey authentication failed. Please try again.')
    }
  }

  <p className="text-center text-sm text-gray-600">
    Don&apos;t have an account?{' '}
    <Link
      to="/signup"
      className="font-medium text-blue-600 hover:text-blue-500"
    >
      Sign up
    </Link>
  </p>


  return (
    <div className="flex min-h-screen items-center justify-center bg-gray-50 px-4">
      <div className="w-full max-w-md space-y-6 rounded-xl bg-white p-8 shadow-lg">
        <div className="text-center">
          <h1 className="text-2xl font-bold text-gray-900">
            Sign in to WorkshopPro
          </h1>
          <p className="mt-1 text-sm text-gray-500">
            Enter your credentials to continue
          </p>
        </div>

        {error && (
          <AlertBanner variant="error" onDismiss={() => setError(null)}>
            {error}
          </AlertBanner>
        )}

        <form onSubmit={handleSubmit} className="space-y-4" noValidate>
          <Input
            label="Email address"
            type="email"
            autoComplete="email"
            required
            value={email}
            onChange={(e) => setEmail(e.target.value)}
            placeholder="you@workshop.co.nz"
          />

          <Input
            label="Password"
            type="password"
            autoComplete="current-password"
            required
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            placeholder="••••••••••••"
          />

          <div className="flex items-center justify-between">
            <label className="flex items-center gap-2 text-sm text-gray-600">
              <input
                type="checkbox"
                checked={remember}
                onChange={(e) => setRemember(e.target.checked)}
                className="h-4 w-4 rounded border-gray-300 text-blue-600 focus:ring-blue-500"
                aria-label="Remember this device"
              />
              Remember this device
            </label>
            <Link
              to="/auth/password-reset"
              className="text-sm font-medium text-blue-600 hover:text-blue-500"
            >
              Forgot password?
            </Link>
          </div>

          <Button
            type="submit"
            loading={submitting}
            className="w-full"
          >
            Sign in
          </Button>
        </form>

        <div className="relative">
          <div className="absolute inset-0 flex items-center">
            <div className="w-full border-t border-gray-200" />
          </div>
          <div className="relative flex justify-center text-sm">
            <span className="bg-white px-2 text-gray-500">
              Or continue with
            </span>
          </div>
        </div>

        <div className="flex flex-col gap-3">
          <Button
            type="button"
            variant="secondary"
            onClick={handleGoogle}
            className="w-full"
            aria-label="Sign in with Google"
          >
            <svg className="mr-2 h-5 w-5" viewBox="0 0 24 24" aria-hidden="true">
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
            Sign in with Google
          </Button>

          <Button
            type="button"
            variant="secondary"
            onClick={handlePasskey}
            className="w-full"
            aria-label="Sign in with Passkey"
          >
            <svg
              className="mr-2 h-5 w-5"
              fill="none"
              viewBox="0 0 24 24"
              strokeWidth={1.5}
              stroke="currentColor"
              aria-hidden="true"
            >
              <path
                strokeLinecap="round"
                strokeLinejoin="round"
                d="M7.864 4.243A7.5 7.5 0 0119.5 10.5c0 2.92-.556 5.709-1.568 8.268M5.742 6.364A7.465 7.465 0 004.5 10.5a48.667 48.667 0 00-1.26 8.303M15 10.5a3 3 0 11-6 0 3 3 0 016 0zm-2.25 6a3.75 3.75 0 00-3.75 3.75v.443c0 .576.162 1.14.47 1.626a7.5 7.5 0 009.06 0c.308-.486.47-1.05.47-1.626v-.443a3.75 3.75 0 00-3.75-3.75h-2.5z"
              />
            </svg>
            Sign in with Passkey
          </Button>
        </div>

        <p className="text-center text-sm text-gray-600">
          Don&apos;t have an account?{' '}
          <Link
            to="/signup"
            className="font-medium text-blue-600 hover:text-blue-500"
          >
            Sign up
          </Link>
        </p>
      </div>
    </div>
  )
}
