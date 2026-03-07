import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, it, expect, vi, beforeEach } from 'vitest'

/**
 * Validates: Requirements 69.1-69.5, 78.2, 78.3
 */

vi.mock('@/api/client', () => {
  const mockGet = vi.fn()
  const mockPost = vi.fn()
  return {
    default: { get: mockGet, post: mockPost },
  }
})

import apiClient from '@/api/client'
import DataPage from '../pages/data/DataPage'
import DataImport from '../pages/data/DataImport'
import DataExport from '../pages/data/DataExport'

/* ------------------------------------------------------------------ */
/*  Helpers                                                            */
/* ------------------------------------------------------------------ */

function createCSVFile(content: string, name = 'test.csv'): File {
  return new File([content], name, { type: 'text/csv' })
}

const CUSTOMER_CSV = `first_name,last_name,email,phone
John,Smith,john@example.com,021-555-0001
Jane,Doe,jane@example.com,021-555-0002
Bad,,invalid-email,`

const VEHICLE_CSV = `rego,make,model,year
ABC123,Toyota,Corolla,2020
XYZ789,Honda,Civic,2019`

/* ------------------------------------------------------------------ */
/*  DataPage tests                                                     */
/* ------------------------------------------------------------------ */

describe('DataPage', () => {
  beforeEach(() => { vi.clearAllMocks() })

  it('renders heading and Import/Export tabs', () => {
    render(<DataPage />)
    expect(screen.getByRole('heading', { name: 'Data Management' })).toBeInTheDocument()
    expect(screen.getByRole('tab', { name: 'Import' })).toBeInTheDocument()
    expect(screen.getByRole('tab', { name: 'Export' })).toBeInTheDocument()
  })

  it('defaults to Import tab', () => {
    render(<DataPage />)
    expect(screen.getByRole('tab', { name: 'Import' })).toHaveAttribute('aria-selected', 'true')
  })

  it('switches to Export tab on click', async () => {
    render(<DataPage />)
    const user = userEvent.setup()
    await user.click(screen.getByRole('tab', { name: 'Export' }))
    expect(screen.getByRole('tab', { name: 'Export' })).toHaveAttribute('aria-selected', 'true')
  })
})

/* ------------------------------------------------------------------ */
/*  DataImport tests                                                   */
/* ------------------------------------------------------------------ */

describe('DataImport', () => {
  beforeEach(() => { vi.clearAllMocks() })

  it('renders import type selector and upload area', () => {
    render(<DataImport />)
    expect(screen.getByLabelText('Import Type')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Upload CSV file' })).toBeInTheDocument()
  })

  it('shows field mapping after CSV upload (Req 69.1)', async () => {
    render(<DataImport />)
    const user = userEvent.setup()
    const file = createCSVFile(CUSTOMER_CSV)
    const input = screen.getByLabelText('Select CSV file')
    await user.upload(input, file)

    await waitFor(() => {
      expect(screen.getByText('Map Fields')).toBeInTheDocument()
    })
    expect(screen.getByText(/3\s*rows detected/)).toBeInTheDocument()
    // Auto-mapped fields should be present
    expect(screen.getByText('first_name')).toBeInTheDocument()
    expect(screen.getByText('last_name')).toBeInTheDocument()
  })

  it('shows validation preview with error highlighting (Req 69.3)', async () => {
    render(<DataImport />)
    const user = userEvent.setup()
    const file = createCSVFile(CUSTOMER_CSV)
    await user.upload(screen.getByLabelText('Select CSV file'), file)

    await waitFor(() => {
      expect(screen.getByText('Map Fields')).toBeInTheDocument()
    })

    await user.click(screen.getByRole('button', { name: /Validate/i }))

    await waitFor(() => {
      expect(screen.getByText('Validation Preview')).toBeInTheDocument()
    })
    // Should show valid and error counts
    expect(screen.getByText(/2 valid/)).toBeInTheDocument()
    expect(screen.getByText(/1 with errors/)).toBeInTheDocument()
    // Error row should be highlighted
    const table = screen.getByRole('grid', { name: 'Validation preview' })
    expect(table).toBeInTheDocument()
  })

  it('imports records and shows progress indicator (Req 78.3)', async () => {
    const mockResult = { total: 3, imported: 2, skipped: 1, errors: [{ row: 4, reason: 'Last name is required' }] }
    ;(apiClient.post as ReturnType<typeof vi.fn>).mockResolvedValue({ data: mockResult })

    render(<DataImport />)
    const user = userEvent.setup()
    await user.upload(screen.getByLabelText('Select CSV file'), createCSVFile(CUSTOMER_CSV))

    await waitFor(() => { expect(screen.getByText('Map Fields')).toBeInTheDocument() })
    await user.click(screen.getByRole('button', { name: /Validate/i }))
    await waitFor(() => { expect(screen.getByText('Validation Preview')).toBeInTheDocument() })

    await user.click(screen.getByRole('button', { name: /Import 2 Records/i }))

    // Should show results summary after import completes
    await waitFor(() => {
      expect(screen.getByText('Import Complete')).toBeInTheDocument()
    })
    expect(screen.getByText('Total Rows')).toBeInTheDocument()
    expect(screen.getByText('Imported')).toBeInTheDocument()
    expect(screen.getByText('Skipped')).toBeInTheDocument()
  })

  it('provides error report download when import has errors (Req 69.5)', async () => {
    const mockResult = { total: 3, imported: 2, skipped: 1, errors: [{ row: 4, reason: 'Last name is required' }] }
    ;(apiClient.post as ReturnType<typeof vi.fn>).mockResolvedValue({ data: mockResult })

    render(<DataImport />)
    const user = userEvent.setup()
    await user.upload(screen.getByLabelText('Select CSV file'), createCSVFile(CUSTOMER_CSV))
    await waitFor(() => { expect(screen.getByText('Map Fields')).toBeInTheDocument() })
    await user.click(screen.getByRole('button', { name: /Validate/i }))
    await waitFor(() => { expect(screen.getByText('Validation Preview')).toBeInTheDocument() })
    await user.click(screen.getByRole('button', { name: /Import 2 Records/i }))

    await waitFor(() => { expect(screen.getByText('Import Complete')).toBeInTheDocument() })
    expect(screen.getByRole('button', { name: /Download Error Report/i })).toBeInTheDocument()
  })

  it('supports vehicle import type (Req 69.2)', async () => {
    render(<DataImport />)
    const user = userEvent.setup()

    // Switch to vehicles
    await user.selectOptions(screen.getByLabelText('Import Type'), 'vehicles')

    const file = createCSVFile(VEHICLE_CSV)
    await user.upload(screen.getByLabelText('Select CSV file'), file)

    await waitFor(() => {
      expect(screen.getByText('Map Fields')).toBeInTheDocument()
    })
    expect(screen.getByText('rego')).toBeInTheDocument()
  })

  it('rejects non-CSV files', async () => {
    render(<DataImport />)
    const user = userEvent.setup()
    const file = new File(['data'], 'test.txt', { type: 'text/plain' })
    const input = screen.getByLabelText('Select CSV file')
    // Temporarily remove accept attribute so userEvent can upload the file
    input.removeAttribute('accept')
    await user.upload(input, file)
    expect(screen.getByText('Please select a CSV file.')).toBeInTheDocument()
  })

  it('requires at least one field mapping', async () => {
    render(<DataImport />)
    const user = userEvent.setup()
    const csv = `col1,col2\na,b`
    await user.upload(screen.getByLabelText('Select CSV file'), createCSVFile(csv))

    await waitFor(() => { expect(screen.getByText('Map Fields')).toBeInTheDocument() })

    // Clear all mappings by selecting skip for each
    const selects = screen.getAllByRole('combobox')
    for (const select of selects) {
      await user.selectOptions(select, '')
    }

    await user.click(screen.getByRole('button', { name: /Validate/i }))
    expect(screen.getByText('Please map at least one field.')).toBeInTheDocument()
  })
})

/* ------------------------------------------------------------------ */
/*  DataExport tests                                                   */
/* ------------------------------------------------------------------ */

describe('DataExport', () => {
  beforeEach(() => { vi.clearAllMocks() })

  it('renders export buttons for customers, vehicles, and invoices (Req 69.4)', () => {
    render(<DataExport />)
    expect(screen.getByText('Customers')).toBeInTheDocument()
    expect(screen.getByText('Vehicles')).toBeInTheDocument()
    expect(screen.getByText('Invoices')).toBeInTheDocument()
    expect(screen.getAllByRole('button', { name: 'Export CSV' })).toHaveLength(3)
  })

  it('triggers CSV download on export click', async () => {
    const csvBlob = new Blob(['id,name\n1,Test'], { type: 'text/csv' })
    ;(apiClient.get as ReturnType<typeof vi.fn>).mockResolvedValue({ data: csvBlob })

    // Mock URL.createObjectURL and revokeObjectURL
    const mockUrl = 'blob:test'
    const createObjectURL = vi.fn(() => mockUrl)
    const revokeObjectURL = vi.fn()
    globalThis.URL.createObjectURL = createObjectURL
    globalThis.URL.revokeObjectURL = revokeObjectURL

    render(<DataExport />)
    const user = userEvent.setup()
    const buttons = screen.getAllByRole('button', { name: 'Export CSV' })
    await user.click(buttons[0]) // customers

    await waitFor(() => {
      expect(apiClient.get).toHaveBeenCalledWith('/data/export/customers', { responseType: 'blob' })
    })
    expect(screen.getByText('Customers exported successfully.')).toBeInTheDocument()
  })

  it('shows error on export failure', async () => {
    ;(apiClient.get as ReturnType<typeof vi.fn>).mockRejectedValue(new Error('Network error'))

    render(<DataExport />)
    const user = userEvent.setup()
    const buttons = screen.getAllByRole('button', { name: 'Export CSV' })
    await user.click(buttons[0])

    await waitFor(() => {
      expect(screen.getByText(/Failed to export customers/i)).toBeInTheDocument()
    })
  })
})
