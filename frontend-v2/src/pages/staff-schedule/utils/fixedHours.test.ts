/**
 * Unit tests for the fixed-working-arrangement helpers used by the
 * Roster Grid Editor to pre-populate and lock fixed-hours staff rows.
 */
import { describe, it, expect } from 'vitest'
import {
  dayKeyForDate,
  isFixedArrangement,
  fixedShiftForDate,
  staffDisplayName,
  fixedHoursEditMessage,
} from './fixedHours'

// 2024-01-01 is a Monday; 2024-01-07 is a Sunday.
const MON = new Date(2024, 0, 1)
const SUN = new Date(2024, 0, 7)

describe('dayKeyForDate', () => {
  it('maps Monday to "monday" and Sunday to "sunday"', () => {
    expect(dayKeyForDate(MON)).toBe('monday')
    expect(dayKeyForDate(SUN)).toBe('sunday')
  })
})

describe('isFixedArrangement', () => {
  it('is true only for working_arrangement "fixed" (case-insensitive)', () => {
    expect(isFixedArrangement({ working_arrangement: 'fixed' })).toBe(true)
    expect(isFixedArrangement({ working_arrangement: 'Fixed' })).toBe(true)
    expect(isFixedArrangement({ working_arrangement: 'rostered' })).toBe(false)
    expect(isFixedArrangement({ working_arrangement: 'casual' })).toBe(false)
    expect(isFixedArrangement({ working_arrangement: undefined })).toBe(false)
  })
})

describe('fixedShiftForDate', () => {
  const fixedStaff = {
    working_arrangement: 'fixed',
    availability_schedule: {
      monday: { start: '09:00', end: '17:00' },
      tuesday: { start: '', end: '' },
    },
  }

  it('returns the configured shift for a fixed staff member on a defined day', () => {
    expect(fixedShiftForDate(fixedStaff, MON)).toEqual({
      start: '09:00',
      end: '17:00',
    })
  })

  it('returns null on a day with no configured hours', () => {
    // Tuesday has empty start/end → treated as not configured.
    expect(fixedShiftForDate(fixedStaff, new Date(2024, 0, 2))).toBeNull()
    // Sunday is absent from the schedule entirely.
    expect(fixedShiftForDate(fixedStaff, SUN)).toBeNull()
  })

  it('returns null for non-fixed staff even with an availability schedule', () => {
    expect(
      fixedShiftForDate(
        {
          working_arrangement: 'rostered',
          availability_schedule: { monday: { start: '09:00', end: '17:00' } },
        },
        MON,
      ),
    ).toBeNull()
  })

  it('returns null when there is no availability schedule', () => {
    expect(
      fixedShiftForDate({ working_arrangement: 'fixed', availability_schedule: undefined }, MON),
    ).toBeNull()
  })
})

describe('staffDisplayName', () => {
  it('prefers the resolved name', () => {
    expect(
      staffDisplayName({ name: 'Romy Sidhu', first_name: 'Romy', last_name: 'Sidhu' }),
    ).toBe('Romy Sidhu')
  })
})

describe('fixedHoursEditMessage', () => {
  it('names the staff member and directs to the Staff working-arrangement edit', () => {
    const msg = fixedHoursEditMessage({
      name: 'Romy Sidhu',
      first_name: 'Romy',
      last_name: 'Sidhu',
    })
    expect(msg).toContain('Romy Sidhu')
    expect(msg).toContain('fixed hours')
    expect(msg).toContain('Staff')
    expect(msg).toContain('Working arrangement')
  })
})
