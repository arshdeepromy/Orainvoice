import { render, screen, within, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, it, expect, vi, beforeEach } from 'vitest'

/**
 * Validates: Requirement 29 — Variation Module
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
import VariationList from '../pages/construction/VariationList'
import VariationForm from '../pages/construction/VariationForm'

const mockVariations = [
  {
    id: 'var-1', project_id: 'proj-1', variation_number: 1,
    description: 'Additional foundation work',
    cost_impact: '15000.00', status: 'draft',
    submitted_at: null, approved_at: null,
    created_at: '2024-06-15T10:00:00Z',
  },
  {
    id: 'var-2', project_id: 'proj-1', variation_number: 2,
    description: 'Remove balcony extension',
    cost_impact: '-8000.00', status: 'approved',
    submitted_at: '2024-06-20T10:00:00Z',
    approved_at: '2024-06-22T10:00:00Z',
    created_at: '2024-06-18T10:00:00Z',
  },
]

describe('VariationList', () => {
  beforeEach(() => { vi.clearAllMocks() })

  it('shows loading spinner initially', () => {
    ;(apiClient.get as ReturnType<typeof vi.fn>).mockReturnValue(new Promise(() => {}))
    render(<VariationList />)
    expect(screen.getByRole('status', { name: 'Loading variations' })).toBeInTheDocument()
  })

  it('displays variations in a table', async () => {
    ;(apiClient.get as ReturnType<typeof vi.fn>).mockResolvedValue({
      data: { variations: mockVariations, total: 2, page: 1, page_size: 50 },
    })
    render(<VariationList />)
    const table = await screen.findByRole('grid', { name: 'Variation orders list' })
    const rows = within(table).getAllByRole('row')
    expect(rows).toHaveLength(3) // header + 2 data rows
  })

  it('shows empty state when no variations', async () => {
    ;(apiClient.get as ReturnType<typeof vi.fn>).mockResolvedValue({
      data: { variations: [], total: 0, page: 1, page_size: 50 },
    })
    render(<VariationList />)
    expect(await screen.findByText(/No variation orders found/)).toBeInTheDocument()
  })

  it('renders status filter dropdown', async () => {
    ;(apiClient.get as ReturnType<typeof vi.fn>).mockResolvedValue({
      data: { variations: [], total: 0, page: 1, page_size: 50 },
    })
    render(<VariationList />)
    await waitFor(() => {
      expect(screen.queryByRole('status')).not.toBeInTheDocument()
    })
    expect(screen.getByLabelText('Status')).toBeInTheDocument()
  })

  it('shows create form when New Variation clicked', async () => {
    ;(apiClient.get as ReturnType<typeof vi.fn>).mockResolvedValue({
      data: { variations: mockVariations, total: 2, page: 1, page_size: 50 },
    })
    render(<VariationList />)
    await screen.findByRole('grid', { name: 'Variation orders list' })

    const user = userEvent.setup()
    await user.click(screen.getByRole('button', { name: 'New variation' }))

    expect(screen.getByRole('form', { name: 'Create variation order' })).toBeInTheDocument()
  })

  it('shows approve button for draft variations', async () => {
    ;(apiClient.get as ReturnType<typeof vi.fn>).mockResolvedValue({
      data: { variations: mockVariations, total: 2, page: 1, page_size: 50 },
    })
    render(<VariationList />)
    await screen.findByRole('grid', { name: 'Variation orders list' })

    expect(screen.getByRole('button', { name: 'Approve variation 1' })).toBeInTheDocument()
  })

  it('calls approve endpoint when approve clicked', async () => {
    ;(apiClient.get as ReturnType<typeof vi.fn>).mockResolvedValue({
      data: { variations: mockVariations, total: 2, page: 1, page_size: 50 },
    })
    ;(apiClient.put as ReturnType<typeof vi.fn>).mockResolvedValue({ data: {} })
    render(<VariationList />)
    await screen.findByRole('grid', { name: 'Variation orders list' })

    const user = userEvent.setup()
    await user.click(screen.getByRole('button', { name: 'Approve variation 1' }))

    expect(apiClient.put).toHaveBeenCalledWith('/api/v2/variations/var-1/approve')
  })

  it('filters by status when dropdown changes', async () => {
    ;(apiClient.get as ReturnType<typeof vi.fn>).mockResolvedValue({
      data: { variations: mockVariations, total: 2, page: 1, page_size: 50 },
    })
    render(<VariationList />)
    await screen.findByRole('grid', { name: 'Variation orders list' })

    const user = userEvent.setup()
    await user.selectOptions(screen.getByLabelText('Status'), 'approved')

    await waitFor(() => {
      const calls = (apiClient.get as ReturnType<typeof vi.fn>).mock.calls
      const lastCall = calls[calls.length - 1][0] as string
      expect(lastCall).toContain('status=approved')
    })
  })
})

describe('VariationForm', () => {
  beforeEach(() => { vi.clearAllMocks() })

  it('renders description and cost impact fields', () => {
    render(<VariationForm projectId="proj-1" />)
    expect(screen.getByLabelText('Description')).toBeInTheDocument()
    expect(screen.getByLabelText('Cost Impact')).toBeInTheDocument()
  })

  it('shows Addition label for positive cost impact', async () => {
    render(<VariationForm projectId="proj-1" />)
    const user = userEvent.setup()

    await user.type(screen.getByLabelText('Cost Impact'), '5000')

    expect(screen.getByTestId('impact-type')).toHaveTextContent('Addition')
  })

  it('shows Deduction label for negative cost impact', async () => {
    render(<VariationForm projectId="proj-1" />)
    const user = userEvent.setup()

    await user.type(screen.getByLabelText('Cost Impact'), '-3000')

    expect(screen.getByTestId('impact-type')).toHaveTextContent('Deduction')
  })

  it('submits form with correct data', async () => {
    ;(apiClient.post as ReturnType<typeof vi.fn>).mockResolvedValue({ data: { id: 'new-var' } })
    render(<VariationForm projectId="proj-1" />)
    const user = userEvent.setup()

    await user.type(screen.getByLabelText('Description'), 'Extra plumbing work')
    await user.type(screen.getByLabelText('Cost Impact'), '12000')

    await user.click(screen.getByRole('button', { name: 'Save Variation' }))

    expect(apiClient.post).toHaveBeenCalledWith('/api/v2/variations', expect.objectContaining({
      project_id: 'proj-1',
      description: 'Extra plumbing work',
      cost_impact: 12000,
    }))
  })

  it('shows error when API returns error on submit', async () => {
    ;(apiClient.post as ReturnType<typeof vi.fn>).mockRejectedValue({
      response: { data: { detail: 'Description is required' } },
    })
    render(<VariationForm projectId="proj-1" />)
    const user = userEvent.setup()

    await user.type(screen.getByLabelText('Description'), 'Test')
    await user.type(screen.getByLabelText('Cost Impact'), '5000')
    await user.click(screen.getByRole('button', { name: 'Save Variation' }))

    await waitFor(() => {
      expect(screen.getByRole('alert')).toHaveTextContent('Description is required')
    })
  })
})
