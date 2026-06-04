/**
 * MfaChallengePage — Re-exports MfaVerify which handles the full MFA challenge flow.
 *
 * The MfaVerify component handles:
 * - Method selection from available methods (from login response)
 * - SMS/email challenge OTP sending via POST /auth/mfa/challenge/send
 * - TOTP and backup code verification via POST /auth/mfa/verify
 * - Passkey WebAuthn assertion flow
 * - 429 lockout and 401 expired token error handling
 */
export { MfaVerify as MfaChallengePage } from './MfaVerify'
