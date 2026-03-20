import { useState, useRef, useEffect, useCallback } from 'react'
import apiClient from '@/api/client'

interface SmsEnrolWizardProps {
  onComplete: () => void
  onCancel: () => void
}

interface EnrolResponse {
  method: string
  qr_uri: string | null
  secret: string | null
  message: string
  provider: string | null
  firebase_config: Record<string, string> | null
  phone_number: string | null
}

type Step = 'phone' | 'verify'

const PHONE_REGEX = /^\+[1-9]\d{6,14}$/

export function SmsEnrolWizard({ onComplete, onCancel }: SmsEnrolWizardProps) {
  const [step, setStep] = useState<Step>('phone')
  const [phoneNumber, setPhoneNumber] = useState('')
  const [message, setMessage] = useState('')
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')
  const [code, setCode] = useState('')
  const [success, setSuccess] = useState(false)
  const [resending, setResending] = useState(false)
  const [isFirebase, setIsFirebase] = useState(false)
  const [cooldown, setCooldown] = useState(0)
  const cooldownRef = useRef<ReturnType<typeof setInterval> | null>(null)

  // Firebase refs — keep these stable across step changes
  const firebaseConfirmationRef = useRef<{
    confirm: (code: string) => Promise<unknown>
  } | null>(null)
  const firebaseConfigRef = useRef<Record<string, string> | null>(null)

  const startCooldown = useCallback(() => {
    setCooldown(60)
    if (cooldownRef.current) clearInterval(cooldownRef.current)
    cooldownRef.current = setInterval(() => {
      setCooldown(prev => {
        if (prev <= 1) {
          if (cooldownRef.current) clearInterval(cooldownRef.current)
          cooldownRef.current = null
          return 0
        }
        return prev - 1
      })
    }, 1000)
  }, [])

  useEffect(() => {
    return () => {
      if (cooldownRef.current) clearInterval(cooldownRef.current)
    }
  }, [])

  const phoneValid = PHONE_REGEX.test(phoneNumber)

  /**
   * Initialize Firebase and send SMS via signInWithPhoneNumber.
   * Stores the confirmationResult in firebaseConfirmationRef for later verify.
   */
  const initFirebaseAndSend = async (fbConfig: Record<string, string>, phone: string) => {
    const { initializeApp, getApps, deleteApp } = await import('firebase/app')
    const { getAuth, signInWithPhoneNumber, RecaptchaVerifier } = await import('firebase/auth')

    // Clean up any existing Firebase app instance
    const existingApps = getApps()
    const existing = existingApps.find(a => a.name === '__mfa_enrol_firebase__')
    if (existing) await deleteApp(existing)

    const app = initializeApp(fbConfig, '__mfa_enrol_firebase__')
    const auth = getAuth(app)

    // Reset the reCAPTCHA container (it lives outside conditional renders)
    const container = document.getElementById('enrol-recaptcha-container')
    if (container) container.innerHTML = ''
    const recaptchaVerifier = new RecaptchaVerifier(auth, 'enrol-recaptcha-container', {
      size: 'invisible',
    })

    const confirmationResult = await signInWithPhoneNumber(auth, phone, recaptchaVerifier)
    firebaseConfirmationRef.current = confirmationResult
    firebaseConfigRef.current = fbConfig
  }

  const sendOtp = async () => {
    if (!phoneValid) {
      setError('Enter a valid international phone number (e.g. +64211234567)')
      return
    }
    setLoading(true)
    setError('')
    try {
      const res = await apiClient.post<EnrolResponse>('/auth/mfa/enrol', {
        method: 'sms',
        phone_number: phoneNumber,
      })

      // Check if Firebase is the MFA provider
      if (res.data.provider === 'firebase_phone_auth') {
        setIsFirebase(true)
        let fbConfig = res.data.firebase_config

        // If config wasn't returned inline, fetch from the public endpoint
        if (!fbConfig?.apiKey || !fbConfig?.projectId) {
          const cfgRes = await apiClient.get('/auth/mfa/provider-config')
          fbConfig = cfgRes.data?.firebase_config
        }

        if (!fbConfig?.apiKey || !fbConfig?.projectId) {
          setError('Firebase configuration could not be loaded. Please contact your administrator.')
          return
        }

        await initFirebaseAndSend(fbConfig, phoneNumber)
        setMessage('A verification code has been sent to your phone via Firebase.')
        startCooldown()
        setStep('verify')
      } else {
        // Server-side OTP (Connexus or other provider)
        setIsFirebase(false)
        setMessage(res.data.message)
        startCooldown()
        setStep('verify')
      }
    } catch (err: unknown) {
      const axiosDetail = (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail
      const firebaseErr = err as { code?: string; message?: string }
      let errorMsg = axiosDetail ?? firebaseErr?.message ?? 'Failed to send SMS. Please try again.'
      if (firebaseErr?.code === 'auth/invalid-phone-number') {
        errorMsg = 'Invalid phone number format. Use E.164 format like +64211234567'
      } else if (firebaseErr?.code === 'auth/too-many-requests') {
        errorMsg = 'Too many requests. Wait a few minutes before trying again.'
      } else if (firebaseErr?.code === 'auth/captcha-check-failed') {
        errorMsg = 'reCAPTCHA verification failed. Refresh the page and try again.'
      } else if (firebaseErr?.code === 'auth/quota-exceeded') {
        errorMsg = 'SMS quota exceeded. Check your Firebase project billing.'
      }
      setError(errorMsg)
    } finally {
      setLoading(false)
    }
  }

  const resendOtp = async () => {
    setResending(true)
    setError('')
    try {
      if (isFirebase) {
        // Re-trigger Firebase flow — re-enrol to reset backend state, then resend
        const res = await apiClient.post<EnrolResponse>('/auth/mfa/enrol', {
          method: 'sms',
          phone_number: phoneNumber,
        })
        const fbConfig = res.data.firebase_config ?? firebaseConfigRef.current
        if (fbConfig) {
          await initFirebaseAndSend(fbConfig, phoneNumber)
          setMessage('A new verification code has been sent.')
          startCooldown()
        }
      } else {
        const res = await apiClient.post<EnrolResponse>('/auth/mfa/enrol', {
          method: 'sms',
          phone_number: phoneNumber,
        })
        setMessage(res.data.message)
        startCooldown()
      }
    } catch (err: unknown) {
      const detail = (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail
      const firebaseErr = err as { code?: string; message?: string }
      if (firebaseErr?.code === 'auth/too-many-requests') {
        setError('Too many requests. Wait a few minutes before trying again.')
      } else {
        setError(detail ?? firebaseErr?.message ?? 'Failed to resend SMS. Please try again.')
      }
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
      if (isFirebase && firebaseConfirmationRef.current) {
        // Firebase handles its own code verification via confirm()
        try {
          const confirmResult = await firebaseConfirmationRef.current.confirm(code) as { user: { getIdToken: () => Promise<string> } }
          const firebaseIdToken = await confirmResult.user.getIdToken()
          // Firebase verified the code — tell the backend to mark enrolment as verified
          await apiClient.post('/auth/mfa/enrol/firebase-verify', { firebase_id_token: firebaseIdToken })
        } catch (fbErr: unknown) {
          const firebaseErr = fbErr as { code?: string; message?: string }
          console.error('Firebase confirm error:', firebaseErr.code, firebaseErr.message)
          if (firebaseErr?.code === 'auth/invalid-verification-code') {
            setError('Invalid verification code. Please check and try again.')
          } else if (firebaseErr?.code === 'auth/code-expired') {
            setError('Verification code has expired. Please request a new code.')
          } else if (firebaseErr?.code === 'auth/session-expired') {
            setError('Verification session expired. Please request a new code.')
          } else if (firebaseErr?.code === 'auth/too-many-requests') {
            setError('Too many failed attempts. Wait a few minutes before trying again.')
          } else {
            setError(firebaseErr?.message ?? 'Verification failed. Please try again.')
          }
          return
        }
        firebaseConfirmationRef.current = null
      } else if (isFirebase && !firebaseConfirmationRef.current) {
        setError('Verification session lost. Please request a new code.')
        return
      } else {
        // Server-side OTP verification (Connexus etc.)
        await apiClient.post('/auth/mfa/enrol/verify', { method: 'sms', code })
      }
      setSuccess(true)
    } catch (err: unknown) {
      const detail = (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail
      setError(detail ?? 'Verification failed. Please try again.')
    } finally {
      setLoading(false)
    }
  }

  const handleCodeChange = (value: string) => {
    const digits = value.replace(/\D/g, '').slice(0, 6)
    setCode(digits)
    if (error) setError('')
  }

  const handlePhoneChange = (value: string) => {
    setPhoneNumber(value)
    if (error) setError('')
  }

  if (success) {
    return (
      <div className="space-y-4 text-center">
        {/* reCAPTCHA container must persist across all renders */}
        <div id="enrol-recaptcha-container" />
        <div className="mx-auto flex h-12 w-12 items-center justify-center rounded-full bg-green-100">
          <svg className="h-6 w-6 text-green-600" fill="none" viewBox="0 0 24 24" strokeWidth="2" stroke="currentColor" aria-hidden="true">
            <path strokeLinecap="round" strokeLinejoin="round" d="M4.5 12.75l6 6 9-13.5" />
          </svg>
        </div>
        <p className="text-sm font-medium text-gray-900">SMS verification enabled</p>
        <p className="text-sm text-gray-500">Your account is now protected with SMS verification codes.</p>
        <button
          onClick={onComplete}
          className="w-full rounded-md bg-blue-600 px-4 py-2 text-sm font-medium text-white hover:bg-blue-700"
        >
          Done
        </button>
      </div>
    )
  }

  return (
    <div className="space-y-4">
      {/* reCAPTCHA container — always rendered, never unmounted between steps */}
      <div id="enrol-recaptcha-container" />

      {step === 'phone' && (
        <>
          <p className="text-sm text-gray-600">
            Enter your phone number to receive SMS verification codes. Use international format (e.g. +64211234567).
          </p>

          <div>
            <label htmlFor="sms-phone" className="block text-sm font-medium text-gray-700 mb-1">
              Phone number
            </label>
            <input
              id="sms-phone"
              type="tel"
              value={phoneNumber}
              onChange={e => handlePhoneChange(e.target.value)}
              placeholder="+64211234567"
              className="block w-full rounded-md border border-gray-300 px-3 py-2 text-sm placeholder:text-gray-400 focus:border-blue-500 focus:outline-none focus:ring-1 focus:ring-blue-500"
              aria-label="Phone number in international format"
              disabled={loading}
            />
          </div>

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
              disabled={loading || !phoneValid}
              className="rounded-md bg-blue-600 px-4 py-2 text-sm font-medium text-white hover:bg-blue-700 disabled:opacity-50"
            >
              {loading ? 'Sending…' : 'Send code'}
            </button>
          </div>
        </>
      )}

      {step === 'verify' && (
        <>
          <p className="text-sm text-gray-600">{message}</p>

          <div>
            <label htmlFor="sms-code" className="block text-sm font-medium text-gray-700 mb-1">
              Verification code
            </label>
            <input
              id="sms-code"
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
              disabled={resending || loading || cooldown > 0}
              className="text-sm text-blue-600 hover:text-blue-700 disabled:opacity-50"
              type="button"
            >
              {resending ? 'Resending…' : cooldown > 0 ? `Resend code (${cooldown}s)` : 'Resend code'}
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
        </>
      )}
    </div>
  )
}
