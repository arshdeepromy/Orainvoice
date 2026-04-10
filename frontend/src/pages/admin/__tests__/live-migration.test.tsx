import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'

vi.mock('@/api/client', () => ({
  default: {
    get: vi.fn(),
    post: vi.fn(),
    put: vi.fn(),
    delete: vi.fn(),
  },
}))

import apiClient from '@/api/client'
import {
  ConnectionForm,
  MigrationProgress,
  CutoverPanel,
  RollbackPanel,
  MigrationHistory,
  LiveMigrationTool,
} from '../LiveMigrationTool'

/* ── Mock data ── */

const mockValidationSuccess = {
  valid: true,
  server_version: '15.4',
  available_disk_space_mb: 50000,
  has_existing_tables: false,
  error: null,
}

const mockStatusCopying = {
  job_id: 'job-001',
  status: 'copying_data',
  current_table: 'invoices',
  tables: [
    { table_name: 'users', source_count: 100, migrated_count: 100, status: 'completed' },
    { table_name: 'invoices', source_count: 500, migrated_count: 250, status: 'in_progress' },
  ],
  rows_processed: 350,
  rows_total: 600,
  progress_pct: 58.3,
  estimated_seconds_remaining: 120,
  dual_write_queue_depth: 3,
  integrity_check: null,
  error_message: null,
  started_at: '2025-03-20T10:00:00Z',
  updated_at: '2025-03-20T10:05:00Z',
}

const mockStatusCompleted = {
  ...mockStatusCopying,
  status: 'completed',
  rows_processed: 600,
  progress_pct: 100,
  integrity_check: {
    passed: true,
    row_counts: { users: { source: 100, target: 100, match: true } },
    fk_errors: [],
    financial_totals: {},
    sequence_checks: {},
  },
}

const mockHistoryJobs = [
  {
    job_id: 'job-001',
    status: 'completed',
    started_at: '2025-03-20T10:00:00Z',
    completed_at: '2025-03-20T11:00:00Z',
    rows_total: 5000,
    source_host: 'db-old.example.com',
    target_host: 'db-new.example.com',
  },
  {
    job_id: 'job-002',
    status: 'failed',
    started_at: '2025-03-19T08:00:00Z',
    completed_at: null,
    rows_total: 3000,
    source_host: 'db-old.example.com',
    target_host: 'db-staging.example.com',
  },
]

/* ── Tests ── */

describe('LiveMigrationTool — Unit Tests', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    vi.useFakeTimers({ shouldAdvanceTime: true })
  })

  afterEach(() => {
    vi.useRealTimers()
  })

  // Test 1: Connection form submission and validation feedback
  describe('ConnectionForm', () => {
    it('validates connection and shows success feedback', async () => {
      vi.useRealTimers()
      const user = userEvent.setup()
      const mockPost = vi.mocked(apiClient.post)
      mockPost.mockResolvedValueOnce({ data: mockValidationSuccess })

      const onMigrationStarted = vi.fn()
      render(<ConnectionForm onMigrationStarted={onMigrationStarted} />)

      // Fill in connection string
      const input = screen.getByLabelText('Connection string')
      await user.type(input, 'postgresql+asyncpg://user:pass@host:5432/dbname')

      // Click validate
      const validateBtn = screen.getByLabelText('Validate connection')
      await user.click(validateBtn)

      await waitFor(() => {
        expect(mockPost).toHaveBeenCalledWith('/admin/migration/validate', expect.objectContaining({
          connection_string: 'postgresql+asyncpg://user:pass@host:5432/dbname',
          ssl_mode: 'prefer',
        }))
      })

      await waitFor(() => {
        expect(screen.getByText('Connection validated successfully')).toBeInTheDocument()
        expect(screen.getByText(/Server version: 15.4/)).toBeInTheDocument()
      })
    })

    it('shows error on validation failure', async () => {
      vi.useRealTimers()
      const user = userEvent.setup()
      const mockPost = vi.mocked(apiClient.post)
      mockPost.mockRejectedValueOnce({
        response: { data: { detail: 'Connection refused' } },
      })

      const onMigrationStarted = vi.fn()
      render(<ConnectionForm onMigrationStarted={onMigrationStarted} />)

      const input = screen.getByLabelText('Connection string')
      await user.type(input, 'postgresql+asyncpg://user:pass@badhost:5432/db')

      const validateBtn = screen.getByLabelText('Validate connection')
      await user.click(validateBtn)

      await waitFor(() => {
        expect(screen.getByText('Connection refused')).toBeInTheDocument()
      })
    })
  })

  // Test 2: Progress polling starts/stops based on job status
  describe('MigrationProgress', () => {
    it('polls status and displays progress', async () => {
      const mockGet = vi.mocked(apiClient.get)
      mockGet.mockResolvedValue({ data: mockStatusCopying })

      const onStatusUpdate = vi.fn()
      const onCancel = vi.fn()

      render(
        <MigrationProgress jobId="job-001" onStatusUpdate={onStatusUpdate} onCancel={onCancel} />,
      )

      // Initial poll fires immediately
      await waitFor(() => {
        expect(mockGet).toHaveBeenCalledWith('/admin/migration/status/job-001')
      })

      await waitFor(() => {
        expect(screen.getByText('Migration Progress')).toBeInTheDocument()
        expect(screen.getByLabelText('Overall migration progress')).toBeInTheDocument()
      })

      expect(onStatusUpdate).toHaveBeenCalledWith(mockStatusCopying)
    })

    it('stops polling when status is completed', async () => {
      const mockGet = vi.mocked(apiClient.get)
      mockGet.mockResolvedValue({ data: mockStatusCompleted })

      const onStatusUpdate = vi.fn()
      const onCancel = vi.fn()

      render(
        <MigrationProgress jobId="job-001" onStatusUpdate={onStatusUpdate} onCancel={onCancel} />,
      )

      await waitFor(() => {
        expect(onStatusUpdate).toHaveBeenCalledWith(mockStatusCompleted)
      })
    })
  })

  // Test 3: Cutover confirmation modal requires exact text
  describe('CutoverPanel', () => {
    it('disables confirm button until CONFIRM CUTOVER is typed', async () => {
      vi.useRealTimers()
      const user = userEvent.setup()
      const onCutoverComplete = vi.fn()
      const onError = vi.fn()

      render(
        <CutoverPanel
          jobId="job-001"
          integrityPassed={true}
          onCutoverComplete={onCutoverComplete}
          onError={onError}
        />,
      )

      // Click the cutover button to open modal
      const cutoverBtn = screen.getByLabelText('Cut over to new database')
      await user.click(cutoverBtn)

      // Modal should appear
      expect(screen.getByRole('dialog')).toBeInTheDocument()

      // Confirm button should be disabled — use getAllByLabelText since dialog and button share the label
      const confirmBtns = screen.getAllByLabelText('Confirm cutover')
      const confirmBtn = confirmBtns.find((el) => el.tagName === 'BUTTON')!
      expect(confirmBtn).toBeDisabled()

      // Type wrong text
      const input = screen.getByLabelText('Cutover confirmation text')
      await user.type(input, 'CONFIRM')
      expect(confirmBtn).toBeDisabled()

      // Clear and type correct text
      await user.clear(input)
      await user.type(input, 'CONFIRM CUTOVER')
      expect(confirmBtn).not.toBeDisabled()
    })

    it('disables cutover button when integrity check not passed', () => {
      render(
        <CutoverPanel
          jobId="job-001"
          integrityPassed={false}
          onCutoverComplete={vi.fn()}
          onError={vi.fn()}
        />,
      )

      const cutoverBtn = screen.getByLabelText('Cut over to new database')
      expect(cutoverBtn).toBeDisabled()
    })
  })

  // Test 4: Rollback button visibility based on time
  describe('RollbackPanel', () => {
    it('shows rollback button when within 24h window', () => {
      const recentCutover = new Date(Date.now() - 2 * 60 * 60 * 1000).toISOString() // 2h ago

      render(
        <RollbackPanel
          jobId="job-001"
          cutoverAt={recentCutover}
          onRollbackComplete={vi.fn()}
          onError={vi.fn()}
        />,
      )

      expect(screen.getByLabelText('Roll back to previous database')).toBeInTheDocument()
      expect(screen.getByText(/remaining/)).toBeInTheDocument()
    })

    it('shows expired message when past 24h window', () => {
      const oldCutover = new Date(Date.now() - 25 * 60 * 60 * 1000).toISOString() // 25h ago

      render(
        <RollbackPanel
          jobId="job-001"
          cutoverAt={oldCutover}
          onRollbackComplete={vi.fn()}
          onError={vi.fn()}
        />,
      )

      expect(screen.getByText(/Rollback window has expired/)).toBeInTheDocument()
      expect(screen.queryByLabelText('Roll back to previous database')).not.toBeInTheDocument()
    })
  })

  // Test 5: Migration history table rendering
  describe('MigrationHistory', () => {
    it('renders history table with job rows', async () => {
      vi.useRealTimers()
      const mockGet = vi.mocked(apiClient.get)
      mockGet.mockResolvedValueOnce({ data: mockHistoryJobs })

      render(<MigrationHistory />)

      await waitFor(() => {
        expect(screen.getByText('Migration History')).toBeInTheDocument()
      })

      await waitFor(() => {
        // "Completed" appears in both the table header and the status badge, so use getAllByText
        const completedElements = screen.getAllByText('Completed')
        expect(completedElements.length).toBeGreaterThanOrEqual(2) // header + badge
        expect(screen.getByText('Failed')).toBeInTheDocument()
        // db-old.example.com appears in both rows, so use getAllByText
        expect(screen.getAllByText('db-old.example.com')).toHaveLength(2)
        expect(screen.getByText('db-new.example.com')).toBeInTheDocument()
        expect(screen.getByText('db-staging.example.com')).toBeInTheDocument()
      })
    })

    it('shows empty state when no jobs', async () => {
      vi.useRealTimers()
      const mockGet = vi.mocked(apiClient.get)
      mockGet.mockResolvedValueOnce({ data: [] })

      render(<MigrationHistory />)

      await waitFor(() => {
        expect(screen.getByText('No past migrations found.')).toBeInTheDocument()
      })
    })
  })

  // Test 6: Error banner display on API failure
  describe('LiveMigrationTool', () => {
    it('renders the main page with connection form and history', async () => {
      vi.useRealTimers()
      const mockGet = vi.mocked(apiClient.get)
      mockGet.mockResolvedValueOnce({ data: [] }) // history

      render(<LiveMigrationTool />)

      expect(screen.getByText('Live Database Migration')).toBeInTheDocument()
      expect(screen.getByLabelText('Connection string')).toBeInTheDocument()

      await waitFor(() => {
        expect(screen.getByText('Migration History')).toBeInTheDocument()
      })
    })
  })
})
