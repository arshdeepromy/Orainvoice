import { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import apiClient from '@/api/client'
import { Button, AlertBanner } from '@/components/ui'

type SetupStep = 'intro' | 'registering' | 'success'

export function PasskeySetup() {
  const navigate = useNavigate()
  const [step, setStep] = useState<SetupStep>('intro')
  const [error, setError] = useState<string | null>(null)

  async function handleRegister() {
    setError(null)
    setStep('registering')
    try {
      // Step 1: get registration options from server
      const optionsRes = await apiClient.post('/auth/passkey/register/options')
      const options = optionsRes.data

      // Step 2: call WebAuthn browser API to create credential
      const credential = await navigator.credentials.create({
        publicKey: options,
      })

      // Step 3: send credential to server for verification and storage
      await apiClient.post('/auth/passkey/register', { credential })
      setStep('success')
    } catch {
      setError(
        'Passkey registration failed. Make sure your device supports passkeys and try again.',
      )
      setStep('intro')
    }
  }

  return (
    <div className="flex min-h-screen items-center justify-center bg-gray-50 px-4">
      <div className="w-full max-w-md space-y-6 rounded-xl bg-white p-8 shadow-lg">
        {step === 'success' ? (
          <div className="space-y-4 text-center">
            <div className="mx-auto flex h-12 w-12 items-center justify-center rounded-full bg-green-100">
              <span className="text-xl text-green-600" aria-hidden="true">✓</span>
            </div>
            <h1 className="text-2xl font-bold text-gray-900">Passkey registered</h1>
            <p className="text-sm text-gray-500">
              You can now sign in using your passkey. No password or MFA code needed.
            </p>
            <Button onClick={() => navigate('/')} className="w-full">
              Continue to dashboard
            </Button>
          </div>
        ) : (
          <>
            <div className="text-center">
              <div className="mx-auto mb-4 flex h-14 w-14 items-center justify-center rounded-full bg-blue-100">
                <svg
                  className="h-7 w-7 text-blue-600"
                  fill="none"
                  viewBox="0 0 24 24"
                  strokeWidth={1.5}
                  stroke="currentColor"
                  aria-hidden="true"
                >
                  <path
                    strokeLinecap="round"
                    strokeLinejoin="round"
                    d="M7.864 4.243A7.5 7.5 0 0119.5 10.5c0 2.92-.556 5.709-1.568 8.268M5.742 6.364A7.465 7.465 0 004.5 10.5a48.667 48.667 0 00-1.26 8.303M15 10.5a3 3 0 11-6 0 3 3 0 016 0zm-2.25 6a3.75 3.75 0 00-3.75 3.75v.443c0 .576.162 1.14.47 1.626a7.5 7.5 0 009.06 0c.308-.486.47-1.05.47-1.626v-.443a3.75 3.75 0 00-3.75-3.75h-2.5z"
                  />
                </svg>
              </div>
              <h1 className="text-2xl font-bold text-gray-900">Set up a Passkey</h1>
              <p className="mt-1 text-sm text-gray-500">
                Use your fingerprint, face, or device PIN to sign in without a password
              </p>
            </div>

            {error && (
              <AlertBanner variant="error" onDismiss={() => setError(null)}>
                {error}
              </AlertBanner>
            )}

            <div className="space-y-3 rounded-lg bg-gray-50 p-4 text-sm text-gray-600">
              <p className="font-medium text-gray-900">How it works</p>
              <ul className="list-inside list-disc space-y-1">
                <li>Your device creates a unique cryptographic key pair</li>
                <li>The private key stays on your device — never shared</li>
                <li>Sign in with biometrics or device PIN — no password needed</li>
                <li>Passkey login satisfies MFA requirements automatically</li>
              </ul>
            </div>

            <Button
              onClick={handleRegister}
              loading={step === 'registering'}
              className="w-full"
            >
              Register Passkey
            </Button>

            <button
              type="button"
              onClick={() => navigate(-1)}
              className="w-full text-center text-sm font-medium text-gray-500 hover:text-gray-700"
            >
              Skip for now
            </button>
          </>
        )}
      </div>
    </div>
  )
}
