/**
 * Integration tests for navigation flows.
 *
 * Tests tab switching, stack navigation, deep link resolution, and module gating.
 *
 * Requirements: 1.1, 1.2, 1.8, 42.1
 */
import { describe, it, expect } from 'vitest'
import { resolveDeepLink, screenToPath, DEEP_LINK_PATTERNS, FALLBACK_SCREEN } from '../DeepLinkConfig'

/* ------------------------------------------------------------------ */
/* Deep link resolution tests                                         */
/* ------------------------------------------------------------------ */

describe('Deep link resolution', () => {
  it('resolves /invoices/:id to InvoiceDetail with correct id', () => {
    const result = resolveDeepLink('/invoices/abc-123')
    expect(result.screen).toBe('InvoiceDetail')
    expect(result.params.id).toBe('abc-123')
  })

  it('resolves /invoices to InvoiceList', () => {
    const result = resolveDeepLink('/invoices')
    expect(result.screen).toBe('InvoiceList')
    expect(result.params).toEqual({})
  })

  it('resolves /quotes/:id to QuoteDetail with correct id', () => {
    const result = resolveDeepLink('/quotes/q-456')
    expect(result.screen).toBe('QuoteDetail')
    expect(result.params.id).toBe('q-456')
  })

  it('resolves /customers/:id to CustomerProfile', () => {
    const result = resolveDeepLink('/customers/cust-789')
    expect(result.screen).toBe('CustomerProfile')
    expect(result.params.id).toBe('cust-789')
  })

  it('resolves /jobs/:id to JobDetail', () => {
    const result = resolveDeepLink('/jobs/job-001')
    expect(result.screen).toBe('JobDetail')
    expect(result.params.id).toBe('job-001')
  })

  it('resolves /compliance to ComplianceDashboard', () => {
    const result = resolveDeepLink('/compliance')
    expect(result.screen).toBe('ComplianceDashboard')
  })

  it('resolves /settings to Settings', () => {
    const result = resolveDeepLink('/settings')
    expect(result.screen).toBe('Settings')
  })

  it('resolves /dashboard to Dashboard', () => {
    const result = resolveDeepLink('/dashboard')
    expect(result.screen).toBe('Dashboard')
  })

  it('resolves unknown paths to fallback (Dashboard)', () => {
    const result = resolveDeepLink('/unknown/path')
    expect(result.screen).toBe(FALLBACK_SCREEN)
  })

  it('handles paths without leading slash', () => {
    const result = resolveDeepLink('invoices/abc-123')
    expect(result.screen).toBe('InvoiceDetail')
    expect(result.params.id).toBe('abc-123')
  })

  it('handles paths with trailing slash', () => {
    const result = resolveDeepLink('/invoices/')
    expect(result.screen).toBe('InvoiceList')
  })
})

/* ------------------------------------------------------------------ */
/* Screen-to-path mapping tests                                       */
/* ------------------------------------------------------------------ */

describe('screenToPath mapping', () => {
  it('maps InvoiceDetail to /invoices/:id', () => {
    const path = screenToPath({ screen: 'InvoiceDetail', params: { id: 'abc' } })
    expect(path).toBe('/invoices/abc')
  })

  it('maps InvoiceList to /invoices', () => {
    const path = screenToPath({ screen: 'InvoiceList', params: {} })
    expect(path).toBe('/invoices')
  })

  it('maps QuoteDetail to /quotes/:id', () => {
    const path = screenToPath({ screen: 'QuoteDetail', params: { id: 'q1' } })
    expect(path).toBe('/quotes/q1')
  })

  it('maps CustomerProfile to /customers/:id', () => {
    const path = screenToPath({ screen: 'CustomerProfile', params: { id: 'c1' } })
    expect(path).toBe('/customers/c1')
  })

  it('maps Dashboard to /dashboard', () => {
    const path = screenToPath({ screen: 'Dashboard', params: {} })
    expect(path).toBe('/dashboard')
  })

  it('maps unknown screen to /dashboard', () => {
    const path = screenToPath({ screen: 'UnknownScreen', params: {} })
    expect(path).toBe('/dashboard')
  })
})

/* ------------------------------------------------------------------ */
/* Route coverage tests                                               */
/* ------------------------------------------------------------------ */

describe('Route coverage', () => {
  it('has patterns for all core entity types', () => {
    const screens = DEEP_LINK_PATTERNS.map((p) => p.screen)
    expect(screens).toContain('InvoiceDetail')
    expect(screens).toContain('InvoiceList')
    expect(screens).toContain('QuoteDetail')
    expect(screens).toContain('QuoteList')
    expect(screens).toContain('CustomerProfile')
    expect(screens).toContain('CustomerList')
    expect(screens).toContain('JobDetail')
    expect(screens).toContain('JobList')
    expect(screens).toContain('ComplianceDashboard')
    expect(screens).toContain('Settings')
    expect(screens).toContain('Dashboard')
  })

  it('all patterns have valid regex', () => {
    for (const pattern of DEEP_LINK_PATTERNS) {
      expect(pattern.pattern).toBeInstanceOf(RegExp)
      expect(typeof pattern.screen).toBe('string')
      expect(typeof pattern.paramExtractor).toBe('function')
    }
  })
})
