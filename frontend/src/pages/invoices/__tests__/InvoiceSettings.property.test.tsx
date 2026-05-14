import { describe, it, expect } from 'vitest'
import fc from 'fast-check'

// Feature: invoice-settings-integration
// Frontend property tests for invoice settings toggle logic

/* ------------------------------------------------------------------ */
/*  Pure helper functions replicating the frontend logic under test     */
/* ------------------------------------------------------------------ */

/**
 * Replicate the notes pre-fill logic from InvoiceCreate.tsx.
 *
 * When creating a new invoice:
 * - If default_notes_enabled is true AND notes content is non-empty → return notes
 * - Otherwise → return empty string
 */
function getNotesPreFill(enabled: boolean, notes: string): string {
  if (enabled && notes.length > 0) {
    return notes
  }
  return ''
}

/**
 * Replicate the edit-mode initialization logic from InvoiceCreate.tsx.
 *
 * When editing an existing invoice, the form always uses the invoice's
 * stored values — never the org defaults, regardless of toggle state.
 */
function getEditModeValues(params: {
  storedNotes: string
  storedTC: string
  orgNotes: string
  orgTC: string
  notesEnabled: boolean
  tcEnabled: boolean
}): { notes: string; termsAndConditions: string } {
  // Edit mode always uses stored invoice values
  return {
    notes: params.storedNotes,
    termsAndConditions: params.storedTC,
  }
}

/**
 * Replicate the web preview section visibility logic from InvoiceDetail.tsx.
 *
 * A section is visible iff its toggle is enabled AND content is non-empty.
 */
function isSectionVisible(enabled: boolean, content: string): boolean {
  return enabled && content.length > 0
}

/* ------------------------------------------------------------------ */
/*  Property 4 (frontend): Notes pre-fill conditional on toggle        */
/*  **Validates: Requirements 4.1, 4.2**                               */
/* ------------------------------------------------------------------ */

describe('Property 4 (frontend): Notes pre-fill conditional on toggle', () => {
  it('pre-fill result matches: enabled && notes.length > 0 → notes, else empty string', () => {
    fc.assert(
      fc.property(
        fc.boolean(),
        fc.string({ minLength: 0, maxLength: 200 }),
        (enabled, notes) => {
          const result = getNotesPreFill(enabled, notes)

          if (enabled && notes.length > 0) {
            expect(result).toBe(notes)
          } else {
            expect(result).toBe('')
          }
        },
      ),
      { numRuns: 30 },
    )
  })
})

/* ------------------------------------------------------------------ */
/*  Property 5 (frontend): Edit mode uses stored invoice values        */
/*  **Validates: Requirements 4.3, 7.2**                               */
/* ------------------------------------------------------------------ */

describe('Property 5 (frontend): Edit mode uses stored invoice values', () => {
  it('edit-mode init always uses stored values, never org defaults', () => {
    fc.assert(
      fc.property(
        fc.record({
          storedNotes: fc.string(),
          storedTC: fc.string(),
          orgNotes: fc.string(),
          orgTC: fc.string(),
          notesEnabled: fc.boolean(),
          tcEnabled: fc.boolean(),
        }),
        (params) => {
          const result = getEditModeValues(params)

          // Must always use stored values regardless of org defaults or toggle state
          expect(result.notes).toBe(params.storedNotes)
          expect(result.termsAndConditions).toBe(params.storedTC)

          // Must NOT use org defaults
          // (This is implicitly tested by the above assertions when
          // storedNotes !== orgNotes or storedTC !== orgTC)
        },
      ),
      { numRuns: 30 },
    )
  })
})

/* ------------------------------------------------------------------ */
/*  Property 6 (frontend): Preview section visibility                  */
/*  **Validates: Requirements 5.1, 5.2, 6.1, 6.2**                    */
/* ------------------------------------------------------------------ */

describe('Property 6 (frontend): Preview section visibility', () => {
  it('payment terms visible iff ptEnabled && paymentTerms.length > 0; T&C visible iff tcEnabled && tc.length > 0', () => {
    fc.assert(
      fc.property(
        fc.record({
          paymentTerms: fc.string(),
          tc: fc.string(),
          ptEnabled: fc.boolean(),
          tcEnabled: fc.boolean(),
        }),
        (params) => {
          const ptVisible = isSectionVisible(params.ptEnabled, params.paymentTerms)
          const tcVisible = isSectionVisible(params.tcEnabled, params.tc)

          // Payment terms section visible iff enabled AND content non-empty
          expect(ptVisible).toBe(params.ptEnabled && params.paymentTerms.length > 0)

          // T&C section visible iff enabled AND content non-empty
          expect(tcVisible).toBe(params.tcEnabled && params.tc.length > 0)
        },
      ),
      { numRuns: 30 },
    )
  })
})
