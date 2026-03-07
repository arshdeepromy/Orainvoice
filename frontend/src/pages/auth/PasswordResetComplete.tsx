import { useState } from 'react'
import type { FormEvent } from 'react'
import { Link, useSearchParams } from 'react-router-dom'
import apiClient from '@/api/client'
import { Button, Input, AlertBanner } from '@/components/ui'

export function PasswordResetComplete() {
  const [searchParams] = useSearchParams()
  const token = searchParams.get('token') ?? ''

  const [password, setPassword] = useState('')
  const [confirm, setConfirm] = useState('')
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
      <div className="flex min-h-screen items-center justify-center bg-gray-50 px-4">
        <div className="w-full max-w-md space-y-6 rounded-xl bg-white p-8 shadow-lg text-center">
          <div className="mx-auto flex h-12 w-12 items-center justify-center rounded-full bg-green-100">
            <span className="text-xl text-green-600" aria-hidden="true">✓</span>
          </div>
          <h1 className="text-2xl font-bold text-gray-900">Password updated</h1>
          <p className="text-sm text-gray-500">
            Your password has been reset. All existing sessions have been signed out.
          </p>
          <Link
            to="/auth/login"
            className="inline-block rounded-md bg-blue-600 px-4 py-2 text-sm font-medium text-white hover:bg-blue-700"
          >
            Sign in with new password
          </Link>
        </div>
      </div>
    )
  }

  return (
    <div className="flex min-h-screen items-center justify-center bg-gray-50 px-4">
      <div className="w-full max-w-md space-y-6 rounded-xl bg-white p-8 shadow-lg">
        <div className="text-center">
          <h1 className="text-2xl font-bold text-gray-900">Set new password</h1>
          <p className="mt-1 text-sm text-gray-500">
            Choose a strong password with at least 12 characters
          </p>
        </div>

        {error && (
          <AlertBanner variant="error" onDismiss={() => setError(null)}>
            {error}
          </AlertBanner>
        )}

        <form onSubmit={handleSubmit} className="space-y-4" noValidate>
          <Input
            label="New password"
            type="password"
            autoComplete="new-password"
            required
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            error={fieldErrors.password}
            placeholder="••••••••••••"
          />

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

          <Button type="submit" loading={submitting} className="w-full">
            Reset password
          </Button>
        </form>

        <p className="text-center text-sm text-gray-500">
          <Link
            to="/auth/login"
            className="font-medium text-blue-600 hover:text-blue-500"
          >
            Back to sign in
          </Link>
        </p>
      </div>
    </div>
  )
}
