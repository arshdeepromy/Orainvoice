import { describe, it, expect } from 'vitest'
import * as fc from 'fast-check'
import { validateSignupForm } from '../signup-validation'
import type { SignupFormData } from '../signup-types'

// Feature: multi-step-signup-wizard, Property 5: Client-side validation rejects invalid form data
// **Validates: Requirements 2.2**

/** A valid password that satisfies all complexity rules */
const VALID_PASSWORD = 'Test1234!'

/** Build a fully valid SignupFormData baseline */
function validForm(overrides: Partial<SignupFormData> = {}): SignupFormData {
  return {
    org_name: 'Acme Corp',
    admin_email: 'user@example.com',
    admin_first_name: 'Jane',
    admin_last_name: 'Doe',
    password: VALID_PASSWORD,
    confirm_password: VALID_PASSWORD,
    plan_id: 'plan-123',
    billing_interval: 'monthly',
    captcha_code: 'AB12CD',
    coupon_code: '',
    country_code: 'NZ',
    trade_family_slug: '',
    ...overrides,
  }
}

/** Arbitrary: a valid complex password (8+ chars, upper, lower, digit, special) */
const validPasswordArb = fc
  .tuple(
    fc.stringMatching(/^[A-Z]{1,4}$/),
    fc.stringMatching(/^[a-z]{1,4}$/),
    fc.stringMatching(/^[0-9]{1,3}$/),
    fc.constantFrom('!', '@', '#', '$', '%', '^', '&', '*'),
    fc.stringMatching(/^[A-Za-z0-9!@#$%^&*]{0,10}$/)
  )
  .map(([upper, lower, digit, special, extra]) => upper + lower + digit + special + extra)
  .filter(p => p.length >= 8 && p.length <= 128)

describe('Property 5: Client-side validation rejects invalid form data', () => {
  // --- Empty org_name ---
  it('rejects empty org_name', () => {
    fc.assert(
      fc.property(validPasswordArb, (pw) => {
        const errors = validateSignupForm(validForm({ org_name: '', password: pw, confirm_password: pw }))
        expect(Object.keys(errors).length).toBeGreaterThan(0)
        expect(errors).toHaveProperty('org_name')
      }),
      { numRuns: 100 }
    )
  })

  // --- Invalid email format ---
  it('rejects invalid email formats (no @ sign)', () => {
    const noAtArb = fc.string({ minLength: 1, maxLength: 50 }).filter(s => !s.includes('@'))
    fc.assert(
      fc.property(noAtArb, (email) => {
        const errors = validateSignupForm(validForm({ admin_email: email }))
        expect(Object.keys(errors).length).toBeGreaterThan(0)
        expect(errors).toHaveProperty('admin_email')
      }),
      { numRuns: 100 }
    )
  })

  it('rejects empty email', () => {
    const errors = validateSignupForm(validForm({ admin_email: '' }))
    expect(Object.keys(errors).length).toBeGreaterThan(0)
    expect(errors).toHaveProperty('admin_email')
  })

  // --- Password complexity: missing uppercase ---
  it('rejects passwords without uppercase letter', () => {
    const noUpperArb = fc.stringMatching(/^[a-z0-9!@#$%^&*]{8,30}$/)
    fc.assert(
      fc.property(noUpperArb, (pw) => {
        const errors = validateSignupForm(validForm({ password: pw, confirm_password: pw }))
        expect(Object.keys(errors).length).toBeGreaterThan(0)
        expect(errors).toHaveProperty('password')
      }),
      { numRuns: 100 }
    )
  })

  // --- Password complexity: missing lowercase ---
  it('rejects passwords without lowercase letter', () => {
    const noLowerArb = fc.stringMatching(/^[A-Z0-9!@#$%^&*]{8,30}$/)
    fc.assert(
      fc.property(noLowerArb, (pw) => {
        const errors = validateSignupForm(validForm({ password: pw, confirm_password: pw }))
        expect(Object.keys(errors).length).toBeGreaterThan(0)
        expect(errors).toHaveProperty('password')
      }),
      { numRuns: 100 }
    )
  })

  // --- Password complexity: missing digit ---
  it('rejects passwords without a digit', () => {
    const noDigitArb = fc.stringMatching(/^[A-Za-z!@#$%^&*]{8,30}$/)
    fc.assert(
      fc.property(noDigitArb, (pw) => {
        const errors = validateSignupForm(validForm({ password: pw, confirm_password: pw }))
        expect(Object.keys(errors).length).toBeGreaterThan(0)
        expect(errors).toHaveProperty('password')
      }),
      { numRuns: 100 }
    )
  })

  // --- Password complexity: missing special character ---
  it('rejects passwords without a special character', () => {
    const noSpecialArb = fc.stringMatching(/^[A-Za-z0-9]{8,30}$/)
    fc.assert(
      fc.property(noSpecialArb, (pw) => {
        const errors = validateSignupForm(validForm({ password: pw, confirm_password: pw }))
        expect(Object.keys(errors).length).toBeGreaterThan(0)
        expect(errors).toHaveProperty('password')
      }),
      { numRuns: 100 }
    )
  })

  // --- Password too short ---
  it('rejects passwords shorter than 8 characters', () => {
    const shortPwArb = fc.string({ minLength: 1, maxLength: 7 })
    fc.assert(
      fc.property(shortPwArb, (pw) => {
        const errors = validateSignupForm(validForm({ password: pw, confirm_password: pw }))
        expect(Object.keys(errors).length).toBeGreaterThan(0)
        expect(errors).toHaveProperty('password')
      }),
      { numRuns: 100 }
    )
  })

  // --- Passwords don't match ---
  it('rejects when confirm_password does not match password', () => {
    fc.assert(
      fc.property(
        validPasswordArb,
        fc.string({ minLength: 1, maxLength: 50 }),
        (pw, suffix) => {
          const mismatch = pw + suffix + 'x'
          fc.pre(mismatch !== pw)
          const errors = validateSignupForm(validForm({ password: pw, confirm_password: mismatch }))
          expect(Object.keys(errors).length).toBeGreaterThan(0)
          expect(errors).toHaveProperty('confirm_password')
        }
      ),
      { numRuns: 100 }
    )
  })

  // --- Missing plan_id ---
  it('rejects empty plan_id', () => {
    const errors = validateSignupForm(validForm({ plan_id: '' }))
    expect(Object.keys(errors).length).toBeGreaterThan(0)
    expect(errors).toHaveProperty('plan_id')
  })

  // --- Invalid captcha_code (not 6 chars) ---
  it('rejects captcha_code that is not exactly 6 characters', () => {
    const badCaptchaArb = fc.string({ minLength: 0, maxLength: 20 }).filter(s => s.length !== 6)
    fc.assert(
      fc.property(badCaptchaArb, (captcha) => {
        const errors = validateSignupForm(validForm({ captcha_code: captcha }))
        expect(Object.keys(errors).length).toBeGreaterThan(0)
        expect(errors).toHaveProperty('captcha_code')
      }),
      { numRuns: 100 }
    )
  })

  // --- Random combination of multiple invalid fields ---
  it('rejects form data with at least one randomly invalidated field', () => {
    // Invalidation strategies: each produces a Partial<SignupFormData> that makes at least one field invalid
    const invalidators: fc.Arbitrary<Partial<SignupFormData>>[] = [
      fc.constant({ org_name: '' }),
      fc.constant({ admin_email: 'not-an-email' }),
      fc.constant({ admin_first_name: '' }),
      fc.constant({ admin_last_name: '' }),
      fc.constant({ password: 'short', confirm_password: 'short' }),
      fc.constant({ plan_id: '' }),
      fc.constant({ captcha_code: '' }),
    ]

    // Pick 1-3 random invalidators and merge them
    const invalidOverridesArb = fc
      .shuffledSubarray(invalidators, { minLength: 1, maxLength: 3 })
      .chain(arbs => {
        if (arbs.length === 1) return arbs[0]
        if (arbs.length === 2) return fc.tuple(arbs[0], arbs[1]).map(([a, b]) => ({ ...a, ...b }))
        return fc.tuple(arbs[0], arbs[1], arbs[2]).map(([a, b, c]) => ({ ...a, ...b, ...c }))
      })

    fc.assert(
      fc.property(invalidOverridesArb, (overrides) => {
        const errors = validateSignupForm(validForm(overrides))
        expect(Object.keys(errors).length).toBeGreaterThan(0)
      }),
      { numRuns: 100 }
    )
  })

  // --- Sanity check: valid form produces no errors ---
  it('accepts fully valid form data (sanity check)', () => {
    fc.assert(
      fc.property(validPasswordArb, (pw) => {
        const form = validForm({ password: pw, confirm_password: pw })
        const errors = validateSignupForm(form)
        expect(Object.keys(errors).length).toBe(0)
      }),
      { numRuns: 100 }
    )
  })
})
