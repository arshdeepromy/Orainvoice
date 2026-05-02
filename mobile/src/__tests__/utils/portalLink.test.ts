import { describe, it, expect } from 'vitest'
import { buildPortalUrl, canSharePortalLink } from '@/utils/portalLink'

/**
 * Unit tests for portal link utility functions.
 * Requirements: 25.1, 25.2, 25.3, 25.4
 */

describe('buildPortalUrl', () => {
  it('should generate URL in /portal/{token} format when token is provided', () => {
    const url = buildPortalUrl('https://app.example.com', 'abc-123-token')
    expect(url).toBe('https://app.example.com/portal/abc-123-token')
  })

  it('should return null when token is null', () => {
    expect(buildPortalUrl('https://app.example.com', null)).toBeNull()
  })

  it('should return null when token is undefined', () => {
    expect(buildPortalUrl('https://app.example.com', undefined)).toBeNull()
  })

  it('should return null when token is empty string', () => {
    expect(buildPortalUrl('https://app.example.com', '')).toBeNull()
  })

  it('should not generate /portal/invoices/{id} format', () => {
    const url = buildPortalUrl('https://app.example.com', 'some-uuid-token')
    expect(url).not.toContain('/portal/invoices/')
    expect(url).not.toContain('/portal/quotes/')
  })

  it('should handle UUID-format tokens', () => {
    const uuid = 'f47ac10b-58cc-4372-a567-0e02b2c3d479'
    const url = buildPortalUrl('https://app.example.com', uuid)
    expect(url).toBe(`https://app.example.com/portal/${uuid}`)
  })
})

describe('canSharePortalLink', () => {
  it('should return true when token exists and portal is enabled', () => {
    expect(canSharePortalLink('abc-token', true)).toBe(true)
  })

  it('should return false when token is null', () => {
    expect(canSharePortalLink(null, true)).toBe(false)
  })

  it('should return false when token is undefined', () => {
    expect(canSharePortalLink(undefined, true)).toBe(false)
  })

  it('should return false when token is empty string', () => {
    expect(canSharePortalLink('', true)).toBe(false)
  })

  it('should return false when portal is disabled', () => {
    expect(canSharePortalLink('abc-token', false)).toBe(false)
  })

  it('should return false when enable_portal is undefined', () => {
    expect(canSharePortalLink('abc-token', undefined)).toBe(false)
  })

  it('should return false when both token is null and portal is disabled', () => {
    expect(canSharePortalLink(null, false)).toBe(false)
  })
})
