import { render, screen, cleanup } from '@testing-library/react'
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import * as fc from 'fast-check'

// Feature: universal-items-catalogue, Property 8: Items page displays all table columns
// **Validates: Requirement 3.2**

/* ------------------------------------------------------------------ */
/*  Mocks                                                              */
/* ------------------------------------------------------------------ */

vi.mock('@/api/client', () => ({
  default: { get: vi.fn(), post: vi.fn(), put: vi.fn(), delete: vi.fn() },
}))

import apiClient from '@/api/client'
import ItemsPage from '@/pages/items/ItemsPage'

/* ------------------------------------------------------------------ */
/*  Types                                                              */
/* ------------------------------------------------------------------ */

interface ItemData {
  id: string
  name: string
  description: string | null
  default_price: string
  is_gst_exempt: boolean
  category: string | null
  is_active: boolean
  created_at: string
  updated_at: string
}

/* ------------------------------------------------------------------ */
/*  Generators                                                         */
/* ------------------------------------------------------------------ */

const safeNameArb = fc
  .stringMatching(/^[A-Za-z][A-Za-z0-9 ]{1,20}$/)
  .map((s) => s.trim())
  .filter((s) => s.length >= 2)

const safeCategoryArb = fc
  .stringMatching(/^[A-Za-z][A-Za-z0-9 ]{1,15}$/)
  .map((s) => s.trim())
  .filter((s) => s.length >= 2)

const itemArb: fc.Arbitrary<ItemData> = fc.record({
  id: fc.uuid(),
  name: safeNameArb,
  description: fc.constant(null),
  default_price: fc
    .float({ min: Math.fround(0.01), max: Math.fround(99999.99), noNaN: true })
    .map((n) => n.toFixed(2)),
  is_gst_exempt: fc.boolean(),
  category: fc.option(safeCategoryArb, { nil: null }),
  is_active: fc.boolean(),
  created_at: fc.constant('2026-01-01T00:00:00Z'),
  updated_at: fc.constant('2026-01-01T00:00:00Z'),
})

const itemListArb = fc.array(itemArb, { minLength: 1, maxLength: 5 })

/* ------------------------------------------------------------------ */
/*  Property 8: Items page displays all table columns                  */
/*  **Validates: Requirement 3.2**                                     */
/* ------------------------------------------------------------------ */

describe('Property 8: Items page displays all table columns', () => {
  beforeEach(() => {
    vi.clearAllMocks()
  })

  it(
    'renders name, category, price, GST exempt, and status for each item',
    async () => {
      await fc.assert(
        fc.asyncProperty(itemListArb, async (items) => {
          cleanup()
          vi.clearAllMocks()

          ;(apiClient.get as ReturnType<typeof vi.fn>).mockResolvedValue({
            data: { items, total: items.length },
          })

          render(<ItemsPage />)

          // Wait for the table to render
          await screen.findByRole('grid')

          // Get data rows (skip header)
          const rows = screen.getAllByRole('row').slice(1)
          expect(rows.length).toBe(items.length)

          for (let i = 0; i < items.length; i++) {
            const item = items[i]
            const cells = rows[i].querySelectorAll('td')

            // Column 0: Name — cell contains item name
            expect(cells[0].textContent).toContain(item.name)

            // Column 1: Category — shows category or em-dash
            if (item.category) {
              expect(cells[1].textContent).toContain(item.category)
            } else {
              expect(cells[1].textContent).toContain('—')
            }

            // Column 2: Price (ex-GST) — shows $<price>
            expect(cells[2].textContent).toContain(item.default_price)

            // Column 3: GST Exempt — Badge shows "Exempt" or "Incl."
            const gstText = item.is_gst_exempt ? 'Exempt' : 'Incl.'
            expect(cells[3].textContent).toContain(gstText)

            // Column 4: Status — Badge shows "Active" or "Inactive"
            const statusText = item.is_active ? 'Active' : 'Inactive'
            expect(cells[4].textContent).toContain(statusText)
          }

          cleanup()
        }),
        { numRuns: 5 },
      )
    },
    { timeout: 60_000 },
  )
})

// Feature: universal-items-catalogue, Property 9: BookingForm uses Items API
// **Validates: Requirement 5.4, 5.5**

import { fireEvent, waitFor } from '@testing-library/react'
import BookingForm from '@/pages/bookings/BookingForm'

/* ------------------------------------------------------------------ */
/*  Additional mocks for BookingForm dependencies                      */
/* ------------------------------------------------------------------ */

vi.mock('@/contexts/ModuleContext', () => ({
  useModules: () => ({ isEnabled: () => false, enabledModules: [] }),
}))

vi.mock('@/components/common/ModuleGate', () => ({
  ModuleGate: ({ children: _children }: { children: React.ReactNode }) => null,
}))

vi.mock('@/components/vehicles/VehicleLiveSearch', () => ({
  VehicleLiveSearch: () => null,
}))

vi.mock('@/utils/bookingFormHelpers', () => ({
  shouldTriggerCustomerSearch: () => false,
  shouldShowAddNewOption: (query: string, count: number) => query.trim().length >= 2 && count === 0,
  getPrePopulatedFirstName: () => '',
}))

/* ------------------------------------------------------------------ */
/*  Generators for Property 9                                          */
/* ------------------------------------------------------------------ */

const searchQueryArb = fc
  .stringMatching(/^[A-Za-z][A-Za-z0-9 ]{1,15}$/)
  .map((s) => s.trim())
  .filter((s) => s.length >= 2)

const inlineItemArb = fc.record({
  name: fc
    .stringMatching(/^[A-Za-z][A-Za-z0-9 ]{1,20}$/)
    .map((s) => s.trim())
    .filter((s) => s.length >= 1),
  default_price: fc
    .float({ min: Math.fround(0.01), max: Math.fround(9999.99), noNaN: true })
    .map((n) => n.toFixed(2)),
  category: fc.option(
    fc
      .stringMatching(/^[A-Za-z][A-Za-z0-9 ]{1,15}$/)
      .map((s) => s.trim())
      .filter((s) => s.length >= 1),
    { nil: '' },
  ),
})

/* ------------------------------------------------------------------ */
/*  Property 9: BookingForm uses Items API                             */
/*  **Validates: Requirement 5.4, 5.5**                                */
/* ------------------------------------------------------------------ */

describe('Property 9: BookingForm uses Items API', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    vi.useFakeTimers()
  })

  afterEach(() => {
    vi.useRealTimers()
  })

  it(
    'typeahead calls GET /catalogue/items with active_only=true for any search query',
    async () => {
      await fc.assert(
        fc.asyncProperty(searchQueryArb, async (query) => {
          cleanup()
          vi.clearAllMocks()

          const getMock = apiClient.get as ReturnType<typeof vi.fn>
          getMock.mockResolvedValue({ data: { items: [], total: 0 } })

          // Also mock plan-features endpoint
          getMock.mockImplementation((url: string) => {
            if (url === '/org/plan-features') {
              return Promise.resolve({ data: { sms_included: false } })
            }
            return Promise.resolve({ data: { items: [], total: 0 } })
          })

          render(
            <BookingForm open={true} onClose={() => {}} onSaved={() => {}} />,
          )

          // Type in the item search field
          const itemInput = screen.getByLabelText('Search item')
          fireEvent.change(itemInput, { target: { value: query } })

          // Advance timers past the 300ms debounce
          await vi.advanceTimersByTimeAsync(350)

          // Verify GET /catalogue/items was called with active_only=true
          const getCalls = getMock.mock.calls.filter(
            (call: unknown[]) => call[0] === '/catalogue/items',
          )
          expect(getCalls.length).toBeGreaterThanOrEqual(1)
          const params = getCalls[0][1]?.params
          expect(params).toBeDefined()
          expect(params.active_only).toBe(true)

          cleanup()
        }),
        { numRuns: 5 },
      )
    },
    { timeout: 60_000 },
  )

  it(
    'inline creation calls POST /catalogue/items with name, default_price, and category',
    async () => {
      vi.useRealTimers()

      await fc.assert(
        fc.asyncProperty(inlineItemArb, async (itemData) => {
          cleanup()
          vi.clearAllMocks()

          const getMock = apiClient.get as ReturnType<typeof vi.fn>
          const postMock = apiClient.post as ReturnType<typeof vi.fn>

          getMock.mockImplementation((url: string) => {
            if (url === '/org/plan-features') {
              return Promise.resolve({ data: { sms_included: false } })
            }
            return Promise.resolve({ data: { items: [], total: 0 } })
          })

          postMock.mockResolvedValue({
            data: {
              item: {
                id: 'new-id',
                name: itemData.name,
                default_price: itemData.default_price,
                category: itemData.category || null,
                is_active: true,
              },
            },
          })

          render(
            <BookingForm open={true} onClose={() => {}} onSaved={() => {}} />,
          )

          // Type a search query to trigger the dropdown
          const itemInput = screen.getByLabelText('Search item')
          fireEvent.change(itemInput, { target: { value: 'zz' } })

          // Wait for dropdown to appear after debounce, then click "Add new item"
          const addNewOption = await screen.findByText('+ Add new item', {}, { timeout: 3000 })
          fireEvent.click(addNewOption)

          // Fill in the inline form
          const nameInput = screen.getByLabelText('Item name')
          const priceInput = screen.getByLabelText('Item default price')
          const categoryInput = screen.getByLabelText('Item category')

          fireEvent.change(nameInput, { target: { value: itemData.name } })
          fireEvent.change(priceInput, { target: { value: itemData.default_price } })
          fireEvent.change(categoryInput, { target: { value: itemData.category } })

          // Click "Create Item"
          const createBtn = screen.getByText('Create Item')
          fireEvent.click(createBtn)

          await waitFor(() => {
            const postCalls = postMock.mock.calls.filter(
              (call: unknown[]) => call[0] === '/catalogue/items',
            )
            expect(postCalls.length).toBeGreaterThanOrEqual(1)
            const body = postCalls[0][1]
            expect(body.name).toBe(itemData.name)
            expect(body.default_price).toBe(itemData.default_price)
            expect(body.category).toBe(itemData.category || null)
          })

          cleanup()
        }),
        { numRuns: 5 },
      )
    },
    { timeout: 60_000 },
  )
})
