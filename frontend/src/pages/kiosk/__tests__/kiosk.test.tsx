import { render, screen, waitFor, act } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'

/**
 * Unit tests for the Kiosk check-in flow.
 * Validates: Requirements 2.2, 2.3, 2.5, 3.1, 3.7, 5.1, 5.3, 5.4, 5.5, 6.3, 6.4
 */

// --- Hoisted mocks ---

vi.mock('@/api/client', () => ({
  default: {
    get: vi.fn(),
    post: vi.fn(),
  },
}))

import apiClient from '@/api/client'
import { KioskPage } from '../KioskPage'

const mockGet = vi.mocked(apiClient.get)
const mockPost = vi.mocked(apiClient.post)

/* ── Mock data ── */

const ORG_SETTINGS = {
  org_name: 'Ace Motors',
  logo_url: 'https://example.com/logo.png',
}

const CHECK_IN_RESPONSE = {
  customer_first_name: 'Jane',
  is_new_customer: true,
  vehicle_linked: false,
}

/* ── Helpers ── */

function setupDefaultMocks() {
  mockGet.mockImplementation((url: string) => {
    if (typeof url === 'string' && url.includes('/org/settings')) {
      return Promise.resolve({ data: ORG_SETTINGS })
    }
    return Promise.resolve({ data: {} })
  })
  mockPost.mockImplementation(() =>
    Promise.resolve({ data: CHECK_IN_RESPONSE }),
  )
}

/** Fill the check-in form with valid data and return the user instance. */
async function fillForm(user: ReturnType<typeof userEvent.setup>) {
  await user.type(screen.getByLabelText(/first name/i), 'Jane')
  await user.type(screen.getByLabelText(/last name/i), 'Doe')
  await user.type(screen.getByLabelText(/phone/i), '0211234567')
}

/* ── Tests ── */

describe('KioskPage — Unit Tests', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    vi.useFakeTimers({ shouldAdvanceTime: true })
    setupDefaultMocks()
  })

  afterEach(() => {
    vi.useRealTimers()
  })

  // --- Welcome screen ---

  it('renders org name and logo on the welcome screen', async () => {
    render(<KioskPage />)

    await waitFor(() => {
      expect(screen.getByText('Ace Motors')).toBeInTheDocument()
    })

    expect(screen.getByText('Welcome to Ace Motors')).toBeInTheDocument()

    const logo = screen.getByAltText('Ace Motors logo')
    expect(logo).toBeInTheDocument()
    expect(logo).toHaveAttribute('src', 'https://example.com/logo.png')
  })

  it('Check In button navigates to the form', async () => {
    vi.useRealTimers()
    const user = userEvent.setup()
    render(<KioskPage />)

    await waitFor(() => {
      expect(screen.getByText('Welcome to Ace Motors')).toBeInTheDocument()
    })

    await user.click(screen.getByRole('button', { name: /check in/i }))

    // Form heading should appear
    expect(screen.getByRole('heading', { name: /check in/i })).toBeInTheDocument()
    // Required form fields should be visible
    expect(screen.getByLabelText(/first name/i)).toBeInTheDocument()
    expect(screen.getByLabelText(/last name/i)).toBeInTheDocument()
    expect(screen.getByLabelText(/phone/i)).toBeInTheDocument()
  })

  // --- Form validation ---

  it('validates required fields before submission', async () => {
    vi.useRealTimers()
    const user = userEvent.setup()
    render(<KioskPage />)

    await waitFor(() => {
      expect(screen.getByText('Welcome to Ace Motors')).toBeInTheDocument()
    })

    await user.click(screen.getByRole('button', { name: /check in/i }))

    // Submit with empty fields
    await user.click(screen.getByRole('button', { name: /submit/i }))

    // Validation errors should appear
    expect(screen.getByText('First name is required')).toBeInTheDocument()
    expect(screen.getByText('Last name is required')).toBeInTheDocument()
    expect(screen.getByText('Phone number is required')).toBeInTheDocument()

    // API should NOT have been called
    expect(mockPost).not.toHaveBeenCalled()
  })

  // --- Submit sends POST ---

  it('submit sends POST to /kiosk/check-in', async () => {
    vi.useRealTimers()
    const user = userEvent.setup()
    render(<KioskPage />)

    await waitFor(() => {
      expect(screen.getByText('Welcome to Ace Motors')).toBeInTheDocument()
    })

    await user.click(screen.getByRole('button', { name: /check in/i }))
    await fillForm(user)
    await user.click(screen.getByRole('button', { name: /submit/i }))

    await waitFor(() => {
      expect(mockPost).toHaveBeenCalledWith('/kiosk/check-in', {
        first_name: 'Jane',
        last_name: 'Doe',
        phone: '0211234567',
        email: null,
        vehicle_rego: null,
      })
    })
  })

  // --- Success screen ---

  it('success screen shows "Thanks [name]" message', async () => {
    vi.useRealTimers()
    const user = userEvent.setup()
    render(<KioskPage />)

    await waitFor(() => {
      expect(screen.getByText('Welcome to Ace Motors')).toBeInTheDocument()
    })

    await user.click(screen.getByRole('button', { name: /check in/i }))
    await fillForm(user)
    await user.click(screen.getByRole('button', { name: /submit/i }))

    await waitFor(() => {
      expect(
        screen.getByText(/thanks jane, we'll be with you shortly/i),
      ).toBeInTheDocument()
    })
  })

  // --- Success screen auto-reset ---

  it('success screen auto-resets after 10 seconds', async () => {
    // Use fake timers with shouldAdvanceTime so promises resolve
    const user = userEvent.setup({ advanceTimers: vi.advanceTimersByTime })
    render(<KioskPage />)

    await waitFor(() => {
      expect(screen.getByText('Welcome to Ace Motors')).toBeInTheDocument()
    })

    await user.click(screen.getByRole('button', { name: /check in/i }))
    await fillForm(user)
    await user.click(screen.getByRole('button', { name: /submit/i }))

    await waitFor(() => {
      expect(
        screen.getByText(/thanks jane/i),
      ).toBeInTheDocument()
    })

    // Advance 11 seconds — should auto-reset to welcome
    await act(async () => {
      vi.advanceTimersByTime(11_000)
    })

    await waitFor(() => {
      expect(screen.getByText('Welcome to Ace Motors')).toBeInTheDocument()
    })
  })

  // --- Done button ---

  it('Done button resets to welcome immediately', async () => {
    vi.useRealTimers()
    const user = userEvent.setup()
    render(<KioskPage />)

    await waitFor(() => {
      expect(screen.getByText('Welcome to Ace Motors')).toBeInTheDocument()
    })

    await user.click(screen.getByRole('button', { name: /check in/i }))
    await fillForm(user)
    await user.click(screen.getByRole('button', { name: /submit/i }))

    await waitFor(() => {
      expect(screen.getByText(/thanks jane/i)).toBeInTheDocument()
    })

    await user.click(screen.getByRole('button', { name: /done/i }))

    await waitFor(() => {
      expect(screen.getByText('Welcome to Ace Motors')).toBeInTheDocument()
    })
  })

  // --- Error screen preserves form data ---

  it('error screen preserves form data on "Try Again"', async () => {
    vi.useRealTimers()
    const user = userEvent.setup()

    // Make the POST fail
    mockPost.mockRejectedValueOnce(new Error('Network error'))

    render(<KioskPage />)

    await waitFor(() => {
      expect(screen.getByText('Welcome to Ace Motors')).toBeInTheDocument()
    })

    await user.click(screen.getByRole('button', { name: /check in/i }))
    await fillForm(user)
    await user.click(screen.getByRole('button', { name: /submit/i }))

    // Error screen should appear
    await waitFor(() => {
      expect(screen.getByText('Something went wrong')).toBeInTheDocument()
    })

    // Click "Try Again"
    await user.click(screen.getByRole('button', { name: /try again/i }))

    // Form should reappear with preserved data
    await waitFor(() => {
      expect(screen.getByLabelText(/first name/i)).toHaveValue('Jane')
    })
    expect(screen.getByLabelText(/last name/i)).toHaveValue('Doe')
    expect(screen.getByLabelText(/phone/i)).toHaveValue('0211234567')
  })

  // --- Back button ---

  it('Back button returns to welcome from form', async () => {
    vi.useRealTimers()
    const user = userEvent.setup()
    render(<KioskPage />)

    await waitFor(() => {
      expect(screen.getByText('Welcome to Ace Motors')).toBeInTheDocument()
    })

    await user.click(screen.getByRole('button', { name: /check in/i }))

    // Should be on the form
    expect(screen.getByLabelText(/first name/i)).toBeInTheDocument()

    await user.click(screen.getByRole('button', { name: /back/i }))

    // Should be back on welcome
    await waitFor(() => {
      expect(screen.getByText('Welcome to Ace Motors')).toBeInTheDocument()
    })
  })

  // --- No localStorage/sessionStorage writes ---

  it('does not write to localStorage or sessionStorage during check-in flow', async () => {
    vi.useRealTimers()
    const user = userEvent.setup()

    const localSetSpy = vi.spyOn(Storage.prototype, 'setItem')

    render(<KioskPage />)

    await waitFor(() => {
      expect(screen.getByText('Welcome to Ace Motors')).toBeInTheDocument()
    })

    // Navigate to form
    await user.click(screen.getByRole('button', { name: /check in/i }))

    // Fill and submit
    await fillForm(user)
    await user.click(screen.getByRole('button', { name: /submit/i }))

    // Wait for success
    await waitFor(() => {
      expect(screen.getByText(/thanks jane/i)).toBeInTheDocument()
    })

    // Click Done to reset
    await user.click(screen.getByRole('button', { name: /done/i }))

    await waitFor(() => {
      expect(screen.getByText('Welcome to Ace Motors')).toBeInTheDocument()
    })

    // Verify no storage writes occurred
    expect(localSetSpy).not.toHaveBeenCalled()

    localSetSpy.mockRestore()
  })
})
