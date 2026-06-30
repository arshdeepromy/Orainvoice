import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import AgreementsDashboardPage from './AgreementsDashboardPage'
import {
  listEnvelopes,
  getEnvelope,
  downloadSignedDocument,
  voidEnvelope,
} from '@/api/esign'
import type { EnvelopeListResult, EnvelopeOut } from '@/api/esign'

/**
 * AgreementsDashboardPage unit tests (feature: esignature-integration, task 17.5).
 *
 * The page consumes the typed esign API client directly, so the client module
 * is mocked here — the real `ENVELOPE_STATUSES` / type exports are preserved
 * via `importOriginal` and only the network functions are replaced with spies.
 * No router / context providers are required: the page renders standalone and
 * the embedded VoidAgreementModal stays closed (its `envelope` is null) so it
 * never touches the (mocked) `voidEnvelope`.
 *
 * Coverage (R11.1 / R11.5):
 *   - renders the empty state when the org has no envelopes
 *   - renders the error state with a Retry button on a fetch failure, and the
 *     Retry button re-issues the list request (recovering to a populated list)
 *
 * _Requirements: 11.1, 11.5_
 */

vi.mock('@/api/esign', async (importOriginal) => {
  const actual = await importOriginal<typeof import('@/api/esign')>()
  return {
    ...actual,
    listEnvelopes: vi.fn(),
    getEnvelope: vi.fn(),
    downloadSignedDocument: vi.fn(),
    voidEnvelope: vi.fn(),
  }
})

const mockListEnvelopes = vi.mocked(listEnvelopes)
const mockGetEnvelope = vi.mocked(getEnvelope)
const mockDownloadSignedDocument = vi.mocked(downloadSignedDocument)
const mockVoidEnvelope = vi.mocked(voidEnvelope)

/** An empty, healthy list result (no rows, no fail-closed filter error). */
function emptyResult(): EnvelopeListResult {
  return { items: [], total: 0, error: null }
}

function sampleEnvelope(overrides: Partial<EnvelopeOut> = {}): EnvelopeOut {
  return {
    id: 'env-1',
    agreement_type: 'sales_agreement',
    originating_entity_type: 'invoice',
    originating_entity_id: 'inv-9',
    status: 'sent',
    recipients: [
      {
        id: 'rec-1',
        name: 'Jane Doe',
        email: 'jane@example.com',
        signing_role: 'SIGNER',
        recipient_status: 'pending',
      },
    ],
    signed_document_url: null,
    created_at: '2026-01-01T00:00:00Z',
    updated_at: '2026-01-01T00:00:00Z',
    ...overrides,
  }
}

beforeEach(() => {
  vi.clearAllMocks()
  mockGetEnvelope.mockResolvedValue(sampleEnvelope())
  mockDownloadSignedDocument.mockResolvedValue(new Blob())
  mockVoidEnvelope.mockResolvedValue(sampleEnvelope({ status: 'voided' }))
  // jsdom does not implement object-URL APIs the preview/download paths use.
  window.URL.createObjectURL = vi.fn(() => 'blob:mock-url')
  window.URL.revokeObjectURL = vi.fn()
})

describe('AgreementsDashboardPage — empty state', () => {
  it('renders the empty state when the org has no envelopes', async () => {
    mockListEnvelopes.mockResolvedValue(emptyResult())

    render(<AgreementsDashboardPage />)

    expect(await screen.findByTestId('empty-state')).toBeInTheDocument()
    expect(screen.getByText('No agreements yet')).toBeInTheDocument()
    // No table rows and no error banner.
    expect(screen.queryByRole('table')).toBeNull()
    expect(screen.queryByRole('alert')).toBeNull()
    expect(mockListEnvelopes).toHaveBeenCalledTimes(1)
  })
})

describe('AgreementsDashboardPage — error + retry', () => {
  it('renders the error state with a Retry button on fetch failure', async () => {
    mockListEnvelopes.mockRejectedValue(new Error('boom'))

    render(<AgreementsDashboardPage />)

    const alert = await screen.findByRole('alert')
    expect(alert).toHaveTextContent('We could not load your agreements. Please try again.')
    expect(screen.getByRole('button', { name: 'Retry' })).toBeInTheDocument()
    // No empty state while the page is in the error state.
    expect(screen.queryByTestId('empty-state')).toBeNull()
  })

  it('re-issues the list request when Retry is clicked, recovering to a populated list', async () => {
    const user = userEvent.setup()
    // First load fails; the retry succeeds with one envelope.
    mockListEnvelopes
      .mockRejectedValueOnce(new Error('boom'))
      .mockResolvedValueOnce({ items: [sampleEnvelope()], total: 1, error: null })

    render(<AgreementsDashboardPage />)

    await screen.findByRole('button', { name: 'Retry' })
    expect(mockListEnvelopes).toHaveBeenCalledTimes(1)

    await user.click(screen.getByRole('button', { name: 'Retry' }))

    // The retry re-issued the request and the error cleared into a real row.
    await waitFor(() => expect(mockListEnvelopes).toHaveBeenCalledTimes(2))
    expect(await screen.findByRole('table')).toBeInTheDocument()
    // Scope to the table: the agreement type now also appears as a Type-filter
    // chip, so assert the row cell specifically.
    expect(within(screen.getByRole('table')).getByText('Sales Agreement')).toBeInTheDocument()
    expect(
      screen.queryByText('We could not load your agreements. Please try again.'),
    ).toBeNull()
  })
})

describe('AgreementsDashboardPage — type filter', () => {
  it('filters rows client-side by agreement type', async () => {
    const user = userEvent.setup()
    mockListEnvelopes.mockResolvedValue({
      items: [
        sampleEnvelope({ id: 'env-nda', agreement_type: 'nda' }),
        sampleEnvelope({ id: 'env-sales', agreement_type: 'sales_agreement' }),
      ],
      total: 2,
      error: null,
    })

    render(<AgreementsDashboardPage />)

    const table = await screen.findByRole('table')
    // Both rows present initially.
    expect(within(table).getByText('Nda')).toBeInTheDocument()
    expect(within(table).getByText('Sales Agreement')).toBeInTheDocument()

    // Activate the "Nda" type chip (inside the type-filter group).
    const typeGroup = screen.getByRole('group', { name: 'Filter by type' })
    await user.click(within(typeGroup).getByRole('button', { name: 'Nda' }))

    // Only the NDA row remains; no extra list request was issued (client-side).
    expect(within(screen.getByRole('table')).queryByText('Sales Agreement')).toBeNull()
    expect(within(screen.getByRole('table')).getByText('Nda')).toBeInTheDocument()
    expect(mockListEnvelopes).toHaveBeenCalledTimes(1)
  })
})

describe('AgreementsDashboardPage — signed-document preview', () => {
  it('opens a preview modal and renders the fetched signed PDF for a completed row', async () => {
    const user = userEvent.setup()
    mockListEnvelopes.mockResolvedValue({
      items: [sampleEnvelope({ id: 'env-done', status: 'completed', agreement_type: 'nda' })],
      total: 1,
      error: null,
    })

    render(<AgreementsDashboardPage />)

    await screen.findByRole('table')
    await user.click(screen.getByRole('button', { name: /Preview signed Nda document/i }))

    // The preview fetched the blob and rendered the inline PDF viewer.
    await waitFor(() => expect(mockDownloadSignedDocument).toHaveBeenCalledWith('env-done', expect.any(AbortSignal)))
    expect(await screen.findByTestId('signed-document-preview')).toBeInTheDocument()
  })
})
