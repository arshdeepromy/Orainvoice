/**
 * Auth pages barrel (Task 13).
 *
 * Mirrors the original frontend/src/pages/auth/index.ts: the Stripe-importing
 * signup components (Signup, SignupWizard, SignupForm, PaymentStep) are NOT
 * re-exported here. They pull @stripe/stripe-js + @stripe/react-stripe-js at
 * the top level; eager-exporting them would drag the heavy Stripe bundle into
 * any module that imports this barrel, and an ad-blocked / failed Stripe script
 * would then crash the whole chunk. Lazy-load them at the route instead, e.g.:
 *   const SignupWizard = lazy(() =>
 *     import('@/pages/auth/SignupWizard').then(m => ({ default: m.SignupWizard })))
 *
 * The supporting modules (signup-types, signup-validation) and the
 * Stripe-free ConfirmationStep are safe to re-export.
 */
export { Login } from './Login'
export { MfaVerify } from './MfaVerify'
export { MfaChallengePage } from './MfaChallenge'
export { PasswordResetRequest } from './PasswordResetRequest'
export { PasswordResetComplete } from './PasswordResetComplete'
export { PasskeySetup } from './PasskeySetup'
export { VerifyEmail } from './VerifyEmail'
export { ConfirmationStep } from './ConfirmationStep'
export * from './signup-types'
export { validateSignupForm, validateVerifyEmailForm } from './signup-validation'
