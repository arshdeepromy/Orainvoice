/**
 * Tests for useRosterGridData (B4):
 *   - Happy path resolves with merged staff/entries/leave data.
 *   - AbortController cancels the in-flight request when the
 *     dependency changes (or the consumer unmounts).
 *
 * Validates: R2.7, R3.7, R16.1, R16.4.
 */

import { renderHook, waitFor, act } from '@testing-library/react'
import { describe, it, expect, vi, beforeEach } from 'vitest'

vi.mock('@/api/client', () => {
  const mockGet = vi.fn()
  return { default: { get: mockGet } }
})

import apiClient from '@/api/client'
import { useRosterGridData } from '../hooks/useRosterGridData'

type GetMock = ReturnType<typeof vi.fn>

const get = apiClient.get as unknown as GetMock

describe('useRosterGridData', () => {
  beforeEach(() => {
    vi.clearAllMocks()
  })

  it('resolves with merged staff, entries, and leave overlay map (happy path)', async () => {
    const staffPayload = {
      staff: [
        {
          id: 'staff-1',
          first_name: 'Alice',
          last_name: 'Smith',
          name: 'Alice Smith',
          position: 'Mechanic',
          is_active: true,
        },
      ],
      total: 1,
    }
    const entriesPayload = {
      entries: [
        {
          id: 'e1',
          org_id: 'o1',
          staff_id: 'staff-1',
          start_time: '2025-06-02T09:00:00Z',
          end_time: '2025-06-02T17:00:00Z',
          entry_type: 'job',
          status: 'scheduled',
          created_at: '2025-06-01T00:00:00Z',
          updated_at: '2025-06-01T00:00:00Z',
        },
      ],
      total: 1,
    }
    const leavePayload = {
      items: [
        {
          staff_id: 'staff-1',
          start_date: '2025-06-04',
          end_date: '2025-06-05',
          leave_type_code: 'annual',
          leave_type_name: 'Annual leave',
        },
      ],
      total: 1,
    }

    get.mockImplementation((url: string) => {
      if (url === '/staff') return Promise.resolve({ data: staffPayload })
      if (url === '/schedule')
        return Promise.resolve({ data: entriesPayload })
      if (url === '/leave/approvals')
        return Promise.resolve({ data: leavePayload })
      return Promise.reject(new Error(`unexpected url: ${url}`))
    })

    const window = {
      start: new Date(2025, 5, 2, 0, 0, 0), // 2 Jun 2025 (Mon)
      end: new Date(2025, 5, 15, 0, 0, 0), // 15 Jun 2025 (Sun)
    }

    const { result } = renderHook(() => useRosterGridData(window))

    await waitFor(() => expect(result.current.isLoading).toBe(false))

    expect(result.current.error).toBeNull()
    expect(result.current.staff).toHaveLength(1)
    expect(result.current.entries).toHaveLength(1)

    // Leave overlay covers exactly 2 dates (Jun 4 + Jun 5).
    const overlay = result.current.leaveByStaffDate.get('staff-1')
    expect(overlay).toBeDefined()
    expect(overlay?.size).toBe(2)
    expect(overlay?.get('2025-06-04')?.leave_type_label).toBe('Annual leave')
    expect(overlay?.get('2025-06-05')?.leave_type_label).toBe('Annual leave')
    expect(overlay?.get('2025-06-06')).toBeUndefined()
  })

  it('aborts the in-flight request when visibleWindow changes', async () => {
    const seenSignals: AbortSignal[] = []

    get.mockImplementation((_url: string, config: { signal?: AbortSignal }) => {
      if (config?.signal) seenSignals.push(config.signal)
      return new Promise((resolve) => {
        // Resolve only once aborted, so the test can observe the abort.
        config?.signal?.addEventListener('abort', () => {
          resolve({ data: {} })
        })
        // Never resolve otherwise — caller must change deps to abort.
      })
    })

    const initial = {
      start: new Date(2025, 5, 2),
      end: new Date(2025, 5, 15),
    }
    const next = {
      start: new Date(2025, 5, 16),
      end: new Date(2025, 5, 29),
    }

    const { rerender } = renderHook(
      ({ window }) => useRosterGridData(window),
      { initialProps: { window: initial } },
    )

    // 3 in-flight signals from the initial render (staff, entries, leave).
    await waitFor(() => expect(seenSignals.length).toBeGreaterThanOrEqual(3))
    const firstBatch = seenSignals.slice(0, 3)

    // Change visibleWindow → previous controller should abort.
    act(() => rerender({ window: next }))

    await waitFor(() => {
      expect(firstBatch.every((s) => s.aborted)).toBe(true)
    })
  })
})
