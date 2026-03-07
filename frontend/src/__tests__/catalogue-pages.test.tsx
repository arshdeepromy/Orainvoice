import { render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, it, expect, vi, beforeEach } from 'vitest'

/**
 * Validates: Requirements 27.1-27.3, 28.1-28.3
 */

vi.mock('@/api/client', () => {
  const mockGet = vi.fn()
  const mockPost = vi.fn()
  const mockPut = vi.fn()
  return {
    default: { get: mockGet, post: mockPost, put: mockPut },
  }
})

import apiClient from '@/api/client'
import ServiceCatalogue from '../pages/catalogue/ServiceCatalogue'
import PartsCatalogue from '../pages/catalogue/PartsCatalogue'
import LabourRates from '../pages/catalogue/LabourRates'
import CataloguePage from '../pages/catalogue/CataloguePage'

/* ------------------------------------------------------------------ */
/*  Mock data                                                          */
/* ------------------------------------------------------------------ */

const mockServices = [
  {
    id: 'svc-1', name: 'WOF Inspection', description: 'Warrant of Fitness check',
    default_price: '55.00', is_gst_exempt: false, category: 'warrant',
    is_active: true, created_at: '2024-01-01T00:00:00Z', updated_at: '2024-01-01T00:00:00Z',
  },
  {
    id: 'svc-2', name: 'Diagnostic Scan', description: null,
    default_price: '85.00', is_gst_exempt: true, category: 'diagnostic',
    is_active: false, created_at: '2024-06-01T00:00:00Z', updated_at: '2024-06-01T00:00:00Z',
  },
]

const mockParts = [
  {
    id: 'part-1', name: 'Brake Pads', part_number: 'BRK-001',
    default_price: '45.00', supplier: 'Repco', is_active: true,
    created_at: '2024-01-01T00:00:00Z', updated_at: '2024-01-01T00:00:00Z',
  },
  {
    id: 'part-2', name: 'Oil Filter', part_number: null,
    default_price: '12.50', supplier: null, is_active: true,
    created_at: '2024-06-01T00:00:00Z', updated_at: '2024-06-01T00:00:00Z',
  },
]

const mockLabourRates = [
  {
    id: 'lr-1', name: 'Standard Rate', hourly_rate: '95.00',
    is_active: true, created_at: '2024-01-01T00:00:00Z', updated_at: '2024-01-01T00:00:00Z',
  },
  {
    id: 'lr-2', name: 'Specialist Rate', hourly_rate: '130.00',
    is_active: false, created_at: '2024-06-01T00:00:00Z', updated_at: '2024-06-01T00:00:00Z',
  },
]

/* ------------------------------------------------------------------ */
/*  ServiceCatalogue tests                                             */
/* ------------------------------------------------------------------ */

describe('ServiceCatalogue', () => {
  beforeEach(() => { vi.clearAllMocks() })

  it('shows loading spinner initially', () => {
    ;(apiClient.get as ReturnType<typeof vi.fn>).mockReturnValue(new Promise(() => {}))
    render(<ServiceCatalogue />)
    expect(screen.getByRole('status', { name: 'Loading services' })).toBeInTheDocument()
  })

  it('renders new service button', async () => {
    ;(apiClient.get as ReturnType<typeof vi.fn>).mockResolvedValue({
      data: { services: mockServices, total: 2 },
    })
    render(<ServiceCatalogue />)
    expect(screen.getByRole('button', { name: '+ New Service' })).toBeInTheDocument()
  })

  it('displays services with name, category, price, GST, status (Req 27.1)', async () => {
    ;(apiClient.get as ReturnType<typeof vi.fn>).mockResolvedValue({
      data: { services: mockServices, total: 2 },
    })
    render(<ServiceCatalogue />)
    const table = await screen.findByRole('grid')
    const rows = within(table).getAllByRole('row')
    expect(rows).toHaveLength(3) // header + 2 data rows
    expect(screen.getByText('WOF Inspection')).toBeInTheDocument()
    expect(screen.getByText('Warrant')).toBeInTheDocument()
    expect(screen.getByText('$55.00')).toBeInTheDocument()
    expect(screen.getByText('Diagnostic Scan')).toBeInTheDocument()
    expect(screen.getByText('$85.00')).toBeInTheDocument()
  })

  it('shows active/inactive status badges (Req 27.2)', async () => {
    ;(apiClient.get as ReturnType<typeof vi.fn>).mockResolvedValue({
      data: { services: mockServices, total: 2 },
    })
    render(<ServiceCatalogue />)
    await screen.findByRole('grid')
    expect(screen.getByText('Active')).toBeInTheDocument()
    expect(screen.getByText('Inactive')).toBeInTheDocument()
  })

  it('shows GST exempt badge for exempt services (Req 27.1)', async () => {
    ;(apiClient.get as ReturnType<typeof vi.fn>).mockResolvedValue({
      data: { services: mockServices, total: 2 },
    })
    render(<ServiceCatalogue />)
    await screen.findByRole('grid')
    expect(screen.getByText('Exempt')).toBeInTheDocument()
    expect(screen.getByText('Incl.')).toBeInTheDocument()
  })

  it('shows empty state when no services', async () => {
    ;(apiClient.get as ReturnType<typeof vi.fn>).mockResolvedValue({
      data: { services: [], total: 0 },
    })
    render(<ServiceCatalogue />)
    expect(await screen.findByText('No services yet. Add your first service to get started.')).toBeInTheDocument()
  })

  it('opens create service modal with form fields (Req 27.1)', async () => {
    ;(apiClient.get as ReturnType<typeof vi.fn>).mockResolvedValue({
      data: { services: [], total: 0 },
    })
    render(<ServiceCatalogue />)
    await screen.findByRole('grid')
    const user = userEvent.setup()
    await user.click(screen.getByRole('button', { name: '+ New Service' }))
    expect(screen.getByRole('dialog')).toBeInTheDocument()
    expect(screen.getByText('New Service')).toBeInTheDocument()
    expect(screen.getByLabelText('Service name *')).toBeInTheDocument()
    expect(screen.getByLabelText('Default price (ex-GST) *')).toBeInTheDocument()
    expect(screen.getByLabelText('Category')).toBeInTheDocument()
    expect(screen.getByLabelText('GST exempt')).toBeInTheDocument()
  })

  it('opens edit modal pre-filled with service data', async () => {
    ;(apiClient.get as ReturnType<typeof vi.fn>).mockResolvedValue({
      data: { services: mockServices, total: 2 },
    })
    render(<ServiceCatalogue />)
    await screen.findByRole('grid')
    const user = userEvent.setup()
    const editButtons = screen.getAllByRole('button', { name: 'Edit' })
    await user.click(editButtons[0])
    expect(screen.getByRole('dialog')).toBeInTheDocument()
    expect(screen.getByText('Edit Service')).toBeInTheDocument()
    expect(screen.getByDisplayValue('WOF Inspection')).toBeInTheDocument()
    expect(screen.getByDisplayValue('55.00')).toBeInTheDocument()
  })
})

/* ------------------------------------------------------------------ */
/*  PartsCatalogue tests                                               */
/* ------------------------------------------------------------------ */

describe('PartsCatalogue', () => {
  beforeEach(() => { vi.clearAllMocks() })

  it('shows loading spinner initially', () => {
    ;(apiClient.get as ReturnType<typeof vi.fn>).mockReturnValue(new Promise(() => {}))
    render(<PartsCatalogue />)
    expect(screen.getByRole('status', { name: 'Loading parts' })).toBeInTheDocument()
  })

  it('renders new part button', async () => {
    ;(apiClient.get as ReturnType<typeof vi.fn>).mockResolvedValue({
      data: { parts: mockParts, total: 2 },
    })
    render(<PartsCatalogue />)
    expect(screen.getByRole('button', { name: '+ New Part' })).toBeInTheDocument()
  })

  it('displays parts with name, part number, price, supplier (Req 28.1)', async () => {
    ;(apiClient.get as ReturnType<typeof vi.fn>).mockResolvedValue({
      data: { parts: mockParts, total: 2 },
    })
    render(<PartsCatalogue />)
    const table = await screen.findByRole('grid')
    const rows = within(table).getAllByRole('row')
    expect(rows).toHaveLength(3)
    expect(screen.getByText('Brake Pads')).toBeInTheDocument()
    expect(screen.getByText('BRK-001')).toBeInTheDocument()
    expect(screen.getByText('$45.00')).toBeInTheDocument()
    expect(screen.getByText('Repco')).toBeInTheDocument()
    expect(screen.getByText('Oil Filter')).toBeInTheDocument()
    expect(screen.getByText('$12.50')).toBeInTheDocument()
  })

  it('shows empty state when no parts', async () => {
    ;(apiClient.get as ReturnType<typeof vi.fn>).mockResolvedValue({
      data: { parts: [], total: 0 },
    })
    render(<PartsCatalogue />)
    expect(await screen.findByText('No parts yet. Add common parts to speed up invoicing.')).toBeInTheDocument()
  })

  it('opens create part modal with form fields (Req 28.1)', async () => {
    ;(apiClient.get as ReturnType<typeof vi.fn>).mockResolvedValue({
      data: { parts: [], total: 0 },
    })
    render(<PartsCatalogue />)
    await screen.findByRole('grid')
    const user = userEvent.setup()
    await user.click(screen.getByRole('button', { name: '+ New Part' }))
    expect(screen.getByRole('dialog')).toBeInTheDocument()
    expect(screen.getByText('New Part')).toBeInTheDocument()
    expect(screen.getByLabelText('Part name *')).toBeInTheDocument()
    expect(screen.getByLabelText('Part number')).toBeInTheDocument()
    expect(screen.getByLabelText('Default price *')).toBeInTheDocument()
    expect(screen.getByLabelText('Supplier')).toBeInTheDocument()
  })
})

/* ------------------------------------------------------------------ */
/*  LabourRates tests                                                  */
/* ------------------------------------------------------------------ */

describe('LabourRates', () => {
  beforeEach(() => { vi.clearAllMocks() })

  it('shows loading spinner initially', () => {
    ;(apiClient.get as ReturnType<typeof vi.fn>).mockReturnValue(new Promise(() => {}))
    render(<LabourRates />)
    expect(screen.getByRole('status', { name: 'Loading labour rates' })).toBeInTheDocument()
  })

  it('renders new rate button', async () => {
    ;(apiClient.get as ReturnType<typeof vi.fn>).mockResolvedValue({
      data: { labour_rates: mockLabourRates, total: 2 },
    })
    render(<LabourRates />)
    expect(screen.getByRole('button', { name: '+ New Rate' })).toBeInTheDocument()
  })

  it('displays labour rates with name, hourly rate, status (Req 28.3)', async () => {
    ;(apiClient.get as ReturnType<typeof vi.fn>).mockResolvedValue({
      data: { labour_rates: mockLabourRates, total: 2 },
    })
    render(<LabourRates />)
    const table = await screen.findByRole('grid')
    const rows = within(table).getAllByRole('row')
    expect(rows).toHaveLength(3)
    expect(screen.getByText('Standard Rate')).toBeInTheDocument()
    expect(screen.getByText('$95.00/hr')).toBeInTheDocument()
    expect(screen.getByText('Specialist Rate')).toBeInTheDocument()
    expect(screen.getByText('$130.00/hr')).toBeInTheDocument()
  })

  it('shows active/inactive status badges (Req 28.3)', async () => {
    ;(apiClient.get as ReturnType<typeof vi.fn>).mockResolvedValue({
      data: { labour_rates: mockLabourRates, total: 2 },
    })
    render(<LabourRates />)
    await screen.findByRole('grid')
    expect(screen.getByText('Active')).toBeInTheDocument()
    expect(screen.getByText('Inactive')).toBeInTheDocument()
  })

  it('shows empty state when no rates', async () => {
    ;(apiClient.get as ReturnType<typeof vi.fn>).mockResolvedValue({
      data: { labour_rates: [], total: 0 },
    })
    render(<LabourRates />)
    expect(await screen.findByText('No labour rates yet. Add rates like "Standard" or "Specialist" to use during invoicing.')).toBeInTheDocument()
  })

  it('opens create rate modal with form fields (Req 28.3)', async () => {
    ;(apiClient.get as ReturnType<typeof vi.fn>).mockResolvedValue({
      data: { labour_rates: [], total: 0 },
    })
    render(<LabourRates />)
    await screen.findByRole('grid')
    const user = userEvent.setup()
    await user.click(screen.getByRole('button', { name: '+ New Rate' }))
    expect(screen.getByRole('dialog')).toBeInTheDocument()
    expect(screen.getByText('New Labour Rate')).toBeInTheDocument()
    expect(screen.getByLabelText('Rate name *')).toBeInTheDocument()
    expect(screen.getByLabelText('Hourly rate ($) *')).toBeInTheDocument()
  })
})

/* ------------------------------------------------------------------ */
/*  CataloguePage tests                                                */
/* ------------------------------------------------------------------ */

describe('CataloguePage', () => {
  beforeEach(() => { vi.clearAllMocks() })

  it('renders heading and tabs for services, parts, labour rates', async () => {
    ;(apiClient.get as ReturnType<typeof vi.fn>).mockResolvedValue({
      data: { services: [], total: 0 },
    })
    render(<CataloguePage />)
    expect(screen.getByRole('heading', { name: 'Catalogue' })).toBeInTheDocument()
    expect(screen.getByRole('tab', { name: 'Services' })).toBeInTheDocument()
    expect(screen.getByRole('tab', { name: 'Parts' })).toBeInTheDocument()
    expect(screen.getByRole('tab', { name: 'Labour Rates' })).toBeInTheDocument()
  })

  it('defaults to services tab', async () => {
    ;(apiClient.get as ReturnType<typeof vi.fn>).mockResolvedValue({
      data: { services: [], total: 0 },
    })
    render(<CataloguePage />)
    const servicesTab = screen.getByRole('tab', { name: 'Services' })
    expect(servicesTab).toHaveAttribute('aria-selected', 'true')
  })

  it('switches to parts tab on click', async () => {
    ;(apiClient.get as ReturnType<typeof vi.fn>).mockResolvedValue({
      data: { services: [], total: 0, parts: [], labour_rates: [] },
    })
    render(<CataloguePage />)
    const user = userEvent.setup()
    await user.click(screen.getByRole('tab', { name: 'Parts' }))
    expect(screen.getByRole('tab', { name: 'Parts' })).toHaveAttribute('aria-selected', 'true')
  })
})
