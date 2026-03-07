import { render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, it, expect, vi, beforeEach } from 'vitest'

/**
 * Validates: Requirements 14.1-14.7, 15.1-15.4
 */

/* Mock react-router-dom */
vi.mock('react-router-dom', () => ({
  useParams: () => ({ id: 'veh-1' }),
}))

vi.mock('@/api/client', () => {
  const mockGet = vi.fn()
  const mockPost = vi.fn()
  return {
    default: { get: mockGet, post: mockPost },
  }
})

import apiClient from '@/api/client'
import VehicleList from '../pages/vehicles/VehicleList'
import VehicleProfile from '../pages/vehicles/VehicleProfile'


const mockVehicleProfile = {
  id: 'veh-1',
  rego: 'ABC123',
  make: 'Toyota',
  model: 'Corolla',
  year: 2020,
  colour: 'White',
  body_type: 'Sedan',
  fuel_type: 'Petrol',
  engine_size: '1.8L',
  seats: 5,
  odometer: 45000,
  last_pulled_at: '2025-01-15T10:00:00Z',
  wof_expiry: { date: '2025-12-01', days_remaining: 120, indicator: 'green' },
  rego_expiry: { date: '2025-04-15', days_remaining: 45, indicator: 'amber' },
  linked_customers: [
    { id: 'cust-1', first_name: 'John', last_name: 'Smith', email: 'john@example.com', phone: '021 123 4567' },
    { id: 'cust-2', first_name: 'Jane', last_name: 'Doe', email: null, phone: '022 987 6543' },
  ],
  service_history: [
    {
      invoice_id: 'inv-1', invoice_number: 'INV-001', status: 'paid',
      issue_date: '2024-12-01', total: '230.00', odometer: 42000,
      customer_name: 'John Smith', description: 'Full service',
    },
    {
      invoice_id: 'inv-2', invoice_number: 'INV-005', status: 'issued',
      issue_date: '2025-01-10', total: '150.00', odometer: 45000,
      customer_name: 'Jane Doe', description: 'WOF check',
    },
  ],
}

/* ------------------------------------------------------------------ */
/*  VehicleList tests                                                  */
/* ------------------------------------------------------------------ */

describe('VehicleList', () => {
  beforeEach(() => { vi.clearAllMocks() })

  it('renders heading and manual entry button', () => {
    render(<VehicleList />)
    expect(screen.getByRole('heading', { name: 'Vehicles' })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: '+ Manual Entry' })).toBeInTheDocument()
  })

  it('has search input for rego lookup (Req 14.1)', () => {
    render(<VehicleList />)
    expect(screen.getByLabelText('Search vehicles by registration number')).toBeInTheDocument()
  })

  it('shows empty state when no search entered', () => {
    render(<VehicleList />)
    expect(screen.getByText(/Enter a registration number/)).toBeInTheDocument()
  })

  it('opens manual entry modal (Req 14.6)', async () => {
    render(<VehicleList />)
    const user = userEvent.setup()
    await user.click(screen.getByRole('button', { name: '+ Manual Entry' }))
    expect(screen.getByRole('dialog')).toBeInTheDocument()
    expect(screen.getByText('Manual Vehicle Entry')).toBeInTheDocument()
    // Check form fields exist
    expect(screen.getByLabelText(/Registration number/)).toBeInTheDocument()
    expect(screen.getByLabelText('Make')).toBeInTheDocument()
    expect(screen.getByLabelText('Model')).toBeInTheDocument()
    expect(screen.getByLabelText('Year')).toBeInTheDocument()
    expect(screen.getByLabelText('Colour')).toBeInTheDocument()
  })

  it('manual entry requires rego (Req 14.7)', async () => {
    render(<VehicleList />)
    const user = userEvent.setup()
    await user.click(screen.getByRole('button', { name: '+ Manual Entry' }))
    await user.click(screen.getByRole('button', { name: 'Create Vehicle' }))
    expect(screen.getByText('Registration number is required.')).toBeInTheDocument()
  })
})

/* ------------------------------------------------------------------ */
/*  VehicleProfile tests                                               */
/* ------------------------------------------------------------------ */

describe('VehicleProfile', () => {
  beforeEach(() => { vi.clearAllMocks() })

  it('shows loading spinner initially', () => {
    ;(apiClient.get as ReturnType<typeof vi.fn>).mockReturnValue(new Promise(() => {}))
    render(<VehicleProfile />)
    expect(screen.getByRole('status', { name: 'Loading vehicle' })).toBeInTheDocument()
  })

  it('displays vehicle title and rego (Req 15.3)', async () => {
    ;(apiClient.get as ReturnType<typeof vi.fn>).mockResolvedValue({ data: mockVehicleProfile })
    render(<VehicleProfile />)
    expect(await screen.findByText('2020 Toyota Corolla')).toBeInTheDocument()
    expect(screen.getByText('ABC123')).toBeInTheDocument()
  })

  it('shows WOF expiry indicator with green badge (Req 15.4)', async () => {
    ;(apiClient.get as ReturnType<typeof vi.fn>).mockResolvedValue({ data: mockVehicleProfile })
    render(<VehicleProfile />)
    await screen.findByText('2020 Toyota Corolla')
    expect(screen.getByText('WOF Expiry')).toBeInTheDocument()
    // Green indicator = OK badge
    const wofSection = screen.getByText('WOF Expiry').closest('div')!
    expect(within(wofSection).getByText('OK')).toBeInTheDocument()
  })

  it('shows rego expiry indicator with amber badge (Req 15.4)', async () => {
    ;(apiClient.get as ReturnType<typeof vi.fn>).mockResolvedValue({ data: mockVehicleProfile })
    render(<VehicleProfile />)
    await screen.findByText('2020 Toyota Corolla')
    expect(screen.getByText('Registration Expiry')).toBeInTheDocument()
    const regoSection = screen.getByText('Registration Expiry').closest('div')!
    expect(within(regoSection).getByText('Due Soon')).toBeInTheDocument()
  })

  it('displays vehicle details section (Req 15.3)', async () => {
    ;(apiClient.get as ReturnType<typeof vi.fn>).mockResolvedValue({ data: mockVehicleProfile })
    render(<VehicleProfile />)
    await screen.findByText('2020 Toyota Corolla')
    expect(screen.getByText('Vehicle Details')).toBeInTheDocument()
    expect(screen.getByText('Sedan')).toBeInTheDocument()
    expect(screen.getByText('Petrol')).toBeInTheDocument()
    expect(screen.getByText('1.8L')).toBeInTheDocument()
  })

  it('has refresh from Carjam button (Req 14.5)', async () => {
    ;(apiClient.get as ReturnType<typeof vi.fn>).mockResolvedValue({ data: mockVehicleProfile })
    render(<VehicleProfile />)
    await screen.findByText('2020 Toyota Corolla')
    expect(screen.getByRole('button', { name: /Refresh from Carjam/ })).toBeInTheDocument()
  })

  it('shows linked customers in customers tab (Req 15.1, 15.2)', async () => {
    ;(apiClient.get as ReturnType<typeof vi.fn>).mockResolvedValue({ data: mockVehicleProfile })
    render(<VehicleProfile />)
    await screen.findByText('2020 Toyota Corolla')
    const user = userEvent.setup()
    await user.click(screen.getByRole('tab', { name: /Customers/ }))
    expect(screen.getByText('John Smith')).toBeInTheDocument()
    expect(screen.getByText('Jane Doe')).toBeInTheDocument()
    expect(screen.getByText('john@example.com')).toBeInTheDocument()
  })

  it('shows service history with invoice details (Req 15.3)', async () => {
    ;(apiClient.get as ReturnType<typeof vi.fn>).mockResolvedValue({ data: mockVehicleProfile })
    render(<VehicleProfile />)
    await screen.findByText('2020 Toyota Corolla')
    // Service history is the default tab
    expect(screen.getByText('INV-001')).toBeInTheDocument()
    expect(screen.getByText('INV-005')).toBeInTheDocument()
  })

  it('shows odometer history tab (Req 15.3)', async () => {
    ;(apiClient.get as ReturnType<typeof vi.fn>).mockResolvedValue({ data: mockVehicleProfile })
    render(<VehicleProfile />)
    await screen.findByText('2020 Toyota Corolla')
    const user = userEvent.setup()
    await user.click(screen.getByRole('tab', { name: /Odometer/ }))
    expect(screen.getByText('42,000 km')).toBeInTheDocument()
    expect(screen.getAllByText('45,000 km').length).toBeGreaterThanOrEqual(1)
  })

  it('shows red indicator for expired WOF (Req 15.4)', async () => {
    const expiredProfile = {
      ...mockVehicleProfile,
      wof_expiry: { date: '2024-12-01', days_remaining: -30, indicator: 'red' },
    }
    ;(apiClient.get as ReturnType<typeof vi.fn>).mockResolvedValue({ data: expiredProfile })
    render(<VehicleProfile />)
    await screen.findByText('2020 Toyota Corolla')
    const wofSection = screen.getByText('WOF Expiry').closest('div')!
    expect(within(wofSection).getByText('Expired / Due')).toBeInTheDocument()
    expect(within(wofSection).getByText('30d overdue')).toBeInTheDocument()
  })

  it('shows error state when profile fails to load', async () => {
    ;(apiClient.get as ReturnType<typeof vi.fn>).mockRejectedValue(new Error('Network error'))
    render(<VehicleProfile />)
    expect(await screen.findByText('Failed to load vehicle profile.')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: /Back to Vehicles/ })).toBeInTheDocument()
  })

  it('calls refresh endpoint when refresh button clicked (Req 14.5)', async () => {
    ;(apiClient.get as ReturnType<typeof vi.fn>).mockResolvedValue({ data: mockVehicleProfile })
    ;(apiClient.post as ReturnType<typeof vi.fn>).mockResolvedValue({ data: {} })
    render(<VehicleProfile />)
    await screen.findByText('2020 Toyota Corolla')
    const user = userEvent.setup()
    await user.click(screen.getByRole('button', { name: /Refresh from Carjam/ }))
    expect(apiClient.post).toHaveBeenCalledWith('/vehicles/veh-1/refresh')
  })
})
