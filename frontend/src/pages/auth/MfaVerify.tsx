import { useState, useRef, useEffect } from 'react'
import type { FormEvent, KeyboardEvent, ClipboardEvent } from 'react'
import { useNavigate } from 'react-router-dom'
import { useAuth } from '@/contexts/AuthContext'
import { Button, AlertBanner } from '@/components/ui'

type MfaMethod = 'totp' | 'sms' | 'email' | 'backup'

const METHOD_LABELS: Record<MfaMethod, string> = {
  totp: 'Authenticator app',
  sms: 'SMS code',
  email: 'Email code',
  backup: 'Backup code',
}

export function MfaVerify() {
  const { completeMfa, mfaPending } = useAuth()
  const navigate = useNavigate()

  const [method, setMethod] = useState<MfaMethod>('totp')
  const [digits, setDigits] = useState<string[]>(Array(6).fill(''))
  const [backupCode, setBackupCode] = useState('')
  const [error, setError] = useState<string | null>(null)
  const [submitting, setSubmitting] = useState(false)
  const inputRefs = useRef<(HTMLInputElement | null)[]>([])

  useEffect(() => {
    if (!mfaPending) navigate('/auth/login')
  }, [mfaPending, navigate])

  useEffect(() => {
    inputRefs.current[0]?.focus()
  }, [method])

  function handleDigitChange(index: number, value: string) {
    if (!/^\d?$/.test(value)) return
    const next = [...digits]
    next[index] = value
    setDigits(next)
    if (value && index < 5) {
      inputRefs.current[index + 1]?.focus()
    }
  }

  function handleKeyDown(index: number, e: KeyboardEvent<HTMLInputElement>) {
    if (e.key === 'Backspace' && !digits[index] && index > 0) {
      inputRefs.current[index - 1]?.focus()
    }
  }

  function handlePaste(e: ClipboardEvent<HTMLInputElement>) {
    e.preventDefault()
    const pasted = e.clipboardData.getData('text').replace(/\D/g, '').slice(0, 6)
    const next = Array(6).fill('')
    for (let i = 0; i < pasted.length; i++) next[i] = pasted[i]
    setDigits(next)
    inputRefs.current[Math.min(pasted.length, 5)]?.focus()
  }

  async function handleSubmit(e: FormEvent) {
    e.preventDefault()
    setError(null)
    const code = method === 'backup' ? backupCode.trim() : digits.join('')
    if (method !== 'backup' && code.length !== 6) {
      setError('Please enter all 6 digits')
      return
    }
    if (method === 'backup' && !code) {
      setError('Please enter a backup code')
      return
    }
    setSubmitting(true)
    try {
      await completeMfa(code, method)
      navigate('/')
    } catch {
      setError('Invalid code. Please try again.')
    } finally {
      setSubmitting(false)
    }
  }

  return (
    <div className="flex min-h-screen items-center justify-center bg-gray-50 px-4">
      <div className="w-full max-w-md space-y-6 rounded-xl bg-white p-8 shadow-lg">
        <div className="text-center">
          <h1 className="text-2xl font-bold text-gray-900">
            Two-factor authentication
          </h1>
          <p className="mt-1 text-sm text-gray-500">
            Enter the verification code to continue
          </p>
        </div>

        {error && (
          <AlertBanner variant="error" onDismiss={() => setError(null)}>
            {error}
          </AlertBanner>
        )}

        {/* Method selector */}
        <fieldset>
          <legend className="text-sm font-medium text-gray-700">
            Verification method
          </legend>
          <div className="mt-2 flex flex-wrap gap-2">
            {(Object.keys(METHOD_LABELS) as MfaMethod[]).map((m) => (
              <button
                key={m}
                type="button"
                onClick={() => {
                  setMethod(m)
                  setDigits(Array(6).fill(''))
                  setBackupCode('')
                  setError(null)
                }}
                className={`rounded-full px-3 py-1 text-sm font-medium transition-colors ${
                  method === m
                    ? 'bg-blue-600 text-white'
                    : 'bg-gray-100 text-gray-700 hover:bg-gray-200'
                }`}
                aria-pressed={method === m}
              >
                {METHOD_LABELS[m]}
              </button>
            ))}
          </div>
        </fieldset>

        <form onSubmit={handleSubmit} className="space-y-4">
          {method === 'backup' ? (
            <div className="flex flex-col gap-1">
              <label
                htmlFor="backup-code"
                className="text-sm font-medium text-gray-700"
              >
                Backup code
              </label>
              <input
                id="backup-code"
                type="text"
                value={backupCode}
                onChange={(e) => setBackupCode(e.target.value)}
                className="rounded-md border border-gray-300 px-3 py-2 text-center font-mono text-lg tracking-widest focus:border-blue-500 focus:outline-none focus:ring-2 focus:ring-blue-500"
                placeholder="xxxx-xxxx-xxxx"
                autoComplete="one-time-code"
              />
            </div>
          ) : (
            <div>
              <label className="mb-2 block text-sm font-medium text-gray-700">
                6-digit code
              </label>
              <div
                className="flex justify-center gap-2"
                role="group"
                aria-label="Verification code"
              >
                {digits.map((d, i) => (
                  <input
                    key={i}
                    ref={(el) => {
                      inputRefs.current[i] = el
                    }}
                    type="text"
                    inputMode="numeric"
                    maxLength={1}
                    value={d}
                    onChange={(e) => handleDigitChange(i, e.target.value)}
                    onKeyDown={(e) => handleKeyDown(i, e)}
                    onPaste={i === 0 ? handlePaste : undefined}
                    className="h-12 w-10 rounded-md border border-gray-300 text-center text-xl font-semibold focus:border-blue-500 focus:outline-none focus:ring-2 focus:ring-blue-500"
                    aria-label={`Digit ${i + 1}`}
                    autoComplete={i === 0 ? 'one-time-code' : 'off'}
                  />
                ))}
              </div>
            </div>
          )}

          <Button type="submit" loading={submitting} className="w-full">
            Verify
          </Button>
        </form>
      </div>
    </div>
  )
}
