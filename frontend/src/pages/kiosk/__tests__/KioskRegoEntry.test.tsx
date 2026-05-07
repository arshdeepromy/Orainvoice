import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, it, expect, vi, beforeEach } from 'vitest'

/**
 * Unit tests for KioskRegoEntry component.
 * Validates: Requirements 2.1, 2.2, 2.3, 2.5, 2.6
 */

// Mock the API module
vi.mock('../api', () => ({
  lookupVehicle: vi.fn(),
}))

import { lookupVehicle } from '../api'
import { KioskRegoEntry } from '../KioskRegoEntry'

const mockLookupVehicle = vi.mocked(lookupVehicle)

const MOCK_VEHICLE_RESULT = {
  id: 'abc-123',
  rego: 'ABC123',
  make: 'Toyota',
  model: 'Corolla',
  body_type: 'Sedan',
  year: 2020,
  colour: 'White',
  wof_expiry: '2025-06-01',
  rego_expiry: '2025-12-01',
  odometer: 45000,
  source: 'cache',
}

describe('KioskRegoEntry — Unit Tests', () => {
  const defaultProps = {
    vehicleCount: 0,
    onVehicleFound: vi.fn(),
    onSkip: vi.fn(),
    onBack: vi.fn(),
  }

  beforeEach(() => {
    vi.clearAllMocks()
  })

  // --- Rendering with correct styles and touch targets (Requirement 2.1) ---

  it('renders input with min-h-[48px] class for touch target', () => {
    render(<KioskRegoEntry {...defaultProps} />)

    const input = screen.getByLabelText(/vehicle registration number/i)
    expect(input).toHaveClass('min-h-[48px]')
  })

  it('renders input with text-lg font size', () => {
    render(<KioskRegoEntry {...defaultProps} />)

    const input = screen.getByLabelText(/vehicle registration number/i)
    expect(input).toHaveClass('text-lg')
  })

  it('renders Confirm button with min-h-[48px] touch target', () => {
    render(<KioskRegoEntry {...defaultProps} />)

    const button = screen.getByRole('button', { name: /confirm/i })
    expect(button).toHaveClass('min-h-[48px]')
  })

  it('renders Skip button with min-h-[48px] touch target', () => {
    render(<KioskRegoEntry {...defaultProps} />)

    const button = screen.getByRole('button', { name: /skip/i })
    expect(button).toHaveClass('min-h-[48px]')
  })

  it('renders Back button with min-h-[48px] touch target', () => {
    render(<KioskRegoEntry {...defaultProps} />)

    const button = screen.getByRole('button', { name: /back/i })
    expect(button).toHaveClass('min-h-[48px]')
  })

  // --- Skip button behaviour (Requirement 2.3) ---

  it('Skip button calls onSkip when clicked', async () => {
    const user = userEvent.setup()
    render(<KioskRegoEntry {...defaultProps} />)

    await user.click(screen.getByRole('button', { name: /skip/i }))

    expect(defaultProps.onSkip).toHaveBeenCalledTimes(1)
  })

  // --- Back button behaviour (Requirement 2.6) ---

  it('Back button calls onBack when clicked', async () => {
    const user = userEvent.setup()
    render(<KioskRegoEntry {...defaultProps} />)

    await user.click(screen.getByRole('button', { name: /back/i }))

    expect(defaultProps.onBack).toHaveBeenCalledTimes(1)
  })

  // --- Confirm button triggers lookup (Requirement 2.2) ---

  it('Confirm button calls lookupVehicle with trimmed uppercase rego', async () => {
    const user = userEvent.setup()
    mockLookupVehicle.mockResolvedValueOnce(MOCK_VEHICLE_RESULT)

    render(<KioskRegoEntry {...defaultProps} />)

    const input = screen.getByLabelText(/vehicle registration number/i)
    await user.type(input, ' abc123 ')
    await user.click(screen.getByRole('button', { name: /confirm/i }))

    await waitFor(() => {
      expect(mockLookupVehicle).toHaveBeenCalledWith('ABC123', expect.any(AbortSignal))
    })
  })

  it('Confirm button calls onVehicleFound on successful lookup', async () => {
    const user = userEvent.setup()
    mockLookupVehicle.mockResolvedValueOnce(MOCK_VEHICLE_RESULT)

    render(<KioskRegoEntry {...defaultProps} />)

    const input = screen.getByLabelText(/vehicle registration number/i)
    await user.type(input, 'ABC123')
    await user.click(screen.getByRole('button', { name: /confirm/i }))

    await waitFor(() => {
      expect(defaultProps.onVehicleFound).toHaveBeenCalledWith(MOCK_VEHICLE_RESULT)
    })
  })

  // --- Empty validation message (Requirement 2.5) ---

  it('shows "Please enter a registration number" when Confirm tapped with empty input', async () => {
    const user = userEvent.setup()
    render(<KioskRegoEntry {...defaultProps} />)

    await user.click(screen.getByRole('button', { name: /confirm/i }))

    expect(screen.getByText('Please enter a registration number')).toBeInTheDocument()
    expect(mockLookupVehicle).not.toHaveBeenCalled()
  })

  it('validation error has role="alert" for accessibility', async () => {
    const user = userEvent.setup()
    render(<KioskRegoEntry {...defaultProps} />)

    await user.click(screen.getByRole('button', { name: /confirm/i }))

    expect(screen.getByRole('alert')).toHaveTextContent('Please enter a registration number')
  })

  // --- Loading state disables Confirm (Requirement 3.6 / 2.2) ---

  it('Confirm button is disabled and shows "Looking up…" during lookup', async () => {
    const user = userEvent.setup()
    // Never resolve — keeps loading state active
    mockLookupVehicle.mockReturnValueOnce(new Promise(() => {}))

    render(<KioskRegoEntry {...defaultProps} />)

    const input = screen.getByLabelText(/vehicle registration number/i)
    await user.type(input, 'ABC123')
    await user.click(screen.getByRole('button', { name: /confirm/i }))

    await waitFor(() => {
      const confirmBtn = screen.getByRole('button', { name: /looking up/i })
      expect(confirmBtn).toBeDisabled()
    })
  })

  it('Skip and Back buttons are disabled during loading', async () => {
    const user = userEvent.setup()
    mockLookupVehicle.mockReturnValueOnce(new Promise(() => {}))

    render(<KioskRegoEntry {...defaultProps} />)

    const input = screen.getByLabelText(/vehicle registration number/i)
    await user.type(input, 'ABC123')
    await user.click(screen.getByRole('button', { name: /confirm/i }))

    await waitFor(() => {
      expect(screen.getByRole('button', { name: /skip/i })).toBeDisabled()
      expect(screen.getByRole('button', { name: /back/i })).toBeDisabled()
    })
  })

  // --- Vehicle count badge ---

  it('shows vehicle count badge when vehicleCount > 0', () => {
    render(<KioskRegoEntry {...defaultProps} vehicleCount={2} />)

    expect(screen.getByText('2 vehicles added')).toBeInTheDocument()
  })

  it('does not show vehicle count badge when vehicleCount is 0', () => {
    render(<KioskRegoEntry {...defaultProps} vehicleCount={0} />)

    expect(screen.queryByText(/vehicle.*added/i)).not.toBeInTheDocument()
  })

  it('shows singular "vehicle" when vehicleCount is 1', () => {
    render(<KioskRegoEntry {...defaultProps} vehicleCount={1} />)

    expect(screen.getByText('1 vehicle added')).toBeInTheDocument()
  })
})
