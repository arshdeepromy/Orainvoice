import { useState } from 'react'
import apiClient from '@/api/client'

interface TotpEnrolWizardProps {
  onComplete: () => void
  onCancel: () => void
}

interface EnrolData {
  qr_uri: string
  secret: string
  message: string
}

type Step = 'setup' | 'verify'

export function TotpEnrolWizard({ onComplete, onCancel }: TotpEnrolWizardProps) {
  const [step, setStep] = useState<Step>('setup')
  const [enrolData, setEnrolData] = useState<EnrolData | null>(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')
  const [code, setCode] = useState('')
  const [success, setSuccess] = useState(false)
  const [copied, setCopied] = useState(false)

  const startEnrolment = async () => {
    setLoading(true)
    setError('')
    try {
      const res = await apiClient.post<EnrolData>('/auth/mfa/enrol', { method: 'totp' })
      setEnrolData(res.data)
      setStep('verify')
    } catch (err: unknown) {
      const detail = (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail
      setError(detail ?? 'Failed to start TOTP enrolment')
    } finally {
      setLoading(false)
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
      await apiClient.post('/auth/mfa/enrol/verify', { method: 'totp', code })
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

  const copySecret = async () => {
    if (!enrolData) return
    try {
      await navigator.clipboard.writeText(enrolData.secret)
      setCopied(true)
      setTimeout(() => setCopied(false), 2000)
    } catch {
      // Fallback: select text for manual copy
    }
  }

  const qrImageUrl = enrolData
    ? `https://api.qrserver.com/v1/create-qr-code/?size=200x200&data=${encodeURIComponent(enrolData.qr_uri)}`
    : ''

  if (success) {
    return (
      <div className="space-y-4 text-center">
        <div className="mx-auto flex h-12 w-12 items-center justify-center rounded-full bg-green-100">
          <svg className="h-6 w-6 text-green-600" fill="none" viewBox="0 0 24 24" strokeWidth="2" stroke="currentColor" aria-hidden="true">
            <path strokeLinecap="round" strokeLinejoin="round" d="M4.5 12.75l6 6 9-13.5" />
          </svg>
        </div>
        <p className="text-sm font-medium text-gray-900">Authenticator app enabled</p>
        <p className="text-sm text-gray-500">Your account is now protected with TOTP verification.</p>
        <button
          onClick={onComplete}
          className="w-full rounded-md bg-blue-600 px-4 py-2 text-sm font-medium text-white hover:bg-blue-700"
        >
          Done
        </button>
      </div>
    )
  }

  if (step === 'setup') {
    return (
      <div className="space-y-4">
        <p className="text-sm text-gray-600">
          Set up your authenticator app (e.g. Google Authenticator, Authy) to generate verification codes for your account.
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
            onClick={startEnrolment}
            disabled={loading}
            className="rounded-md bg-blue-600 px-4 py-2 text-sm font-medium text-white hover:bg-blue-700 disabled:opacity-50"
          >
            {loading ? 'Setting up…' : 'Continue'}
          </button>
        </div>
      </div>
    )
  }

  // Step: verify — show QR code, secret, and code input
  return (
    <div className="space-y-5">
      {/* Step 1: QR code and secret */}
      <div className="space-y-3">
        <p className="text-sm font-medium text-gray-900">Step 1: Scan QR code</p>
        <p className="text-sm text-gray-600">
          Scan this QR code with your authenticator app, or enter the secret key manually.
        </p>

        <div className="flex justify-center">
          <img
            src={qrImageUrl}
            alt="TOTP QR code for authenticator app"
            width={200}
            height={200}
            className="rounded-md border border-gray-200"
          />
        </div>

        {/* Manual entry secret */}
        <div className="rounded-md bg-gray-50 border border-gray-200 p-3">
          <p className="text-xs text-gray-500 mb-1">Manual entry key:</p>
          <div className="flex items-center gap-2">
            <code className="flex-1 text-sm font-mono text-gray-900 break-all select-all">
              {enrolData?.secret}
            </code>
            <button
              onClick={copySecret}
              className="shrink-0 rounded border border-gray-300 px-2 py-1 text-xs text-gray-600 hover:bg-gray-100"
              type="button"
            >
              {copied ? 'Copied!' : 'Copy'}
            </button>
          </div>
        </div>
      </div>

      {/* Step 2: Code verification */}
      <div className="space-y-3">
        <p className="text-sm font-medium text-gray-900">Step 2: Enter verification code</p>
        <p className="text-sm text-gray-600">
          Enter the 6-digit code from your authenticator app to verify setup.
        </p>

        <input
          type="text"
          inputMode="numeric"
          autoComplete="one-time-code"
          maxLength={6}
          value={code}
          onChange={e => handleCodeChange(e.target.value)}
          placeholder="000000"
          className="block w-full rounded-md border border-gray-300 px-3 py-2 text-center text-lg font-mono tracking-widest placeholder:text-gray-400 focus:border-blue-500 focus:outline-none focus:ring-1 focus:ring-blue-500"
          aria-label="Verification code"
          disabled={loading}
        />

        {error && (
          <div className="rounded-md bg-red-50 border border-red-200 p-3" role="alert">
            <p className="text-sm text-red-700">{error}</p>
          </div>
        )}
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
