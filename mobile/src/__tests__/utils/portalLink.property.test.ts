// Feature: platform-feature-gaps, Property 22: Mobile portal URL format is correct
// **Validates: Requirements 25.1, 25.2**

import { describe, it, expect } from 'vitest'
import * as fc from 'fast-check'
import { buildPortalUrl, canSharePortalLink } from '@/utils/portalLink'

/**
 * Property 22: Mobile portal URL format is correct.
 *
 * For any customer with a non-null portal_token, the generated share URL
 * SHALL match the pattern `/portal/{portal_token}` (not `/portal/invoices/{id}`
 * or `/portal/quotes/{id}`).
 *
 * **Validates: Requirements 25.1, 25.2**
 */
describe('Property 22: Mobile portal URL format is correct', () => {
  // Strategy: non-empty token strings (UUIDs, url-safe tokens, etc.)
  const tokenArb = fc.oneof(
    fc.uuid(),
    fc.stringMatching(/^[A-Za-z0-9_-]{10,64}$/),
  )

  const originArb = fc.constantFrom(
    'https://app.example.com',
    'https://portal.workshop.co.nz',
    'http://localhost:3000',
    'https://invoicing.local:8999',
  )

  it('generated URL uses /portal/{token} format for any non-null token', () => {
    fc.assert(
      fc.property(originArb, tokenArb, (origin, token) => {
        const url = buildPortalUrl(origin, token)

        // URL must not be null for non-empty tokens
        expect(url).not.toBeNull()

        // URL must follow /portal/{token} format
        expect(url).toBe(`${origin}/portal/${token}`)
      }),
      { numRuns: 200 },
    )
  })

  it('generated URL never contains /portal/invoices/ or /portal/quotes/', () => {
    fc.assert(
      fc.property(originArb, tokenArb, (origin, token) => {
        const url = buildPortalUrl(origin, token)

        expect(url).not.toBeNull()
        expect(url!).not.toContain('/portal/invoices/')
        expect(url!).not.toContain('/portal/quotes/')
      }),
      { numRuns: 200 },
    )
  })

  it('URL path has exactly two segments after origin: /portal/{token}', () => {
    fc.assert(
      fc.property(originArb, tokenArb, (origin, token) => {
        const url = buildPortalUrl(origin, token)
        expect(url).not.toBeNull()

        // Extract path from URL
        const path = url!.replace(origin, '')
        const segments = path.split('/').filter(Boolean)

        expect(segments).toHaveLength(2)
        expect(segments[0]).toBe('portal')
        expect(segments[1]).toBe(token)
      }),
      { numRuns: 200 },
    )
  })

  it('returns null for null, undefined, or empty token', () => {
    const nullishTokenArb = fc.constantFrom(null, undefined, '')

    fc.assert(
      fc.property(originArb, nullishTokenArb, (origin, token) => {
        const url = buildPortalUrl(origin, token)
        expect(url).toBeNull()
      }),
      { numRuns: 50 },
    )
  })

  it('canSharePortalLink returns false when token is falsy or portal disabled', () => {
    const falsyTokenArb = fc.constantFrom(null, undefined, '')
    const enabledArb = fc.boolean()

    fc.assert(
      fc.property(falsyTokenArb, enabledArb, (token, enabled) => {
        expect(canSharePortalLink(token, enabled)).toBe(false)
      }),
      { numRuns: 50 },
    )
  })

  it('canSharePortalLink returns true only when token is truthy AND portal enabled', () => {
    fc.assert(
      fc.property(tokenArb, fc.boolean(), (token, enabled) => {
        const result = canSharePortalLink(token, enabled)
        if (enabled) {
          expect(result).toBe(true)
        } else {
          expect(result).toBe(false)
        }
      }),
      { numRuns: 200 },
    )
  })
})
