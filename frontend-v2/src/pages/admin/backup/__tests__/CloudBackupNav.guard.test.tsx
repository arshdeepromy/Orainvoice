/**
 * Cloud Backup navigation gating — Req 1.4 (Task 17.8).
 *
 * Requirement 1.4: "WHEN the application interface is rendered for a user whose
 * role is not global_admin, THE Backup_System SHALL NOT display any backup or
 * restore configuration, control, or navigation entry, and SHALL expose these
 * elements only when the user's role is global_admin."
 *
 * Architecture: the Cloud Backup area lives entirely inside the Global-Admin
 * Admin Console. The entry point is a "Cloud Backup" item in the Admin Console
 * sidebar (AdminLayout), and the whole /admin tree is mounted behind
 * RequireGlobalAdmin — so a non-global-admin can never reach it. The org-user
 * shell Sidebar exposes NO backup entry to anyone.
 *
 * This suite asserts the user-visible contract:
 *   1. The Admin Console (AdminLayout) renders the "Cloud Backup" entry pointing
 *      at /admin/backup — the global-admin entry point.
 *   2. The org-user shell Sidebar never renders a "Cloud Backup" entry, for any
 *      role (org_admin, salesperson) — the front-of-house equivalent of the
 *      API's 403: a non-global-admin never sees the entry point at all.
 *
 * Mounts the REAL Auth → Tenant → Module → FeatureFlag → Branch provider tree
 * (ShellProviders) against the deterministic `@/api/client` mock, mirroring the
 * existing shell unit tests. GlobalSearchBar is stubbed — it is unrelated to the
 * navigation contract under test and pulls in its own data/keyboard wiring.
 */
import { describe, it, expect, afterEach, vi } from 'vitest'
import { render, screen } from '@testing-library/react'
import Sidebar from '@/components/shell/Sidebar'
import { AdminLayout } from '@/layouts/AdminLayout'
import { setAccessToken } from '@/api/client'
import { ShellProviders, seedSession, makeToken } from '@/test/providers'

vi.mock('@/api/client', () => import('@/test/apiClientMock'))
// The admin console's global search bar is irrelevant to the nav contract and
// brings its own data + keyboard listeners; stub it to keep the test focused.
vi.mock('@/components/search', () => ({ GlobalSearchBar: () => null }))

const noop = () => {}

function renderSidebar() {
  return render(
    <ShellProviders initialEntries={['/dashboard']}>
      <Sidebar open={false} onClose={noop} />
    </ShellProviders>,
  )
}

function renderAdminConsole() {
  return render(
    <ShellProviders initialEntries={['/admin/dashboard']}>
      <AdminLayout />
    </ShellProviders>,
  )
}

afterEach(() => {
  sessionStorage.clear()
  setAccessToken(null)
})

describe('Cloud Backup nav entry — global_admin gating (Req 1.4)', () => {
  it('renders the "Cloud Backup" entry in the Admin Console for a global_admin', async () => {
    seedSession(makeToken({ role: 'global_admin', org_id: null }))
    renderAdminConsole()

    const link = await screen.findByRole('link', { name: 'Cloud Backup' })
    expect(link).toBeInTheDocument()
    expect(link).toHaveAttribute('href', '/admin/backup')
  })

  it('hides any backup entry from an org_admin in the org-user shell', async () => {
    seedSession(makeToken({ role: 'org_admin' }))
    renderSidebar()

    // Wait for the rail to settle (an always-visible item resolves).
    await screen.findByRole('link', { name: 'Invoices' })

    expect(screen.queryByRole('link', { name: 'Cloud Backup' })).not.toBeInTheDocument()
  })

  it('hides any backup entry from a salesperson in the org-user shell', async () => {
    seedSession(makeToken({ role: 'salesperson' }))
    renderSidebar()

    await screen.findByRole('link', { name: 'Invoices' })

    expect(screen.queryByRole('link', { name: 'Cloud Backup' })).not.toBeInTheDocument()
  })
})
