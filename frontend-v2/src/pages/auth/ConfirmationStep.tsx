import { Button } from '@/components/ui'

/**
 * ConfirmationStep — "check your email" panel shown after a successful signup
 * (Task 13 port of frontend/src/pages/auth/ConfirmationStep).
 *
 * Logic is unchanged (renders the email + 48-hour expiry copy + a link back to
 * /login). Styling is remapped to the design system: an accent-soft card with
 * the prototype's envelope glyph, token typography, and the primary Button
 * rendered as a link to /login (matching the original's "Go to login" anchor).
 */
interface ConfirmationStepProps {
  email: string
}

export function ConfirmationStep({ email }: ConfirmationStepProps) {
  return (
    <div className="rounded-card border border-accent/20 bg-accent-soft p-6 text-center">
      <svg className="mx-auto h-12 w-12 text-accent" fill="none" viewBox="0 0 24 24" stroke="currentColor" aria-hidden="true">
        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M3 8l7.89 5.26a2 2 0 002.22 0L21 8M5 19h14a2 2 0 002-2V7a2 2 0 00-2-2H5a2 2 0 00-2 2v10a2 2 0 002 2z" />
      </svg>
      <h2 className="mt-4 text-xl font-semibold text-text">
        Check your email
      </h2>
      <p className="mt-2 text-[13.5px] text-muted">
        We've sent a verification link to <span className="font-semibold text-text">{email}</span>.
        Please click the link to verify your email and activate your account.
      </p>
      <p className="mt-3 text-[12px] text-muted-2">
        The link expires in 48 hours. Check your spam folder if you don't see it.
      </p>
      <Button href="/login" className="mt-4">
        Go to login
      </Button>
    </div>
  )
}
