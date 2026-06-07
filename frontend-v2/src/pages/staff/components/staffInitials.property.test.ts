import { describe, it, expect } from 'vitest'
import fc from 'fast-check'
import { staffInitials } from './staffInitials'

/**
 * Feature: staff-redesign, Property 7
 * Property 7: Avatar initials derive from first and last name.
 * **Validates: Requirements 4.1**
 *
 * fast-check over arbitrary first/last names. The initials are the uppercased
 * first character of the first name followed by the uppercased first character
 * of the last name, omitting the second initial when there is no last name.
 * Names are trimmed first; an empty/whitespace-only part contributes nothing.
 *
 * The reference below mirrors the EXACT operations the implementation uses
 * (`.trim()` + `.charAt(0).toUpperCase()`) so it stays aligned across Unicode
 * inputs rather than asserting an independent (and possibly divergent) notion
 * of "first character" / "uppercase".
 */

/** Independent reference matching the helper's contract (R4.1). */
function expectedInitials(
  firstName: string | null | undefined,
  lastName: string | null | undefined,
): string {
  const first = (firstName ?? '').trim()
  const last = (lastName ?? '').trim()
  const firstInitial = first ? first.charAt(0).toUpperCase() : ''
  const lastInitial = last ? last.charAt(0).toUpperCase() : ''
  return firstInitial + lastInitial
}

// Arbitrary name parts: include plain strings plus some whitespace-padded and
// empty variants so trimming behaviour is exercised.
const namePart = fc.oneof(
  fc.string(),
  fc.string().map((s) => `  ${s}  `),
  fc.constantFrom('', ' ', '   ', '\t', '\n', '  \t  '),
)

// Nullable name parts to cover the null/undefined branches.
const nullableNamePart = fc.oneof(namePart, fc.constant(null), fc.constant(undefined))

describe('Feature: staff-redesign, Property 7 — avatar initials', () => {
  it('derives initials from the first and last name (R4.1)', () => {
    fc.assert(
      fc.property(nullableNamePart, nullableNamePart, (first, last) => {
        expect(staffInitials(first, last)).toBe(expectedInitials(first, last))
      }),
      { numRuns: 200 },
    )
  })

  it('omits the second initial when there is no last name (R4.1)', () => {
    const emptyLast = fc.constantFrom<string | null | undefined>(
      '',
      ' ',
      '   ',
      '\t',
      '\n',
      '  \t  ',
      null,
      undefined,
    )
    fc.assert(
      fc.property(nullableNamePart, emptyLast, (first, last) => {
        const result = staffInitials(first, last)
        // With no usable last name there is no second initial: the result is
        // exactly the (single) first initial, identical to passing an empty
        // last name. We compare against the first-only reference rather than a
        // raw code-unit length because `toUpperCase()` can expand one character
        // (e.g. 'ß' → 'SS'); "at most one initial" still holds.
        expect(result).toBe(expectedInitials(first, ''))
      }),
      { numRuns: 200 },
    )
  })
})
