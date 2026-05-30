// Feature: quote-settings-parity, Property 4: Detail-page rendering gates
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { render, cleanup, act, screen, waitFor } from '@testing-library/react'
import * as fc from 'fast-check'

// ─── Mocks ───────────────────────────────────────────────────────────────────

const mockGet = vi.fn()
const mockPost = vi.fn()
const mockPut = vi.fn()
const mockDelete = vi.fn()
vi.mock('../../../api/client', () => ({
  default: {
    get: (...args: unknown[]) => mockGet(...args),
    post: (...args: unknown[]) => mockPost(...args),
    put: (...args: unknown[]) => mockPut(...args),
    delete: (...args: unknown[]) => mockDelete(...args),
  },
}))

const mockNavigate = vi.fn()
vi.mock('react-router-dom', () => ({
  useNavigate: () => mockNavigate,
  useSearchParams: () => [new URLSearchParams(), vi.fn()],
}))

vi.mock('../../../contexts/TenantContext', () => ({
  useTenant: () => ({ tradeFamily: 'automotive-transport' }),
}))

// QuoteAttachmentList performs its own API fetch on mount. Stub it out so the
// only network traffic in this test is the quote fetch we control.
vi.mock('../../../components/quotes/QuoteAttachmentList', () => ({
  default: () => null,
}))
vi.mock('../../../components/quotes/CancelQuoteModal', () => ({
  default: () => null,
}))

import QuoteDetail from '../QuoteDetail'

// ─── Helpers ─────────────────────────────────────────────────────────────────

function buildQuote(opts: {
  notes: string | null
  payment_terms_text: string | null
  terms_and_conditions_enabled: boolean
  terms_and_conditions: string | null
}) {
  return {
    id: 'q-1',
    org_id: 'org-1',
    customer_id: 'c-1',
    quote_number: 'QT-0001',
    vehicle_rego: null,
    vehicle_make: null,
    vehicle_model: null,
    vehicle_year: null,
    project_id: null,
    status: 'draft',
    valid_until: '2026-12-31',
    subtotal: '0.00',
    gst_amount: '0.00',
    total: '0.00',
    discount_type: null,
    discount_value: '0',
    discount_amount: '0',
    shipping_charges: '0',
    adjustment: '0',
    notes: opts.notes,
    // Keep `terms` null so the meta-panel "Terms :" tile does not render. The
    // long-form Terms & Conditions section is gated solely by the new
    // terms_and_conditions / terms_and_conditions_enabled fields.
    terms: null,
    subject: null,
    acceptance_token: null,
    converted_invoice_id: null,
    line_items: [],
    created_by: 'u-1',
    created_at: '2026-05-01T00:00:00Z',
    updated_at: '2026-05-01T00:00:00Z',
    order_number: null,
    salesperson_id: null,
    salesperson_name: null,
    additional_vehicles: [],
    fluid_usage: [],
    attachment_count: 0,
    customer_name: 'Test Customer',
    customer_email: 't@t.com',
    payment_terms_text: opts.payment_terms_text,
    terms_and_conditions: opts.terms_and_conditions,
    terms_and_conditions_enabled: opts.terms_and_conditions_enabled,
  }
}

function setupApiMocks(quote: ReturnType<typeof buildQuote>) {
  mockGet.mockImplementation((url: string) => {
    if (url === `/quotes/${quote.id}`) {
      return Promise.resolve({ data: quote })
    }
    return Promise.resolve({ data: {} })
  })
}

// ─── Tests ───────────────────────────────────────────────────────────────────

describe('QuoteDetail — rendering gates (Property 4)', () => {
  beforeEach(() => {
    vi.clearAllMocks()
  })
  afterEach(() => {
    cleanup()
  })

  /**
   * Property 4 — detail-page rendering gates.
   * **Validates: Requirements 2.1, 2.2, 4.1, 4.2, 7.1, 7.2, 7.3**
   *
   * For any (notes, payment_terms_text, terms_and_conditions_enabled,
   * terms_and_conditions) tuple, the rendered QuoteDetail shows:
   *   - the Notes label iff notes is a non-empty string,
   *   - the Payment Terms label iff payment_terms_text is non-empty,
   *   - the Terms & Conditions label iff
   *     terms_and_conditions_enabled && terms_and_conditions is non-empty.
   */
  it('Property 4: renders Notes / Payment Terms / Terms & Conditions iff their gates pass', async () => {
    await fc.assert(
      fc.asyncProperty(
        fc.option(fc.string({ maxLength: 30 }), { nil: null }),
        fc.option(fc.string({ maxLength: 30 }), { nil: null }),
        fc.boolean(),
        fc.option(fc.string({ maxLength: 30 }), { nil: null }),
        async (
          notes,
          payment_terms_text,
          terms_and_conditions_enabled,
          terms_and_conditions,
        ) => {
          const quote = buildQuote({
            notes,
            payment_terms_text,
            terms_and_conditions_enabled,
            terms_and_conditions,
          })
          setupApiMocks(quote)

          await act(async () => {
            render(<QuoteDetail quoteId={quote.id} />)
          })
          // Wait for the quote fetch and resulting render.
          await waitFor(() => {
            expect(mockGet).toHaveBeenCalledWith(`/quotes/${quote.id}`)
          })
          // Allow the post-fetch state update to flush.
          await act(async () => {
            await new Promise((r) => setTimeout(r, 0))
          })

          // JS truthiness gates as used by QuoteDetail.tsx (`{quote.notes && (...)}`).
          const notesVisible = !!notes && notes.length > 0
          const payTermsVisible = !!payment_terms_text && payment_terms_text.length > 0
          const tcVisible = !!(
            terms_and_conditions_enabled &&
            terms_and_conditions &&
            terms_and_conditions.length > 0
          )

          // Strict equality matching: the meta-panel uses the distinct text
          // "Terms :" (with a trailing space and colon), while the long-form
          // section uses "Terms & Conditions" — different strings, so
          // `queryAllByText('Terms & Conditions')` only matches the section.
          const notesMatches = screen.queryAllByText('Notes')
          const payTermsMatches = screen.queryAllByText('Payment Terms')
          const tcMatches = screen.queryAllByText('Terms & Conditions')

          if (notesVisible) {
            expect(notesMatches.length).toBeGreaterThanOrEqual(1)
          } else {
            expect(notesMatches.length).toBe(0)
          }

          if (payTermsVisible) {
            expect(payTermsMatches.length).toBeGreaterThanOrEqual(1)
          } else {
            expect(payTermsMatches.length).toBe(0)
          }

          if (tcVisible) {
            expect(tcMatches.length).toBeGreaterThanOrEqual(1)
          } else {
            expect(tcMatches.length).toBe(0)
          }

          cleanup()
        },
      ),
      { numRuns: 100 },
    )
  })
})
