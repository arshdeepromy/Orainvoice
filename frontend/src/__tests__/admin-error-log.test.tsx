import { render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, it, expect, vi, beforeEach } from 'vitest'

/**
 * Validates: Requirements 49.1-49.7
 * - 49.1: Capture every exception, integration failure, background job failure
 * - 49.2: Error record fields (ID, timestamp, severity, module, stack trace, org/user, HTTP details, message, category)
 * - 49.3: Error categories (Payment, Integration, Storage, Authentication, Data, Background Job, Application)
 * - 49.4: Dashboard with real-time counts (1h/24h/7d), live feed colour-coded by severity, search/filter
 * - 49.5: Critical error push notifications
 * - 49.6: Error detail view with stack trace, context, request/response, status management, notes
 * - 49.7: Retention and export
 */

vi.mock('@/api/client', () => {
  const mockGet = vi.fn()
  const mockPut = vi.fn()
  return {
    default: { get: mockGet, put: mockPut },
  }
})

import apiClient from '@/api/client'
import { ErrorLog } from '../pages/admin/ErrorLog'

/* ── Backend-shaped types (what the API actually returns) ── */

interface BackendSummaryCount {
  label: string
  count_1h: number
  count_24h: number
  count_7d: number
}

interface BackendDashboardResponse {
  by_severity: BackendSummaryCount[]
  by_category: BackendSummaryCount[]
  total_1h: number
  total_24h: number
  total_7d: number
}

interface BackendErrorRecord {
  id: string
  severity: string
  category: string
  module: string
  function_name: string | null
  message: string
  stack_trace: string | null
  org_id: string | null
  user_id: string | null
  http_method: string | null
  http_endpoint: string | null
  request_body_sanitised: Record<string, unknown> | null
  response_body_sanitised: Record<string, unknown> | null
  status: string
  resolution_notes: string | null
  created_at: string
}

interface BackendErrorListResponse {
  errors: BackendErrorRecord[]
  total: number
  page: number
  page_size: number
}

/* ── Test data factories ── */

function makeDashboard(overrides: Partial<Record<string, Partial<BackendSummaryCount>>> = {}): BackendDashboardResponse {
  const defaults: BackendSummaryCount[] = [
    { label: 'critical', count_1h: 1, count_24h: 3, count_7d: 8 },
    { label: 'error', count_1h: 5, count_24h: 22, count_7d: 87 },
    { label: 'warning', count_1h: 12, count_24h: 45, count_7d: 210 },
    { label: 'info', count_1h: 30, count_24h: 120, count_7d: 500 },
  ]
  const by_severity = defaults.map((s) => ({ ...s, ...(overrides[s.label] ?? {}) }))
  return {
    by_severity,
    by_category: [],
    total_1h: by_severity.reduce((a, s) => a + s.count_1h, 0),
    total_24h: by_severity.reduce((a, s) => a + s.count_24h, 0),
    total_7d: by_severity.reduce((a, s) => a + s.count_7d, 0),
  }
}

function makeBackendError(overrides: Partial<BackendErrorRecord> = {}): BackendErrorRecord {
  return {
    id: 'err-001',
    severity: 'error',
    category: 'payment',
    module: 'payments.service',
    function_name: 'process_payment',
    message: 'Stripe API timeout after 30s',
    stack_trace: 'Traceback (most recent call last):\n  File "payments/service.py", line 42\n    raise TimeoutError()',
    org_id: 'org-abc',
    user_id: 'user-123',
    http_method: 'POST',
    http_endpoint: '/api/v1/payments/cash',
    request_body_sanitised: { amount: 150.0 },
    response_body_sanitised: null,
    status: 'open',
    resolution_notes: '',
    created_at: new Date().toISOString(),
    ...overrides,
  }
}

function makeBackendErrorList(items: BackendErrorRecord[] = [makeBackendError()]): BackendErrorListResponse {
  return { errors: items, total: items.length, page: 1, page_size: 25 }
}

function setupMocks(
  dashboard: BackendDashboardResponse = makeDashboard(),
  errorList: BackendErrorListResponse = makeBackendErrorList(),
  detail?: BackendErrorRecord,
) {
  ;(apiClient.get as ReturnType<typeof vi.fn>).mockImplementation((url: string) => {
    if (url === '/admin/errors/dashboard') {
      return Promise.resolve({ data: dashboard })
    }
    if (url === '/admin/errors') {
      return Promise.resolve({ data: errorList })
    }
    if (url.startsWith('/admin/errors/')) {
      return Promise.resolve({ data: detail ?? errorList.errors[0] })
    }
    return Promise.reject(new Error('Unknown URL'))
  })
  ;(apiClient.put as ReturnType<typeof vi.fn>).mockResolvedValue({ data: {} })
}

describe('Admin Error Log page', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    // Suppress Notification API in tests
    vi.stubGlobal('Notification', undefined)
  })

  // 49.4: Summary cards show error counts by severity for 1h, 24h, 7d
  it('renders summary cards with error counts for all severities', async () => {
    setupMocks()
    render(<ErrorLog />)

    const summary = await screen.findByRole('region', { name: /error count summary/i })
    expect(within(summary).getByText('Critical')).toBeInTheDocument()
    expect(within(summary).getByText('Error')).toBeInTheDocument()
    expect(within(summary).getByText('Warning')).toBeInTheDocument()
    expect(within(summary).getByText('Info')).toBeInTheDocument()

    // Check specific counts
    expect(within(summary).getByText('1')).toBeInTheDocument() // Critical 1h
    expect(within(summary).getByText('3')).toBeInTheDocument() // Critical 24h
    expect(within(summary).getByText('8')).toBeInTheDocument() // Critical 7d
  })

  // 49.4: Live feed table renders errors
  it('renders error feed table with error records', async () => {
    const errors = [
      makeBackendError({ id: 'err-001', severity: 'warning', message: 'Payment gateway down', category: 'payment' }),
      makeBackendError({ id: 'err-002', severity: 'warning', category: 'integration', message: 'Carjam rate limit' }),
    ]
    setupMocks(makeDashboard(), makeBackendErrorList(errors))
    render(<ErrorLog />)

    expect(await screen.findByText('Payment gateway down')).toBeInTheDocument()
    expect(screen.getByText('Carjam rate limit')).toBeInTheDocument()
    expect(screen.getByText('2 errors found')).toBeInTheDocument()
  })

  // 49.4: Colour-coded severity badges in feed
  it('displays severity badges in the error feed', async () => {
    const errors = [
      makeBackendError({ id: 'err-c', severity: 'warning', message: 'A warning msg' }),
      makeBackendError({ id: 'err-i', severity: 'info', message: 'An info msg' }),
    ]
    setupMocks(makeDashboard(), makeBackendErrorList(errors))
    render(<ErrorLog />)

    await screen.findByText('A warning msg')
    // The table should contain rows with severity badges
    const table = screen.getByRole('grid', { name: /error log feed/i })
    expect(within(table).getByText('Warning')).toBeInTheDocument()
    expect(within(table).getByText('Info')).toBeInTheDocument()
  })

  // 49.3: Category filter options include all required categories
  it('renders category filter with all required categories', async () => {
    setupMocks()
    render(<ErrorLog />)

    await screen.findByLabelText('Category')
    const select = screen.getByLabelText('Category')
    const options = within(select).getAllByRole('option')
    const labels = options.map((o) => o.textContent)

    expect(labels).toContain('Payment')
    expect(labels).toContain('Integration')
    expect(labels).toContain('Storage')
    expect(labels).toContain('Authentication')
    expect(labels).toContain('Data')
    expect(labels).toContain('Background Job')
    expect(labels).toContain('Application')
  })

  // 49.4: Severity filter options
  it('renders severity filter with all severity levels', async () => {
    setupMocks()
    render(<ErrorLog />)

    await screen.findByLabelText('Severity')
    const select = screen.getByLabelText('Severity')
    const options = within(select).getAllByRole('option')
    const labels = options.map((o) => o.textContent)

    expect(labels).toContain('Info')
    expect(labels).toContain('Warning')
    expect(labels).toContain('Error')
    expect(labels).toContain('Critical')
  })

  // 49.4: Search input present
  it('renders search input for message/module filtering', async () => {
    setupMocks()
    render(<ErrorLog />)

    expect(await screen.findByLabelText('Search')).toBeInTheDocument()
    expect(screen.getByPlaceholderText(/search by message or module/i)).toBeInTheDocument()
  })

  // 49.4: Filters are sent as query params
  it('sends filter params when severity filter is changed', async () => {
    setupMocks()
    const user = userEvent.setup()
    render(<ErrorLog />)

    await screen.findByLabelText('Severity')
    await user.selectOptions(screen.getByLabelText('Severity'), 'Critical')

    // The API should be called with severity param (lowercased by the component)
    const getCalls = (apiClient.get as ReturnType<typeof vi.fn>).mock.calls
    const errorCalls = getCalls.filter(
      (c: unknown[]) => c[0] === '/admin/errors' && (c[1] as Record<string, unknown>)?.params &&
        ((c[1] as Record<string, Record<string, string>>).params?.severity === 'critical'),
    )
    expect(errorCalls.length).toBeGreaterThanOrEqual(1)
  })

  // 49.6: Clicking a row opens the error detail modal
  it('opens error detail modal when View button is clicked', async () => {
    const err = makeBackendError({
      id: 'err-detail',
      message: 'Detailed error message',
      stack_trace: 'Traceback:\n  File "test.py", line 1',
    })
    setupMocks(makeDashboard(), makeBackendErrorList([err]), err)
    const user = userEvent.setup()
    render(<ErrorLog />)

    await screen.findByText('Detailed error message')
    await user.click(screen.getByRole('button', { name: 'View' }))

    // Modal should show error detail
    expect(await screen.findByText('Error Detail')).toBeInTheDocument()
    expect(screen.getByText('err-detail')).toBeInTheDocument()
    // Message appears in both table and modal — use getAllByText
    const messages = screen.getAllByText('Detailed error message')
    expect(messages.length).toBeGreaterThanOrEqual(2)
  })

  // 49.6: Detail modal shows stack trace
  it('displays formatted stack trace in detail modal', async () => {
    const err = makeBackendError({
      id: 'err-stack',
      stack_trace: 'Traceback (most recent call last):\n  File "service.py", line 42\nValueError: bad input',
    })
    setupMocks(makeDashboard(), makeBackendErrorList([err]), err)
    const user = userEvent.setup()
    render(<ErrorLog />)

    await screen.findByText(err.message)
    await user.click(screen.getByRole('button', { name: 'View' }))

    expect(await screen.findByText(/Traceback \(most recent call last\)/)).toBeInTheDocument()
    expect(screen.getByText(/ValueError: bad input/)).toBeInTheDocument()
  })

  // 49.6: Detail modal shows context (org, user)
  it('displays organisation and user context in detail modal', async () => {
    const err = makeBackendError({ id: 'err-ctx', org_id: 'org-xyz', user_id: 'user-456' })
    setupMocks(makeDashboard(), makeBackendErrorList([err]), err)
    const user = userEvent.setup()
    render(<ErrorLog />)

    await screen.findByText(err.message)
    await user.click(screen.getByRole('button', { name: 'View' }))

    expect(await screen.findByText('org-xyz')).toBeInTheDocument()
    expect(screen.getByText('user-456')).toBeInTheDocument()
  })

  // 49.6: Detail modal shows HTTP request details
  it('displays HTTP request details in detail modal', async () => {
    const err = makeBackendError({
      id: 'err-http',
      http_method: 'POST',
      http_endpoint: '/api/v1/payments/cash',
      request_body_sanitised: { amount: 150.0 },
    })
    setupMocks(makeDashboard(), makeBackendErrorList([err]), err)
    const user = userEvent.setup()
    render(<ErrorLog />)

    await screen.findByText(err.message)
    await user.click(screen.getByRole('button', { name: 'View' }))

    expect(await screen.findByText(/POST \/api\/v1\/payments\/cash/)).toBeInTheDocument()
  })

  // 49.6: Status management — update status via detail modal
  it('allows updating error status and notes from detail modal', async () => {
    const err = makeBackendError({ id: 'err-status', status: 'open', resolution_notes: '' })
    setupMocks(makeDashboard(), makeBackendErrorList([err]), err)
    const user = userEvent.setup()
    render(<ErrorLog />)

    await screen.findByText(err.message)
    await user.click(screen.getByRole('button', { name: 'View' }))

    await screen.findByText('Error Detail')

    // Change status to Investigating
    await user.selectOptions(screen.getByLabelText('Status'), 'Investigating')

    // Add notes
    const notesInput = screen.getByLabelText('Notes')
    await user.type(notesInput, 'Looking into Stripe timeout')

    // Save
    await user.click(screen.getByRole('button', { name: 'Save changes' }))

    expect(apiClient.put).toHaveBeenCalledWith('/admin/errors/err-status/status', {
      status: 'investigating',
      resolution_notes: 'Looking into Stripe timeout',
    })
  })

  // 49.5: Critical error alert banner
  it('shows critical error alert banner when critical errors exist in last hour', async () => {
    const criticalErr = makeBackendError({
      id: 'err-crit',
      severity: 'critical',
      created_at: new Date().toISOString(), // within last hour
      message: 'Payment gateway unreachable',
    })
    setupMocks(makeDashboard(), makeBackendErrorList([criticalErr]))
    render(<ErrorLog />)

    expect(await screen.findByText('Critical Errors Detected')).toBeInTheDocument()
    expect(screen.getByText(/1 critical error in the last hour/)).toBeInTheDocument()
  })

  // 49.5: No critical alert when no recent critical errors
  it('does not show critical alert when no critical errors in last hour', async () => {
    const oldErr = makeBackendError({
      id: 'err-old',
      severity: 'critical',
      created_at: new Date(Date.now() - 2 * 60 * 60 * 1000).toISOString(), // 2 hours ago
      message: 'Old critical error',
    })
    setupMocks(makeDashboard(), makeBackendErrorList([oldErr]))
    render(<ErrorLog />)

    await screen.findByText('Old critical error')
    expect(screen.queryByText('Critical Errors Detected')).not.toBeInTheDocument()
  })

  // Empty state
  it('shows empty state when no errors found', async () => {
    setupMocks(makeDashboard(), makeBackendErrorList([]))
    render(<ErrorLog />)

    expect(await screen.findByText('No errors found')).toBeInTheDocument()
    expect(screen.getByText('0 errors found')).toBeInTheDocument()
  })

  // Loading state
  it('shows loading spinner while fetching error log', () => {
    ;(apiClient.get as ReturnType<typeof vi.fn>).mockReturnValue(new Promise(() => {}))
    render(<ErrorLog />)

    expect(screen.getByRole('status', { name: /loading error log/i })).toBeInTheDocument()
  })

  // Error state
  it('shows error banner when error log fails to load', async () => {
    ;(apiClient.get as ReturnType<typeof vi.fn>).mockImplementation((url: string) => {
      if (url === '/admin/errors/dashboard') return Promise.resolve({ data: makeDashboard() })
      return Promise.reject(new Error('Network error'))
    })
    render(<ErrorLog />)

    expect(await screen.findByText(/Could not load error log/)).toBeInTheDocument()
  })

  // 49.6: Status badges in feed (Open, Investigating, Resolved)
  it('displays status badges for different error statuses', async () => {
    const errors = [
      makeBackendError({ id: 'e1', status: 'open', message: 'Open error' }),
      makeBackendError({ id: 'e2', status: 'investigating', message: 'Investigating error' }),
      makeBackendError({ id: 'e3', status: 'resolved', message: 'Resolved error' }),
    ]
    setupMocks(makeDashboard(), makeBackendErrorList(errors))
    render(<ErrorLog />)

    await screen.findByText('Open error')
    expect(screen.getByText('Open')).toBeInTheDocument()
    expect(screen.getByText('Investigating')).toBeInTheDocument()
    expect(screen.getByText('Resolved')).toBeInTheDocument()
  })

  // 49.2: Module and function displayed in detail
  it('displays module and function in error detail', async () => {
    const err = makeBackendError({
      id: 'err-mod',
      module: 'integrations.carjam',
      function_name: 'lookup_vehicle',
    })
    setupMocks(makeDashboard(), makeBackendErrorList([err]), err)
    const user = userEvent.setup()
    render(<ErrorLog />)

    await screen.findByText(err.message)
    await user.click(screen.getByRole('button', { name: 'View' }))

    await screen.findByText('Error Detail')
    // Module appears in both table and modal — use getAllByText
    const moduleTexts = screen.getAllByText('integrations.carjam')
    expect(moduleTexts.length).toBeGreaterThanOrEqual(2)
    expect(screen.getByText('lookup_vehicle')).toBeInTheDocument()
  })
})
