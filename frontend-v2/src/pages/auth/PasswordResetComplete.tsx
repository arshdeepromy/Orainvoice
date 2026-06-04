import { useState } from 'react'
import type { FormEvent } from 'react'
import { Link, useSearchParams } from 'react-router-dom'
import apiClient from '@/api/client'
import { Button, Input, AlertBanner } from '@/components/ui'

/**
 * PasswordResetComplete — set-new-password-from-token page (Task 14 port of
 * frontend/src/pages/auth/PasswordResetComplete).
 *
 * ALL logic is copied verbatim from the original: the `token` read from the URL
 * `?token=` query param, the `validate()` rules (password ≥ 12 chars, password
 * === confirm), the missing-token guard ('Invalid or expired reset link'), the
 * submit → POST /auth/password/reset { token, new_password }, the
 * invalid/expired-token catch message, and the success state. Field-level
 * errors and the submitting flag are preserved unchanged.
 *
 * The page renders ONLY its card content into the AuthLayout `<Outlet/>`
 * (Task 12). The markup follows OraInvoice_Handoff/app/PasswordReset.html's
 * `complete` + `success` states: the `.auth-head`, the `.field-pw` new-password
 * field with a peek toggle + `.pw-meter` strength bars (designed on the fly per
 * FR-2b — purely presentational, it does NOT change the verbatim ≥12-char
 * validation), the confirm field, the `btn-lg` submit, and the ok-soft
 * "Password updated" success panel with a "Sign in with new password" button.
 */

/** Strength score (0–4) — presentational only, mirrors PasswordReset.html. */
function passwordStrength(v: string): number {
  let s = 0
  if (v.length >= 8) s++
  if (v.length >= 12) s++
  if (/[0-9]/.test(v)) s++
  if (/[^A-Za-z0-9]/.test(v)) s++
  return Math.min(4, s)
}

const METER_FILL: Record<number, string> = {
  0: 'bg-border',
  1: 'bg-danger',
  2: 'bg-warn',
  3: 'bg-[#3B9E6E]',
  4: 'bg-ok',
}

export function PasswordResetComplete() {
  const [searchParams] = useSearchParams()
  const token = searchParams.get('token') ?? ''

  const [password, setPassword] = useState('')
  const [confirm, setConfirm] = useState('')
  const [showPassword, setShowPassword] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [fieldErrors, setFieldErrors] = useState<Record<string, string>>({})
  const [submitting, setSubmitting] = useState(false)
  const [success, setSuccess] = useState(false)

  function validate(): boolean {
    const errs: Record<string, string> = {}
    if (password.length < 12) {
      errs.password = 'Password must be at least 12 characters'
    }
    if (password !== confirm) {
      errs.confirm = 'Passwords do not match'
    }
    setFieldErrors(errs)
    return Object.keys(errs).length === 0
  }

  async function handleSubmit(e: FormEvent) {
    e.preventDefault()
    setError(null)
    if (!validate()) return
    if (!token) {
      setError('Invalid or expired reset link')
      return
    }
    setSubmitting(true)
    try {
      await apiClient.post('/auth/password/reset', {
        token,
        new_password: password,
      })
      setSuccess(true)
    } catch {
      setError('Reset link is invalid or has expired. Please request a new one.')
    } finally {
      setSubmitting(false)
    }
  }

  if (success) {
    return (
      <div className="w-full max-w-[400px] text-center">
        <div className="mx-auto mb-5 grid h-[60px] w-[60px] place-items-center rounded-full bg-ok-soft">
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={2.2} aria-hidden="true" className="h-7 w-7 text-ok">
            <path d="M20 6L9 17l-5-5" />
          </svg>
        </div>
        <h1 className="text-[23px] font-bold tracking-[-0.02em] text-text">Password updated</h1>
        <p className="mt-2 text-[14px] text-muted">
          Your password has been reset. All existing sessions have been signed out.
        </p>
        <Button href="/login" fullWidth className="mt-6 h-[46px] text-[14.5px]">
          Sign in with new password
        </Button>
      </div>
    )
  }

  return (
    <div className="w-full max-w-[400px]">
      <div className="mb-[26px]">
        <h1 className="text-[25px] font-bold tracking-[-0.02em] text-text">Set new password</h1>
        <p className="mt-[7px] text-[14px] text-muted">
          Choose a strong password with at least 12 characters
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
        {/* New password — field-pw peek toggle + strength meter (FR-2b) */}
        <div className="flex flex-col gap-[7px]">
          <label htmlFor="new-password" className="text-[12.5px] font-medium text-text">
            New password
          </label>
          <div className="relative">
            <input
              id="new-password"
              type={showPassword ? 'text' : 'password'}
              autoComplete="new-password"
              required
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              placeholder="••••••••••••"
              aria-invalid={fieldErrors.password ? 'true' : undefined}
              className={`h-[42px] w-full rounded-ctl border bg-card pl-[13px] pr-11 text-[13.5px] text-text transition-[border-color,box-shadow] duration-150 placeholder:text-muted-2 focus:outline-none focus:shadow-[0_0_0_3px_var(--accent-soft)] ${fieldErrors.password ? 'border-danger focus:border-danger' : 'border-border focus:border-accent'}`}
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
          {/* Strength meter — presentational, mirrors PasswordReset.html `.pw-meter` */}
          {password && (
            <div className="mt-1 flex gap-[5px]" aria-hidden="true">
              {[1, 2, 3, 4].map((bar) => {
                const score = passwordStrength(password)
                return (
                  <span
                    key={bar}
                    className={`h-1 flex-1 rounded-[3px] transition-colors ${bar <= score ? METER_FILL[score] : 'bg-border'}`}
                  />
                )
              })}
            </div>
          )}
          {fieldErrors.password && (
            <p className="text-[12.5px] text-danger" role="alert">{fieldErrors.password}</p>
          )}
        </div>

        <Input
          label="Confirm password"
          type="password"
          autoComplete="new-password"
          required
          value={confirm}
          onChange={(e) => setConfirm(e.target.value)}
          error={fieldErrors.confirm}
          placeholder="••••••••••••"
        />

        <Button type="submit" loading={submitting} fullWidth className="h-[46px] text-[14.5px]">
          Reset password
        </Button>
      </form>

      <p className="mt-6 text-center text-[13.5px] text-muted">
        <Link to="/login" className="font-semibold text-accent hover:text-accent-press">
          Back to sign in
        </Link>
      </p>
    </div>
  )
}
