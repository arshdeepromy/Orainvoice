import { useState, FormEvent } from 'react'
import { useSearchParams, useNavigate } from 'react-router-dom'
import apiClient, { setAccessToken } from '@/api/client'
import { Button, Input, AlertBanner } from '@/components/ui'
import { validateVerifyEmailForm } from './signup-validation'
import type { VerifyEmailResponse } from './signup-types'

export function VerifyEmail() {
  const [searchParams] = useSearchParams()
  const navigate = useNavigate()
  const token = searchParams.get('token')

  const [password, setPassword] = useState('')
  const [confirmPassword, setConfirmPassword] = useState('')
  const [errors, setErrors] = useState<Record<string, string>>({})
  const [apiError, setApiError] = useState<string | null>(null)
  const [submitting, setSubmitting] = useState(false)

  async function handleSubmit(e: FormEvent) {
    e.preventDefault()
    setApiError(null)

    const validationErrors = validateVerifyEmailForm(password, confirmPassword)
    setErrors(validationErrors)
    if (Object.keys(validationErrors).length > 0) return

    setSubmitting(true)
    try {
      const res = await apiClient.post<VerifyEmailResponse>('/auth/verify-email', {
        token,
        password,
      })
      setAccessToken(res.data.access_token)
      // Refresh token is now stored as httpOnly cookie by the server
      navigate('/setup')
    } catch (err: unknown) {
      if (
        err &&
        typeof err === 'object' &&
        'response' in err &&
        (err as { response?: { status?: number; data?: { detail?: string } } }).response?.status === 400
      ) {
        const detail = (err as { response: { data: { detail?: string } } }).response.data.detail
        setApiError(detail ?? 'Verification failed. Please try again.')
      } else {
        setApiError('Something went wrong. Please try again.')
      }
    } finally {
      setSubmitting(false)
    }
  }

  if (!token) {
    return (
      <div className="flex min-h-screen items-center justify-center bg-gray-50 px-4">
        <div className="w-full max-w-md space-y-6 rounded-xl bg-white p-8 shadow-lg">
          <AlertBanner variant="error">This verification link is invalid.</AlertBanner>
        </div>
      </div>
    )
  }

  return (
    <div className="flex min-h-screen items-center justify-center bg-gray-50 px-4">
      <div className="w-full max-w-md space-y-6 rounded-xl bg-white p-8 shadow-lg">
        <div className="text-center">
          <h1 className="text-2xl font-bold text-gray-900">Set your password</h1>
          <p className="mt-1 text-sm text-gray-500">
            Choose a password to complete your account setup
          </p>
        </div>

        {apiError && (
          <AlertBanner variant="error" onDismiss={() => setApiError(null)}>
            {apiError}
          </AlertBanner>
        )}

        <form onSubmit={handleSubmit} className="space-y-4" noValidate>
          <Input
            label="Password"
            type="password"
            autoComplete="new-password"
            required
            value={password}
            onChange={(e) => {
              setPassword(e.target.value)
              if (errors.password) {
                setErrors((prev) => {
                  const next = { ...prev }
                  delete next.password
                  return next
                })
              }
            }}
            error={errors.password}
            placeholder="••••••••••••"
          />

          <Input
            label="Confirm password"
            type="password"
            autoComplete="new-password"
            required
            value={confirmPassword}
            onChange={(e) => {
              setConfirmPassword(e.target.value)
              if (errors.confirmPassword) {
                setErrors((prev) => {
                  const next = { ...prev }
                  delete next.confirmPassword
                  return next
                })
              }
            }}
            error={errors.confirmPassword}
            placeholder="••••••••••••"
          />

          <Button type="submit" loading={submitting} className="w-full">
            Set password
          </Button>
        </form>
      </div>
    </div>
  )
}
