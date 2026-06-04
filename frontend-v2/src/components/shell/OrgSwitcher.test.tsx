import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest'
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { Routes, Route, useLocation } from 'react-router-dom'
import OrgSwitcher from './OrgSwitcher'
import { ShellProviders, seedSession } from '@/test/providers'
import { setAccessToken } from '@/api/client'

/**
 * OrgSwitcher unit tests (Tasks 10, 15).
 *
 * Task 15 replaced the context shims with the REAL providers, so these tests
 * mount OrgSwitcher inside the real Auth → Tenant tree (ShellProviders) with a
 * seeded org_admin session and a mocked `@/api/client` (test/apiClientMock).
 * TenantContext now resolves `/org/settings`, so the org name comes from the
 * real branding payload ("Kerikeri Motors"). The menu renders its admin actions
 * (Organisation settings, Billing) but not the global-admin-only entries.
 */

vi.mock('@/api/client', () => import('@/test/apiClientMock'))

/** Surfaces the current router location so we can assert navigation targets. */
function LocationProbe() {
  const loc = useLocation()
  return <div data-testid="location">{loc.pathname + loc.search}</div>
}

function renderOrgSwitcher() {
  render(
    <ShellProviders initialEntries={['/dashboard']}>
      <OrgSwitcher />
      <Routes>
        <Route path="*" element={<LocationProbe />} />
      </Routes>
    </ShellProviders>,
  )
}

beforeEach(() => {
  sessionStorage.clear()
  seedSession()
})

afterEach(() => {
  sessionStorage.clear()
  setAccessToken(null)
})

describe('OrgSwitcher — trigger', () => {
  it('renders the org name, plan line and initials avatar', async () => {
    renderOrgSwitcher()
    // Org name comes from the real /org/settings branding payload once resolved.
    const trigger = await screen.findByRole('button', { name: /Organisation: Kerikeri Motors/ })
    expect(trigger).toBeInTheDocument()
    expect(trigger).toHaveTextContent('Kerikeri Motors')
    // Plan line is still the presentational prototype fallback (no real source).
    expect(trigger).toHaveTextContent('PRO · 12 SEATS')
    // Gradient avatar shows the derived initials ("Kerikeri Motors" → "KM").
    expect(trigger).toHaveTextContent('KM')
  })
})

describe('OrgSwitcher — admin actions', () => {
  it('opens the menu and navigates to Organisation settings', async () => {
    const user = userEvent.setup()
    renderOrgSwitcher()

    await user.click(await screen.findByRole('button', { name: /Organisation: Kerikeri Motors/ }))
    const settings = await screen.findByRole('menuitem', { name: 'Organisation settings' })
    await user.click(settings)
    expect(screen.getByTestId('location')).toHaveTextContent('/settings')
  })

  it('navigates to the Billing tab', async () => {
    const user = userEvent.setup()
    renderOrgSwitcher()

    await user.click(await screen.findByRole('button', { name: /Organisation: Kerikeri Motors/ }))
    await user.click(await screen.findByRole('menuitem', { name: 'Billing' }))
    expect(screen.getByTestId('location')).toHaveTextContent('/settings?tab=billing')
  })

  it('does not show global-admin-only entries for an org_admin', async () => {
    const user = userEvent.setup()
    renderOrgSwitcher()

    await user.click(await screen.findByRole('button', { name: /Organisation: Kerikeri Motors/ }))
    await screen.findByRole('menuitem', { name: 'Organisation settings' })
    expect(screen.queryByRole('menuitem', { name: 'View all organisations' })).not.toBeInTheDocument()
    expect(screen.queryByRole('menuitem', { name: 'Back to Admin' })).not.toBeInTheDocument()
  })
})
