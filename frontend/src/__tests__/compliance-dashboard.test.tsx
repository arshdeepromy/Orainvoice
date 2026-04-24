import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { MemoryRouter } from 'react-router-dom'

/**
 * Validates: Requirement — Compliance Module (legacy integration tests)
 *
 * These tests validate the ComplianceDashboard component against the
 * rebuilt compliance documents feature. The primary test suite is at
 * src/pages/compliance/__tests__/ComplianceDashboard.test.tsx.
 */

vi.mock('@/api/client', () => {
  const mockGet = vi.fn()
  const mockPost = vi.fn()
  const mockPut = vi.fn()
  const mockDelete = vi.fn()
  return {
    default: { get: mockGet, post: mockPost, put: mockPut, delete: mockDelete },
  }
})

import apiClient from '@/api/client'
import ComplianceDashboard from '../pages/compliance/ComplianceDashboard'

/* Helper to render with router context */
function renderDashboard() {
  return render(
    <MemoryRouter>
      <ComplianceDashboard />
    </MemoryRouter>,
  )
}

const MOCK_CATEGORIES = {
  items: [
    { id: 'cat-1', name: 'Business License', is_predefined: true },
  ],
  total: 1,
}

const mockDashboard = {
  total_documents: 3,
  valid_documents: 2,
  expiring_soon: 1,
  expired: 0,
  documents: [
    {
      id: 'doc-1', org_id: 'org-1', document_type: 'Business License',
      description: 'Trade license', file_key: 'compliance/abc.pdf',
      file_name: 'trade_license.pdf', expiry_date: '2099-08-01',
      status: 'valid',
      invoice_id: null, job_id: null, uploaded_by: null,
      created_at: '2024-06-15T10:00:00Z',
    },
    {
      id: 'doc-2', org_id: 'org-1', document_type: 'Public Liability Insurance',
      description: null, file_key: 'compliance/def.pdf',
      file_name: 'liability_insurance.pdf', expiry_date: null,
      status: 'no_expiry',
      invoice_id: null, job_id: null, uploaded_by: null,
      created_at: '2024-07-01T10:00:00Z',
    },
    {
      id: 'doc-3', org_id: 'org-1', document_type: 'Trade Certification',
      description: 'ISO 9001', file_key: 'compliance/ghi.pdf',
      file_name: 'iso_cert.pdf', expiry_date: '2025-03-15',
      status: 'expiring_soon',
      invoice_id: 'inv-1', job_id: null, uploaded_by: null,
      created_at: '2024-05-01T10:00:00Z',
    },
  ],
}

/**
 * Mock apiClient.get to return dashboard data for the main call
 * and categories for the categories call.
 */
function setupMockApi(dashboardData = mockDashboard) {
  ;(apiClient.get as ReturnType<typeof vi.fn>).mockImplementation((url: string) => {
    if (typeof url === 'string' && url.includes('categories')) {
      return Promise.resolve({ data: MOCK_CATEGORIES })
    }
    if (typeof url === 'string' && url.includes('badge-count')) {
      return Promise.resolve({ data: { count: dashboardData.expiring_soon + dashboardData.expired } })
    }
    return Promise.resolve({ data: dashboardData })
  })
}

describe('ComplianceDashboard', () => {
  beforeEach(() => { vi.clearAllMocks() })

  it('shows skeleton placeholders during loading', () => {
    ;(apiClient.get as ReturnType<typeof vi.fn>).mockReturnValue(new Promise(() => {}))
    renderDashboard()
    // During loading, skeleton cards with animate-pulse are shown
    const summaryRegion = screen.getByRole('region', { name: 'Compliance summary' })
    expect(summaryRegion).toBeInTheDocument()
    expect(summaryRegion.querySelector('.animate-pulse')).toBeTruthy()
  })

  it('displays summary counts', async () => {
    setupMockApi()
    renderDashboard()

    await waitFor(() => {
      expect(screen.getByTestId('total-count')).toHaveTextContent('3')
    })
    expect(screen.getByTestId('expiring-count')).toHaveTextContent('1')
    expect(screen.getByTestId('expired-count')).toHaveTextContent('0')
  })

  it('displays documents in a table', async () => {
    setupMockApi()
    renderDashboard()

    // Wait for documents to render
    expect(await screen.findByText('trade_license.pdf')).toBeInTheDocument()
    expect(screen.getByText('liability_insurance.pdf')).toBeInTheDocument()
    expect(screen.getByText('iso_cert.pdf')).toBeInTheDocument()
  })

  it('shows empty state when no documents', async () => {
    setupMockApi({
      total_documents: 0, valid_documents: 0, expiring_soon: 0, expired: 0, documents: [],
    })
    renderDashboard()
    expect(
      await screen.findByText(/No compliance documents yet/)
    ).toBeInTheDocument()
  })

  it('shows upload form when Upload Document clicked', async () => {
    setupMockApi()
    renderDashboard()
    // Wait for data to load
    await screen.findByText('trade_license.pdf')

    const user = userEvent.setup()
    await user.click(screen.getByRole('button', { name: /upload document/i }))

    // Upload form should be visible (drag-and-drop zone)
    expect(screen.getByText(/drag.*drop|choose.*file|select.*file/i)).toBeInTheDocument()
  })

  it('shows error when API fails', async () => {
    ;(apiClient.get as ReturnType<typeof vi.fn>).mockRejectedValue(new Error('Network error'))
    renderDashboard()
    expect(await screen.findByRole('alert')).toBeInTheDocument()
  })

  it('shows No Expiry badge for documents without expiry date', async () => {
    setupMockApi()
    renderDashboard()
    await screen.findByText('trade_license.pdf')
    // "No Expiry" appears in both the status filter dropdown and the status badge
    const noExpiryElements = screen.getAllByText('No Expiry')
    expect(noExpiryElements.length).toBeGreaterThanOrEqual(2) // dropdown option + badge
  })

  it('shows Expiring Soon badge for expiring documents', async () => {
    setupMockApi()
    renderDashboard()
    await screen.findByText('trade_license.pdf')
    // "Expiring Soon" appears in summary card, status filter dropdown, and status badge
    const expiringSoonElements = screen.getAllByText('Expiring Soon')
    expect(expiringSoonElements.length).toBeGreaterThanOrEqual(2)
  })

  it('renders valid count in summary cards', async () => {
    setupMockApi()
    renderDashboard()
    await waitFor(() => {
      expect(screen.getByTestId('valid-count')).toHaveTextContent('2')
    })
  })
})
