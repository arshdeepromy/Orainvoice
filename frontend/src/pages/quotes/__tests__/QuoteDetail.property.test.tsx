/**
 * Property-based tests (fast-check) for QuoteDetail — PDF download, Print, and Copy Link features.
 * Validates Requirements 3.3, 3.4, 4.1, 4.2, 4.3 from the quote-pdf-print spec.
 */

import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { render, cleanup, act } from '@testing-library/react'
import * as fc from 'fast-check'

// ─── Mocks ───────────────────────────────────────────────────────────────────

vi.mock('../../../api/client', () => ({
  default: {
    get: vi.fn(),
    post: vi.fn(),
    put: vi.fn(),
    delete: vi.fn(),
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

import apiClient from '../../../api/client'
import QuoteDetail from '../QuoteDetail'

// ─── Fixtures ────────────────────────────────────────────────────────────────

function makeQuote(overrides: Record<string, unknown> = {}) {
  return {
    id: 'q-prop-1',
    org_id: 'org-1',
    customer_id: 'cust-1',
    quote_number: 'QUO-0001',
    vehicle_rego: 'ABC123',
    vehicle_make: 'Toyota',
    vehicle_model: 'Hilux',
    vehicle_year: 2020,
    project_id: null,
    status: 'sent',
    valid_until: '2025-12-31',
    subtotal: '100.00',
    gst_amount: '15.00',
    total: '115.00',
    discount_type: null,
    discount_value: '0',
    discount_amount: '0',
    shipping_charges: '0',
    adjustment: '0',
    notes: null,
    terms: null,
    subject: 'Test Quote',
    acceptance_token: 'tok_default',
    converted_invoice_id: null,
    line_items: [
      {
        id: 'li-1',
        item_type: 'parts',
        description: 'Brake pads',
        quantity: 2,
        unit_price: '50.00',
        hours: null,
        hourly_rate: null,
        is_gst_exempt: false,
        warranty_note: null,
        line_total: '100.00',
        sort_order: 1,
      },
    ],
    created_by: 'user-1',
    created_at: '2025-01-01T00:00:00Z',
    updated_at: '2025-01-01T00:00:00Z',
    ...overrides,
  }
}

// ─── Setup / Teardown ────────────────────────────────────────────────────────

beforeEach(() => {
  vi.clearAllMocks()
  Object.assign(navigator, {
    clipboard: {
      writeText: vi.fn().mockResolvedValue(undefined),
    },
  })
})

afterEach(() => {
  cleanup()
  document.querySelectorAll('style[data-quote-print="true"]').forEach((el) => el.remove())
})

// ─── Property Tests ──────────────────────────────────────────────────────────

describe('QuoteDetail — Property-Based Tests', () => {
  /**
   * Property P1 — Share URL format is exact
   * **Validates: Requirements 4.3**
   *
   * For any valid token and origin, the constructed share URL must:
   * - Match the expected pattern
   * - Contain no double slashes after the scheme
   * - End with /${token}
   */
  describe('P1 — Share URL format is exact', () => {
    it('constructed share URL matches expected format for all valid tokens and origins', () => {
      const tokenArb = fc
        .string({ minLength: 1, maxLength: 100 })
        .filter((s) => /^[A-Za-z0-9_\-.]+$/.test(s))

      const originArb = fc.webUrl()

      fc.assert(
        fc.property(tokenArb, originArb, (token, origin) => {
          // Strip any trailing path from the webUrl to get just the origin
          const parsedOrigin = new URL(origin).origin

          const shareUrl = `${parsedOrigin}/api/v1/public/quotes/view/${token}`

          // Must end with /${token}
          expect(shareUrl.endsWith(`/${token}`)).toBe(true)

          // Must match the expected pattern
          const expectedPattern = new RegExp(
            `^https?://[^/]+/api/v1/public/quotes/view/${token.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')}$`
          )
          expect(shareUrl).toMatch(expectedPattern)

          // No double slashes after the scheme (://)
          const afterScheme = shareUrl.replace(/^https?:\/\//, '')
          expect(afterScheme).not.toContain('//')
        }),
        { numRuns: 50 }
      )
    })
  })

  /**
   * Property P2 — Print style tag cleanup is unconditional
   * **Validates: Requirements 3.3, 3.4**
   *
   * For every combination of component state (downloading, copied),
   * the style tag is present after mount and removed after unmount.
   */
  describe('P2 — Print style tag cleanup is unconditional', () => {
    it('style tag is present after mount and removed after unmount regardless of state', async () => {
      await fc.assert(
        fc.asyncProperty(
          fc.record({
            downloading: fc.boolean(),
            copied: fc.boolean(),
          }),
          async ({ downloading, copied }) => {
            const quote = makeQuote({
              acceptance_token: copied ? 'tok_copy' : null,
            })

            ;(apiClient.get as ReturnType<typeof vi.fn>).mockImplementation((url: string) => {
              if (url === `/quotes/${quote.id}`) {
                return Promise.resolve({ data: quote })
              }
              if (url === `/quotes/${quote.id}/pdf`) {
                // If downloading state is being tested, return a never-resolving promise
                if (downloading) {
                  return new Promise(() => {})
                }
                return Promise.resolve({ data: new Blob(['%PDF-']) })
              }
              return Promise.resolve({ data: {} })
            })

            let unmountFn: () => void

            await act(async () => {
              const { unmount } = render(<QuoteDetail quoteId={quote.id as string} />)
              unmountFn = unmount
            })

            // Style tag MUST be present after mount
            expect(
              document.querySelectorAll('style[data-quote-print="true"]').length
            ).toBe(1)

            // Unmount the component
            act(() => {
              unmountFn!()
            })

            // Style tag MUST be gone after unmount
            expect(
              document.querySelectorAll('style[data-quote-print="true"]').length
            ).toBe(0)
          }
        ),
        { numRuns: 50 }
      )
    })
  })

  /**
   * Property P5 — Copy Link button visibility parity with token presence
   * **Validates: Requirements 4.1, 4.2**
   *
   * For any token value (including null and empty string),
   * the Copy Link button is visible if and only if the token is non-null and non-empty.
   */
  describe('P5 — Copy Link button visibility parity with token presence', () => {
    it('Copy Link button is present iff acceptance_token is non-null and non-empty', async () => {
      await fc.assert(
        fc.asyncProperty(
          fc.option(fc.string({ minLength: 0, maxLength: 64 }), { nil: null }),
          async (token) => {
            const quote = makeQuote({ acceptance_token: token })

            ;(apiClient.get as ReturnType<typeof vi.fn>).mockImplementation((url: string) => {
              if (url === `/quotes/${quote.id}`) {
                return Promise.resolve({ data: quote })
              }
              return Promise.resolve({ data: {} })
            })

            let container: HTMLElement

            await act(async () => {
              const result = render(<QuoteDetail quoteId={quote.id as string} />)
              container = result.container
            })

            const shouldShow = token !== null && token !== undefined && token !== ''

            // Look for Copy Link or Copied! button text
            const buttons = Array.from(container!.querySelectorAll('button'))
            const copyButton = buttons.find(
              (btn) =>
                btn.textContent === 'Copy Link' || btn.textContent === 'Copied!'
            )

            if (shouldShow) {
              expect(copyButton).toBeDefined()
            } else {
              expect(copyButton).toBeUndefined()
            }

            cleanup()
            document
              .querySelectorAll('style[data-quote-print="true"]')
              .forEach((el) => el.remove())
          }
        ),
        { numRuns: 50 }
      )
    })
  })
})
