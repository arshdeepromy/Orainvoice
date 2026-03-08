import { describe, it, expect } from 'vitest'
import * as fc from 'fast-check'
import {
  detectOverlap,
  aggregateTimeByProject,
  canConvertToInvoice,
  type TimeRange,
  type AggregationEntry,
} from '../utils/timeTrackingCalcs'

// Feature: production-readiness-gaps, Property 12: Time entry overlap detection
// Feature: production-readiness-gaps, Property 13: Time entry aggregation is correct
// Feature: production-readiness-gaps, Property 14: Invoiced time entries cannot be double-billed
// **Validates: Requirements 7.3, 7.4, 7.5, 7.6**

/* ------------------------------------------------------------------ */
/*  Generators                                                         */
/* ------------------------------------------------------------------ */

/** Arbitrary time range: start is a timestamp, end = start + positive duration */
const timeRangeArb: fc.Arbitrary<TimeRange> = fc
  .tuple(
    fc.integer({ min: 0, max: 1_000_000_000 }),
    fc.integer({ min: 1, max: 86_400_000 }),
  )
  .map(([startMs, durationMs]) => ({
    start: new Date(startMs),
    end: new Date(startMs + durationMs),
  }))

/** Arbitrary list of time ranges */
const timeRangeListArb = fc.array(timeRangeArb, { minLength: 0, maxLength: 20 })

/** Arbitrary project id */
const projectIdArb = fc.constantFrom('proj-a', 'proj-b', 'proj-c', 'proj-d')

/** Arbitrary aggregation entry */
const aggregationEntryArb: fc.Arbitrary<AggregationEntry> = fc.record({
  project_id: projectIdArb,
  hours: fc.double({ min: 0, max: 1000, noNaN: true, noDefaultInfinity: true }),
  billable: fc.boolean(),
  rate: fc.double({ min: 0, max: 500, noNaN: true, noDefaultInfinity: true }),
})

/** Arbitrary list of aggregation entries */
const aggregationEntryListArb = fc.array(aggregationEntryArb, { minLength: 0, maxLength: 30 })

/** Arbitrary time entry status */
const statusArb = fc.constantFrom('draft', 'billable', 'invoiced', 'approved')

/* ------------------------------------------------------------------ */
/*  Property 12: Time entry overlap detection                          */
/* ------------------------------------------------------------------ */

describe('Property 12: Time entry overlap detection', () => {
  it('detectOverlap correctly identifies all overlapping pairs', () => {
    fc.assert(
      fc.property(timeRangeListArb, (entries) => {
        const result = detectOverlap(entries)

        // Verify every returned pair actually overlaps
        for (const pair of result) {
          const a = entries[pair.index1]
          const b = entries[pair.index2]
          expect(a.start < b.end && b.start < a.end).toBe(true)
        }

        // Verify no overlapping pair is missed
        for (let i = 0; i < entries.length; i++) {
          for (let j = i + 1; j < entries.length; j++) {
            const a = entries[i]
            const b = entries[j]
            const overlaps = a.start < b.end && b.start < a.end
            const found = result.some(
              (p) => p.index1 === i && p.index2 === j,
            )
            expect(found).toBe(overlaps)
          }
        }
      }),
      { numRuns: 100 },
    )
  })

  it('non-overlapping entries produce empty result', () => {
    fc.assert(
      fc.property(
        fc.array(fc.integer({ min: 1, max: 100 }), { minLength: 0, maxLength: 10 }),
        (durations) => {
          // Build sequential non-overlapping entries
          const entries: TimeRange[] = []
          let cursor = 0
          for (const dur of durations) {
            entries.push({
              start: new Date(cursor),
              end: new Date(cursor + dur),
            })
            cursor += dur + 1 // gap of 1ms ensures no overlap
          }
          const result = detectOverlap(entries)
          expect(result).toHaveLength(0)
        },
      ),
      { numRuns: 100 },
    )
  })

  it('empty input returns empty result', () => {
    expect(detectOverlap([])).toEqual([])
  })

  it('single entry returns empty result', () => {
    fc.assert(
      fc.property(timeRangeArb, (entry) => {
        expect(detectOverlap([entry])).toEqual([])
      }),
      { numRuns: 100 },
    )
  })
})

/* ------------------------------------------------------------------ */
/*  Property 13: Time entry aggregation is correct                     */
/* ------------------------------------------------------------------ */

describe('Property 13: Time entry aggregation is correct', () => {
  it('totalHours = billableHours + nonBillableHours per project', () => {
    fc.assert(
      fc.property(aggregationEntryListArb, (entries) => {
        const result = aggregateTimeByProject(entries)
        for (const projectId of Object.keys(result)) {
          const agg = result[projectId]
          expect(agg.totalHours).toBeCloseTo(
            agg.billableHours + agg.nonBillableHours,
            5,
          )
        }
      }),
      { numRuns: 100 },
    )
  })

  it('totalCost = sum of (billableHours × rate) per project', () => {
    fc.assert(
      fc.property(aggregationEntryListArb, (entries) => {
        const result = aggregateTimeByProject(entries)

        // Compute expected cost per project manually
        const expectedCost: Record<string, number> = {}
        for (const entry of entries) {
          if (!expectedCost[entry.project_id]) {
            expectedCost[entry.project_id] = 0
          }
          if (entry.billable) {
            expectedCost[entry.project_id] += entry.hours * entry.rate
          }
        }

        for (const projectId of Object.keys(result)) {
          expect(result[projectId].totalCost).toBeCloseTo(
            expectedCost[projectId] ?? 0,
            5,
          )
        }
      }),
      { numRuns: 100 },
    )
  })

  it('all projects in input appear in output', () => {
    fc.assert(
      fc.property(aggregationEntryListArb, (entries) => {
        const result = aggregateTimeByProject(entries)
        const inputProjects = new Set(entries.map((e) => e.project_id))
        for (const pid of inputProjects) {
          expect(result).toHaveProperty(pid)
        }
      }),
      { numRuns: 100 },
    )
  })

  it('empty input returns empty result', () => {
    expect(aggregateTimeByProject([])).toEqual({})
  })
})

/* ------------------------------------------------------------------ */
/*  Property 14: Invoiced time entries cannot be double-billed         */
/* ------------------------------------------------------------------ */

describe('Property 14: Invoiced time entries cannot be double-billed', () => {
  it('canConvertToInvoice returns false for invoiced entries', () => {
    fc.assert(
      fc.property(fc.boolean(), (billable) => {
        expect(canConvertToInvoice({ billable, status: 'invoiced' })).toBe(false)
      }),
      { numRuns: 100 },
    )
  })

  it('canConvertToInvoice returns true for billable non-invoiced entries', () => {
    fc.assert(
      fc.property(
        statusArb.filter((s) => s !== 'invoiced'),
        (status) => {
          expect(canConvertToInvoice({ billable: true, status })).toBe(true)
        },
      ),
      { numRuns: 100 },
    )
  })

  it('canConvertToInvoice returns false for non-billable entries regardless of status', () => {
    fc.assert(
      fc.property(statusArb, (status) => {
        expect(canConvertToInvoice({ billable: false, status })).toBe(false)
      }),
      { numRuns: 100 },
    )
  })

  it('result is always a boolean', () => {
    fc.assert(
      fc.property(fc.boolean(), statusArb, (billable, status) => {
        const result = canConvertToInvoice({ billable, status })
        expect(typeof result).toBe('boolean')
      }),
      { numRuns: 100 },
    )
  })
})
