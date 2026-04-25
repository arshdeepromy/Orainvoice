import { describe, it, expect, vi, beforeEach } from 'vitest'
import {
  jobsToBoardItems,
  updateJobStatus,
} from '@/screens/jobs/JobBoardScreen'
import { formatElapsedTime } from '@/hooks/useTimer'
import type { Job } from '@shared/types/job'

/**
 * Unit tests for JobBoardScreen drag-drop status update and
 * JobDetailScreen timer.
 *
 * Requirements: 10.3, 10.4, 10.6
 */

// Mock apiClient
vi.mock('@/api/client', () => ({
  default: {
    patch: vi.fn(),
    post: vi.fn(),
    get: vi.fn(),
  },
}))

import apiClient from '@/api/client'

const mockedPatch = vi.mocked(apiClient.patch)

describe('JobBoardScreen', () => {
  beforeEach(() => {
    vi.clearAllMocks()
  })

  describe('jobsToBoardItems', () => {
    it('should convert jobs to board items with correct columnId from status', () => {
      const jobs: Job[] = [
        {
          id: 'j1',
          title: 'Fix engine',
          description: null,
          status: 'pending',
          customer_id: 'c1',
          customer_name: 'Alice',
          assigned_staff_id: null,
          assigned_staff_name: null,
          created_at: '2024-01-01',
          updated_at: '2024-01-01',
        },
        {
          id: 'j2',
          title: 'Paint job',
          description: null,
          status: 'in_progress',
          customer_id: 'c2',
          customer_name: 'Bob',
          assigned_staff_id: 's1',
          assigned_staff_name: 'Charlie',
          created_at: '2024-01-02',
          updated_at: '2024-01-02',
        },
      ]

      const items = jobsToBoardItems(jobs)

      expect(items).toHaveLength(2)
      expect(items[0]).toEqual({
        id: 'j1',
        columnId: 'pending',
        title: 'Fix engine',
        customerName: 'Alice',
        assignedStaffName: null,
      })
      expect(items[1]).toEqual({
        id: 'j2',
        columnId: 'in_progress',
        title: 'Paint job',
        customerName: 'Bob',
        assignedStaffName: 'Charlie',
      })
    })

    it('should handle empty jobs array', () => {
      expect(jobsToBoardItems([])).toEqual([])
    })

    it('should default missing status to pending', () => {
      const jobs = [
        {
          id: 'j1',
          title: 'Test',
          description: null,
          customer_id: 'c1',
          customer_name: 'Test',
          assigned_staff_id: null,
          assigned_staff_name: null,
          created_at: '',
          updated_at: '',
        },
      ] as Job[]

      const items = jobsToBoardItems(jobs)
      expect(items[0].columnId).toBe('pending')
    })
  })

  describe('updateJobStatus', () => {
    it('should PATCH the job status and return true on success', async () => {
      mockedPatch.mockResolvedValueOnce({ data: {} })

      const result = await updateJobStatus('j1', 'in_progress')

      expect(mockedPatch).toHaveBeenCalledWith('/api/v2/jobs/j1', {
        status: 'in_progress',
      })
      expect(result).toBe(true)
    })

    it('should return false when the API call fails', async () => {
      mockedPatch.mockRejectedValueOnce(new Error('Network error'))

      const result = await updateJobStatus('j1', 'completed')

      expect(result).toBe(false)
    })
  })
})

describe('useTimer - formatElapsedTime', () => {
  it('should format 0 seconds as 00:00:00', () => {
    expect(formatElapsedTime(0)).toBe('00:00:00')
  })

  it('should format seconds correctly', () => {
    expect(formatElapsedTime(45)).toBe('00:00:45')
  })

  it('should format minutes and seconds correctly', () => {
    expect(formatElapsedTime(125)).toBe('00:02:05')
  })

  it('should format hours, minutes, and seconds correctly', () => {
    expect(formatElapsedTime(3661)).toBe('01:01:01')
  })

  it('should handle large values', () => {
    expect(formatElapsedTime(36000)).toBe('10:00:00')
  })
})
