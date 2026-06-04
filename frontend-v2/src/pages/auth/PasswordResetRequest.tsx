import { useState } from 'react'
import type { FormEvent } from 'react'
import { Link } from 'react-router-dom'
import apiClient from '@/api/client'
import { Button, Input, AlertBanner } from '@/components/ui'

/**
 * PasswordResetRequest — "forgot password" email request page (Task 14 port of
 * frontend/src/pages/auth/PasswordResetRequest).
 *
 * ALL logic is copied verbatim from the original: the email state, the submit →
 * POST /auth/password/reset-request, and — critically — the anti-enumeration
 * behaviour (Req 4.4): `setSubmitted(true)` runs in BOTH the success and the
 * catch branch so the confirmation screen shows regardless of whether the
 * account exists. The submitting flag and error banner are preserved.
 *
 * The page renders ONLY its card content into the AuthLayout `<Outlet/>`
 * (Task 12) — the prototype's account-recovery brand panel lives in the layout.
 * The markup follows OraInvoice_Handoff/app/PasswordReset.html: the `.auth-head`
 * heading + sub-copy, the token `.field`/`.input` email field, the `btn-lg`
 * submit, and the `.auth-foot-link` back to sign in. The submitted state uses
 * the prototype's ok-soft circle + envelope glyph "Check your email" panel.
 *
 * Back-links point at `/login` (the wired frontend-v2 login route) rather than
 * the original's `/auth/login`, matching the prototype's "Back to sign in" link.
 */
export function PasswordResetRequest() {
  const [email, setEmail] = useState('')
  const [submitted, setSubmitted] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [submitting, setSubmitting] = useState(false)

  async function handleSubmit(e: FormEvent) {
    e.preventDefault()
    setError(null)
    setSubmitting(true)
    try {
      await apiClient.post('/auth/password/reset-request', { email })
      setSubmitted(true)
    } catch {
      // Show same message regardless to prevent account enumeration (Req 4.4)
      setSubmitted(true)
    } finally {
      setSubmitting(false)
    }
  }

  if (submitted) {
    return (
      <div className="w-full max-w-[400px] text-center">
        <div className="mx-auto mb-5 grid h-[60px] w-[60px] place-items-center rounded-full bg-ok-soft">
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={2} aria-hidden="true" className="h-7 w-7 text-ok">
            <path d="M22 6l-10 7L2 6m0 0v12a2 2 0 002 2h16a2 2 0 002-2V6a2 2 0 00-2-2H4a2 2 0 00-2 2z" />
          </svg>
        </div>
        <h1 className="text-[23px] font-bold tracking-[-0.02em] text-text">Check your email</h1>
        <p className="mt-2 text-[14px] text-muted">
          If an account exists for <span className="font-medium text-text">{email}</span>,
          we&apos;ve sent a password reset link. The link expires in 1 hour.
        </p>
        <p className="mt-6 text-[13.5px] text-muted">
          <Link to="/login" className="font-semibold text-accent hover:text-accent-press">
            Back to sign in
          </Link>
        </p>
      </div>
    )
  }

  return (
    <div className="w-full max-w-[400px]">
      <div className="mb-[26px]">
        <h1 className="text-[25px] font-bold tracking-[-0.02em] text-text">Reset your password</h1>
        <p className="mt-[7px] text-[14px] text-muted">
          Enter your email and we&apos;ll send you a reset link
        </p>
      </div>

      {error && (
        <div className="mb-4">
          <AlertBanner variant="error" onDismiss={() => setError(null)}>
            {error}
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

        <Button type="submit" loading={submitting} fullWidth className="h-[46px] text-[14.5px]">
          Send reset link
        </Button>
      </form>

      <p className="mt-6 text-center text-[13.5px] text-muted">
        Remember your password?{' '}
        <Link to="/login" className="font-semibold text-accent hover:text-accent-press">
          Sign in
        </Link>
      </p>
    </div>
  )
}
