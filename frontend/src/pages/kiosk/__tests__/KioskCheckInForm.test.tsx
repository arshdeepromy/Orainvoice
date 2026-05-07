import { render, screen, act, fireEvent } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { useState } from 'react'

/**
 * Unit tests for KioskCheckInForm auto-fill feature.
 * Validates: Requirements 9.1, 9.2, 9.3, 9.4, 9.8
 */

// --- Hoisted mocks ---

vi.mock('../api', () => ({
  lookupCustomer: vi.fn(),
}))

vi.mock('@/api/client', () => ({
  default: {
    get: vi.fn(),
    post: vi.fn(),
  },
}))

import { lookupCustomer } from '../api'
import { KioskCheckInForm } from '../KioskCheckInForm'
import type { KioskFormData } from '../types'

const mockLookupCustomer = vi.mocked(lookupCustomer)

/* ── Mock data ── */

const SINGLE_MATCH = {
  items: [
    {
      id: 'cust-001',
      first_name: 'Jane',
      last_name: 'Smith',
      phone: '0211234567',
      email: 'jane@example.com',
    },
  ],
  total: 1,
}

const MULTIPLE_MATCHES = {
  items: [
    {
      id: 'cust-001',
      first_name: 'Jane',
      last_name: 'Smith',
      phone: '0211234567',
      email: 'jane@example.com',
    },
    {
      id: 'cust-002',
      first_name: 'John',
      last_name: 'Smith',
      phone: '0211234567',
      email: 'john@example.com',
    },
  ],
  total: 2,
}

const NO_MATCHES = { items: [], total: 0 }

/* ── Wrapper component to manage controlled form state ── */

function FormWrapper({
  initialData,
  ...props
}: {
  initialData?: Partial<KioskFormData>
  onSuccess?: () => void
  onError?: () => void
  onBack?: () => void
}) {
  const [formData, setFormData] = useState<KioskFormData>({
    first_name: '',
    last_name: '',
    phone: '',
    email: '',
    ...initialData,
  })

  return (
    <KioskCheckInForm
      formData={formData}
      onFormDataChange={setFormData}
      onSuccess={props.onSuccess ?? vi.fn()}
      onError={props.onError ?? vi.fn()}
      onBack={props.onBack ?? vi.fn()}
    />
  )
}

/** Helper: simulate typing a value into an input using fireEvent (works with fake timers). */
function typeValue(input: HTMLElement, value: string) {
  fireEvent.change(input, { target: { value } })
}

/** Helper: flush microtask queue so resolved promises settle. */
function flushMicrotasks() {
  return new Promise<void>((resolve) => resolve())
}

/** Helper: advance timers and flush all pending promises. */
async function advanceTimersAndFlush(ms: number) {
  await act(async () => {
    vi.advanceTimersByTime(ms)
    await flushMicrotasks()
    await flushMicrotasks()
  })
}

/* ── Tests ── */

describe('KioskCheckInForm — Auto-fill Unit Tests', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    vi.useFakeTimers()
  })

  afterEach(() => {
    vi.useRealTimers()
  })

  // --- Debounced lookup triggers after 500ms (Requirement 9.1) ---

  it('triggers customer lookup after 500ms of no typing in phone field', async () => {
    mockLookupCustomer.mockResolvedValue(NO_MATCHES)

    render(<FormWrapper />)

    const phoneInput = screen.getByLabelText(/phone/i)
    typeValue(phoneInput, '0211234567')

    await advanceTimersAndFlush(500)

    expect(mockLookupCustomer).toHaveBeenCalledWith(
      expect.objectContaining({ phone: '0211234567' }),
      expect.any(AbortSignal),
    )
  })

  it('does NOT trigger lookup before 500ms (debounce works)', async () => {
    mockLookupCustomer.mockResolvedValue(NO_MATCHES)

    render(<FormWrapper />)

    const phoneInput = screen.getByLabelText(/phone/i)
    typeValue(phoneInput, '0211234567')

    await advanceTimersAndFlush(400)

    expect(mockLookupCustomer).not.toHaveBeenCalled()
  })

  it('resets debounce timer on each keystroke', async () => {
    mockLookupCustomer.mockResolvedValue(NO_MATCHES)

    render(<FormWrapper />)

    const phoneInput = screen.getByLabelText(/phone/i)

    // Type first value
    typeValue(phoneInput, '021123')

    // Advance 400ms (not enough to trigger)
    await advanceTimersAndFlush(400)

    // Type more — resets the timer
    typeValue(phoneInput, '0211234567')

    // Advance another 400ms — still not enough from last change
    await advanceTimersAndFlush(400)

    expect(mockLookupCustomer).not.toHaveBeenCalled()

    // Advance remaining 100ms to hit 500ms from last change
    await advanceTimersAndFlush(100)

    expect(mockLookupCustomer).toHaveBeenCalledTimes(1)
  })

  // --- Auto-fill banner appears on single match (Requirement 9.2) ---

  it('shows auto-fill banner when single match found', async () => {
    mockLookupCustomer.mockResolvedValue(SINGLE_MATCH)

    render(<FormWrapper />)

    const phoneInput = screen.getByLabelText(/phone/i)
    typeValue(phoneInput, '0211234567')

    await advanceTimersAndFlush(500)

    expect(
      screen.getByText(/we found your details — tap to auto-fill/i),
    ).toBeInTheDocument()

    // Should show the customer name
    expect(screen.getByText(/Jane Smith/)).toBeInTheDocument()
  })

  // --- Multiple matches show selectable list (Requirement 9.8) ---

  it('shows selectable list when multiple matches found', async () => {
    mockLookupCustomer.mockResolvedValue(MULTIPLE_MATCHES)

    render(<FormWrapper />)

    const phoneInput = screen.getByLabelText(/phone/i)
    typeValue(phoneInput, '0211234567')

    await advanceTimersAndFlush(500)

    expect(screen.getByRole('list', { name: /customer matches/i })).toBeInTheDocument()

    // Both customers should be listed
    expect(screen.getByText(/Jane Smith/)).toBeInTheDocument()
    expect(screen.getByText(/John Smith/)).toBeInTheDocument()
  })

  // --- Form fields populated correctly on auto-fill (Requirement 9.3) ---

  it('populates form fields when auto-fill banner is tapped (single match)', async () => {
    mockLookupCustomer.mockResolvedValue(SINGLE_MATCH)

    render(<FormWrapper />)

    const phoneInput = screen.getByLabelText(/phone/i)
    typeValue(phoneInput, '0211234567')

    await advanceTimersAndFlush(500)

    expect(
      screen.getByText(/we found your details — tap to auto-fill/i),
    ).toBeInTheDocument()

    // Tap the auto-fill button
    const autoFillBtn = screen.getByRole('button', { name: /auto-fill customer details/i })
    fireEvent.click(autoFillBtn)

    // Verify all fields are populated
    expect(screen.getByLabelText(/first name/i)).toHaveValue('Jane')
    expect(screen.getByLabelText(/last name/i)).toHaveValue('Smith')
    expect(screen.getByLabelText(/phone/i)).toHaveValue('0211234567')
    expect(screen.getByLabelText(/email/i)).toHaveValue('jane@example.com')
  })

  it('populates form fields when selecting from multiple matches', async () => {
    mockLookupCustomer.mockResolvedValue(MULTIPLE_MATCHES)

    render(<FormWrapper />)

    const phoneInput = screen.getByLabelText(/phone/i)
    typeValue(phoneInput, '0211234567')

    await advanceTimersAndFlush(500)

    expect(screen.getByText(/John Smith/)).toBeInTheDocument()

    // Click the second match (John Smith)
    const buttons = screen.getAllByRole('button')
    const johnButton = buttons.find((btn) => btn.textContent?.includes('John Smith'))
    expect(johnButton).toBeDefined()
    fireEvent.click(johnButton!)

    // Verify fields populated with John's data
    expect(screen.getByLabelText(/first name/i)).toHaveValue('John')
    expect(screen.getByLabelText(/last name/i)).toHaveValue('Smith')
    expect(screen.getByLabelText(/phone/i)).toHaveValue('0211234567')
    expect(screen.getByLabelText(/email/i)).toHaveValue('john@example.com')
  })

  // --- Auto-fill banner disappears after selection ---

  it('auto-fill banner disappears after selection', async () => {
    mockLookupCustomer.mockResolvedValue(SINGLE_MATCH)

    render(<FormWrapper />)

    const phoneInput = screen.getByLabelText(/phone/i)
    typeValue(phoneInput, '0211234567')

    await advanceTimersAndFlush(500)

    expect(
      screen.getByText(/we found your details — tap to auto-fill/i),
    ).toBeInTheDocument()

    // Tap auto-fill
    const autoFillBtn = screen.getByRole('button', { name: /auto-fill customer details/i })
    fireEvent.click(autoFillBtn)

    // Banner should disappear
    expect(
      screen.queryByText(/we found your details — tap to auto-fill/i),
    ).not.toBeInTheDocument()
  })

  // --- Lookup failures are silently ignored (Requirement 9.8) ---

  it('silently ignores lookup failures (no error shown)', async () => {
    mockLookupCustomer.mockRejectedValue(new Error('Network error'))

    render(<FormWrapper />)

    const phoneInput = screen.getByLabelText(/phone/i)
    typeValue(phoneInput, '0211234567')

    await advanceTimersAndFlush(500)

    // No error message should appear
    expect(screen.queryByText(/error/i)).not.toBeInTheDocument()
    expect(screen.queryByRole('alert')).not.toBeInTheDocument()

    // Form should still be functional
    expect(screen.getByLabelText(/phone/i)).toHaveValue('0211234567')
  })

  // --- Existing validation rules preserved (Requirement 8.2) ---

  it('shows validation error when first_name is empty on submit', async () => {
    vi.useRealTimers()
    const user = userEvent.setup()
    render(<FormWrapper />)

    await user.click(screen.getByRole('button', { name: /submit/i }))

    expect(screen.getByText('First name is required')).toBeInTheDocument()
  })

  it('shows validation error when last_name is empty on submit', async () => {
    vi.useRealTimers()
    const user = userEvent.setup()
    render(<FormWrapper initialData={{ first_name: 'Jane' }} />)

    await user.click(screen.getByRole('button', { name: /submit/i }))

    expect(screen.getByText('Last name is required')).toBeInTheDocument()
  })

  it('shows validation error when phone is empty on submit', async () => {
    vi.useRealTimers()
    const user = userEvent.setup()
    render(
      <FormWrapper initialData={{ first_name: 'Jane', last_name: 'Smith' }} />,
    )

    await user.click(screen.getByRole('button', { name: /submit/i }))

    expect(screen.getByText('Phone number is required')).toBeInTheDocument()
  })

  it('shows validation error for invalid email format', async () => {
    vi.useRealTimers()
    const user = userEvent.setup()
    render(
      <FormWrapper
        initialData={{
          first_name: 'Jane',
          last_name: 'Smith',
          phone: '0211234567',
          email: 'not-an-email',
        }}
      />,
    )

    await user.click(screen.getByRole('button', { name: /submit/i }))

    expect(screen.getByText('Please enter a valid email address')).toBeInTheDocument()
  })

  // --- Does not trigger lookup for short phone numbers ---

  it('does not trigger lookup when phone has fewer than 7 digits', async () => {
    mockLookupCustomer.mockResolvedValue(NO_MATCHES)

    render(<FormWrapper />)

    const phoneInput = screen.getByLabelText(/phone/i)
    typeValue(phoneInput, '02112')

    await advanceTimersAndFlush(500)

    expect(mockLookupCustomer).not.toHaveBeenCalled()
  })
})
