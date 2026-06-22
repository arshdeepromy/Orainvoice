import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, fireEvent, waitFor } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'

/**
 * Unit tests for OrgLookupScreen (mobile org lookup → branded login).
 *
 * Covers the input + lookup states from the task:
 *  - single match → routes to the branded login (R10.4)
 *  - multiple matches → disambiguation list (R9.4)
 *  - none / disabled → inline error, input retained (R10.6, R12.1, R12.2)
 *  - failure → error with retry, input retained (R10.7, R12.3)
 *  - offline with no persisted selection → network-required message (R12.4)
 *  - submit disabled while a lookup is in flight (R10.5)
 *
 * Requirements: 10.3, 10.5, 10.6, 10.7, 12.1, 12.2, 12.3, 12.4
 */

/* ------------------------------------------------------------------ */
/* Mocks                                                              */
/* ------------------------------------------------------------------ */

const mockGet = vi.fn()
vi.mock('@/api/client', () => ({
  default: { get: (...args: unknown[]) => mockGet(...args) },
}))

const mockNavigate = vi.fn()
vi.mock('react-router-dom', async () => {
  const actual = await vi.importActual<typeof import('react-router-dom')>(
    'react-router-dom',
  )
  return { ...actual, useNavigate: () => mockNavigate }
})

const mockOffline = { isOnline: true }
vi.mock('@/contexts/OfflineContext', () => ({
  useOffline: () => mockOffline,
}))

const mockSelection: { selection: unknown } = { selection: null }
vi.mock('@/contexts/PortalSelectionContext', () => ({
  usePortalSelection: () => mockSelection,
}))

/* ------------------------------------------------------------------ */
/* Imports (after mocks)                                              */
/* ------------------------------------------------------------------ */

import OrgLookupScreen, {
  resolvePortalApiBase,
} from '@/screens/portal-select/OrgLookupScreen'

/* ------------------------------------------------------------------ */
/* Helpers                                                            */
/* ------------------------------------------------------------------ */

function renderScreen(portalType: 'employee' | 'fleet' = 'employee') {
  return render(
    <MemoryRouter
      initialEntries={[
        { pathname: '/portal-select/lookup', state: { portal_type: portalType } },
      ]}
    >
      <OrgLookupScreen />
    </MemoryRouter>,
  )
}

function typeQuery(value: string) {
  const input = screen.getByLabelText(/organisation name or code/i)
  fireEvent.change(input, { target: { value } })
  return input
}

/* ------------------------------------------------------------------ */
/* Setup                                                              */
/* ------------------------------------------------------------------ */

beforeEach(() => {
  vi.clearAllMocks()
  mockOffline.isOnline = true
  mockSelection.selection = null
})

/* ------------------------------------------------------------------ */
/* Tests                                                              */
/* ------------------------------------------------------------------ */

describe('resolvePortalApiBase', () => {
  it('maps employee → /e/api and fleet → /fleet/api on web', () => {
    expect(resolvePortalApiBase('employee')).toBe('/e/api')
    expect(resolvePortalApiBase('fleet')).toBe('/fleet/api')
  })
})

describe('OrgLookupScreen', () => {
  it('renders the input and a disabled submit until text is entered (R10.3)', () => {
    renderScreen()
    expect(screen.getByLabelText(/organisation name or code/i)).toBeInTheDocument()
    const submit = screen.getByRole('button', { name: /continue/i })
    expect(submit).toBeDisabled()
  })

  it('routes to the branded login on a single match (R10.4)', async () => {
    mockGet.mockResolvedValueOnce({
      data: {
        match: {
          org_id: 'org-1',
          org_name: 'Acme Auto',
          branding: { logo_url: 'l.png', primary_colour: '#111', secondary_colour: null },
        },
      },
    })
    renderScreen()
    typeQuery('acme')
    fireEvent.click(screen.getByRole('button', { name: /continue/i }))

    await waitFor(() => expect(mockNavigate).toHaveBeenCalled())
    const [path, opts] = mockNavigate.mock.calls[0]
    expect(path).toBe('/portal-select/employee-login')
    expect(opts.state).toMatchObject({
      portal_type: 'employee',
      org_id: 'org-1',
      slug: 'acme',
      api_base: '/e/api',
      org_name: 'Acme Auto',
    })
    // the resolve was called with q + portal_type
    expect(mockGet).toHaveBeenCalledWith('/api/v2/public/portal-resolve', {
      params: { q: 'acme', portal_type: 'employee' },
      signal: expect.any(Object),
    })
  })

  it('shows a disambiguation list when multiple match (R9.4)', async () => {
    mockGet.mockResolvedValueOnce({
      data: {
        candidates: [
          { org_name: 'Acme North', branding: {} },
          { org_name: 'Acme South', branding: {} },
        ],
      },
    })
    renderScreen()
    typeQuery('acme')
    fireEvent.click(screen.getByRole('button', { name: /continue/i }))

    await waitFor(() =>
      expect(screen.getByText(/multiple organisations match/i)).toBeInTheDocument(),
    )
    expect(screen.getByRole('button', { name: /acme north/i })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: /acme south/i })).toBeInTheDocument()
    expect(mockNavigate).not.toHaveBeenCalled()
  })

  it('shows an inline not-found error and retains input on 404 (R10.6, R12.1)', async () => {
    mockGet.mockRejectedValueOnce({ response: { status: 404 } })
    renderScreen()
    typeQuery('missingco')
    fireEvent.click(screen.getByRole('button', { name: /continue/i }))

    await waitFor(() =>
      expect(screen.getByRole('alert')).toHaveTextContent(/couldn’t find an organisation/i),
    )
    // input retained
    expect(screen.getByLabelText(/organisation name or code/i)).toHaveValue('missingco')
    // retry action present (R12.2)
    expect(screen.getByRole('button', { name: /try again/i })).toBeInTheDocument()
  })

  it('shows a failure error with retry that re-runs the same lookup (R10.7, R12.3)', async () => {
    mockGet
      .mockRejectedValueOnce(new Error('network'))
      .mockResolvedValueOnce({ data: { match: { org_id: 'o2', org_name: 'Beta', branding: {} } } })
    renderScreen()
    typeQuery('beta')
    fireEvent.click(screen.getByRole('button', { name: /continue/i }))

    await waitFor(() =>
      expect(screen.getByRole('alert')).toHaveTextContent(/could not be completed/i),
    )
    expect(screen.getByLabelText(/organisation name or code/i)).toHaveValue('beta')

    // retry re-invokes the resolve with the same input
    fireEvent.click(screen.getByRole('button', { name: /try again/i }))
    await waitFor(() => expect(mockNavigate).toHaveBeenCalled())
    expect(mockGet).toHaveBeenCalledTimes(2)
    expect(mockGet.mock.calls[1][1].params).toEqual({ q: 'beta', portal_type: 'employee' })
  })

  it('shows the network-required message and blocks submit when offline with no selection (R12.4)', () => {
    mockOffline.isOnline = false
    renderScreen()
    typeQuery('acme')
    expect(screen.getByText(/network connection is required/i)).toBeInTheDocument()
    expect(screen.getByRole('button', { name: /continue/i })).toBeDisabled()
  })
})
