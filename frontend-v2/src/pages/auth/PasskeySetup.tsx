import { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import apiClient from '@/api/client'
import { Button, AlertBanner } from '@/components/ui'

/**
 * PasskeySetup — WebAuthn enrolment page (Task 14 port of
 * frontend/src/pages/auth/PasskeySetup).
 *
 * ALL logic is copied verbatim from the original: the three-step state machine
 * (intro → registering → success), the register flow (POST
 * /auth/passkey/register/options → navigator.credentials.create →
 * POST /auth/passkey/register), the generic failure message that resets to
 * intro, the success → navigate('/') continue, and the navigate(-1) "skip for
 * now". No request shapes or endpoints are changed.
 *
 * The page renders ONLY its card content into the AuthLayout `<Outlet/>`
 * (Task 12). The markup is remapped to the design system per
 * OraInvoice_Handoff/app/PasskeySetup.html: the `.ic-top` accent-soft passkey
 * glyph, centered heading, the numbered `.pk-step` list (designed from the
 * prototype's three steps; the original used a bullet "How it works" list — the
 * copy is preserved, FR-2c), the `btn-lg` "Create passkey" button with leading
 * glyph, the "Skip for now" quiet link, and the ok-soft success state with the
 * check glyph + "Continue to dashboard".
 */

type SetupStep = 'intro' | 'registering' | 'success'

/** Numbered enrolment steps — copy verbatim from PasskeySetup.html `.pk-step`. */
const PK_STEPS: { title: string; desc: string }[] = [
  { title: 'Tap "Register Passkey"', desc: 'Your browser will ask which device to use.' },
  { title: 'Confirm with your device', desc: 'Use Touch ID, Face ID, Windows Hello or a security key.' },
  { title: "You're done", desc: 'Next time, sign in with just your device.' },
]

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

  if (step === 'success') {
    return (
      <div className="w-full max-w-[440px] text-center">
        <div className="mx-auto mb-5 grid h-[60px] w-[60px] place-items-center rounded-full bg-ok-soft">
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={2.2} aria-hidden="true" className="h-7 w-7 text-ok">
            <path d="M20 6L9 17l-5-5" />
          </svg>
        </div>
        <h1 className="text-[22px] font-bold tracking-[-0.02em] text-text">Passkey registered</h1>
        <p className="mt-2 text-[14px] text-muted">
          You can now sign in using your passkey. No password or MFA code needed.
        </p>
        <Button onClick={() => navigate('/')} fullWidth className="mt-6 h-[46px] text-[14.5px]">
          Continue to dashboard
        </Button>
      </div>
    )
  }

  return (
    <div className="w-full max-w-[440px]">
      {/* ic-top — accent-soft passkey glyph (PasskeySetup.html `.ic-top`) */}
      <div className="mx-auto mb-[18px] grid h-[56px] w-[56px] place-items-center rounded-[15px] bg-accent-soft">
        <svg
          viewBox="0 0 24 24"
          fill="none"
          stroke="currentColor"
          strokeWidth={1.7}
          aria-hidden="true"
          className="h-7 w-7 text-accent"
        >
          <path d="M7.864 4.243A7.5 7.5 0 0119.5 10.5c0 2.92-.556 5.709-1.568 8.268M5.742 6.364A7.465 7.465 0 004.5 10.5a48.667 48.667 0 00-1.26 8.303M15 10.5a3 3 0 11-6 0 3 3 0 016 0zm-2.25 6a3.75 3.75 0 00-3.75 3.75v.443c0 .576.162 1.14.47 1.626a7.5 7.5 0 009.06 0c.308-.486.47-1.05.47-1.626v-.443a3.75 3.75 0 00-3.75-3.75h-2.5z" />
        </svg>
      </div>

      <div className="mb-[22px] text-center">
        <h1 className="text-[22px] font-bold tracking-[-0.02em] text-text">Set up a Passkey</h1>
        <p className="mt-[7px] text-[14px] text-muted">
          Use your fingerprint, face, or device PIN to sign in without a password
        </p>
      </div>

      {error && (
        <div className="mb-4">
          <AlertBanner variant="error" onDismiss={() => setError(null)}>
            {error}
          </AlertBanner>
        </div>
      )}

      {/* Numbered steps (PasskeySetup.html `.pk-step`) */}
      <div className="mb-[22px]">
        {PK_STEPS.map((s, i) => (
          <div
            key={s.title}
            className="flex gap-[13px] border-b border-border py-[14px] last:border-none"
          >
            <span className="mono grid h-[26px] w-[26px] flex-shrink-0 place-items-center rounded-full border border-border bg-canvas text-[12px] font-semibold text-muted">
              {i + 1}
            </span>
            <div>
              <div className="text-[13.5px] font-semibold text-text">{s.title}</div>
              <div className="mt-0.5 text-[12.5px] text-muted">{s.desc}</div>
            </div>
          </div>
        ))}
      </div>

      <Button
        onClick={handleRegister}
        loading={step === 'registering'}
        fullWidth
        className="h-[46px] text-[14.5px]"
        leftIcon={
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={2} aria-hidden="true">
            <path d="M7.9 4.2A7.5 7.5 0 0119.5 10.5c0 2.9-.6 5.7-1.6 8.3M15 10.5a3 3 0 11-6 0 3 3 0 016 0z" />
          </svg>
        }
      >
        Register Passkey
      </Button>

      <p className="mt-[18px] text-center">
        <button
          type="button"
          onClick={() => navigate(-1)}
          className="text-[13px] font-medium text-muted hover:text-text"
        >
          Skip for now
        </button>
      </p>
    </div>
  )
}
