import { useState } from 'react'
import apiClient from '@/api/client'

interface EmailEnrolWizardProps {
  onComplete: () => void
  onCancel: () => void
}

interface EnrolResponse {
  method: string
  qr_uri: string | null
  secret: string | null
  message: string
}

type Step = 'send' | 'verify'

export function EmailEnrolWizard({ onComplete, onCancel }: EmailEnrolWizardProps) {
  const [step, setStep] = useState<Step>('send')
  const [message, setMessage] = useState('')
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')
  const [code, setCode] = useState('')
  const [success, setSuccess] = useState(false)
  const [resending, setResending] = useState(false)

  const sendOtp = async () => {
    setLoading(true)
    setError('')
    try {
      const res = await apiClient.post<EnrolResponse>('/auth/mfa/enrol', {
        method: 'email',
      })
      setMessage(res.data.message)
      setStep('verify')
    } catch (err: unknown) {
      const detail = (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail
      setError(detail ?? 'Failed to send verification email. Please try again.')
    } finally {
      setLoading(false)
    }
  }

  const resendOtp = async () => {
    setResending(true)
    setError('')
    try {
      const res = await apiClient.post<EnrolResponse>('/auth/mfa/enrol', {
        method: 'email',
      })
      setMessage(res.data.message)
    } catch (err: unknown) {
      const detail = (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail
      setError(detail ?? 'Failed to resend verification email. Please try again.')
    } finally {
      setResending(false)
    }
  }

  const verifyCode = async () => {
    if (code.length !== 6) {
      setError('Please enter a 6-digit code')
      return
    }
    setLoading(true)
    setError('')
    try {
      await apiClient.post('/auth/mfa/enrol/verify', { method: 'email', code })
      setSuccess(true)
    } catch (err: unknown) {
      const detail = (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail
      setError(detail ?? 'Invalid code. Please try again.')
    } finally {
      setLoading(false)
    }
  }

  const handleCodeChange = (value: string) => {
    const digits = value.replace(/\D/g, '').slice(0, 6)
    setCode(digits)
    if (error) setError('')
  }

  if (success) {
    return (
      <div className="space-y-4 text-center">
        <div className="mx-auto flex h-12 w-12 items-center justify-center rounded-full bg-green-100">
          <svg className="h-6 w-6 text-green-600" fill="none" viewBox="0 0 24 24" strokeWidth="2" stroke="currentColor" aria-hidden="true">
            <path strokeLinecap="round" strokeLinejoin="round" d="M4.5 12.75l6 6 9-13.5" />
          </svg>
        </div>
        <p className="text-sm font-medium text-gray-900">Email verification enabled</p>
        <p className="text-sm text-gray-500">Your account is now protected with email verification codes.</p>
        <button
          onClick={onComplete}
          className="w-full rounded-md bg-blue-600 px-4 py-2 text-sm font-medium text-white hover:bg-blue-700"
        >
          Done
        </button>
      </div>
    )
  }

  if (step === 'send') {
    return (
      <div className="space-y-4">
        <p className="text-sm text-gray-600">
          A 6-digit verification code will be sent to your registered email address.
        </p>

        {error && (
          <div className="rounded-md bg-red-50 border border-red-200 p-3" role="alert">
            <p className="text-sm text-red-700">{error}</p>
          </div>
        )}

        <div className="flex gap-3">
          <button
            onClick={onCancel}
            className="rounded-md border border-gray-300 px-4 py-2 text-sm text-gray-700 hover:bg-gray-50"
            disabled={loading}
          >
            Cancel
          </button>
          <button
            onClick={sendOtp}
            disabled={loading}
            className="rounded-md bg-blue-600 px-4 py-2 text-sm font-medium text-white hover:bg-blue-700 disabled:opacity-50"
          >
            {loading ? 'Sending…' : 'Send code'}
          </button>
        </div>
      </div>
    )
  }

  // Step: verify — enter 6-digit OTP code
  return (
    <div className="space-y-4">
      <p className="text-sm text-gray-600">{message}</p>

      <div>
        <label htmlFor="email-code" className="block text-sm font-medium text-gray-700 mb-1">
          Verification code
        </label>
        <input
          id="email-code"
          type="text"
          inputMode="numeric"
          autoComplete="one-time-code"
          maxLength={6}
          value={code}
          onChange={e => handleCodeChange(e.target.value)}
          placeholder="000000"
          className="block w-full rounded-md border border-gray-300 px-3 py-2 text-center text-lg font-mono tracking-widest placeholder:text-gray-400 focus:border-blue-500 focus:outline-none focus:ring-1 focus:ring-blue-500"
          aria-label="6-digit verification code"
          disabled={loading}
        />
      </div>

      {error && (
        <div className="rounded-md bg-red-50 border border-red-200 p-3" role="alert">
          <p className="text-sm text-red-700">{error}</p>
        </div>
      )}

      <div className="flex items-center justify-between">
        <button
          onClick={resendOtp}
          disabled={resending || loading}
          className="text-sm text-blue-600 hover:text-blue-700 disabled:opacity-50"
          type="button"
        >
          {resending ? 'Resending…' : 'Resend code'}
        </button>
      </div>

      <div className="flex gap-3">
        <button
          onClick={onCancel}
          className="rounded-md border border-gray-300 px-4 py-2 text-sm text-gray-700 hover:bg-gray-50"
          disabled={loading}
        >
          Cancel
        </button>
        <button
          onClick={verifyCode}
          disabled={loading || code.length !== 6}
          className="rounded-md bg-blue-600 px-4 py-2 text-sm font-medium text-white hover:bg-blue-700 disabled:opacity-50"
        >
          {loading ? 'Verifying…' : 'Verify'}
        </button>
      </div>
    </div>
  )
}
