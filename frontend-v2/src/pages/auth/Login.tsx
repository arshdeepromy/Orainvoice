import { useState } from 'react'
import type { FormEvent } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import { useAuth } from '@/contexts/AuthContext'
import apiClient from '@/api/client'
import { Button, Input, AlertBanner, Spinner } from '@/components/ui'
import { MfaModal } from '@/components/auth/MfaModal'
import { NodeStatusIndicator } from '@/components/ha/NodeStatusIndicator'

/**
 * Login — sign-in page (Task 13 port of frontend/src/pages/auth/Login).
 *
 * ALL logic is copied verbatim from the original: the email/password/remember
 * state, the `login()` → mfaRequired branch (opens MfaModal) or setup-wizard
 * progress check → navigate('/setup') / navigate('/'), the
 * `loginWithGoogle('')` and `loginWithPasskey()` handlers, the
 * resend-verification flow gated on the "verify your email" error substring, the
 * isLoading session spinner, and the MfaModal + NodeStatusIndicator mounts.
 *
 * The page now renders ONLY its heading + form into the AuthLayout `<Outlet/>`
 * (Task 12) — the split-screen brand panel + mobile logo live in the layout. The
 * markup is remapped to the design system per OraInvoice_Handoff/app/Login.html:
 * the `.auth-head` heading, token inputs (with the prototype's password peek
 * toggle — FR-2b), the primary `.btn-lg`, the `.divider-or` separator, the
 * `.btn-sso` Google/Passkey buttons, and the `.auth-foot-link` to /signup.
 */
export function Login() {
  const { login, loginWithGoogle, loginWithPasskey, isLoading } =
    useAuth()
  const navigate = useNavigate()

  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [showPassword, setShowPassword] = useState(false)
  const [remember, setRemember] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [submitting, setSubmitting] = useState(false)
  const [resendingVerification, setResendingVerification] = useState(false)
  const [resendSuccess, setResendSuccess] = useState(false)
  const [showMfaModal, setShowMfaModal] = useState(false)

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
    setResendSuccess(false)
    setSubmitting(true)
    try {
      const { mfaRequired } = await login({ email, password, remember })
      if (mfaRequired) {
        setShowMfaModal(true)
      } else {
        // Check if this org needs the setup wizard
        try {
          const progressRes = await apiClient.get('/api/v2/setup-wizard/progress')
          if (progressRes.data && !progressRes.data.wizard_completed) {
            navigate('/setup')
            return
          }
        } catch {
          // If progress check fails, just go to dashboard
        }
        navigate('/')
      }
    } catch (err: unknown) {
      const msg =
        err instanceof Error ? err.message : 'Invalid email or password'
      setError(msg)
    } finally {
      setSubmitting(false)
    }
  }

  async function handleResendVerification() {
    if (!email) return
    setResendingVerification(true)
    try {
      await apiClient.post('/auth/resend-verification', { email })
      setResendSuccess(true)
    } catch {
      // Still show success to avoid leaking info
      setResendSuccess(true)
    } finally {
      setResendingVerification(false)
    }
  }

  const isEmailNotVerified = error?.includes('verify your email')

  async function handleGoogle() {
    setError(null)
    try {
      // In production, this would use the Google Identity Services SDK
      // to obtain an id_token before calling loginWithGoogle
      const { mfaRequired } = await loginWithGoogle('')
      if (mfaRequired) setShowMfaModal(true)
      else navigate('/')
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

  return (
    <div className="w-full max-w-[400px]">
      {/* auth-head */}
      <div className="mb-[26px]">
        <h1 className="text-[25px] font-bold tracking-[-0.02em] text-text">Sign in</h1>
        <p className="mt-[7px] text-[14px] text-muted">
          Welcome back. Enter your details to continue.
        </p>
      </div>

      {error && (
        <div className="mb-4">
          <AlertBanner variant={isEmailNotVerified ? 'warning' : 'error'} onDismiss={() => setError(null)}>
            <div>
              <p>{error}</p>
              {isEmailNotVerified && (
                <div className="mt-2">
                  {resendSuccess ? (
                    <p className="text-[13px] text-ok">Verification email sent. Check your inbox.</p>
                  ) : (
                    <button
                      type="button"
                      onClick={handleResendVerification}
                      disabled={resendingVerification}
                      className="text-[13px] font-semibold text-accent underline hover:text-accent-press"
                    >
                      {resendingVerification ? 'Sending...' : 'Resend verification email'}
                    </button>
                  )}
                </div>
              )}
            </div>
          </AlertBanner>
        </div>
      )}

      <form onSubmit={handleSubmit} className="flex flex-col gap-4" noValidate>
        <Input
          label="Email address"
          type="email"
          autoComplete="email"
          required
          value={email}
          onChange={(e) => setEmail(e.target.value)}
          placeholder="you@workshop.co.nz"
        />

        {/* Password field with prototype peek toggle (FR-2b) */}
        <div className="flex flex-col gap-[7px]">
          <label htmlFor="password" className="text-[12.5px] font-medium text-text">
            Password
          </label>
          <div className="relative">
            <input
              id="password"
              type={showPassword ? 'text' : 'password'}
              autoComplete="current-password"
              required
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              placeholder="••••••••••••"
              className="h-[42px] w-full rounded-ctl border border-border bg-card pl-[13px] pr-11 text-[13.5px] text-text transition-[border-color,box-shadow] duration-150 placeholder:text-muted-2 focus:border-accent focus:outline-none focus:shadow-[0_0_0_3px_var(--accent-soft)]"
            />
            <button
              type="button"
              onClick={() => setShowPassword((v) => !v)}
              aria-label={showPassword ? 'Hide password' : 'Show password'}
              className={`absolute right-[11px] top-1/2 grid -translate-y-1/2 place-items-center p-1 ${showPassword ? 'text-accent' : 'text-muted-2 hover:text-muted'}`}
            >
              <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={2} className="h-[18px] w-[18px]" aria-hidden="true">
                <path d="M2 12s3.5-7 10-7 10 7 10 7-3.5 7-10 7-10-7-10-7z" />
                <circle cx="12" cy="12" r="3" />
              </svg>
            </button>
          </div>
        </div>

        <div className="flex items-center justify-between">
          <label className="flex cursor-pointer items-center gap-[9px] text-[13px] text-muted">
            <input
              type="checkbox"
              checked={remember}
              onChange={(e) => setRemember(e.target.checked)}
              className="checkbox"
              aria-label="Remember this device"
            />
            Remember this device
          </label>
          <Link
            to="/auth/password-reset"
            className="text-[13px] font-semibold text-accent hover:text-accent-press"
          >
            Forgot password?
          </Link>
        </div>

        <Button type="submit" loading={submitting} fullWidth className="h-[46px] text-[14.5px]">
          Sign in
        </Button>
      </form>

      {/* divider-or */}
      <div className="my-1 mt-5 flex items-center gap-3.5 text-[12px] text-muted-2 before:h-px before:flex-1 before:bg-border before:content-[''] after:h-px after:flex-1 after:bg-border after:content-['']">
        Or continue with
      </div>

      <div className="flex flex-col gap-2.5">
        <button
          type="button"
          onClick={handleGoogle}
          aria-label="Sign in with Google"
          className="flex h-11 items-center justify-center gap-2.5 rounded-ctl border border-border bg-card text-[14px] font-semibold text-text transition-[background-color,border-color] duration-150 hover:border-border-strong hover:bg-canvas"
        >
          <svg className="h-[19px] w-[19px]" viewBox="0 0 24 24" aria-hidden="true">
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
        </button>

        <button
          type="button"
          onClick={handlePasskey}
          aria-label="Sign in with Passkey"
          className="flex h-11 items-center justify-center gap-2.5 rounded-ctl border border-border bg-card text-[14px] font-semibold text-text transition-[background-color,border-color] duration-150 hover:border-border-strong hover:bg-canvas"
        >
          <svg
            className="h-[19px] w-[19px]"
            fill="none"
            viewBox="0 0 24 24"
            strokeWidth={1.6}
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
        </button>
      </div>

      <p className="mt-6 text-center text-[13.5px] text-muted">
        Don&apos;t have an account?{' '}
        <Link to="/signup" className="font-semibold text-accent hover:text-accent-press">
          Start a free trial
        </Link>
      </p>

      <MfaModal
        open={showMfaModal}
        onClose={() => setShowMfaModal(false)}
        onSuccess={() => navigate('/')}
      />

      {/* HA node indicator — small, non-intrusive */}
      <div className="fixed bottom-4 left-4">
        <NodeStatusIndicator />
      </div>
    </div>
  )
}
