import { describe, it, expect } from 'vitest'
import fc from 'fast-check'
import { EMAIL_RE } from './RecipientChips'

/**
 * RecipientChips email-regex property fuzz (task 12.8 — OPTIONAL, R4.3).
 *
 * Property: the recipient validation regex `EMAIL_RE`
 * (`/^[^\s@]+@[^\s@]+\.[^\s@]+$/`) matches generated well-formed addresses, and
 * rejects strings that lack exactly one '@' or a dotted domain / contain
 * whitespace.
 *
 * This is hardening beyond the required four backend properties; it fuzzes only
 * the pure exported regex (no rendering).
 */

// A local-part / label segment with no '@', whitespace, or '.'.
const segment = fc
  .stringMatching(/^[A-Za-z0-9!#$%&'*+/=?^_`{|}~-]+$/)
  .filter((s) => s.length > 0 && s.length <= 20)

// A well-formed email: local@label(.label)+ — at least one dot in the domain.
const validEmail = fc
  .tuple(segment, segment, fc.array(segment, { minLength: 1, maxLength: 3 }))
  .map(([local, host, tlds]) => `${local}@${host}.${tlds.join('.')}`)

describe('EMAIL_RE — property fuzz (R4.3)', () => {
  it('matches generated well-formed emails', () => {
    fc.assert(
      fc.property(validEmail, (email) => {
        expect(EMAIL_RE.test(email)).toBe(true)
      }),
      { numRuns: 300 },
    )
  })

  it('rejects strings that do not have exactly one "@"', () => {
    fc.assert(
      fc.property(
        fc.string().filter((s) => (s.match(/@/g) ?? []).length !== 1),
        (s) => {
          expect(EMAIL_RE.test(s)).toBe(false)
        },
      ),
      { numRuns: 300 },
    )
  })

  it('rejects an otherwise-valid local@host with no dotted domain', () => {
    fc.assert(
      fc.property(
        fc.tuple(segment, segment),
        ([local, host]) => {
          // host has no '.', so the domain is not dotted → must be rejected.
          expect(EMAIL_RE.test(`${local}@${host}`)).toBe(false)
        },
      ),
      { numRuns: 300 },
    )
  })

  it('rejects addresses containing whitespace', () => {
    fc.assert(
      fc.property(
        fc.tuple(segment, segment, segment, fc.constantFrom(' ', '\t', '\n')),
        ([local, host, tld, ws]) => {
          expect(EMAIL_RE.test(`${local}${ws}@${host}.${tld}`)).toBe(false)
        },
      ),
      { numRuns: 300 },
    )
  })
})
