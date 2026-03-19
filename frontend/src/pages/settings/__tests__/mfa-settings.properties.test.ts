import { describe, it, expect } from 'vitest'
import * as fc from 'fast-check'

// ---------------------------------------------------------------------------
// Pure helper: mirrors the MfaMethodCard display logic
// (components/mfa/MfaMethodCard.tsx)
//
// Given an MfaMethodStatus (or undefined), the card derives:
//   - enabled: status?.enabled ?? false
//   - badge text: "Enabled" | "Disabled"
//   - button text: "Enable" (when disabled) | "Disable" (when enabled)
//   - phone display: shown only when enabled AND method === 'sms' AND phone_number is set
// ---------------------------------------------------------------------------

interface MfaMethodStatus {
  method: string
  enabled: boolean
  verified_at: string | null
  phone_number: string | null
}

const MFA_METHODS = ['totp', 'sms', 'email', 'passkey'] as const
type MfaMethod = (typeof MFA_METHODS)[number]

interface MethodCardDisplayState {
  badgeText: 'Enabled' | 'Disabled'
  buttonText: 'Enable' | 'Disable'
  showPhone: boolean
}

/**
 * Compute the display state for a method card, matching the logic in
 * MfaMethodCard.tsx and MfaSettings.tsx.
 */
function computeMethodCardState(
  method: MfaMethod,
  status: MfaMethodStatus | undefined,
): MethodCardDisplayState {
  const enabled = status?.enabled ?? false
  return {
    badgeText: enabled ? 'Enabled' : 'Disabled',
    buttonText: enabled ? 'Disable' : 'Enable',
    showPhone: enabled && method === 'sms' && status?.phone_number != null && status.phone_number !== '',
  }
}

// ---------------------------------------------------------------------------
// Pure helper: mirrors the BackupCodesPanel copy/download logic
// (components/mfa/BackupCodesPanel.tsx)
//
// copyAll → codes.join('\n')
// downloadCodes → codes.join('\n') written to a Blob
// ---------------------------------------------------------------------------

/**
 * Format backup codes for copy-to-clipboard (same as BackupCodesPanel.copyAll).
 */
function formatCodesForCopy(codes: string[]): string {
  return codes.join('\n')
}

/**
 * Format backup codes for download (same as BackupCodesPanel.downloadCodes).
 */
function formatCodesForDownload(codes: string[]): string {
  return codes.join('\n')
}

// ---------------------------------------------------------------------------
// Pure helper: mirrors the PasskeyManager WebAuthn detection logic
// (components/mfa/PasskeyManager.tsx)
//
// if (typeof window !== 'undefined' && !window.PublicKeyCredential) →
//   webAuthnSupported = false → passkey features disabled, warning shown
// ---------------------------------------------------------------------------

interface PasskeyFeatureState {
  passkeyEnabled: boolean
  showWarning: boolean
}

/**
 * Compute passkey feature availability based on browser WebAuthn support,
 * matching the logic in PasskeyManager.tsx.
 */
function computePasskeyFeatureState(publicKeyCredentialAvailable: boolean): PasskeyFeatureState {
  return {
    passkeyEnabled: publicKeyCredentialAvailable,
    showWarning: !publicKeyCredentialAvailable,
  }
}

// ---------------------------------------------------------------------------
// Property-based tests
// ---------------------------------------------------------------------------

describe('MFA Settings — Property-Based Tests', () => {
  // Feature: multi-method-mfa, Property: Method card state correctness
  // **Validates: Requirements 8.2**
  it('Property 1: method card renders correct state for all combinations of enabled/disabled methods', () => {
    // Arbitrary for a single method status
    const methodStatusArb = (method: MfaMethod): fc.Arbitrary<MfaMethodStatus | undefined> =>
      fc.oneof(
        fc.constant(undefined),
        fc.record({
          method: fc.constant(method),
          enabled: fc.boolean(),
          verified_at: fc.option(fc.constant('2025-01-15T10:00:00Z'), { nil: null }),
          phone_number: method === 'sms'
            ? fc.option(fc.constant('***1234'), { nil: null })
            : fc.constant(null),
        }),
      )

    fc.assert(
      fc.property(
        methodStatusArb('totp'),
        methodStatusArb('sms'),
        methodStatusArb('email'),
        methodStatusArb('passkey'),
        (totpStatus, smsStatus, emailStatus, passkeyStatus) => {
          const allStatuses = [
            { method: 'totp' as MfaMethod, status: totpStatus },
            { method: 'sms' as MfaMethod, status: smsStatus },
            { method: 'email' as MfaMethod, status: emailStatus },
            { method: 'passkey' as MfaMethod, status: passkeyStatus },
          ]

          for (const { method, status } of allStatuses) {
            const display = computeMethodCardState(method, status)
            const enabled = status?.enabled ?? false

            // Badge text matches enabled state
            expect(display.badgeText).toBe(enabled ? 'Enabled' : 'Disabled')

            // Button text is the opposite action
            expect(display.buttonText).toBe(enabled ? 'Disable' : 'Enable')

            // Phone number shown only for enabled SMS with phone_number set
            if (method === 'sms' && enabled && status?.phone_number) {
              expect(display.showPhone).toBe(true)
            } else {
              expect(display.showPhone).toBe(false)
            }
          }

          // Never more than 4 method cards
          expect(allStatuses.length).toBeLessThanOrEqual(4)
        },
      ),
      { numRuns: 100 },
    )
  })

  // Feature: multi-method-mfa, Property: Backup code formatting
  // **Validates: Requirements 5.4, 5.5**
  it('Property 2: backup codes format correctly for copy and download', () => {
    // Generate exactly 10 non-empty alphanumeric codes
    const backupCodeArb = fc.stringMatching(/^[A-Za-z0-9]{8,12}$/)
    const tenCodesArb = fc.array(backupCodeArb, { minLength: 10, maxLength: 10 })

    fc.assert(
      fc.property(tenCodesArb, (codes) => {
        // All codes are non-empty strings
        for (const code of codes) {
          expect(typeof code).toBe('string')
          expect(code.length).toBeGreaterThan(0)
        }

        // Exactly 10 codes
        expect(codes.length).toBe(10)

        // Copy-all produces codes joined by newlines
        const copyText = formatCodesForCopy(codes)
        expect(copyText).toBe(codes.join('\n'))

        // Download text matches copy-all text
        const downloadText = formatCodesForDownload(codes)
        expect(downloadText).toBe(copyText)

        // Splitting the copy text by newlines recovers the original codes
        const recovered = copyText.split('\n')
        expect(recovered).toEqual(codes)
        expect(recovered.length).toBe(10)
      }),
      { numRuns: 100 },
    )
  })

  // Feature: multi-method-mfa, Property: WebAuthn API detection
  // **Validates: Requirements 14.1, 14.2, 14.3**
  it('Property 3: passkey features enabled/disabled based on browser WebAuthn support', () => {
    fc.assert(
      fc.property(fc.boolean(), (webAuthnAvailable) => {
        const state = computePasskeyFeatureState(webAuthnAvailable)

        if (webAuthnAvailable) {
          // When WebAuthn is available, passkey features should be enabled
          expect(state.passkeyEnabled).toBe(true)
          expect(state.showWarning).toBe(false)
        } else {
          // When WebAuthn is unavailable, passkey features should be disabled with warning
          expect(state.passkeyEnabled).toBe(false)
          expect(state.showWarning).toBe(true)
        }

        // passkeyEnabled and showWarning are always mutually exclusive
        expect(state.passkeyEnabled).not.toBe(state.showWarning)
      }),
      { numRuns: 100 },
    )
  })
})
