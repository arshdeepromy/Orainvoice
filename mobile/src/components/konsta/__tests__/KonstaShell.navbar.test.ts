import { describe, it, expect } from 'vitest'

/**
 * The resolveNavbarMeta function was removed from KonstaShell as part of
 * the Konsta UI redesign. Each screen now owns its own Konsta <Navbar>
 * inside its <Page> component, so centralised route-to-title resolution
 * is no longer needed.
 *
 * These tests verify the new shell structure expectations.
 */
describe('KonstaShell structure', () => {
  it('exports KonstaShell component', async () => {
    const mod = await import('../KonstaShell')
    expect(mod.KonstaShell).toBeDefined()
    expect(typeof mod.KonstaShell).toBe('function')
  })

  it('does not export resolveNavbarMeta (removed — screens own their navbars)', async () => {
    const mod = await import('../KonstaShell') as Record<string, unknown>
    expect(mod.resolveNavbarMeta).toBeUndefined()
  })
})
