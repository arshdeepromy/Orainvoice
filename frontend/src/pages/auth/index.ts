export { Login } from './Login'
export { MfaVerify } from './MfaVerify'
export { MfaChallengePage } from './MfaChallenge'
export { PasswordResetRequest } from './PasswordResetRequest'
export { PasswordResetComplete } from './PasswordResetComplete'
export { PasskeySetup } from './PasskeySetup'
// Signup is NOT re-exported here — it must be lazy-loaded to avoid
// pulling @stripe/stripe-js into the initial bundle (breaks if ad-blocked).
// Use: const Signup = lazy(() => import('@/pages/auth/Signup').then(m => ({ default: m.Signup })))
export { VerifyEmail } from './VerifyEmail'
