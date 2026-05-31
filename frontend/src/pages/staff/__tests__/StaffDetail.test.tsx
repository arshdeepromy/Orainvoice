/**
 * StaffDetail (tabbed shell) — task E2.
 *
 * Validates: Requirement R1 (tabbed Staff Detail page).
 *
 * Cases covered:
 *   1. Module disabled → legacy single-form view renders.
 *   2. Module enabled  → tab strip with Overview / Roster / Documents.
 *   3. Tab click       → URL hash updates to the selected tab.
 */

import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router-dom'
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'

// Module hook — flip per test via the shared mock state.
const mockIsEnabled = vi.fn<(slug: string) => boolean>()

vi.mock('@/contexts/ModuleContext', () => ({
  ModuleProvider: ({ children }: { children: React.ReactNode }) => <>{children}</>,
  useModules: () => ({
    modules: [],
    enabledModules: [],
    isLoading: false,
    error: null,
    isEnabled: mockIsEnabled,
    refetch: async () => {},
  }),
}))

// Legacy component — we only care that it renders, so swap for a marker.
vi.mock('@/pages/staff/_legacy/StaffDetail.legacy', () => ({
  default: ({ staffId }: { staffId: string }) => (
    <div data-testid="legacy-staff-detail">Legacy view for {staffId}</div>
  ),
}))

// Stub tab components so we don't pull the (also-stub) lazy chunks via the
// real module graph during the synchronous part of the test.
vi.mock('@/pages/staff/tabs/OverviewTab', () => ({
  default: () => <div data-testid="tab-content-overview">Overview content</div>,
}))
vi.mock('@/pages/staff/tabs/RosterTab', () => ({
  default: () => <div data-testid="tab-content-roster">Roster content</div>,
}))
vi.mock('@/pages/staff/tabs/PayslipsTab', () => ({
  default: () => <div data-testid="tab-content-payslips">Payslips content</div>,
}))
vi.mock('@/pages/staff/tabs/DocumentsTab', () => ({
  default: () => <div data-testid="tab-content-documents">Documents content</div>,
}))

import StaffDetail from '../StaffDetail'

function clearHash() {
  window.history.replaceState(
    null,
    '',
    window.location.pathname + window.location.search
  )
}

function renderShell(staffId = 'staff-1') {
  return render(
    <MemoryRouter>
      <StaffDetail staffId={staffId} />
    </MemoryRouter>
  )
}

describe('StaffDetail tabbed shell', () => {
  beforeEach(() => {
    clearHash()
    mockIsEnabled.mockReset()
  })

  afterEach(() => {
    clearHash()
  })

  it('renders the legacy single-form view when staff_management is disabled', () => {
    mockIsEnabled.mockImplementation((slug) => slug !== 'staff_management')

    renderShell('staff-42')

    expect(screen.getByTestId('legacy-staff-detail')).toBeInTheDocument()
    expect(screen.getByText('Legacy view for staff-42')).toBeInTheDocument()
    // Tab strip must NOT render in legacy mode
    expect(screen.queryByRole('tablist')).not.toBeInTheDocument()
  })

  it('renders the tab strip with all four tabs when staff_management is enabled', async () => {
    mockIsEnabled.mockReturnValue(true)

    renderShell()

    expect(screen.getByRole('tablist')).toBeInTheDocument()
    const tabs = screen.getAllByRole('tab')
    expect(tabs).toHaveLength(4)
    expect(tabs[0]).toHaveTextContent('Overview')
    expect(tabs[1]).toHaveTextContent('Roster')
    expect(tabs[2]).toHaveTextContent('Payslips')
    expect(tabs[3]).toHaveTextContent('Documents')

    // Default tab is Overview, and its content lazy-loads via Suspense.
    expect(tabs[0]).toHaveAttribute('aria-selected', 'true')
    expect(tabs[1]).toHaveAttribute('aria-selected', 'false')
    expect(tabs[2]).toHaveAttribute('aria-selected', 'false')
    expect(tabs[3]).toHaveAttribute('aria-selected', 'false')
    expect(await screen.findByTestId('tab-content-overview')).toBeInTheDocument()
  })

  it('updates the URL hash when a tab is clicked', async () => {
    mockIsEnabled.mockReturnValue(true)
    const user = userEvent.setup()

    renderShell()

    // Initial state — no hash, default tab active.
    expect(window.location.hash).toBe('')

    const rosterTab = screen.getByRole('tab', { name: 'Roster' })
    await user.click(rosterTab)

    expect(window.location.hash).toBe('#roster')
    await waitFor(() =>
      expect(screen.getByRole('tab', { name: 'Roster' })).toHaveAttribute(
        'aria-selected',
        'true'
      )
    )
    expect(await screen.findByTestId('tab-content-roster')).toBeInTheDocument()

    const documentsTab = screen.getByRole('tab', { name: 'Documents' })
    await user.click(documentsTab)

    expect(window.location.hash).toBe('#documents')
    await waitFor(() =>
      expect(
        screen.getByRole('tab', { name: 'Documents' })
      ).toHaveAttribute('aria-selected', 'true')
    )
    expect(await screen.findByTestId('tab-content-documents')).toBeInTheDocument()
  })
})
