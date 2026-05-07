import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import * as fc from 'fast-check'
import { render, fireEvent, screen, act, cleanup } from '@testing-library/react'
import { KioskCheckInForm } from '../KioskCheckInForm'
import type { KioskFormData, AutoFillMatch } from '../types'

// Mock the API modules
vi.mock('../api', () => ({
  lookupCustomer: vi.fn(),
}))

vi.mock('@/api/client', () => ({
  default: {
    post: vi.fn(),
    get: vi.fn(),
  },
}))

import { lookupCustomer } from '../api'

const mockedLookupCustomer = vi.mocked(lookupCustomer)

// ---------------------------------------------------------------------------
// Arbitraries
// ---------------------------------------------------------------------------

/** Generate a non-empty string for name fields (1-30 printable ASCII chars) */
const nameArb = fc
  .string({ minLength: 1, maxLength: 30 })
  .filter((s) => s.trim().length > 0 && /^[\x20-\x7E]+$/.test(s))

/** Generate a valid phone number (7+ digits) */
const phoneArb = fc
  .string({ minLength: 7, maxLength: 15 })
  .map((s) => s.replace(/[^0-9]/g, ''))
  .filter((s) => s.length >= 7)

/** Generate a valid email address */
const emailArb = fc
  .tuple(
    fc.string({ minLength: 1, maxLength: 10 }).filter((s) => /^[a-z0-9]+$/.test(s)),
    fc.string({ minLength: 2, maxLength: 8 }).filter((s) => /^[a-z]+$/.test(s)),
    fc.constantFrom('com', 'co.nz', 'org', 'net'),
  )
  .map(([user, domain, tld]) => `${user}@${domain}.${tld}`)

/**
 * Generate an AutoFillMatch with a mix of null and non-null fields.
 * first_name and last_name are always non-null (required by the type).
 * phone and email are nullable.
 */
const autoFillMatchArb: fc.Arbitrary<AutoFillMatch> = fc.record({
  id: fc.uuid(),
  first_name: nameArb,
  last_name: nameArb,
  phone: fc.option(phoneArb, { nil: null }),
  email: fc.option(emailArb, { nil: null }),
})

/**
 * Generate an AutoFillMatch that has at least one non-null nullable field,
 * ensuring the auto-fill has something meaningful to populate beyond names.
 */
const autoFillMatchWithFieldsArb: fc.Arbitrary<AutoFillMatch> = autoFillMatchArb.filter(
  (m) => m.phone !== null || m.email !== null,
)

// ---------------------------------------------------------------------------
// Helper: Wrapper component that manages controlled form state
// ---------------------------------------------------------------------------

function TestWrapper({
  match,
  onAutoFillApplied,
}: {
  match: AutoFillMatch
  onAutoFillApplied: (data: KioskFormData) => void
}) {
  const [formData, setFormData] = React.useState<KioskFormData>({
    first_name: '',
    last_name: '',
    phone: '',
    email: '',
  })

  const handleFormDataChange = (data: KioskFormData) => {
    setFormData(data)
    onAutoFillApplied(data)
  }

  return (
    <KioskCheckInForm
      formData={formData}
      onFormDataChange={handleFormDataChange}
      onSuccess={() => {}}
      onError={() => {}}
      onBack={() => {}}
    />
  )
}

import React from 'react'

// ---------------------------------------------------------------------------
// Property-based tests
// ---------------------------------------------------------------------------

describe('KioskCheckInForm — Property-Based Tests', () => {
  beforeEach(() => {
    vi.useFakeTimers()
    vi.clearAllMocks()
  })

  afterEach(() => {
    vi.useRealTimers()
    cleanup()
  })

  // Feature: kiosk-vehicle-checkin, Property 9: Auto-fill populates all non-null fields
  // **Validates: Requirements 9.3**
  describe('Property 9: Auto-fill populates all non-null fields', () => {
    it('for any customer record, tapping auto-fill populates every non-null field into form state', async () => {
      await fc.assert(
        fc.asyncProperty(autoFillMatchWithFieldsArb, async (match) => {
          vi.clearAllMocks()
          cleanup()

          const onAutoFillApplied = vi.fn()

          // Mock lookupCustomer to return our generated match
          mockedLookupCustomer.mockResolvedValue({
            items: [match],
            total: 1,
          })

          render(
            <TestWrapper match={match} onAutoFillApplied={onAutoFillApplied} />,
          )

          // Type a valid phone number to trigger the debounced lookup
          const phoneInput = screen.getByLabelText(/phone/i)
          await act(async () => {
            fireEvent.change(phoneInput, { target: { value: '0211234567' } })
          })

          // Advance past the 500ms debounce and flush microtasks
          await act(async () => {
            vi.advanceTimersByTime(600)
            await vi.runAllTimersAsync()
          })

          // The auto-fill banner should now be visible
          const autoFillButton = screen.queryByRole('button', { name: /auto-fill/i })
          if (!autoFillButton) {
            // If banner didn't appear, try flushing again
            await act(async () => {
              await Promise.resolve()
            })
          }

          const banner = screen.getByRole('button', { name: /auto-fill/i })

          // Clear mock calls from the phone input change
          onAutoFillApplied.mockClear()

          // Tap the auto-fill banner
          await act(async () => {
            fireEvent.click(banner)
          })

          // Verify onAutoFillApplied was called with all non-null fields populated
          expect(onAutoFillApplied).toHaveBeenCalled()
          const lastCall = onAutoFillApplied.mock.calls[onAutoFillApplied.mock.calls.length - 1][0] as KioskFormData

          // first_name and last_name are always non-null in AutoFillMatch
          expect(lastCall.first_name).toBe(match.first_name)
          expect(lastCall.last_name).toBe(match.last_name)

          // phone: if non-null in match, should be populated
          if (match.phone !== null) {
            expect(lastCall.phone).toBe(match.phone)
          }

          // email: if non-null in match, should be populated
          if (match.email !== null) {
            expect(lastCall.email).toBe(match.email)
          }
        }),
        { numRuns: 100 },
      )
    }, 120000) // Extended timeout for 100 property runs with async rendering
  })
})
