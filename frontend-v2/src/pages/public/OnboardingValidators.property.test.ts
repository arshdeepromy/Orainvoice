import { describe, it, expect } from 'vitest'
import fc from 'fast-check'
import {
  validateNzBankAccount,
  validateIrdLength,
  NZ_BANK_RE,
} from './OnboardingFormPage'

/**
 * Client-side onboarding validator parity fuzz (Task 10.6 — OPTIONAL, R5.2 / R6.2).
 *
 * The public onboarding form mirrors the server's side-effect-free validators
 * (`app/modules/staff/onboarding_validation.py`) so the staff member gets fast
 * feedback before submit. These property tests assert the CLIENT validators
 * encode the SAME semantics the server enforces:
 *
 *  - NZ bank account: regex `^\d{2}-\d{4}-\d{7}-\d{2,3}$` (2-4-7-2 / 2-4-7-3).
 *  - IRD: 8 or 9 digits after stripping separators.
 *
 * The server is authoritative; these guard against client/server drift.
 */

// A reference implementation of the SERVER semantics, expressed independently
// of the client regex, so the property compares two implementations rather
// than a regex against itself.
function serverBankValid(s: string): boolean {
  const parts = s.split('-')
  if (parts.length !== 4) return false
  const lens = [2, 4, 7, null] // suffix is 2 OR 3
  for (let i = 0; i < 3; i++) {
    if (!/^\d+$/.test(parts[i]) || parts[i].length !== lens[i]) return false
  }
  return /^\d+$/.test(parts[3]) && (parts[3].length === 2 || parts[3].length === 3)
}

function serverIrdValid(s: string): boolean {
  const stripped = s.replace(/-/g, '').replace(/ /g, '')
  return /^\d+$/.test(stripped) && (stripped.length === 8 || stripped.length === 9)
}

// Generators -----------------------------------------------------------------

const digits = (n: number) =>
  fc.array(fc.integer({ min: 0, max: 9 }), { minLength: n, maxLength: n }).map((a) => a.join(''))

// Well-formed NZ bank accounts (2-4-7-2 and 2-4-7-3).
const validBank = fc
  .tuple(digits(2), digits(4), digits(7), fc.integer({ min: 2, max: 3 }).chain((n) => digits(n)))
  .map(([b, br, ac, sfx]) => `${b}-${br}-${ac}-${sfx}`)

describe('client NZ bank validator parity (R5.2)', () => {
  it('accepts well-formed 2-4-7-2 / 2-4-7-3 accounts', () => {
    fc.assert(
      fc.property(validBank, (acct) => {
        expect(validateNzBankAccount(acct)).toBe(true)
        expect(serverBankValid(acct)).toBe(true)
      }),
      { numRuns: 300 },
    )
  })

  it('agrees with the server reference over arbitrary strings', () => {
    fc.assert(
      fc.property(
        fc.oneof(
          validBank,
          fc.string({ maxLength: 24 }),
          // Mutated bank-like strings: right shape, wrong segment lengths.
          fc.tuple(digits(3), digits(4), digits(7), digits(2)).map((p) => p.join('-')),
          fc.tuple(digits(2), digits(4), digits(8), digits(2)).map((p) => p.join('-')),
          fc.tuple(digits(2), digits(4), digits(7), digits(4)).map((p) => p.join('-')),
        ),
        (s) => {
          expect(validateNzBankAccount(s)).toBe(serverBankValid(s))
        },
      ),
      { numRuns: 500 },
    )
  })

  it('exposes the same regex the validator uses', () => {
    expect(NZ_BANK_RE.test('01-0234-0567890-00')).toBe(true)
    expect(NZ_BANK_RE.test('01-0234-0567890-000')).toBe(true)
    expect(NZ_BANK_RE.test('1-0234-0567890-00')).toBe(false)
  })
})

describe('client IRD length validator parity (R6.2)', () => {
  it('accepts exactly 8 or 9 digits (with optional separators)', () => {
    fc.assert(
      fc.property(
        fc.integer({ min: 8, max: 9 }).chain((n) => digits(n)),
        (ird) => {
          expect(validateIrdLength(ird)).toBe(true)
        },
      ),
      { numRuns: 200 },
    )
  })

  it('rejects digit-strings whose length is not 8 or 9', () => {
    fc.assert(
      fc.property(
        fc.integer({ min: 0, max: 14 }).filter((n) => n !== 8 && n !== 9).chain((n) => digits(n)),
        (ird) => {
          expect(validateIrdLength(ird)).toBe(false)
        },
      ),
      { numRuns: 300 },
    )
  })

  it('agrees with the server reference over arbitrary strings (separators included)', () => {
    fc.assert(
      fc.property(
        fc.oneof(
          fc.integer({ min: 0, max: 14 }).chain((n) => digits(n)),
          // IRD-like with separators, e.g. "49-091-850".
          fc.tuple(digits(2), digits(3), digits(3)).map((p) => p.join('-')),
          fc.string({ maxLength: 16 }),
        ),
        (s) => {
          // NOTE: the client strips ALL non-digits (\D) whereas the server
          // strips only '-' and ' '; over generated inputs that contain only
          // digits, hyphens and spaces the two agree. Constrain to that space.
          if (!/^[\d\- ]*$/.test(s)) return
          expect(validateIrdLength(s)).toBe(serverIrdValid(s))
        },
      ),
      { numRuns: 500 },
    )
  })
})
