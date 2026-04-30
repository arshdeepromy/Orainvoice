import { describe, it, expect } from 'vitest'
import { resolveNavbarMeta } from '../KonstaShell'

describe('resolveNavbarMeta', () => {
  it('returns correct title for root-level routes with no back button', () => {
    expect(resolveNavbarMeta('/dashboard')).toEqual({
      title: 'Dashboard',
      showBack: false,
    })
    expect(resolveNavbarMeta('/invoices')).toEqual({
      title: 'Invoices',
      showBack: false,
    })
    expect(resolveNavbarMeta('/customers')).toEqual({
      title: 'Customers',
      showBack: false,
    })
  })

  it('returns showBack=true for nested/detail routes', () => {
    const result = resolveNavbarMeta('/invoices/123')
    expect(result.showBack).toBe(true)
    expect(result.title).toBe('Invoices')
  })

  it('returns showBack=true for deeply nested routes', () => {
    const result = resolveNavbarMeta('/invoices/123/edit')
    expect(result.showBack).toBe(true)
    expect(result.title).toBe('Invoices')
  })

  it('returns showBack=true for customer detail routes', () => {
    const result = resolveNavbarMeta('/customers/abc-123')
    expect(result.showBack).toBe(true)
    expect(result.title).toBe('Customers')
  })

  it('returns correct title for all known root routes', () => {
    const routes: Record<string, string> = {
      '/dashboard': 'Dashboard',
      '/invoices': 'Invoices',
      '/customers': 'Customers',
      '/quotes': 'Quotes',
      '/jobs': 'Active Jobs',
      '/job-cards': 'Job Cards',
      '/bookings': 'Bookings',
      '/vehicles': 'Vehicles',
      '/inventory': 'Inventory',
      '/reports': 'Reports',
      '/settings': 'Settings',
    }

    for (const [path, expectedTitle] of Object.entries(routes)) {
      const result = resolveNavbarMeta(path)
      expect(result.title).toBe(expectedTitle)
      expect(result.showBack).toBe(false)
    }
  })

  it('returns empty title and showBack=false for unknown root path', () => {
    const result = resolveNavbarMeta('/unknown')
    expect(result.title).toBe('')
    expect(result.showBack).toBe(false)
  })

  it('returns showBack=true for unknown nested path', () => {
    const result = resolveNavbarMeta('/unknown/nested')
    expect(result.showBack).toBe(true)
  })

  it('handles root path /', () => {
    const result = resolveNavbarMeta('/')
    expect(result.showBack).toBe(false)
  })
})
