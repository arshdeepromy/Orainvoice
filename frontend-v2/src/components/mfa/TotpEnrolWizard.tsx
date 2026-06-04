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
        <div className="mx-auto flex h-12 w-12 items-center justify-center rounded-full bg-ok-soft">
          <svg className="h-6 w-6 text-ok" fill="none" viewBox="0 0 24 24" strokeWidth="2" stroke="currentColor" aria-hidden="true">
            <path strokeLinecap="round" strokeLinejoin="round" d="M4.5 12.75l6 6 9-13.5" />
          </svg>
        </div>
        <p className="text-sm font-medium text-text">Authenticator app enabled</p>
        <p className="text-sm text-muted-2">Your account is now protected with TOTP verification.</p>
        <button
          onClick={onComplete}
          className="w-full rounded-ctl bg-accent px-4 py-2 text-sm font-medium text-white hover:bg-accent-press"
        >
          Done
        </button>
      </div>
    )
  }

  if (step === 'setup') {
    return (
      <div className="space-y-4">
        <p className="text-sm text-muted">
          Set up your authenticator app (e.g. Google Authenticator, Authy) to generate verification codes for your account.
        </p>
        {error && (
          <div className="rounded-ctl bg-danger-soft border border-danger p-3" role="alert">
            <p className="text-sm text-danger">{error}</p>
          </div>
        )}
        <div className="flex gap-3">
          <button
            onClick={onCancel}
            className="rounded-ctl border border-border px-4 py-2 text-sm text-muted hover:bg-canvas"
            disabled={loading}
          >
            Cancel
          </button>
          <button
            onClick={startEnrolment}
            disabled={loading}
            className="rounded-ctl bg-accent px-4 py-2 text-sm font-medium text-white hover:bg-accent-press disabled:opacity-50"
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
        <p className="text-sm font-medium text-text">Step 1: Scan QR code</p>
        <p className="text-sm text-muted">
          Scan this QR code with your authenticator app, or enter the secret key manually.
        </p>

        <div className="flex justify-center">
          <img
            src={qrImageUrl}
            alt="TOTP QR code for authenticator app"
            width={200}
            height={200}
            className="rounded-ctl border border-border"
          />
        </div>

        {/* Manual entry secret */}
        <div className="rounded-ctl bg-canvas border border-border p-3">
          <p className="text-xs text-muted-2 mb-1">Manual entry key:</p>
          <div className="flex items-center gap-2">
            <code className="flex-1 text-sm font-mono text-text break-all select-all">
              {enrolData?.secret}
            </code>
            <button
              onClick={copySecret}
              className="shrink-0 rounded border border-border px-2 py-1 text-xs text-muted hover:bg-canvas"
              type="button"
            >
              {copied ? 'Copied!' : 'Copy'}
            </button>
          </div>
        </div>
      </div>

      {/* Step 2: Code verification */}
      <div className="space-y-3">
        <p className="text-sm font-medium text-text">Step 2: Enter verification code</p>
        <p className="text-sm text-muted">
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
          className="block w-full rounded-ctl border border-border bg-card px-3 py-2 text-center text-lg font-mono tracking-widest text-text placeholder:text-muted-2 focus:border-accent focus:outline-none focus:shadow-[0_0_0_3px_var(--accent-soft)]"
          aria-label="Verification code"
          disabled={loading}
        />

        {error && (
          <div className="rounded-ctl bg-danger-soft border border-danger p-3" role="alert">
            <p className="text-sm text-danger">{error}</p>
          </div>
        )}
      </div>

      <div className="flex gap-3">
        <button
          onClick={onCancel}
          className="rounded-ctl border border-border px-4 py-2 text-sm text-muted hover:bg-canvas"
          disabled={loading}
        >
          Cancel
        </button>
        <button
          onClick={verifyCode}
          disabled={loading || code.length !== 6}
          className="rounded-ctl bg-accent px-4 py-2 text-sm font-medium text-white hover:bg-accent-press disabled:opacity-50"
        >
          {loading ? 'Verifying…' : 'Verify'}
        </button>
      </div>
    </div>
  )
}
