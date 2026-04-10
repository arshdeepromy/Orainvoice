import { describe, it, expect } from 'vitest'
import * as fc from 'fast-check'
import { validateSignupForm } from '../pages/auth/signup-validation'
import type { SignupFormData } from '../pages/auth/signup-types'

// Feature: public-signup-flow, Property 1: Field length validation rejects out-of-bounds strings
// **Validates: Requirements 1.6, 1.8**

/** Helper: build valid form data with one field overridden */
function validFormWith(overrides: Partial<SignupFormData>): SignupFormData {
  return {
    org_name: 'Test Organisation',
    admin_email: 'test@example.com',
    admin_first_name: 'Jane',
    admin_last_name: 'Doe',
    password: 'SecurePass10',
    confirm_password: 'SecurePass10',
    plan_id: 'plan-1',
    billing_interval: 'monthly',
    captcha_code: '',
    coupon_code: '',
    country_code: 'NZ',
    trade_family_slug: '',
    ...overrides,
  }
}

describe('Property 1: Field length validation rejects out-of-bounds strings', () => {
  // --- org_name [1, 255] ---

  it('rejects org_name with length outside [1, 255]', () => {
    fc.assert(
      fc.property(
        fc.oneof(
          fc.constant(''),
          fc.string({ minLength: 256, maxLength: 500 })
        ),
        (orgName) => {
          const errors = validateSignupForm(validFormWith({ org_name: orgName }))
          expect(errors).toHaveProperty('org_name')
        }
      ),
      { numRuns: 100 }
    )
  })

  it('accepts org_name with length within [1, 255]', () => {
    fc.assert(
      fc.property(
        fc.string({ minLength: 1, maxLength: 255 }),
        (orgName) => {
          const errors = validateSignupForm(validFormWith({ org_name: orgName }))
          expect(errors).not.toHaveProperty('org_name')
        }
      ),
      { numRuns: 100 }
    )
  })

  // --- admin_first_name [1, 100] ---

  it('rejects admin_first_name with length outside [1, 100]', () => {
    fc.assert(
      fc.property(
        fc.oneof(
          fc.constant(''),
          fc.string({ minLength: 101, maxLength: 300 })
        ),
        (firstName) => {
          const errors = validateSignupForm(validFormWith({ admin_first_name: firstName }))
          expect(errors).toHaveProperty('admin_first_name')
        }
      ),
      { numRuns: 100 }
    )
  })

  it('accepts admin_first_name with length within [1, 100]', () => {
    fc.assert(
      fc.property(
        fc.string({ minLength: 1, maxLength: 100 }),
        (firstName) => {
          const errors = validateSignupForm(validFormWith({ admin_first_name: firstName }))
          expect(errors).not.toHaveProperty('admin_first_name')
        }
      ),
      { numRuns: 100 }
    )
  })

  // --- admin_last_name [1, 100] ---

  it('rejects admin_last_name with length outside [1, 100]', () => {
    fc.assert(
      fc.property(
        fc.oneof(
          fc.constant(''),
          fc.string({ minLength: 101, maxLength: 300 })
        ),
        (lastName) => {
          const errors = validateSignupForm(validFormWith({ admin_last_name: lastName }))
          expect(errors).toHaveProperty('admin_last_name')
        }
      ),
      { numRuns: 100 }
    )
  })

  it('accepts admin_last_name with length within [1, 100]', () => {
    fc.assert(
      fc.property(
        fc.string({ minLength: 1, maxLength: 100 }),
        (lastName) => {
          const errors = validateSignupForm(validFormWith({ admin_last_name: lastName }))
          expect(errors).not.toHaveProperty('admin_last_name')
        }
      ),
      { numRuns: 100 }
    )
  })
})

// Feature: public-signup-flow, Property 2: Email format validation rejects invalid emails
// **Validates: Requirements 1.7**

describe('Property 2: Email format validation rejects invalid emails', () => {
  /** Helper: build valid form data with one field overridden */
  function validFormWith(overrides: Partial<SignupFormData>): SignupFormData {
    return {
      org_name: 'Test Organisation',
      admin_email: 'test@example.com',
      admin_first_name: 'Jane',
      admin_last_name: 'Doe',
      password: 'SecurePass10',
      confirm_password: 'SecurePass10',
      plan_id: 'plan-1',
      billing_interval: 'monthly',
      captcha_code: '',
      coupon_code: '',
      country_code: 'NZ',
      trade_family_slug: '',
      ...overrides,
    }
  }

  /** Arbitrary: non-empty string without whitespace or @ (valid local part / domain label) */
  const localPartArb = fc.stringMatching(/^[^\s@]{1,30}$/)

  /** Arbitrary: non-empty string without whitespace, @, or dots (domain label) */
  const domainLabelArb = fc.stringMatching(/^[^\s@.]{1,15}$/)

  // --- Rejection cases ---

  it('rejects strings with no @ sign', () => {
    const noAtArb = fc.string({ minLength: 1, maxLength: 50 }).filter((s) => !s.includes('@'))
    fc.assert(
      fc.property(noAtArb, (email) => {
        const errors = validateSignupForm(validFormWith({ admin_email: email }))
        expect(errors).toHaveProperty('admin_email')
      }),
      { numRuns: 100 }
    )
  })

  it('rejects strings with multiple @ signs', () => {
    fc.assert(
      fc.property(localPartArb, localPartArb, domainLabelArb, domainLabelArb, (a, b, c, d) => {
        const email = `${a}@${b}@${c}.${d}`
        const errors = validateSignupForm(validFormWith({ admin_email: email }))
        expect(errors).toHaveProperty('admin_email')
      }),
      { numRuns: 100 }
    )
  })

  it('rejects emails with empty local part', () => {
    fc.assert(
      fc.property(domainLabelArb, domainLabelArb, (domain, tld) => {
        const email = `@${domain}.${tld}`
        const errors = validateSignupForm(validFormWith({ admin_email: email }))
        expect(errors).toHaveProperty('admin_email')
      }),
      { numRuns: 100 }
    )
  })

  it('rejects emails with empty domain part', () => {
    fc.assert(
      fc.property(localPartArb, (local) => {
        const email = `${local}@`
        const errors = validateSignupForm(validFormWith({ admin_email: email }))
        expect(errors).toHaveProperty('admin_email')
      }),
      { numRuns: 100 }
    )
  })

  it('rejects emails with no dot in domain', () => {
    fc.assert(
      fc.property(localPartArb, domainLabelArb, (local, domain) => {
        const email = `${local}@${domain}`
        const errors = validateSignupForm(validFormWith({ admin_email: email }))
        expect(errors).toHaveProperty('admin_email')
      }),
      { numRuns: 100 }
    )
  })

  it('rejects empty string as email', () => {
    const errors = validateSignupForm(validFormWith({ admin_email: '' }))
    expect(errors).toHaveProperty('admin_email')
  })

  // --- Acceptance case ---

  it('accepts well-formed emails (local@domain.tld)', () => {
    fc.assert(
      fc.property(localPartArb, domainLabelArb, domainLabelArb, (local, domain, tld) => {
        const email = `${local}@${domain}.${tld}`
        const errors = validateSignupForm(validFormWith({ admin_email: email }))
        expect(errors).not.toHaveProperty('admin_email')
      }),
      { numRuns: 100 }
    )
  })
})

// Feature: public-signup-flow, Property 5: Password minimum length validation
// **Validates: Requirements 3.7**

import { validateVerifyEmailForm } from '../pages/auth/signup-validation'

describe('Property 5: Password minimum length validation', () => {
  it('rejects passwords shorter than 10 characters', () => {
    fc.assert(
      fc.property(
        fc.string({ minLength: 0, maxLength: 9 }),
        (password) => {
          const errors = validateVerifyEmailForm(password, password)
          expect(errors).toHaveProperty('password')
        }
      ),
      { numRuns: 100 }
    )
  })

  it('accepts passwords of 10 or more characters', () => {
    fc.assert(
      fc.property(
        fc.string({ minLength: 10, maxLength: 200 }),
        (password) => {
          const errors = validateVerifyEmailForm(password, password)
          expect(errors).not.toHaveProperty('password')
        }
      ),
      { numRuns: 100 }
    )
  })
})

// Feature: public-signup-flow, Property 6: Password confirmation match validation
// **Validates: Requirements 3.8**

describe('Property 6: Password confirmation match validation', () => {
  it('returns confirmPassword error when password and confirmPassword differ', () => {
    fc.assert(
      fc.property(
        fc.string({ minLength: 10, maxLength: 200 }),
        fc.string({ minLength: 10, maxLength: 200 }),
        (password, confirmPassword) => {
          fc.pre(password !== confirmPassword)
          const errors = validateVerifyEmailForm(password, confirmPassword)
          expect(errors).toHaveProperty('confirmPassword')
        }
      ),
      { numRuns: 100 }
    )
  })

  it('returns no confirmPassword error when password and confirmPassword match', () => {
    fc.assert(
      fc.property(
        fc.string({ minLength: 10, maxLength: 200 }),
        (password) => {
          const errors = validateVerifyEmailForm(password, password)
          expect(errors).not.toHaveProperty('confirmPassword')
        }
      ),
      { numRuns: 100 }
    )
  })
})
