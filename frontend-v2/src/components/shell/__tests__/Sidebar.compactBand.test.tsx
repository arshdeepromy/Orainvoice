import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest'
import { render, screen, waitFor } from '@testing-library/react'
import Sidebar from '../Sidebar'
import apiClient, { setAccessToken } from '@/api/client'
import { ShellProviders, seedSession } from '@/test/providers'

/**
 * Sidebar — Compact_Band (icon-only rail) unit tests (Task 6.2).
 *
 * The Compact_Band (861–1279px) icon-only treatment is implemented as PURE CSS
 * in `shell.css` (a media query scoped to `.app-shell .shell-sidebar`). There is
 * NO JS state and NO API call tied to the responsive tier. jsdom has no layout
 * engine, so this suite does NOT assert the visual collapse (that's verified in
 * the manual/Playwright pass, task 7). Instead it asserts the two contracts that
 * survive into the DOM/behaviour layer:
 *
 *   1. Accessibility contract (Req 4.8) — under the icon-only treatment every
 *      nav item still exposes an accessible name. The label text stays in the
 *      DOM (`.shell-nav-label`, only visually hidden by CSS) and each NavLink
 *      carries an `aria-label`, so `getByRole('link', { name })` resolves.
 *   2. No-persistence contract (Req 4.6) — crossing the Compact_Band tier (a
 *      `matchMedia` `change` event) fires NO settings-mutation API call. Because
 *      the band is pure CSS, the Sidebar subscribes to no matchMedia listener at
 *      all; the assertion is simply that no `/org/settings` write (or any
 *      `sidebar_display_mode` mutation) happens during/after a simulated change.
 *
 * Mounts the REAL Auth → Tenant → Module → FeatureFlag → Branch tree
 * (ShellProviders) with a seeded org_admin session and the mocked `@/api/client`
 * (test/apiClientMock), mirroring the existing shell suite (OrgSwitcher/TopBar).
 */

vi.mock('@/api/client', () => import('@/test/apiClientMock'))

/**
 * Install a controllable `window.matchMedia` mock that records its created
 * MediaQueryList objects so a test can flip `matches` and dispatch a `change`
 * event to every subscriber — simulating the viewport crossing into/out of the
 * Compact_Band. Returns a `dispatchChange` helper and the underlying spy.
 */
function installMatchMedia(initialMatches = false) {
  const created: Array<{
    media: string
    matches: boolean
    listeners: Set<(e: { matches: boolean; media: string }) => void>
  }> = []

  const matchMedia = vi.fn((query: string) => {
    const listeners = new Set<(e: { matches: boolean; media: string }) => void>()
    const entry = { media: query, matches: initialMatches, listeners }
    created.push(entry)
    return {
      get matches() {
        return entry.matches
      },
      media: query,
      onchange: null,
      addEventListener: (_type: string, cb: (e: { matches: boolean; media: string }) => void) =>
        listeners.add(cb),
      removeEventListener: (_type: string, cb: (e: { matches: boolean; media: string }) => void) =>
        listeners.delete(cb),
      // Legacy API some libraries still use.
      addListener: (cb: (e: { matches: boolean; media: string }) => void) => listeners.add(cb),
      removeListener: (cb: (e: { matches: boolean; media: string }) => void) => listeners.delete(cb),
      dispatchEvent: () => true,
    } as unknown as MediaQueryList
  })

  ;(window as unknown as { matchMedia: typeof window.matchMedia }).matchMedia =
    matchMedia as unknown as typeof window.matchMedia

  return {
    matchMedia,
    /** Flip every created query's `matches` and notify its `change` listeners. */
    dispatchChange(matches: boolean) {
      for (const entry of created) {
        entry.matches = matches
        entry.listeners.forEach((cb) => cb({ matches, media: entry.media }))
      }
    },
  }
}

const noop = () => {}

function renderSidebar() {
  return render(
    <ShellProviders initialEntries={['/invoices']}>
      <Sidebar open={false} onClose={noop} />
    </ShellProviders>,
  )
}

let originalMatchMedia: typeof window.matchMedia | undefined

beforeEach(() => {
  sessionStorage.clear()
  originalMatchMedia = window.matchMedia
  seedSession()
})

afterEach(() => {
  sessionStorage.clear()
  setAccessToken(null)
  if (originalMatchMedia) {
    window.matchMedia = originalMatchMedia
  } else {
    delete (window as unknown as { matchMedia?: typeof window.matchMedia }).matchMedia
  }
})

describe('Sidebar — Compact_Band accessible names (Req 4.8)', () => {
  // Ungated items (no module/flag/role/trade gate) that always render so we can
  // assert their accessible names deterministically under the icon-only rail.
  const ALWAYS_VISIBLE = ['Dashboard', 'Reports', 'Invoices', 'Customers', 'Notifications', 'Data']

  it('exposes each nav item by its accessible name (aria-label survives icon-only CSS)', async () => {
    installMatchMedia(true)
    renderSidebar()

    // Each ungated nav item is reachable by its accessible name. The accessible
    // name comes from the NavLink `aria-label` (and the in-DOM label text), so
    // it survives even when the Compact_Band CSS visually hides the label.
    for (const name of ALWAYS_VISIBLE) {
      const link = await screen.findByRole('link', { name })
      expect(link).toBeInTheDocument()
    }
  })

  it('keeps the label text in the DOM (visually hidden, not removed) so the name survives', async () => {
    installMatchMedia(true)
    const { container } = renderSidebar()

    // The label span must remain in the DOM — the Compact_Band only hides it
    // visually via CSS. Removing it would drop the accessible name.
    await screen.findByRole('link', { name: 'Invoices' })
    const labels = container.querySelectorAll('.shell-nav-label')
    expect(labels.length).toBeGreaterThan(0)

    const labelText = Array.from(labels).map((el) => el.textContent?.trim())
    expect(labelText).toContain('Invoices')
    expect(labelText).toContain('Dashboard')
    expect(labelText).toContain('Customers')
  })

  it('exposes the accessible name via aria-label even though it duplicates the label text', async () => {
    installMatchMedia(true)
    renderSidebar()

    const invoices = await screen.findByRole('link', { name: 'Invoices' })
    expect(invoices).toHaveAttribute('aria-label', 'Invoices')
  })
})

describe('Sidebar — Compact_Band no persistence (Req 4.6)', () => {
  it('fires no settings-mutation API call when a matchMedia change crosses the tier', async () => {
    const media = installMatchMedia(false)
    renderSidebar()

    // Let the providers settle (settings/modules resolve via GET on mount).
    await screen.findByRole('link', { name: 'Invoices' })

    const post = vi.mocked(apiClient.post)
    const postCallsBefore = post.mock.calls.length

    // Simulate the viewport crossing into the Compact_Band, then back out.
    media.dispatchChange(true)
    media.dispatchChange(false)

    // Give any (hypothetical) async listener a chance to run.
    await waitFor(() => {
      expect(post.mock.calls.length).toBe(postCallsBefore)
    })

    // Belt and braces: no POST ever targeted org settings or wrote the
    // sidebar_display_mode preference.
    const settingsWrites = post.mock.calls.filter(([url, body]) => {
      const u = typeof url === 'string' ? url : ''
      const serialized = JSON.stringify(body ?? '')
      return /settings/i.test(u) || /sidebar_display_mode/i.test(serialized)
    })
    expect(settingsWrites).toHaveLength(0)
  })

  it('does not subscribe the rail to a matchMedia listener (the tier is pure CSS)', async () => {
    const media = installMatchMedia(false)
    renderSidebar()
    await screen.findByRole('link', { name: 'Invoices' })

    // The Sidebar itself does not observe the viewport — the Compact_Band is
    // presentation-only CSS. Dispatching a change must not throw or trigger any
    // POST. (We don't assert matchMedia was never called, since nested shell
    // pieces may query it; we assert the responsive change has no write effect.)
    const post = vi.mocked(apiClient.post)
    const before = post.mock.calls.length
    expect(() => media.dispatchChange(true)).not.toThrow()
    expect(post.mock.calls.length).toBe(before)
  })
})
