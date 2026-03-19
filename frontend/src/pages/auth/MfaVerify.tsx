import { useState, useRef, useEffect, useCallback } from 'react'
import type { FormEvent, KeyboardEvent, ClipboardEvent } from 'react'
import { useNavigate } from 'react-router-dom'
import { useAuth } from '@/contexts/AuthContext'
import apiClient from '@/api/client'
import { Button, AlertBanner } from '@/components/ui'

type MfaMethod = 'totp' | 'sms' | 'email' | 'backup' | 'passkey'

const METHOD_LABELS: Record<MfaMethod, string> = {
  totp: 'Authenticator app',
  sms: 'SMS code',
  email: 'Email code',
  backup: 'Backup code',
  passkey: 'Passkey',
}

/** SVG icon components for each MFA method */
function TotpIcon({ className }: { className?: string }) {
  return (
    <svg className={className} fill="none" viewBox="0 0 24 24" strokeWidth={1.5} stroke="currentColor" aria-hidden="true">
      <path strokeLinecap="round" strokeLinejoin="round" d="M16.5 10.5V6.75a4.5 4.5 0 10-9 0v3.75m-.75 11.25h10.5a2.25 2.25 0 002.25-2.25v-6.75a2.25 2.25 0 00-2.25-2.25H6.75a2.25 2.25 0 00-2.25 2.25v6.75a2.25 2.25 0 002.25 2.25z" />
    </svg>
  )
}

function SmsIcon({ className }: { className?: string }) {
  return (
    <svg className={className} fill="none" viewBox="0 0 24 24" strokeWidth={1.5} stroke="currentColor" aria-hidden="true">
      <path strokeLinecap="round" strokeLinejoin="round" d="M10.5 1.5H8.25A2.25 2.25 0 006 3.75v16.5a2.25 2.25 0 002.25 2.25h7.5A2.25 2.25 0 0018 20.25V3.75a2.25 2.25 0 00-2.25-2.25H13.5m-3 0V3h3V1.5m-3 0h3m-3 18.75h3" />
    </svg>
  )
}

function EmailIcon({ className }: { className?: string }) {
  return (
    <svg className={className} fill="none" viewBox="0 0 24 24" strokeWidth={1.5} stroke="currentColor" aria-hidden="true">
      <path strokeLinecap="round" strokeLinejoin="round" d="M21.75 6.75v10.5a2.25 2.25 0 01-2.25 2.25h-15a2.25 2.25 0 01-2.25-2.25V6.75m19.5 0A2.25 2.25 0 0019.5 4.5h-15a2.25 2.25 0 00-2.25 2.25m19.5 0v.243a2.25 2.25 0 01-1.07 1.916l-7.5 4.615a2.25 2.25 0 01-2.36 0L3.32 8.91a2.25 2.25 0 01-1.07-1.916V6.75" />
    </svg>
  )
}

function BackupIcon({ className }: { className?: string }) {
  return (
    <svg className={className} fill="none" viewBox="0 0 24 24" strokeWidth={1.5} stroke="currentColor" aria-hidden="true">
      <path strokeLinecap="round" strokeLinejoin="round" d="M15.75 5.25a3 3 0 013 3m3 0a6 6 0 01-7.029 5.912c-.563-.097-1.159.026-1.563.43L10.5 17.25H8.25v2.25H6v2.25H2.25v-2.818c0-.597.237-1.17.659-1.591l6.499-6.499c.404-.404.527-1 .43-1.563A6 6 0 1121.75 8.25z" />
    </svg>
  )
}

function PasskeyIcon({ className }: { className?: string }) {
  return (
    <svg className={className} fill="none" viewBox="0 0 24 24" strokeWidth={1.5} stroke="currentColor" aria-hidden="true">
      <path strokeLinecap="round" strokeLinejoin="round" d="M7.864 4.243A7.5 7.5 0 0119.5 10.5c0 2.92-.556 5.709-1.568 8.268M5.742 6.364A7.465 7.465 0 004.5 10.5a48.667 48.667 0 00-1.26 8.303M15 10.5a3 3 0 11-6 0 3 3 0 016 0zm-2.25 6a3.75 3.75 0 00-3.75 3.75v.443c0 .576.162 1.14.47 1.626a7.5 7.5 0 009.06 0c.308-.486.47-1.05.47-1.626v-.443a3.75 3.75 0 00-3.75-3.75h-2.5z" />
    </svg>
  )
}

const METHOD_ICON_COMPONENTS: Record<MfaMethod, React.FC<{ className?: string }>> = {
  totp: TotpIcon,
  sms: SmsIcon,
  email: EmailIcon,
  backup: BackupIcon,
  passkey: PasskeyIcon,
}

/** Helper to base64url-encode an ArrayBuffer for WebAuthn */
function bufferToBase64url(buffer: ArrayBuffer): string {
  const bytes = new Uint8Array(buffer)
  let binary = ''
  for (const b of bytes) binary += String.fromCharCode(b)
  return btoa(binary).replace(/\+/g, '-').replace(/\//g, '_').replace(/=+$/, '')
}

/** Helper to decode base64url to ArrayBuffer for WebAuthn */
function base64urlToBuffer(base64url: string): ArrayBuffer {
  const base64 = base64url.replace(/-/g, '+').replace(/_/g, '/')
  const padded = base64 + '='.repeat((4 - (base64.length % 4)) % 4)
  const binary = atob(padded)
  const bytes = new Uint8Array(binary.length)
  for (let i = 0; i < binary.length; i++) bytes[i] = binary.charCodeAt(i)
  return bytes.buffer
}

export function MfaVerify() {
  const { completeMfa, completeFirebaseMfa, mfaPending, mfaSessionToken, mfaMethods, mfaDefaultMethod } = useAuth()
  const navigate = useNavigate()

  // Only show methods the backend says are enabled — no fallback to all methods.
  // The backend sends the exact list of enabled methods for this user.
  const availableMethods: MfaMethod[] = mfaMethods.length > 0
    ? (mfaMethods as MfaMethod[])
    : ['totp'] // minimal fallback — TOTP is always the base method

  // Pre-select the user's default method if set, otherwise first available
  const initialMethod: MfaMethod = (mfaDefaultMethod && availableMethods.includes(mfaDefaultMethod as MfaMethod))
    ? (mfaDefaultMethod as MfaMethod)
    : (availableMethods[0] ?? 'totp')

  const [method, setMethod] = useState<MfaMethod>(initialMethod)
  const [digits, setDigits] = useState<string[]>(Array(6).fill(''))
  const [backupCode, setBackupCode] = useState('')
  const [error, setError] = useState<string | null>(null)
  const [submitting, setSubmitting] = useState(false)
  const [challengeSent, setChallengeSent] = useState(false)
  const [sendingChallenge, setSendingChallenge] = useState(false)
  const [passkeyLoading, setPasskeyLoading] = useState(false)
  const [resendCooldown, setResendCooldown] = useState(0)
  const inputRefs = useRef<(HTMLInputElement | null)[]>([])
  const firebaseConfirmationRef = useRef<{ confirm: (code: string) => Promise<{ user: { getIdToken: () => Promise<string> } }> } | null>(null)

  useEffect(() => {
    if (!mfaPending) navigate('/login')
  }, [mfaPending, navigate])

  // Tick down the resend cooldown timer
  useEffect(() => {
    if (resendCooldown <= 0) return
    const id = setInterval(() => setResendCooldown((c) => Math.max(0, c - 1)), 1000)
    return () => clearInterval(id)
  }, [resendCooldown])

  // Auto-send challenge OTP when SMS or email is selected
  const sendChallengeOtp = useCallback(
    async (selectedMethod: MfaMethod) => {
      if (selectedMethod !== 'sms' && selectedMethod !== 'email') return
      if (!mfaSessionToken) return
      setSendingChallenge(true)
      setError(null)
      try {
        // For SMS: check if Firebase is the MFA default provider
        if (selectedMethod === 'sms') {
          const cfgRes = await apiClient.post('/auth/mfa/provider-config', {
            mfa_token: mfaSessionToken,
          })
          const { provider, firebase_config, phone_number } = cfgRes.data

          if (provider === 'firebase_phone_auth' && firebase_config && phone_number) {
            const { initializeApp, getApps, deleteApp } = await import('firebase/app')
            const { getAuth, signInWithPhoneNumber, RecaptchaVerifier } = await import('firebase/auth')

            const existingApps = getApps()
            const existing = existingApps.find(a => a.name === '__mfa_firebase__')
            if (existing) await deleteApp(existing)
            const app = initializeApp(firebase_config, '__mfa_firebase__')
            const auth = getAuth(app)

            const container = document.getElementById('mfa-recaptcha-container')
            if (container) container.innerHTML = ''
            const recaptchaVerifier = new RecaptchaVerifier(auth, 'mfa-recaptcha-container', {
              size: 'invisible',
            })

            const confirmationResult = await signInWithPhoneNumber(auth, phone_number, recaptchaVerifier)
            firebaseConfirmationRef.current = confirmationResult
            setChallengeSent(true)
            setResendCooldown(60)
            return
          }
        }

        // Default: use server-side OTP
        await apiClient.post('/auth/mfa/challenge/send', {
          mfa_token: mfaSessionToken,
          method: selectedMethod,
        })
        setChallengeSent(true)
        setResendCooldown(60)
      } catch (err: unknown) {
        const response = (err as { response?: { status?: number; data?: { detail?: string } } })?.response
        if (response?.status === 429) {
          setError('Too many code requests. Please wait before requesting a new code.')
        } else if (response?.status === 401) {
          setError('Your session has expired. Please log in again.')
          setTimeout(() => navigate('/login'), 2000)
        } else {
          setError(response?.data?.detail ?? 'Failed to send verification code. Please try again.')
        }
      } finally {
        setSendingChallenge(false)
      }
    },
    [mfaSessionToken, navigate],
  )

  // Send challenge when SMS/email is first selected
  useEffect(() => {
    if (method === 'sms' || method === 'email') {
      setChallengeSent(false)
      sendChallengeOtp(method)
    }
    inputRefs.current[0]?.focus()
  }, [method]) // eslint-disable-line react-hooks/exhaustive-deps

  function handleMethodSelect(m: MfaMethod) {
    setMethod(m)
    setDigits(Array(6).fill(''))
    setBackupCode('')
    setError(null)
    setChallengeSent(false)
    if (m === 'passkey') handlePasskeyAuth()
  }

  function handleDigitChange(index: number, value: string) {
    if (!/^\d?$/.test(value)) return
    const next = [...digits]
    next[index] = value
    setDigits(next)
    if (value && index < 5) inputRefs.current[index + 1]?.focus()
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

  async function handlePasskeyAuth() {
    if (!mfaSessionToken) return
    setPasskeyLoading(true)
    setError(null)
    try {
      const optionsRes = await apiClient.post('/auth/passkey/login/options', {
        mfa_token: mfaSessionToken,
      })
      const options = optionsRes.data.options ?? optionsRes.data

      const publicKeyOptions: PublicKeyCredentialRequestOptions = {
        challenge: base64urlToBuffer(options.challenge),
        timeout: options.timeout,
        rpId: window.location.hostname,
        allowCredentials: (options.allowCredentials ?? []).map(
          (cred: { id: string; type: string; transports?: string[] }) => ({
            id: base64urlToBuffer(cred.id),
            type: cred.type,
            transports: cred.transports,
          }),
        ),
        userVerification: options.userVerification ?? 'preferred',
      }

      const credential = (await navigator.credentials.get({
        publicKey: publicKeyOptions,
      })) as PublicKeyCredential | null

      if (!credential) {
        setError('Passkey authentication was cancelled.')
        setPasskeyLoading(false)
        return
      }

      const assertionResponse = credential.response as AuthenticatorAssertionResponse

      const verifyRes = await apiClient.post('/auth/passkey/login/verify', {
        mfa_token: mfaSessionToken,
        credential_id: bufferToBase64url(credential.rawId),
        authenticator_data: bufferToBase64url(assertionResponse.authenticatorData),
        client_data_json: bufferToBase64url(assertionResponse.clientDataJSON),
        signature: bufferToBase64url(assertionResponse.signature),
        user_handle: assertionResponse.userHandle
          ? bufferToBase64url(assertionResponse.userHandle)
          : null,
      })

      const { access_token } = verifyRes.data
      if (access_token) {
        const { setAccessToken } = await import('@/api/client')
        setAccessToken(access_token)
        window.location.replace('/')
      }
    } catch (err: unknown) {
      const response = (err as { response?: { status?: number; data?: { detail?: string } } })?.response
      if (response?.status === 429) {
        setError('Too many failed attempts. Please log in again.')
      } else if (response?.status === 401) {
        setError('Your session has expired. Please log in again.')
        setTimeout(() => navigate('/login'), 2000)
      } else if (response?.status === 403) {
        setError('This passkey has been flagged for security review. Please use another method or contact your administrator.')
      } else {
        setError('Passkey authentication failed. Please try again or use another method.')
      }
    } finally {
      setPasskeyLoading(false)
    }
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
      // If Firebase was used to send the code, verify via Firebase then complete MFA
      if (method === 'sms' && firebaseConfirmationRef.current) {
        await firebaseConfirmationRef.current.confirm(code)
        await completeFirebaseMfa()
        firebaseConfirmationRef.current = null
      } else {
        await completeMfa(code, method)
      }
      navigate('/')
    } catch (err: unknown) {
      const response = (err as { response?: { status?: number; data?: { detail?: string } } })?.response
      if (response?.status === 429) {
        setError('Too many failed attempts. Your session has been locked. Please log in again.')
        setTimeout(() => navigate('/login'), 3000)
      } else if (response?.status === 401) {
        setError('Your session has expired. Please log in again.')
        setTimeout(() => navigate('/login'), 2000)
      } else {
        setError(response?.data?.detail ?? 'Invalid code. Please try again.')
      }
    } finally {
      setSubmitting(false)
    }
  }

  const methodHint = method === 'sms'
    ? 'Enter the 6-digit code sent to your phone'
    : method === 'email'
      ? 'Enter the 6-digit code sent to your email'
      : method === 'totp'
        ? 'Enter the code from your authenticator app'
        : undefined

  return (
    <div className="flex min-h-screen items-center justify-center bg-gray-50 px-4">
      <div className="w-full max-w-md space-y-6 rounded-xl bg-white p-8 shadow-lg">
        <div className="text-center">
          <div className="mx-auto mb-3 flex h-12 w-12 items-center justify-center rounded-full bg-blue-100">
            <svg className="h-6 w-6 text-blue-600" fill="none" viewBox="0 0 24 24" strokeWidth={1.5} stroke="currentColor" aria-hidden="true">
              <path strokeLinecap="round" strokeLinejoin="round" d="M9 12.75L11.25 15 15 9.75m-3-7.036A11.959 11.959 0 013.598 6 11.99 11.99 0 003 9.749c0 5.592 3.824 10.29 9 11.623 5.176-1.332 9-6.03 9-11.622 0-1.31-.21-2.571-.598-3.751h-.152c-3.196 0-6.1-1.248-8.25-3.285z" />
            </svg>
          </div>
          <h1 className="text-2xl font-bold text-gray-900">
            Two-factor authentication
          </h1>
          <p className="mt-1 text-sm text-gray-500">
            Verify your identity to continue
          </p>
        </div>

        {error && (
          <AlertBanner variant="error" onDismiss={() => setError(null)}>
            {error}
          </AlertBanner>
        )}

        {/* Method selector — only show if more than one method available */}
        {availableMethods.length > 1 && (
          <div>
            <p className="mb-2 text-sm font-medium text-gray-700">
              Verification method
            </p>
            <div className="flex flex-wrap gap-2">
              {availableMethods.map((m) => {
                const IconComponent = METHOD_ICON_COMPONENTS[m]
                return (
                  <button
                    key={m}
                    type="button"
                    onClick={() => handleMethodSelect(m)}
                    className={`flex items-center gap-1.5 rounded-lg border px-3 py-2 text-sm font-medium transition-colors ${
                      method === m
                        ? 'border-blue-600 bg-blue-50 text-blue-700'
                        : 'border-gray-200 bg-white text-gray-700 hover:border-gray-300 hover:bg-gray-50'
                    }`}
                    aria-pressed={method === m}
                    disabled={passkeyLoading}
                  >
                    <IconComponent className="h-4 w-4" />
                    {METHOD_LABELS[m]}
                  </button>
                )
              })}
            </div>
          </div>
        )}

        {/* Passkey flow */}
        {method === 'passkey' && (
          <div className="space-y-4 text-center">
            {passkeyLoading ? (
              <div className="py-8">
                <div className="mx-auto h-8 w-8 animate-spin rounded-full border-4 border-blue-600 border-t-transparent" />
                <p className="mt-3 text-sm text-gray-600">
                  Waiting for your passkey...
                </p>
              </div>
            ) : (
              <div className="py-4">
                <p className="text-sm text-gray-600 mb-4">
                  Use your security key or device biometrics to verify your identity.
                </p>
                <Button type="button" onClick={() => handlePasskeyAuth()} className="w-full">
                  Try passkey again
                </Button>
              </div>
            )}
          </div>
        )}

        {/* Code-based methods (totp, sms, email, backup) */}
        {method !== 'passkey' && (
          <form onSubmit={handleSubmit} className="space-y-4">
            {(method === 'sms' || method === 'email') && sendingChallenge && (
              <p className="text-center text-sm text-gray-500">Sending code...</p>
            )}

            {methodHint && (method === 'totp' || challengeSent) && (
              <p className="text-center text-sm text-gray-500">{methodHint}</p>
            )}

            {method === 'backup' ? (
              <div className="flex flex-col gap-1">
                <label htmlFor="backup-code" className="text-sm font-medium text-gray-700">
                  Backup code
                </label>
                <input
                  id="backup-code"
                  type="text"
                  value={backupCode}
                  onChange={(e) => setBackupCode(e.target.value)}
                  className="rounded-lg border border-gray-300 px-3 py-2.5 text-center font-mono text-lg tracking-widest focus:border-blue-500 focus:outline-none focus:ring-2 focus:ring-blue-500"
                  placeholder="xxxx-xxxx-xxxx"
                  autoComplete="one-time-code"
                />
              </div>
            ) : (
              <div>
                <label className="mb-2 block text-sm font-medium text-gray-700">
                  6-digit code
                </label>
                <div className="flex justify-center gap-2" role="group" aria-label="Verification code">
                  {digits.map((d, i) => (
                    <input
                      key={i}
                      ref={(el) => { inputRefs.current[i] = el }}
                      type="text"
                      inputMode="numeric"
                      maxLength={1}
                      value={d}
                      onChange={(e) => handleDigitChange(i, e.target.value)}
                      onKeyDown={(e) => handleKeyDown(i, e)}
                      onPaste={i === 0 ? handlePaste : undefined}
                      className="h-12 w-10 rounded-lg border border-gray-300 text-center text-xl font-semibold focus:border-blue-500 focus:outline-none focus:ring-2 focus:ring-blue-500"
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

            {(method === 'sms' || method === 'email') && challengeSent && (
              <button
                type="button"
                onClick={() => sendChallengeOtp(method)}
                disabled={sendingChallenge || resendCooldown > 0}
                className="w-full text-center text-sm font-medium text-blue-600 hover:text-blue-500 disabled:text-gray-400"
              >
                {sendingChallenge ? 'Sending...' : resendCooldown > 0 ? `Resend code (${resendCooldown}s)` : 'Resend code'}
              </button>
            )}
          </form>
        )}

        {/* Recovery: always show backup code option when not already using it */}
        {method !== 'backup' && (
          <p className="text-center text-sm text-gray-500">
            Can&apos;t access your verification method?{' '}
            <button
              type="button"
              onClick={() => handleMethodSelect('backup')}
              className="font-medium text-blue-600 hover:text-blue-500"
            >
              Use a backup code
            </button>
          </p>
        )}

        {/* Back to login link */}
        <p className="text-center text-sm text-gray-500">
          <button
            type="button"
            onClick={() => navigate('/login')}
            className="font-medium text-blue-600 hover:text-blue-500"
          >
            Back to sign in
          </button>
        </p>
        {/* Invisible reCAPTCHA container for Firebase Phone Auth */}
        <div id="mfa-recaptcha-container" />
      </div>
    </div>
  )
}
