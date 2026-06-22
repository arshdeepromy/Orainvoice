/**
 * Org Settings → Employee Portal panel (Task 14.5).
 *
 * Covers (R3.2, R3.7, R3.8, R3.9, R4.4):
 *   • Debounced live availability: shows exactly one of
 *     available / unavailable / invalid after the ≥300ms debounce.
 *   • On a fetch error/timeout it shows "could not complete" and NEVER reports
 *     the candidate as available.
 *   • Save-time `409` retains the entered slug and reflects the unavailable
 *     reason.
 *   • Enabling without a slug surfaces the `slug_required` message and leaves
 *     the toggle disabled.
 *
 * `@/api/client` is mocked so the panel's `apiClient.get`/`apiClient.put`
 * calls resolve against deterministic shapes. Timers are faked to drive the
 * 350ms debounce deterministically.
 */
import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest'
import { render, screen, fireEvent, act } from '@testing-library/react'

vi.mock('@/api/client', () => ({ default: { get: vi.fn(), put: vi.fn() } }))

import apiClient from '@/api/client'
import { EmployeePortalTab } from '../OrgSettings'

const mockGet = apiClient.get as ReturnType<typeof vi.fn>
const mockPut = apiClient.put as ReturnType<typeof vi.fn>

/** Default `/org/settings` load: no slug, portal disabled. */
function settingsResponse(overrides: Record<string, unknown> = {}) {
  return Promise.resolve({ data: { slug: null, employee_portal_enabled: false, ...overrides } })
}

/** Advance fake timers past the debounce + flush the availability promise. */
async function flushAvailability() {
  await act(async () => {
    await vi.advanceTimersByTimeAsync(400)
  })
}

/** Let the mount-time `/org/settings` load resolve. */
async function flushMount() {
  await act(async () => {
    await vi.advanceTimersByTimeAsync(0)
  })
}

beforeEach(() => {
  vi.clearAllMocks()
  vi.useFakeTimers()
})

afterEach(() => {
  vi.useRealTimers()
})

describe('EmployeePortalTab — debounced availability states', () => {
  it('shows "Available" when the endpoint reports available', async () => {
    mockGet.mockImplementation((url: string) => {
      if (url === '/org/settings') return settingsResponse()
      if (url === '/api/v2/organisations/slug-availability')
        return Promise.resolve({ data: { result: 'available', reason: null } })
      return Promise.reject(new Error('unexpected'))
    })

    render(<EmployeePortalTab />)
    await flushMount()

    fireEvent.change(screen.getByLabelText('Organisation Slug'), {
      target: { value: 'acme-motors' },
    })
    await flushAvailability()

    expect(screen.getByText('✓ Available')).toBeInTheDocument()
  })

  it('shows the unavailable reason when the slug is taken', async () => {
    mockGet.mockImplementation((url: string) => {
      if (url === '/org/settings') return settingsResponse()
      if (url === '/api/v2/organisations/slug-availability')
        return Promise.resolve({ data: { result: 'unavailable', reason: 'Already taken.' } })
      return Promise.reject(new Error('unexpected'))
    })

    render(<EmployeePortalTab />)
    await flushMount()

    fireEvent.change(screen.getByLabelText('Organisation Slug'), {
      target: { value: 'taken-slug' },
    })
    await flushAvailability()

    expect(screen.getByText('✗ Already taken.')).toBeInTheDocument()
    expect(screen.queryByText('✓ Available')).not.toBeInTheDocument()
  })

  it('shows the invalid reason for a bad-format slug', async () => {
    mockGet.mockImplementation((url: string) => {
      if (url === '/org/settings') return settingsResponse()
      if (url === '/api/v2/organisations/slug-availability')
        return Promise.resolve({ data: { result: 'invalid', reason: 'Not a valid format.' } })
      return Promise.reject(new Error('unexpected'))
    })

    render(<EmployeePortalTab />)
    await flushMount()

    fireEvent.change(screen.getByLabelText('Organisation Slug'), {
      target: { value: 'Bad Slug!' },
    })
    await flushAvailability()

    expect(screen.getByText('✗ Not a valid format.')).toBeInTheDocument()
    expect(screen.queryByText('✓ Available')).not.toBeInTheDocument()
  })

  it('shows "could not complete" and NEVER "available" on a fetch error', async () => {
    mockGet.mockImplementation((url: string) => {
      if (url === '/org/settings') return settingsResponse()
      if (url === '/api/v2/organisations/slug-availability')
        return Promise.reject({ response: { status: 500 } })
      return Promise.reject(new Error('unexpected'))
    })

    render(<EmployeePortalTab />)
    await flushMount()

    fireEvent.change(screen.getByLabelText('Organisation Slug'), {
      target: { value: 'acme-motors' },
    })
    await flushAvailability()

    expect(
      screen.getByText('Could not complete the availability check. Try again.'),
    ).toBeInTheDocument()
    expect(screen.queryByText('✓ Available')).not.toBeInTheDocument()
  })
})

describe('EmployeePortalTab — save-time 409 retains input', () => {
  it('keeps the entered slug and shows the unavailable reason on a 409', async () => {
    mockGet.mockImplementation((url: string) => {
      if (url === '/org/settings') return settingsResponse()
      if (url === '/api/v2/organisations/slug-availability')
        return Promise.resolve({ data: { result: 'available', reason: null } })
      return Promise.reject(new Error('unexpected'))
    })
    // Save-time race: the slug was taken since the live check.
    mockPut.mockRejectedValue({
      response: { status: 409, data: { code: 'slug_taken', message: 'This slug is no longer available.' } },
    })

    render(<EmployeePortalTab />)
    await flushMount()

    const input = screen.getByLabelText('Organisation Slug') as HTMLInputElement
    fireEvent.change(input, { target: { value: 'acme-motors' } })
    await flushAvailability()
    expect(screen.getByText('✓ Available')).toBeInTheDocument()

    await act(async () => {
      fireEvent.click(screen.getByRole('button', { name: 'Save Slug' }))
      await vi.advanceTimersByTimeAsync(0)
    })

    // Input value is retained (not cleared) and the unavailable reason shows.
    expect((screen.getByLabelText('Organisation Slug') as HTMLInputElement).value).toBe('acme-motors')
    expect(screen.getByText('✗ This slug is no longer available.')).toBeInTheDocument()
    expect(mockPut).toHaveBeenCalledWith('/api/v2/organisations/slug', { slug: 'acme-motors' })
  })
})

describe('EmployeePortalTab — enable without a slug', () => {
  it('surfaces the slug_required message and stays Disabled', async () => {
    mockGet.mockImplementation((url: string) => {
      if (url === '/org/settings') return settingsResponse()
      return Promise.reject(new Error('unexpected'))
    })
    mockPut.mockRejectedValue({
      response: { status: 422, data: { code: 'slug_required', message: 'Set a slug before enabling the portal.' } },
    })

    render(<EmployeePortalTab />)
    await flushMount()

    const toggle = screen.getByRole('switch')
    expect(toggle).toHaveAttribute('aria-checked', 'false')

    await act(async () => {
      fireEvent.click(toggle)
      await vi.advanceTimersByTimeAsync(0)
    })

    expect(screen.getByText('Set a slug before enabling the portal.')).toBeInTheDocument()
    // The toggle remains off (server left the flag disabled).
    expect(screen.getByRole('switch')).toHaveAttribute('aria-checked', 'false')
    expect(mockPut).toHaveBeenCalledWith('/api/v2/organisations/employee-portal', { enabled: true })
  })
})
