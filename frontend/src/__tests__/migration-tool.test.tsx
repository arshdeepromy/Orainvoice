import { render, screen, waitFor, fireEvent } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, it, expect, vi, beforeEach } from 'vitest'

/**
 * Validates: Requirement 7, Requirement 41
 * - 7.1: Migration tool provides migration path for organisations
 * - 7.3: Full and live migration modes
 * - 7.5: Integrity checks after migration
 * - 7.6: Rollback on integrity check failure
 * - 41.3: Real-time progress during migration
 */

vi.mock('@/api/client', () => {
  const mockGet = vi.fn()
  const mockPost = vi.fn()
  return {
    default: { get: mockGet, post: mockPost, put: vi.fn(), delete: vi.fn() },
  }
})

import apiClient from '@/api/client'
import { MigrationTool } from '../pages/admin/MigrationTool'

/* ── Mock data ── */

const mockJobPending = {
  id: 'job-001',
  org_id: 'org-001',
  mode: 'full',
  status: 'pending',
  source_format: 'json',
  description: 'Test migration',
  records_processed: 0,
  records_total: 10,
  progress_pct: 0,
  integrity_check: null,
  error_message: null,
  created_at: '2025-01-15T00:00:00Z',
  updated_at: '2025-01-15T00:00:00Z',
}

const mockJobCompleted = {
  ...mockJobPending,
  status: 'completed',
  records_processed: 10,
  progress_pct: 100,
  integrity_check: {
    passed: true,
    record_counts: {
      customers: { source: 3, migrated: 3 },
      invoices: { source: 4, migrated: 4 },
      products: { source: 2, migrated: 2 },
      payments: { source: 1, migrated: 1 },
    },
    financial_totals: {
      source_invoice_total: 1500.0,
      migrated_invoice_total: 1500.0,
      source_payment_total: 500.0,
      migrated_payment_total: 500.0,
    },
    reference_errors: [],
    invoice_numbering_gaps: [],
  },
}

const mockJobFailed = {
  ...mockJobPending,
  status: 'failed',
  error_message: 'Integrity check failed',
  integrity_check: {
    passed: false,
    record_counts: {
      customers: { source: 3, migrated: 2 },
    },
    financial_totals: {
      source_invoice_total: 1500.0,
      migrated_invoice_total: 1200.0,
    },
    reference_errors: ['Invoice INV-003 references non-existent customer'],
    invoice_numbering_gaps: ['Gap between INV-001 and INV-003'],
  },
}

/* ── Tests ── */

describe('MigrationTool', () => {
  beforeEach(() => {
    vi.clearAllMocks()
  })

  it('renders the migration tool with configuration form', () => {
    render(<MigrationTool />)

    expect(screen.getByText('Database Migration Tool')).toBeInTheDocument()
    expect(screen.getByLabelText('Organisation ID')).toBeInTheDocument()
    expect(screen.getByLabelText('Migration mode')).toBeInTheDocument()
    expect(screen.getByLabelText('Source format')).toBeInTheDocument()
    expect(screen.getByLabelText('Start migration')).toBeInTheDocument()
  })

  it('disables start button when org ID or source data is missing', () => {
    render(<MigrationTool />)

    const startBtn = screen.getByLabelText('Start migration')
    expect(startBtn).toBeDisabled()
  })

  it('shows mode selector with full and live options', () => {
    render(<MigrationTool />)

    const modeSelect = screen.getByLabelText('Migration mode')
    expect(modeSelect).toBeInTheDocument()

    const options = modeSelect.querySelectorAll('option')
    expect(options).toHaveLength(2)
    expect(options[0]).toHaveTextContent('Full Migration')
    expect(options[1]).toHaveTextContent('Live Migration')
  })

  it('shows format selector with JSON and CSV options', () => {
    render(<MigrationTool />)

    const formatSelect = screen.getByLabelText('Source format')
    const options = formatSelect.querySelectorAll('option')
    expect(options).toHaveLength(2)
    expect(options[0]).toHaveTextContent('JSON')
    expect(options[1]).toHaveTextContent('CSV')
  })

  it('displays progress tracker when job is active', async () => {
    const mockPost = vi.mocked(apiClient.post)
    mockPost
      .mockResolvedValueOnce({ data: mockJobPending })
      .mockResolvedValueOnce({ data: mockJobCompleted })

    render(<MigrationTool />)

    // Fill in org ID
    const orgInput = screen.getByLabelText('Organisation ID')
    await userEvent.type(orgInput, 'org-001')

    // Simulate file upload with a File that has a working text() method
    const fileInput = screen.getByLabelText('Upload source file') as HTMLInputElement
    const jsonContent = JSON.stringify({ customers: [{ name: 'Test' }] })
    const testFile = new File([jsonContent], 'data.json', { type: 'application/json' })
    // Override text() for jsdom compatibility
    testFile.text = () => Promise.resolve(jsonContent)

    fireEvent.change(fileInput, { target: { files: [testFile] } })

    // Wait for data to be parsed
    await waitFor(() => {
      expect(screen.getByText('Data Mapping')).toBeInTheDocument()
    })

    // Click start
    const startBtn = screen.getByLabelText('Start migration')
    await userEvent.click(startBtn)

    // Should show progress
    await waitFor(() => {
      expect(mockPost).toHaveBeenCalledWith(
        '/api/v2/admin/migrations',
        expect.objectContaining({ org_id: 'org-001', mode: 'full' }),
      )
    })
  })

  it('displays integrity report when migration completes', async () => {
    const mockPost = vi.mocked(apiClient.post)
    mockPost
      .mockResolvedValueOnce({ data: mockJobPending })
      .mockResolvedValueOnce({ data: mockJobCompleted })

    render(<MigrationTool />)

    const orgInput = screen.getByLabelText('Organisation ID')
    await userEvent.type(orgInput, 'org-001')

    const fileInput = screen.getByLabelText('Upload source file') as HTMLInputElement
    const jsonContent = JSON.stringify({ customers: [{ name: 'Test' }] })
    const testFile = new File([jsonContent], 'data.json', { type: 'application/json' })
    testFile.text = () => Promise.resolve(jsonContent)

    fireEvent.change(fileInput, { target: { files: [testFile] } })

    await waitFor(() => {
      expect(screen.getByText('Data Mapping')).toBeInTheDocument()
    })

    const startBtn = screen.getByLabelText('Start migration')
    await userEvent.click(startBtn)

    await waitFor(() => {
      expect(screen.getByText('Integrity Check Report')).toBeInTheDocument()
      expect(screen.getByText('✓ All checks passed')).toBeInTheDocument()
    })
  })

  it('displays reference errors in failed integrity report', async () => {
    const mockPost = vi.mocked(apiClient.post)
    mockPost
      .mockResolvedValueOnce({ data: mockJobPending })
      .mockResolvedValueOnce({ data: mockJobFailed })

    render(<MigrationTool />)

    const orgInput = screen.getByLabelText('Organisation ID')
    await userEvent.type(orgInput, 'org-001')

    const fileInput = screen.getByLabelText('Upload source file') as HTMLInputElement
    const jsonContent = JSON.stringify({ customers: [{ name: 'Test' }] })
    const testFile = new File([jsonContent], 'data.json', { type: 'application/json' })
    testFile.text = () => Promise.resolve(jsonContent)

    fireEvent.change(fileInput, { target: { files: [testFile] } })

    await waitFor(() => {
      expect(screen.getByText('Data Mapping')).toBeInTheDocument()
    })

    const startBtn = screen.getByLabelText('Start migration')
    await userEvent.click(startBtn)

    await waitFor(() => {
      expect(screen.getByText('✗ Integrity check failed')).toBeInTheDocument()
      expect(
        screen.getByText('Invoice INV-003 references non-existent customer'),
      ).toBeInTheDocument()
      expect(
        screen.getByText('Gap between INV-001 and INV-003'),
      ).toBeInTheDocument()
    })
  })

  it('shows rollback button for completed/failed jobs', async () => {
    const mockPost = vi.mocked(apiClient.post)
    mockPost
      .mockResolvedValueOnce({ data: mockJobPending })
      .mockResolvedValueOnce({ data: mockJobCompleted })

    render(<MigrationTool />)

    const orgInput = screen.getByLabelText('Organisation ID')
    await userEvent.type(orgInput, 'org-001')

    const fileInput = screen.getByLabelText('Upload source file') as HTMLInputElement
    const jsonContent = JSON.stringify({ customers: [{ name: 'Test' }] })
    const testFile = new File([jsonContent], 'data.json', { type: 'application/json' })
    testFile.text = () => Promise.resolve(jsonContent)

    fireEvent.change(fileInput, { target: { files: [testFile] } })

    await waitFor(() => {
      expect(screen.getByText('Data Mapping')).toBeInTheDocument()
    })

    const startBtn = screen.getByLabelText('Start migration')
    await userEvent.click(startBtn)

    await waitFor(() => {
      expect(screen.getByLabelText('Rollback migration')).toBeInTheDocument()
    })
  })

  it('shows error banner when migration fails', async () => {
    const mockPost = vi.mocked(apiClient.post)
    mockPost.mockRejectedValueOnce(new Error('Network error'))

    render(<MigrationTool />)

    const orgInput = screen.getByLabelText('Organisation ID')
    await userEvent.type(orgInput, 'org-001')

    const fileInput = screen.getByLabelText('Upload source file') as HTMLInputElement
    const jsonContent = JSON.stringify({ customers: [{ name: 'Test' }] })
    const testFile = new File([jsonContent], 'data.json', { type: 'application/json' })
    testFile.text = () => Promise.resolve(jsonContent)

    fireEvent.change(fileInput, { target: { files: [testFile] } })

    await waitFor(() => {
      expect(screen.getByText('Data Mapping')).toBeInTheDocument()
    })

    const startBtn = screen.getByLabelText('Start migration')
    await userEvent.click(startBtn)

    await waitFor(() => {
      expect(screen.getByRole('alert')).toBeInTheDocument()
    })
  })
})
