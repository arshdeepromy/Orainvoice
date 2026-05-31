/**
 * Tests for the new optional `defaultValues` prop on
 * `ScheduleEntryModal` (Workstream B / task B6a).
 *
 * Two cases:
 *   - Create mode (entry == null) with `defaultValues` → form fields
 *     pre-populated from the defaults (staff_id, start_time,
 *     end_time, entry_type).
 *   - Edit mode (entry != null) with `defaultValues` also supplied →
 *     the entry's values win; defaults are ignored.
 *
 * Validates: R4.1, R4.2.
 */

import { render, screen, waitFor, cleanup } from '@testing-library/react'
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'

vi.mock('@/api/client', () => {
  const mockGet = vi.fn()
  const mockPost = vi.fn()
  const mockPut = vi.fn()
  return { default: { get: mockGet, post: mockPost, put: mockPut } }
})

import apiClient from '@/api/client'
import ScheduleEntryModal from '../ScheduleEntryModal'

const mockStaff = [
  { id: 'abc', name: 'Alice Adams', position: 'Mechanic' },
  { id: 'xyz', name: 'Bob Brown', position: null },
]

const get = apiClient.get as ReturnType<typeof vi.fn>

beforeEach(() => {
  vi.clearAllMocks()
  get.mockImplementation((url: string) => {
    if (url === '/api/v2/schedule/templates') {
      return Promise.resolve({ data: { templates: [], total: 0 } })
    }
    return Promise.resolve({ data: { staff: mockStaff } })
  })
})

afterEach(() => {
  cleanup()
})

describe('ScheduleEntryModal — defaultValues prop (B6a)', () => {
  it('pre-populates form fields in create mode when defaultValues are provided', async () => {
    render(
      <ScheduleEntryModal
        open={true}
        onClose={() => {}}
        onSave={() => {}}
        entry={null}
        defaultValues={{
          staff_id: 'abc',
          start_time: '2026-06-01T09:00',
          end_time: '2026-06-01T17:00',
          entry_type: 'booking',
        }}
      />,
    )

    // Wait for staff dropdown to populate.
    await waitFor(() => {
      const select = screen.getByLabelText('Staff Member') as HTMLSelectElement
      expect(select.options.length).toBeGreaterThan(1)
    })

    const staffSelect = screen.getByLabelText(
      'Staff Member',
    ) as HTMLSelectElement
    expect(staffSelect.value).toBe('abc')

    const startInput = screen.getByLabelText('Start Time') as HTMLInputElement
    expect(startInput.value).toBe('2026-06-01T09:00')

    const endInput = screen.getByLabelText('End Time') as HTMLInputElement
    expect(endInput.value).toBe('2026-06-01T17:00')

    const typeSelect = screen.getByLabelText('Entry Type') as HTMLSelectElement
    expect(typeSelect.value).toBe('booking')
  })

  it('ignores defaultValues when an `entry` is supplied (edit mode wins)', async () => {
    const entry = {
      id: 'entry-1',
      staff_id: 'xyz',
      job_id: null,
      booking_id: null,
      title: 'Existing entry',
      description: null,
      start_time: '2025-06-15T08:00:00',
      end_time: '2025-06-15T12:00:00',
      entry_type: 'job',
      status: 'scheduled',
      recurrence_group_id: null,
    }

    render(
      <ScheduleEntryModal
        open={true}
        onClose={() => {}}
        onSave={() => {}}
        entry={entry}
        defaultValues={{
          staff_id: 'abc',
          start_time: '2026-06-01T09:00',
          end_time: '2026-06-01T17:00',
          entry_type: 'booking',
        }}
      />,
    )

    await waitFor(() => {
      const select = screen.getByLabelText('Staff Member') as HTMLSelectElement
      expect(select.options.length).toBeGreaterThan(1)
    })

    const staffSelect = screen.getByLabelText(
      'Staff Member',
    ) as HTMLSelectElement
    expect(staffSelect.value).toBe('xyz')

    const typeSelect = screen.getByLabelText('Entry Type') as HTMLSelectElement
    expect(typeSelect.value).toBe('job')

    // Datetime inputs use `<input type="datetime-local">` and the
    // existing modal converts ISO strings via `toDatetimeLocal`.
    // We don't pin the exact local string here (depends on the test
    // runner's timezone); we just assert the entry's value populated
    // (i.e. NOT the defaultValues string).
    const startInput = screen.getByLabelText('Start Time') as HTMLInputElement
    expect(startInput.value).not.toBe('2026-06-01T09:00')
    expect(startInput.value).not.toBe('')
  })
})
