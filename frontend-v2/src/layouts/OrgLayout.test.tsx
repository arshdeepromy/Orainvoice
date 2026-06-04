import { render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { Routes, Route } from 'react-router-dom'
import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest'
import OrgLayout from './OrgLayout'
import { ShellProviders, seedSession } from '@/test/providers'
import { setAccessToken } from '@/api/client'

/**
 * Task 9 — responsive shell drawer behaviour (provider wiring: Task 15).
 *
 * jsdom does not evaluate CSS media queries, so the *visual* collapse at
 * ≤860px (sidebar transform, scrim fade, search→icon, branch hidden,
 * "New"→icon) lives in shell.css / `max-mobile:` variants and is verified
 * by the production build, not here. These tests cover the breakpoint-
 * agnostic state machine that drives all of it: the `data-nav-open` flag and
 * every affordance that opens/closes the drawer (hamburger, scrim, in-drawer
 * close button, nav-item activation, and Escape).
 *
 * OrgLayout mounts the real Sidebar + TopBar, which consume the real contexts,
 * so the shell is rendered inside the real provider tree (ShellProviders) with
 * a seeded org_admin session and a mocked `@/api/client` (test/apiClientMock).
 */

vi.mock('@/api/client', () => import('@/test/apiClientMock'))

/** Render OrgLayout inside the real provider tree with a trivial outlet page. */
function renderShell(initialPath = '/dashboard') {
  return render(
    <ShellProviders initialEntries={[initialPath]}>
      <Routes>
        <Route element={<OrgLayout />}>
          <Route path="/dashboard" element={<div>Dashboard page</div>} />
          <Route path="/invoices" element={<div>Invoices page</div>} />
        </Route>
      </Routes>
    </ShellProviders>,
  )
}

beforeEach(() => {
  localStorage.clear()
  seedSession()
})

afterEach(() => {
  localStorage.clear()
  setAccessToken(null)
})

/** The shell root carries the `data-nav-open` flag that drives the drawer CSS. */
function getShellRoot(container: HTMLElement): HTMLElement {
  const root = container.querySelector('.app-shell')
  if (!root) throw new Error('app-shell root not found')
  return root as HTMLElement
}

describe('OrgLayout responsive drawer', () => {
  it('starts with the drawer closed (data-nav-open=false)', () => {
    const { container } = renderShell()
    expect(getShellRoot(container)).toHaveAttribute('data-nav-open', 'false')
  })

  it('opens the drawer when the hamburger is clicked', async () => {
    const user = userEvent.setup()
    const { container } = renderShell()

    await user.click(screen.getByRole('button', { name: /open navigation menu/i }))

    expect(getShellRoot(container)).toHaveAttribute('data-nav-open', 'true')
  })

  it('mirrors the open state onto the sidebar data-open hook', async () => {
    const user = userEvent.setup()
    renderShell()

    const sidebar = screen.getByRole('complementary', { name: /primary navigation/i })
    expect(sidebar).toHaveAttribute('data-open', 'false')

    await user.click(screen.getByRole('button', { name: /open navigation menu/i }))
    expect(sidebar).toHaveAttribute('data-open', 'true')
  })

  it('closes the drawer when the in-drawer close button is clicked', async () => {
    const user = userEvent.setup()
    const { container } = renderShell()

    await user.click(screen.getByRole('button', { name: /open navigation menu/i }))
    expect(getShellRoot(container)).toHaveAttribute('data-nav-open', 'true')

    await user.click(screen.getByRole('button', { name: /close navigation/i }))
    expect(getShellRoot(container)).toHaveAttribute('data-nav-open', 'false')
  })

  it('closes the drawer when the scrim is clicked', async () => {
    const user = userEvent.setup()
    const { container } = renderShell()

    await user.click(screen.getByRole('button', { name: /open navigation menu/i }))
    const root = getShellRoot(container)
    expect(root).toHaveAttribute('data-nav-open', 'true')

    const scrim = container.querySelector('.shell-scrim') as HTMLElement
    await user.click(scrim)
    expect(root).toHaveAttribute('data-nav-open', 'false')
  })

  it('closes the drawer when a nav item is activated', async () => {
    const user = userEvent.setup()
    const { container } = renderShell()

    await user.click(screen.getByRole('button', { name: /open navigation menu/i }))
    const root = getShellRoot(container)
    expect(root).toHaveAttribute('data-nav-open', 'true')

    const sidebar = screen.getByRole('complementary', { name: /primary navigation/i })
    await user.click(within(sidebar).getByRole('link', { name: /invoices/i }))

    expect(root).toHaveAttribute('data-nav-open', 'false')
  })

  it('closes the drawer when Escape is pressed', async () => {
    const user = userEvent.setup()
    const { container } = renderShell()

    await user.click(screen.getByRole('button', { name: /open navigation menu/i }))
    const root = getShellRoot(container)
    expect(root).toHaveAttribute('data-nav-open', 'true')

    await user.keyboard('{Escape}')
    expect(root).toHaveAttribute('data-nav-open', 'false')
  })

  it('exposes a scrim dismiss surface marked aria-hidden', () => {
    const { container } = renderShell()
    const scrim = container.querySelector('.shell-scrim')
    expect(scrim).not.toBeNull()
    expect(scrim).toHaveAttribute('aria-hidden', 'true')
  })
})
