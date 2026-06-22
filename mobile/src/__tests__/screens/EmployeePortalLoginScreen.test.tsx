import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { render, screen, fireEvent, waitFor, act } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'

/**
 * Unit tests for EmployeePortalLoginScreen (org-branded mobile login).
 *
 * Focus (new coverage — the branded-login default-branding fallback):
 *  - renders branding supplied via route state and keeps the form usable (R13.5)
 *  - an org with no logo/colour falls back to the neutral default without an
 *    error, form usable (R13.2)
 *  - branding missing → short fallback fetch fails → neutral default + a
 *    non-blocking "branding could not be loaded" indication, form still usable
 *    and submittable (R13.6)
 *  - branding slow (>5s) → treated as could-not-load, neutral default, form
 *    usable (R13.6)
 *  - direct navigation without portal context never renders blank — it shows a
 *    recovery prompt back to the selector (R12.4)
 *
 * Requirements: 13.5, 13.6, 12.4
 */

/* ------------------------------------------------------------------ */
/* Mocks                                                              */
/* ------------------------------------------------------------------ */

const { mockAxiosGet, mockAxiosPost } = vi.hoisted(() => ({
  mockAxiosGet: vi.fn(),
  mockAxiosPost: vi.fn(),
}))
vi.mock('axios', () => ({
  default: { get: mockAxiosGet, post: mockAxiosPost, isAxiosError: () => false },
}))

const mockNavigate = vi.fn()
vi.mock('react-router-dom', async () => {
  const actual = await vi.importActual<typeof import('react-router-dom')>(
    'react-router-dom',
  )
  return { ...actual, useNavigate: () => mockNavigate }
})

const mockSave = vi.fn<(sel: unknown) => Promise<boolean>>()
vi.mock('@/contexts/PortalSelectionContext', () => ({
  usePortalSelection: () => ({ save: mockSave }),
}))

/* ------------------------------------------------------------------ */
/* Imports (after mocks)                                              */
/* ------------------------------------------------------------------ */

import EmployeePortalLoginScreen, {
  type EmployeePortalLoginState,
} from '@/screens/portal-select/EmployeePortalLoginScreen'

/** Mirror of the screen's branding fallback timeout (not exported). */
const BRANDING_TIMEOUT_MS = 5_000

/* ------------------------------------------------------------------ */
/* Helpers                                                            */
/* ------------------------------------------------------------------ */

function renderScreen(state: EmployeePortalLoginState | undefined) {
  return render(
    <MemoryRouter
      initialEntries={[{ pathname: '/portal-select/employee-login', state }]}
    >
      <EmployeePortalLoginScreen />
    </MemoryRouter>,
  )
}

function expectFormUsable() {
  const email = screen.getByLabelText(/email/i)
  const password = screen.getByLabelText(/password/i)
  const submit = screen.getByRole('button', { name: /sign in/i })
  expect(email).toBeInTheDocument()
  expect(password).toBeInTheDocument()

  // The form is genuinely usable: typing valid credentials enables submit.
  fireEvent.change(email, { target: { value: 'worker@acme.test' } })
  fireEvent.change(password, { target: { value: 'hunter2' } })
  expect(submit).not.toBeDisabled()
}

/* ------------------------------------------------------------------ */
/* Setup                                                              */
/* ------------------------------------------------------------------ */

beforeEach(() => {
  vi.clearAllMocks()
  mockSave.mockResolvedValue(true)
})

afterEach(() => {
  vi.useRealTimers()
})

/* ------------------------------------------------------------------ */
/* Tests                                                              */
/* ------------------------------------------------------------------ */

describe('EmployeePortalLoginScreen — branding', () => {
  it('renders branding from route state and keeps the form usable (R13.5)', () => {
    renderScreen({
      portal_type: 'employee',
      org_id: 'org-1',
      slug: 'acme',
      api_base: '/e/api',
      org_name: 'Acme Auto',
      branding: {
        org_name: 'Acme Auto',
        logo_url: 'https://cdn.test/logo.png',
        primary_colour: '#cc0000',
        secondary_colour: null,
      },
    })

    // Org name from branding is shown.
    expect(screen.getByRole('heading', { name: /acme auto/i })).toBeInTheDocument()
    // Logo from branding is rendered with an accessible name.
    expect(screen.getByAltText(/acme auto logo/i)).toBeInTheDocument()
    // No "branding could not be loaded" indication when branding is present.
    expect(screen.queryByText(/branding could not be loaded/i)).not.toBeInTheDocument()
    // No fallback fetch is performed when branding came with the route state.
    expect(mockAxiosGet).not.toHaveBeenCalled()
    expectFormUsable()
  })

  it('falls back to the neutral default for an org with no logo/colour, no error, form usable (R13.2)', () => {
    renderScreen({
      portal_type: 'employee',
      slug: 'acme',
      api_base: '/e/api',
      org_name: 'Acme Auto',
      // Branding object present but every field null (org never set branding).
      branding: { org_name: null, logo_url: null, primary_colour: null, secondary_colour: null },
    })

    // Falls back to the org_name from the lookup; no logo image rendered.
    expect(screen.getByRole('heading', { name: /acme auto/i })).toBeInTheDocument()
    expect(screen.queryByAltText(/logo/i)).not.toBeInTheDocument()
    // A present (all-null) branding object is not an error.
    expect(screen.queryByText(/branding could not be loaded/i)).not.toBeInTheDocument()
    expect(mockAxiosGet).not.toHaveBeenCalled()
    expectFormUsable()
  })

  it('shows the neutral default + non-blocking notice when the branding fetch fails, form stays usable (R13.6)', async () => {
    mockAxiosGet.mockRejectedValueOnce(new Error('network'))
    renderScreen({
      portal_type: 'employee',
      slug: 'acme',
      api_base: '/e/api',
      org_name: 'Acme Auto',
      // No branding in route state → screen performs a short fallback fetch.
    })

    // It attempted the fallback branding fetch.
    await waitFor(() => expect(mockAxiosGet).toHaveBeenCalled())
    // Non-blocking notice appears…
    await waitFor(() =>
      expect(screen.getByText(/branding could not be loaded/i)).toBeInTheDocument(),
    )
    // …and the org name still falls back to the lookup value, never blank.
    expect(screen.getByRole('heading', { name: /acme auto/i })).toBeInTheDocument()
    expectFormUsable()
  })

  it('treats a slow (>5s) branding fetch as could-not-load and keeps the form usable (R13.6)', async () => {
    vi.useFakeTimers()
    // The fallback fetch only settles when its AbortSignal fires (i.e. on the
    // 5s timeout) — mirroring how axios rejects an aborted request.
    mockAxiosGet.mockImplementation(
      (_url: string, opts: { signal?: AbortSignal }) =>
        new Promise((_resolve, reject) => {
          opts.signal?.addEventListener('abort', () =>
            reject(Object.assign(new Error('aborted'), { name: 'CanceledError' })),
          )
        }),
    )

    renderScreen({
      portal_type: 'employee',
      slug: 'acme',
      api_base: '/e/api',
      org_name: 'Acme Auto',
    })

    // Advance past the branding timeout and flush the resulting rejection.
    await act(async () => {
      await vi.advanceTimersByTimeAsync(BRANDING_TIMEOUT_MS)
    })

    expect(screen.getByText(/branding could not be loaded/i)).toBeInTheDocument()
    expect(screen.getByRole('heading', { name: /acme auto/i })).toBeInTheDocument()
    // Form remains present/usable after the fallback (real timers for events).
    vi.useRealTimers()
    expectFormUsable()
  })

  it('never renders blank when navigated without portal context (R12.4)', () => {
    renderScreen(undefined)
    expect(screen.getByRole('heading', { name: /portal not selected/i })).toBeInTheDocument()
    const choose = screen.getByRole('button', { name: /choose portal/i })
    fireEvent.click(choose)
    expect(mockNavigate).toHaveBeenCalledWith('/portal-select', { replace: true })
  })
})
