import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, fireEvent, waitFor, within } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'

/**
 * Unit tests for PortalTypeSelector (mobile first-run portal chooser).
 *
 * Focus (new coverage — not duplicated by OrgLookupScreen.test.tsx):
 *  - exactly three selectable choices are rendered (R10.1)
 *  - every choice is a ≥44px touch target (R10.8)
 *  - Employee/Staff and Fleet route to the org lookup carrying portal_type,
 *    without persisting a selection (R10.1, R11.1)
 *  - Organisation persists {portal_type:'org'} and routes to the org login (R10.2)
 *
 * Requirements: 10.1, 10.2, 10.8
 */

/* ------------------------------------------------------------------ */
/* Mocks                                                              */
/* ------------------------------------------------------------------ */

const mockNavigate = vi.fn()
vi.mock('react-router-dom', async () => {
  const actual = await vi.importActual<typeof import('react-router-dom')>(
    'react-router-dom',
  )
  return { ...actual, useNavigate: () => mockNavigate }
})

// PortalTypeSelector resolves the org API base via Capacitor; force the web
// (non-native) branch so resolveOrgApiBase() returns the relative '/api/v1'.
vi.mock('@capacitor/core', () => ({
  Capacitor: { isNativePlatform: () => false },
}))

const mockSave = vi.fn<(sel: unknown) => Promise<boolean>>()
vi.mock('@/contexts/PortalSelectionContext', () => ({
  usePortalSelection: () => ({ save: mockSave }),
}))

/* ------------------------------------------------------------------ */
/* Imports (after mocks)                                              */
/* ------------------------------------------------------------------ */

import PortalTypeSelector, {
  ORG_LOOKUP_PATH,
  ORG_LOGIN_PATH,
  resolveOrgApiBase,
} from '@/screens/portal-select/PortalTypeSelector'

/* ------------------------------------------------------------------ */
/* Helpers                                                            */
/* ------------------------------------------------------------------ */

function renderScreen() {
  return render(
    <MemoryRouter initialEntries={['/portal-select']}>
      <PortalTypeSelector />
    </MemoryRouter>,
  )
}

/* ------------------------------------------------------------------ */
/* Setup                                                              */
/* ------------------------------------------------------------------ */

beforeEach(() => {
  vi.clearAllMocks()
  mockSave.mockResolvedValue(true)
})

/* ------------------------------------------------------------------ */
/* Tests                                                              */
/* ------------------------------------------------------------------ */

describe('resolveOrgApiBase', () => {
  it('uses the relative reverse-proxy base on web', () => {
    expect(resolveOrgApiBase()).toBe('/api/v1')
  })
})

describe('PortalTypeSelector', () => {
  it('renders exactly three portal choices (R10.1)', () => {
    renderScreen()
    const group = screen.getByRole('group', { name: /choose a portal type/i })
    const buttons = within(group).getAllByRole('button')
    expect(buttons).toHaveLength(3)
    expect(screen.getByRole('button', { name: /employee \/ staff/i })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: /^fleet$/i })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: /^organisation$/i })).toBeInTheDocument()
  })

  it('renders each choice as a ≥44px touch target (R10.8)', () => {
    renderScreen()
    const group = screen.getByRole('group', { name: /choose a portal type/i })
    const buttons = within(group).getAllByRole('button')
    expect(buttons).toHaveLength(3)
    for (const btn of buttons) {
      expect(btn).toHaveClass('min-h-[44px]')
    }
  })

  it('routes Employee/Staff to the org lookup carrying portal_type and persists nothing (R10.1, R11.1)', () => {
    renderScreen()
    fireEvent.click(screen.getByRole('button', { name: /employee \/ staff/i }))
    expect(mockNavigate).toHaveBeenCalledWith(ORG_LOOKUP_PATH, {
      state: { portal_type: 'employee' },
    })
    expect(mockSave).not.toHaveBeenCalled()
  })

  it('routes Fleet to the org lookup carrying portal_type and persists nothing (R10.1, R11.1)', () => {
    renderScreen()
    fireEvent.click(screen.getByRole('button', { name: /^fleet$/i }))
    expect(mockNavigate).toHaveBeenCalledWith(ORG_LOOKUP_PATH, {
      state: { portal_type: 'fleet' },
    })
    expect(mockSave).not.toHaveBeenCalled()
  })

  it('persists the org selection and routes to the org login on Organisation (R10.2)', async () => {
    renderScreen()
    fireEvent.click(screen.getByRole('button', { name: /^organisation$/i }))

    await waitFor(() =>
      expect(mockSave).toHaveBeenCalledWith({
        portal_type: 'org',
        api_base: '/api/v1',
      }),
    )
    await waitFor(() => expect(mockNavigate).toHaveBeenCalledWith(ORG_LOGIN_PATH))
  })
})
