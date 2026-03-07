import { render, screen, within, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, it, expect, vi, beforeEach } from 'vitest'

/**
 * Validates: Requirement — Compliance Module, Task 38.10
 */

vi.mock('@/api/client', () => {
  const mockGet = vi.fn()
  const mockPost = vi.fn()
  return {
    default: { get: mockGet, post: mockPost },
  }
})

import apiClient from '@/api/client'
import ComplianceDashboard from '../pages/compliance/ComplianceDashboard'

const mockDashboard = {
  total_documents: 3,
  expiring_soon: 1,
  expired: 0,
  documents: [
    {
      id: 'doc-1', org_id: 'org-1', document_type: 'license',
      description: 'Trade license', file_key: 'compliance/abc.pdf',
      file_name: 'trade_license.pdf', expiry_date: '2025-08-01',
      invoice_id: null, job_id: null, uploaded_by: null,
      created_at: '2024-06-15T10:00:00Z',
    },
    {
      id: 'doc-2', org_id: 'org-1', document_type: 'insurance',
      description: null, file_key: 'compliance/def.pdf',
      file_name: 'liability_insurance.pdf', expiry_date: null,
      invoice_id: null, job_id: null, uploaded_by: null,
      created_at: '2024-07-01T10:00:00Z',
    },
    {
      id: 'doc-3', org_id: 'org-1', document_type: 'certification',
      description: 'ISO 9001', file_key: 'compliance/ghi.pdf',
      file_name: 'iso_cert.pdf', expiry_date: '2025-03-15',
      invoice_id: 'inv-1', job_id: null, uploaded_by: null,
      created_at: '2024-05-01T10:00:00Z',
    },
  ],
}

describe('ComplianceDashboard', () => {
  beforeEach(() => { vi.clearAllMocks() })

  it('shows loading spinner initially', () => {
    ;(apiClient.get as ReturnType<typeof vi.fn>).mockReturnValue(new Promise(() => {}))
    render(<ComplianceDashboard />)
    expect(screen.getByRole('status', { name: 'Loading compliance dashboard' })).toBeInTheDocument()
  })

  it('displays summary counts', async () => {
    ;(apiClient.get as ReturnType<typeof vi.fn>).mockResolvedValue({ data: mockDashboard })
    render(<ComplianceDashboard />)

    await waitFor(() => {
      expect(screen.getByTestId('total-count')).toHaveTextContent('3')
    })
    expect(screen.getByTestId('expiring-count')).toHaveTextContent('1')
    expect(screen.getByTestId('expired-count')).toHaveTextContent('0')
  })

  it('displays documents in a table', async () => {
    ;(apiClient.get as ReturnType<typeof vi.fn>).mockResolvedValue({ data: mockDashboard })
    render(<ComplianceDashboard />)

    const table = await screen.findByRole('grid', { name: 'Compliance documents list' })
    const rows = within(table).getAllByRole('row')
    expect(rows).toHaveLength(4) // header + 3 data rows
  })

  it('shows empty state when no documents', async () => {
    ;(apiClient.get as ReturnType<typeof vi.fn>).mockResolvedValue({
      data: { total_documents: 0, expiring_soon: 0, expired: 0, documents: [] },
    })
    render(<ComplianceDashboard />)
    expect(await screen.findByText(/No compliance documents found/)).toBeInTheDocument()
  })

  it('shows upload form when Upload Document clicked', async () => {
    ;(apiClient.get as ReturnType<typeof vi.fn>).mockResolvedValue({ data: mockDashboard })
    render(<ComplianceDashboard />)
    await screen.findByRole('grid', { name: 'Compliance documents list' })

    const user = userEvent.setup()
    await user.click(screen.getByRole('button', { name: 'Upload document' }))

    expect(screen.getByRole('form', { name: 'Upload compliance document' })).toBeInTheDocument()
  })

  it('submits upload form with correct data', async () => {
    ;(apiClient.get as ReturnType<typeof vi.fn>).mockResolvedValue({ data: mockDashboard })
    ;(apiClient.post as ReturnType<typeof vi.fn>).mockResolvedValue({ data: { id: 'new-doc' } })
    render(<ComplianceDashboard />)
    await screen.findByRole('grid', { name: 'Compliance documents list' })

    const user = userEvent.setup()
    await user.click(screen.getByRole('button', { name: 'Upload document' }))

    await user.type(screen.getByLabelText('Document Type'), 'license')
    await user.type(screen.getByLabelText('File Name'), 'new_license.pdf')
    await user.type(screen.getByLabelText('Expiry Date'), '2026-01-01')

    await user.click(screen.getByRole('button', { name: 'Save document' }))

    expect(apiClient.post).toHaveBeenCalledWith('/api/v2/compliance-docs', expect.objectContaining({
      document_type: 'license',
      file_name: 'new_license.pdf',
      expiry_date: '2026-01-01',
    }))
  })

  it('shows error when API fails', async () => {
    ;(apiClient.get as ReturnType<typeof vi.fn>).mockRejectedValue(new Error('Network error'))
    render(<ComplianceDashboard />)
    expect(await screen.findByRole('alert')).toHaveTextContent('Failed to load compliance dashboard')
  })

  it('shows No expiry for documents without expiry date', async () => {
    ;(apiClient.get as ReturnType<typeof vi.fn>).mockResolvedValue({ data: mockDashboard })
    render(<ComplianceDashboard />)
    await screen.findByRole('grid', { name: 'Compliance documents list' })
    expect(screen.getByText('No expiry')).toBeInTheDocument()
  })

  it('shows upload error when API returns error', async () => {
    ;(apiClient.get as ReturnType<typeof vi.fn>).mockResolvedValue({ data: mockDashboard })
    ;(apiClient.post as ReturnType<typeof vi.fn>).mockRejectedValue({
      response: { data: { detail: 'Invalid document type' } },
    })
    render(<ComplianceDashboard />)
    await screen.findByRole('grid', { name: 'Compliance documents list' })

    const user = userEvent.setup()
    await user.click(screen.getByRole('button', { name: 'Upload document' }))
    await user.type(screen.getByLabelText('Document Type'), 'bad')
    await user.type(screen.getByLabelText('File Name'), 'test.pdf')
    await user.click(screen.getByRole('button', { name: 'Save document' }))

    await waitFor(() => {
      expect(screen.getByRole('alert')).toHaveTextContent('Invalid document type')
    })
  })
})
