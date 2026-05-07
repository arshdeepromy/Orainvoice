import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, it, expect, vi, beforeEach } from 'vitest'

/**
 * Unit tests for KioskVehicleSummary component.
 * Validates: Requirements 4.6, 4.7, 4.8, 5.1
 */

import { KioskVehicleSummary } from '../KioskVehicleSummary'
import type { VehicleLookupResult } from '../types'

const FULL_VEHICLE: VehicleLookupResult = {
  id: 'vehicle-uuid-1',
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

const PARTIAL_VEHICLE: VehicleLookupResult = {
  id: 'vehicle-uuid-2',
  rego: 'XYZ789',
  make: 'Honda',
  model: null,
  body_type: null,
  year: null,
  colour: null,
  wof_expiry: null,
  rego_expiry: null,
  odometer: null,
  source: 'carjam',
}

describe('KioskVehicleSummary — Unit Tests', () => {
  const defaultProps = {
    vehicle: FULL_VEHICLE,
    vehicleCount: 0,
    onConfirm: vi.fn(),
    onAddAnother: vi.fn(),
    onBack: vi.fn(),
  }

  beforeEach(() => {
    vi.clearAllMocks()
  })

  // --- Renders vehicle details correctly (Requirements 4.1–4.5) ---

  it('renders vehicle rego prominently', () => {
    render(<KioskVehicleSummary {...defaultProps} />)

    expect(screen.getByText('ABC123')).toBeInTheDocument()
  })

  it('renders body_type when present', () => {
    render(<KioskVehicleSummary {...defaultProps} />)

    expect(screen.getByText('Sedan')).toBeInTheDocument()
  })

  it('renders make and model when present', () => {
    render(<KioskVehicleSummary {...defaultProps} />)

    expect(screen.getByText('Toyota Corolla')).toBeInTheDocument()
  })

  it('renders wof_expiry when present', () => {
    render(<KioskVehicleSummary {...defaultProps} />)

    expect(screen.getByText('2025-06-01')).toBeInTheDocument()
  })

  it('renders rego_expiry when present', () => {
    render(<KioskVehicleSummary {...defaultProps} />)

    expect(screen.getByText('2025-12-01')).toBeInTheDocument()
  })

  it('renders last recorded odometer when present', () => {
    render(<KioskVehicleSummary {...defaultProps} />)

    // odometer is formatted with toLocaleString() + " km"
    expect(screen.getByText(/45,000 km/)).toBeInTheDocument()
  })

  // --- Does not render null fields ---

  it('does not render body_type row when null', () => {
    render(<KioskVehicleSummary {...defaultProps} vehicle={PARTIAL_VEHICLE} />)

    expect(screen.queryByText('Type')).not.toBeInTheDocument()
  })

  it('does not render wof_expiry row when null', () => {
    render(<KioskVehicleSummary {...defaultProps} vehicle={PARTIAL_VEHICLE} />)

    expect(screen.queryByText('WOF Expiry')).not.toBeInTheDocument()
  })

  it('does not render rego_expiry row when null', () => {
    render(<KioskVehicleSummary {...defaultProps} vehicle={PARTIAL_VEHICLE} />)

    expect(screen.queryByText('Rego Expiry')).not.toBeInTheDocument()
  })

  it('does not render odometer row when null', () => {
    render(<KioskVehicleSummary {...defaultProps} vehicle={PARTIAL_VEHICLE} />)

    expect(screen.queryByText('Last Recorded KM')).not.toBeInTheDocument()
  })

  // --- Odometer input accepts numeric values (Requirement 4.6) ---

  it('renders odometer input field', () => {
    render(<KioskVehicleSummary {...defaultProps} />)

    const input = screen.getByLabelText(/current kilometers/i)
    expect(input).toBeInTheDocument()
    expect(input).toHaveAttribute('type', 'number')
  })

  it('odometer input accepts numeric values', async () => {
    const user = userEvent.setup()
    render(<KioskVehicleSummary {...defaultProps} />)

    const input = screen.getByLabelText(/current kilometers/i)
    await user.type(input, '85000')

    expect(input).toHaveValue(85000)
  })

  // --- Confirm button calls onConfirm with entered odometer value (Requirement 4.7) ---

  it('Confirm button calls onConfirm with entered odometer value', async () => {
    const user = userEvent.setup()
    render(<KioskVehicleSummary {...defaultProps} />)

    const input = screen.getByLabelText(/current kilometers/i)
    await user.type(input, '92000')
    await user.click(screen.getByRole('button', { name: /^confirm$/i }))

    expect(defaultProps.onConfirm).toHaveBeenCalledWith(92000)
  })

  it('Confirm button calls onConfirm with null when odometer is empty', async () => {
    const user = userEvent.setup()
    render(<KioskVehicleSummary {...defaultProps} />)

    await user.click(screen.getByRole('button', { name: /^confirm$/i }))

    expect(defaultProps.onConfirm).toHaveBeenCalledWith(null)
  })

  // --- Back button calls onBack (Requirement 4.8) ---

  it('Back button calls onBack when clicked', async () => {
    const user = userEvent.setup()
    render(<KioskVehicleSummary {...defaultProps} />)

    await user.click(screen.getByRole('button', { name: /back/i }))

    expect(defaultProps.onBack).toHaveBeenCalledTimes(1)
  })

  // --- Add Another Vehicle button calls onAddAnother (Requirement 5.1) ---

  it('Add Another Vehicle button calls onConfirm then onAddAnother', async () => {
    const user = userEvent.setup()
    render(<KioskVehicleSummary {...defaultProps} />)

    const input = screen.getByLabelText(/current kilometers/i)
    await user.type(input, '50000')
    await user.click(screen.getByRole('button', { name: /add another vehicle/i }))

    expect(defaultProps.onConfirm).toHaveBeenCalledWith(50000)
    expect(defaultProps.onAddAnother).toHaveBeenCalledTimes(1)
  })

  it('Add Another Vehicle button calls onConfirm with null when odometer empty', async () => {
    const user = userEvent.setup()
    render(<KioskVehicleSummary {...defaultProps} />)

    await user.click(screen.getByRole('button', { name: /add another vehicle/i }))

    expect(defaultProps.onConfirm).toHaveBeenCalledWith(null)
    expect(defaultProps.onAddAnother).toHaveBeenCalledTimes(1)
  })

  // --- Vehicle count badge (Requirement 5.4) ---

  it('shows vehicle count badge when vehicleCount > 0', () => {
    render(<KioskVehicleSummary {...defaultProps} vehicleCount={3} />)

    expect(screen.getByText('3 vehicles added')).toBeInTheDocument()
  })

  it('does not show vehicle count badge when vehicleCount is 0', () => {
    render(<KioskVehicleSummary {...defaultProps} vehicleCount={0} />)

    expect(screen.queryByText(/vehicle.*added/i)).not.toBeInTheDocument()
  })

  it('shows singular "vehicle" when vehicleCount is 1', () => {
    render(<KioskVehicleSummary {...defaultProps} vehicleCount={1} />)

    expect(screen.getByText('1 vehicle added')).toBeInTheDocument()
  })
})
