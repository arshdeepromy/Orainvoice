import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { render, screen, fireEvent, waitFor, act } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'

/**
 * Supplemental OrgLookupScreen UI-state tests — covers the states NOT already
 * exercised by OrgLookupScreen.test.tsx:
 *
 *  - while a lookup is in flight, the submit shows a spinner and is disabled,
 *    and the input is disabled (R10.5)
 *  - a lookup that exceeds the 10s timeout shows a timeout error, retains the
 *    entered input, never blanks, and offers retry (R10.7, R12.3)
 *
 * Requirements: 10.5, 10.7, 12.3
 */

/* ------------------------------------------------------------------ */
/* Mocks (mirror OrgLookupScreen.test.tsx)                            */
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

import OrgLookupScreen from '@/screens/portal-select/OrgLookupScreen'

/** Mirror of the screen's resolve timeout (not exported). */
const RESOLVE_TIMEOUT_MS = 10_000

/* ------------------------------------------------------------------ */
/* Helpers                                                            */
/* ------------------------------------------------------------------ */

function renderScreen() {
  return render(
    <MemoryRouter
      initialEntries={[
        { pathname: '/portal-select/lookup', state: { portal_type: 'employee' } },
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

afterEach(() => {
  vi.useRealTimers()
})

/* ------------------------------------------------------------------ */
/* Tests                                                              */
/* ------------------------------------------------------------------ */

describe('OrgLookupScreen — in-flight + timeout states', () => {
  it('disables submit and shows a spinner while a lookup is in flight (R10.5)', async () => {
    // A resolve that never settles keeps the screen in the loading state.
    mockGet.mockImplementation(() => new Promise(() => {}))
    renderScreen()
    typeQuery('acme')

    const submit = screen.getByRole('button', { name: /continue/i })
    fireEvent.click(submit)

    // The control switches to the searching/spinner state and is disabled.
    await waitFor(() =>
      expect(screen.getByRole('button', { name: /searching/i })).toBeDisabled(),
    )
    // The input is also disabled while in flight.
    expect(screen.getByLabelText(/organisation name or code/i)).toBeDisabled()
    expect(mockNavigate).not.toHaveBeenCalled()
  })

  it('shows a timeout error, retains input, and offers retry after the deadline (R10.7, R12.3)', async () => {
    vi.useFakeTimers()
    // The resolve only settles when its AbortSignal fires (on the 10s timeout),
    // mirroring how the API client rejects an aborted request.
    mockGet.mockImplementation(
      (_path: string, opts: { signal: AbortSignal }) =>
        new Promise((_resolve, reject) => {
          opts.signal.addEventListener('abort', () =>
            reject(Object.assign(new Error('aborted'), { name: 'CanceledError' })),
          )
        }),
    )

    renderScreen()
    typeQuery('slowco')
    fireEvent.click(screen.getByRole('button', { name: /continue/i }))

    await act(async () => {
      await vi.advanceTimersByTimeAsync(RESOLVE_TIMEOUT_MS)
    })

    // Timeout-specific error is surfaced, never a blank screen.
    expect(screen.getByRole('alert')).toHaveTextContent(/took too long/i)
    // Input is retained for re-entry/retry.
    expect(screen.getByLabelText(/organisation name or code/i)).toHaveValue('slowco')
    // Retry action is present.
    expect(screen.getByRole('button', { name: /try again/i })).toBeInTheDocument()
  })
})
