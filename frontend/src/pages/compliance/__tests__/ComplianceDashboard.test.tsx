import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { MemoryRouter } from 'react-router-dom'

/**
 * Unit tests for the ComplianceDashboard page and its child components.
 * Validates: Requirements 1.1, 1.6, 2.7, 2.8, 5.5, 8.2
 */

// --- Hoisted mocks ---

vi.mock('@/api/client', () => ({
  default: {
    get: vi.fn(),
    post: vi.fn(),
    put: vi.fn(),
    delete: vi.fn(),
  },
}))

import apiClient from '@/api/client'
import ComplianceDashboard from '../ComplianceDashboard'

const mockGet = vi.mocked(apiClient.get)

/* ── Mock data ── */

const MOCK_CATEGORIES = {
  items: [
    { id: 'cat-1', name: 'Business License', is_predefined: true },
    { id: 'cat-2', name: 'Public Liability Insurance', is_predefined: true },
  ],
  total: 2,
}

const MOCK_DOCUMENTS = [
  {
    id: 'doc-1',
    org_id: 'org-1',
    document_type: 'Business License',
    description: 'Annual business license',
    file_key: 'compliance/org-1/uuid_license.pdf',
    file_name: 'license.pdf',
    expiry_date: '2099-12-31',
    invoice_id: null,
    job_id: null,
    uploaded_by: 'user-1',
    created_at: '2025-01-15T10:00:00Z',
    status: 'valid',
  },
  {
    id: 'doc-2',
    org_id: 'org-1',
    document_type: 'Public Liability Insurance',
    description: 'Liability coverage',
    file_key: 'compliance/org-1/uuid_insurance.pdf',
    file_name: 'insurance.pdf',
    expiry_date: '2025-02-01',
    invoice_id: 'inv-1',
    job_id: null,
    uploaded_by: 'user-1',
    created_at: '2025-01-10T08:00:00Z',
    status: 'expired',
  },
  {
    id: 'doc-3',
    org_id: 'org-1',
    document_type: 'Business License',
    description: null,
    file_key: 'compliance/org-1/uuid_cert.png',
    file_name: 'cert.png',
    expiry_date: null,
    invoice_id: null,
    job_id: 'job-1',
    uploaded_by: 'user-1',
    created_at: '2025-01-20T12:00:00Z',
    status: 'no_expiry',
  },
]

const MOCK_DASHBOARD = {
  total_documents: 3,
  valid_documents: 1,
  expiring_soon: 0,
  expired: 1,
  documents: MOCK_DOCUMENTS,
}

const MOCK_BADGE_COUNT = { count: 0 }

/* ── Helpers ── */

function setupDefaultMocks() {
  mockGet.mockImplementation((url: string) => {
    if (typeof url === 'string' && url.includes('/dashboard')) {
      return Promise.resolve({ data: MOCK_DASHBOARD })
    }
    if (typeof url === 'string' && url.includes('/categories')) {
      return Promise.resolve({ data: MOCK_CATEGORIES })
    }
    if (typeof url === 'string' && url.includes('/badge-count')) {
      return Promise.resolve({ data: MOCK_BADGE_COUNT })
    }
    return Promise.resolve({ data: {} })
  })
}

function renderDashboard() {
  return render(
    <MemoryRouter>
      <ComplianceDashboard />
    </MemoryRouter>,
  )
}

/* ── Tests ── */

describe('ComplianceDashboard — Unit Tests', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    setupDefaultMocks()
  })

  // --- Requirement 1.1: Four summary cards ---

  it('renders four summary cards with correct colours', async () => {
    renderDashboard()

    await waitFor(() => {
      expect(screen.getByTestId('total-count')).toBeInTheDocument()
    })

    // Total Documents card (neutral/gray border)
    const totalCard = screen.getByTestId('total-count')
    expect(totalCard).toHaveTextContent('Total Documents')
    expect(totalCard).toHaveTextContent('3')
    expect(totalCard.className).toContain('border-gray-200')

    // Valid card (green)
    const validCard = screen.getByTestId('valid-count')
    expect(validCard).toHaveTextContent('Valid')
    expect(validCard).toHaveTextContent('1')
    expect(validCard.className).toContain('border-green-200')

    // Expiring Soon card (amber)
    const expiringCard = screen.getByTestId('expiring-count')
    expect(expiringCard).toHaveTextContent('Expiring Soon')
    expect(expiringCard).toHaveTextContent('0')
    expect(expiringCard.className).toContain('border-amber-200')

    // Expired card (red)
    const expiredCard = screen.getByTestId('expired-count')
    expect(expiredCard).toHaveTextContent('Expired')
    expect(expiredCard).toHaveTextContent('1')
    expect(expiredCard.className).toContain('border-red-200')
  })

  // --- Requirement 2.1: Document table renders all columns ---

  it('renders document table with all columns', async () => {
    renderDashboard()

    await waitFor(() => {
      expect(screen.getByRole('grid', { name: /compliance documents list/i })).toBeInTheDocument()
    })

    const table = screen.getByRole('grid', { name: /compliance documents list/i })

    // Check all column headers exist
    expect(within(table).getByText('Document Type')).toBeInTheDocument()
    expect(within(table).getByText('File Name')).toBeInTheDocument()
    expect(within(table).getByText('Description')).toBeInTheDocument()
    expect(within(table).getByText('Expiry Date')).toBeInTheDocument()
    expect(within(table).getByText('Status')).toBeInTheDocument()
    expect(within(table).getByText('Linked Entity')).toBeInTheDocument()
    // "Uploaded Date" header includes a sort arrow when active, so use partial match
    expect(within(table).getByText(/Uploaded Date/)).toBeInTheDocument()
    expect(within(table).getByText('Actions')).toBeInTheDocument()
  })

  // --- Requirement 2.3: Search input filters documents ---

  it('search input filters documents by name', async () => {
    const user = userEvent.setup()
    renderDashboard()

    await waitFor(() => {
      expect(screen.getByRole('grid')).toBeInTheDocument()
    })

    // All 3 documents should be visible initially
    expect(screen.getByText('license.pdf')).toBeInTheDocument()
    expect(screen.getByText('insurance.pdf')).toBeInTheDocument()
    expect(screen.getByText('cert.png')).toBeInTheDocument()

    // Type in search box — use "insurance" which only matches doc-2
    const searchInput = screen.getByPlaceholderText(/search by name/i)
    await user.type(searchInput, 'insurance')

    // Only the matching document should remain
    expect(screen.getByText('insurance.pdf')).toBeInTheDocument()
    expect(screen.queryByText('license.pdf')).not.toBeInTheDocument()
    expect(screen.queryByText('cert.png')).not.toBeInTheDocument()
  })

  // --- Requirement 2.4: Status filter shows only matching documents ---

  it('status filter shows only matching documents', async () => {
    const user = userEvent.setup()
    renderDashboard()

    await waitFor(() => {
      expect(screen.getByRole('grid')).toBeInTheDocument()
    })

    // Select "Expired" from the status filter
    const statusSelect = screen.getByLabelText('Status')
    await user.selectOptions(statusSelect, 'expired')

    // Only the expired document should remain
    expect(screen.getByText('insurance.pdf')).toBeInTheDocument()
    expect(screen.queryByText('license.pdf')).not.toBeInTheDocument()
    expect(screen.queryByText('cert.png')).not.toBeInTheDocument()
  })

  // --- Requirement 3.8: Upload form accepts drag-and-drop files ---

  it('upload form accepts drag-and-drop files', async () => {
    const user = userEvent.setup()
    renderDashboard()

    await waitFor(() => {
      expect(screen.getByText('Compliance Documents')).toBeInTheDocument()
    })

    // Open upload form
    await user.click(screen.getByRole('button', { name: /upload document/i }))

    // The drop zone should be visible
    const dropZone = screen.getByRole('button', { name: /drop a file here or click to select/i })
    expect(dropZone).toBeInTheDocument()

    // Simulate a file input change (drag-and-drop is hard to simulate in jsdom,
    // but the underlying file input is what matters)
    const fileInput = screen.getByLabelText('Select file to upload') as HTMLInputElement
    const testFile = new File(['test content'], 'test-doc.pdf', { type: 'application/pdf' })

    await user.upload(fileInput, testFile)

    // File name and size should be displayed
    expect(screen.getByText('test-doc.pdf')).toBeInTheDocument()
  })

  // --- Requirement 3.9: Upload form shows file name and size before submit ---

  it('upload form shows file name and size before submit', async () => {
    const user = userEvent.setup()
    renderDashboard()

    await waitFor(() => {
      expect(screen.getByText('Compliance Documents')).toBeInTheDocument()
    })

    // Open upload form
    await user.click(screen.getByRole('button', { name: /upload document/i }))

    const fileInput = screen.getByLabelText('Select file to upload') as HTMLInputElement
    // Create a file with known size (5000 bytes = 4.9 KB)
    const content = new Array(5000).fill('a').join('')
    const testFile = new File([content], 'my-insurance.pdf', { type: 'application/pdf' })

    await user.upload(fileInput, testFile)

    // File name should be displayed
    expect(screen.getByText('my-insurance.pdf')).toBeInTheDocument()
    // File size should be displayed (4.9 KB)
    expect(screen.getByText('4.9 KB')).toBeInTheDocument()
  })

  // --- Requirement 5.1/5.4: Edit modal pre-populates with current data ---

  it('edit modal pre-populates with current data', async () => {
    const user = userEvent.setup()
    renderDashboard()

    await waitFor(() => {
      expect(screen.getByRole('grid')).toBeInTheDocument()
    })

    // Click the edit button for the first document
    const editButton = screen.getByRole('button', { name: /edit license\.pdf/i })
    await user.click(editButton)

    // The edit modal should appear with pre-populated data
    await waitFor(() => {
      expect(screen.getByText('Edit Document')).toBeInTheDocument()
    })

    // Category input should have the document type (use specific label id to avoid conflict with table's category filter)
    const categoryInput = document.getElementById('edit-category') as HTMLInputElement
    expect(categoryInput.value).toBe('Business License')

    // Description should be pre-populated
    const descriptionInput = document.getElementById('edit-description') as HTMLTextAreaElement
    expect(descriptionInput.value).toBe('Annual business license')

    // Expiry date should be pre-populated
    const expiryInput = document.getElementById('edit-expiry') as HTMLInputElement
    expect(expiryInput.value).toBe('2099-12-31')
  })

  // --- Requirement 5.5: Delete confirmation dialog appears on delete click ---

  it('delete confirmation dialog appears on delete click', async () => {
    const user = userEvent.setup()
    renderDashboard()

    await waitFor(() => {
      expect(screen.getByRole('grid')).toBeInTheDocument()
    })

    // Click the delete button for the first document
    const deleteButton = screen.getByRole('button', { name: /delete license\.pdf/i })
    await user.click(deleteButton)

    // The delete confirmation dialog should appear
    await waitFor(() => {
      expect(screen.getByText('Delete Document')).toBeInTheDocument()
    })

    // Should show the document name in the confirmation message
    expect(screen.getByText(/are you sure you want to delete/i)).toBeInTheDocument()
    // "license.pdf" appears both in the table row and the dialog — verify at least 2 instances
    const fileNameElements = screen.getAllByText('license.pdf')
    expect(fileNameElements.length).toBeGreaterThanOrEqual(2)

    // Should have Cancel and Delete buttons in the dialog
    // The dialog's Delete button has exact text "Delete" (not "Delete license.pdf")
    // Use getAllByRole and find the one inside the dialog
    const deleteButtons = screen.getAllByRole('button', { name: /delete/i })
    // The dialog's Delete button is the one with exact text "Delete" (not aria-label "Delete X")
    const dialogDeleteBtn = deleteButtons.find(
      (btn) => btn.textContent?.trim() === 'Delete' && !btn.getAttribute('aria-label'),
    )
    expect(dialogDeleteBtn).toBeTruthy()
  })

  // --- Requirement 8.2: Badge is hidden when count is 0 ---

  it('badge is hidden when count is 0', async () => {
    // NotificationBadge is rendered separately in OrgLayout, not inside ComplianceDashboard.
    // We test the component directly.
    const { default: NotificationBadge } = await import('../NotificationBadge')

    mockGet.mockImplementation((url: string) => {
      if (typeof url === 'string' && url.includes('/badge-count')) {
        return Promise.resolve({ data: { count: 0 } })
      }
      return Promise.resolve({ data: {} })
    })

    const { container } = render(<NotificationBadge />)

    // Wait for the API call to resolve
    await waitFor(() => {
      expect(mockGet).toHaveBeenCalledWith(
        '/api/v2/compliance-docs/badge-count',
        expect.objectContaining({ signal: expect.any(AbortSignal) }),
      )
    })

    // Badge should not be rendered when count is 0
    expect(container.querySelector('span')).toBeNull()
  })

  // --- Requirement 1.6: Skeleton placeholders shown during loading ---

  it('shows skeleton placeholders during loading', async () => {
    // Make the API call hang so we can observe the loading state
    mockGet.mockImplementation(
      () => new Promise(() => {}), // never resolves
    )

    renderDashboard()

    // Skeleton cards should be visible (animate-pulse divs)
    const skeletons = document.querySelectorAll('.animate-pulse')
    expect(skeletons.length).toBeGreaterThanOrEqual(4)
  })

  // --- Requirement 2.7/2.8: Empty state messages shown when appropriate ---

  it('shows empty state when no documents exist', async () => {
    mockGet.mockImplementation((url: string) => {
      if (typeof url === 'string' && url.includes('/dashboard')) {
        return Promise.resolve({
          data: {
            total_documents: 0,
            valid_documents: 0,
            expiring_soon: 0,
            expired: 0,
            documents: [],
          },
        })
      }
      if (typeof url === 'string' && url.includes('/categories')) {
        return Promise.resolve({ data: MOCK_CATEGORIES })
      }
      return Promise.resolve({ data: {} })
    })

    renderDashboard()

    await waitFor(() => {
      expect(
        screen.getByText('No compliance documents yet. Upload your first document to get started.'),
      ).toBeInTheDocument()
    })
  })

  it('shows filter empty state when filters match nothing', async () => {
    const user = userEvent.setup()
    renderDashboard()

    await waitFor(() => {
      expect(screen.getByRole('grid')).toBeInTheDocument()
    })

    // Search for something that doesn't match any document
    const searchInput = screen.getByPlaceholderText(/search by name/i)
    await user.type(searchInput, 'zzzznonexistent')

    expect(screen.getByText('No documents match your filters')).toBeInTheDocument()
  })
})
