import { describe, it, expect } from 'vitest'
import {
  resolveApiBase,
  isCookiePortal,
  csrfCookieName,
} from './client'

/**
 * Unit tests for the portal-aware API base + auth-model resolution helpers
 * added in task 15.2. The exhaustive property (Property 23) lives in task 15.8.
 */
describe('resolveApiBase', () => {
  const origin = 'https://example.test'

  it('resolves the org portal to …/api/v1 (unchanged JWT surface)', () => {
    expect(resolveApiBase('org', origin)).toBe('https://example.test/api/v1')
  })

  it('resolves the employee portal to …/e/api', () => {
    expect(resolveApiBase('employee', origin)).toBe('https://example.test/e/api')
  })

  it('resolves the fleet portal to …/fleet/api', () => {
    expect(resolveApiBase('fleet', origin)).toBe('https://example.test/fleet/api')
  })

  it('is deterministic for the same input', () => {
    expect(resolveApiBase('employee', origin)).toBe(resolveApiBase('employee', origin))
  })

  it('supports a relative (web) origin', () => {
    expect(resolveApiBase('org', '')).toBe('/api/v1')
    expect(resolveApiBase('employee', '')).toBe('/e/api')
    expect(resolveApiBase('fleet', '')).toBe('/fleet/api')
  })
})

describe('isCookiePortal', () => {
  it('treats employee and fleet as cookie portals', () => {
    expect(isCookiePortal('employee')).toBe(true)
    expect(isCookiePortal('fleet')).toBe(true)
  })

  it('treats org (and unset) as a JWT portal, not cookie', () => {
    expect(isCookiePortal('org')).toBe(false)
    expect(isCookiePortal(undefined)).toBe(false)
    expect(isCookiePortal(null)).toBe(false)
  })
})

describe('csrfCookieName', () => {
  it('returns the per-portal CSRF cookie name for cookie portals', () => {
    expect(csrfCookieName('employee')).toBe('emp_portal_csrf')
    expect(csrfCookieName('fleet')).toBe('fleet_portal_csrf')
  })

  it('returns null for the org portal (no CSRF cookie)', () => {
    expect(csrfCookieName('org')).toBeNull()
    expect(csrfCookieName(undefined)).toBeNull()
  })
})
