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
import type { ErrorSummary, ErrorRecord, ErrorLogResponse } from '../pages/admin/ErrorLog'

/* ── Test data factories ── */

function makeSummaries(overrides: Partial<Record<string, Partial<ErrorSummary>>> = {}): ErrorSummary[] {
  const defaults: ErrorSummary[] = [
    { severity: 'Critical', last_hour: 1, last_24h: 3, last_7d: 8 },
    { severity: 'Error', last_hour: 5, last_24h: 22, last_7d: 87 },
    { severity: 'Warning', last_hour: 12, last_24h: 45, last_7d: 210 },
    { severity: 'Info', last_hour: 30, last_24h: 120, last_7d: 500 },
  ]
  return defaults.map((s) => ({ ...s, ...(overrides[s.severity] ?? {}) }))
}

function makeError(overrides: Partial<ErrorRecord> = {}): ErrorRecord {
  return {
    id: 'err-001',
    timestamp: new Date().toISOString(),
    severity: 'Error',
    category: 'Payment',
    module: 'payments.service',
    function_name: 'process_payment',
    message: 'Stripe API timeout after 30s',
    stack_trace: 'Traceback (most recent call last):\n  File "payments/service.py", line 42\n    raise TimeoutError()',
    org_id: 'org-abc',
    user_id: 'user-123',
    http_method: 'POST',
    http_endpoint: '/api/v1/payments/cash',
    request_body: '{"amount": 150.00}',
    response_body: null,
    status: 'Open',
    notes: '',
    ...overrides,
  }
}

function makeErrorList(items: ErrorRecord[] = [makeError()]): ErrorLogResponse {
  return { items, total: items.length }
}

function setupMocks(
  summaries: ErrorSummary[] = makeSummaries(),
  errorList: ErrorLogResponse = makeErrorList(),
  detail?: ErrorRecord,
) {
  ;(apiClient.get as ReturnType<typeof vi.fn>).mockImplementation((url: string) => {
    if (url === '/admin/errors/summary') {
      return Promise.resolve({ data: summaries })
    }
    if (url === '/admin/errors') {
      return Promise.resolve({ data: errorList })
    }
    if (url.startsWith('/admin/errors/')) {
      return Promise.resolve({ data: detail ?? errorList.items[0] })
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
      makeError({ id: 'err-001', severity: 'Warning', message: 'Payment gateway down', category: 'Payment' }),
      makeError({ id: 'err-002', severity: 'Warning', category: 'Integration', message: 'Carjam rate limit' }),
    ]
    setupMocks(makeSummaries(), makeErrorList(errors))
    render(<ErrorLog />)

    expect(await screen.findByText('Payment gateway down')).toBeInTheDocument()
    expect(screen.getByText('Carjam rate limit')).toBeInTheDocument()
    expect(screen.getByText('2 errors found')).toBeInTheDocument()
  })

  // 49.4: Colour-coded severity badges in feed
  it('displays severity badges in the error feed', async () => {
    const errors = [
      makeError({ id: 'err-c', severity: 'Warning', message: 'A warning msg' }),
      makeError({ id: 'err-i', severity: 'Info', message: 'An info msg' }),
    ]
    setupMocks(makeSummaries(), makeErrorList(errors))
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

    // The API should be called with severity param
    const getCalls = (apiClient.get as ReturnType<typeof vi.fn>).mock.calls
    const errorCalls = getCalls.filter(
      (c: unknown[]) => c[0] === '/admin/errors' && (c[1] as Record<string, unknown>)?.params &&
        ((c[1] as Record<string, Record<string, string>>).params?.severity === 'Critical'),
    )
    expect(errorCalls.length).toBeGreaterThanOrEqual(1)
  })

  // 49.6: Clicking a row opens the error detail modal
  it('opens error detail modal when View button is clicked', async () => {
    const err = makeError({
      id: 'err-detail',
      message: 'Detailed error message',
      stack_trace: 'Traceback:\n  File "test.py", line 1',
    })
    setupMocks(makeSummaries(), makeErrorList([err]), err)
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
    const err = makeError({
      id: 'err-stack',
      stack_trace: 'Traceback (most recent call last):\n  File "service.py", line 42\nValueError: bad input',
    })
    setupMocks(makeSummaries(), makeErrorList([err]), err)
    const user = userEvent.setup()
    render(<ErrorLog />)

    await screen.findByText(err.message)
    await user.click(screen.getByRole('button', { name: 'View' }))

    expect(await screen.findByText(/Traceback \(most recent call last\)/)).toBeInTheDocument()
    expect(screen.getByText(/ValueError: bad input/)).toBeInTheDocument()
  })

  // 49.6: Detail modal shows context (org, user)
  it('displays organisation and user context in detail modal', async () => {
    const err = makeError({ id: 'err-ctx', org_id: 'org-xyz', user_id: 'user-456' })
    setupMocks(makeSummaries(), makeErrorList([err]), err)
    const user = userEvent.setup()
    render(<ErrorLog />)

    await screen.findByText(err.message)
    await user.click(screen.getByRole('button', { name: 'View' }))

    expect(await screen.findByText('org-xyz')).toBeInTheDocument()
    expect(screen.getByText('user-456')).toBeInTheDocument()
  })

  // 49.6: Detail modal shows HTTP request details
  it('displays HTTP request details in detail modal', async () => {
    const err = makeError({
      id: 'err-http',
      http_method: 'POST',
      http_endpoint: '/api/v1/payments/cash',
      request_body: '{"amount": 150.00}',
    })
    setupMocks(makeSummaries(), makeErrorList([err]), err)
    const user = userEvent.setup()
    render(<ErrorLog />)

    await screen.findByText(err.message)
    await user.click(screen.getByRole('button', { name: 'View' }))

    expect(await screen.findByText(/POST \/api\/v1\/payments\/cash/)).toBeInTheDocument()
    expect(screen.getByText('{"amount": 150.00}')).toBeInTheDocument()
  })

  // 49.6: Status management — update status via detail modal
  it('allows updating error status and notes from detail modal', async () => {
    const err = makeError({ id: 'err-status', status: 'Open', notes: '' })
    setupMocks(makeSummaries(), makeErrorList([err]), err)
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

    expect(apiClient.put).toHaveBeenCalledWith('/admin/errors/err-status', {
      status: 'Investigating',
      notes: 'Looking into Stripe timeout',
    })
  })

  // 49.5: Critical error alert banner
  it('shows critical error alert banner when critical errors exist in last hour', async () => {
    const criticalErr = makeError({
      id: 'err-crit',
      severity: 'Critical',
      timestamp: new Date().toISOString(), // within last hour
      message: 'Payment gateway unreachable',
    })
    setupMocks(makeSummaries(), makeErrorList([criticalErr]))
    render(<ErrorLog />)

    expect(await screen.findByText('Critical Errors Detected')).toBeInTheDocument()
    expect(screen.getByText(/1 critical error in the last hour/)).toBeInTheDocument()
  })

  // 49.5: No critical alert when no recent critical errors
  it('does not show critical alert when no critical errors in last hour', async () => {
    const oldErr = makeError({
      id: 'err-old',
      severity: 'Critical',
      timestamp: new Date(Date.now() - 2 * 60 * 60 * 1000).toISOString(), // 2 hours ago
      message: 'Old critical error',
    })
    setupMocks(makeSummaries(), makeErrorList([oldErr]))
    render(<ErrorLog />)

    await screen.findByText('Old critical error')
    expect(screen.queryByText('Critical Errors Detected')).not.toBeInTheDocument()
  })

  // Empty state
  it('shows empty state when no errors found', async () => {
    setupMocks(makeSummaries(), makeErrorList([]))
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
      if (url === '/admin/errors/summary') return Promise.resolve({ data: makeSummaries() })
      return Promise.reject(new Error('Network error'))
    })
    render(<ErrorLog />)

    expect(await screen.findByText(/Could not load error log/)).toBeInTheDocument()
  })

  // 49.6: Status badges in feed (Open, Investigating, Resolved)
  it('displays status badges for different error statuses', async () => {
    const errors = [
      makeError({ id: 'e1', status: 'Open', message: 'Open error' }),
      makeError({ id: 'e2', status: 'Investigating', message: 'Investigating error' }),
      makeError({ id: 'e3', status: 'Resolved', message: 'Resolved error' }),
    ]
    setupMocks(makeSummaries(), makeErrorList(errors))
    render(<ErrorLog />)

    await screen.findByText('Open error')
    expect(screen.getByText('Open')).toBeInTheDocument()
    expect(screen.getByText('Investigating')).toBeInTheDocument()
    expect(screen.getByText('Resolved')).toBeInTheDocument()
  })

  // 49.2: Module and function displayed in detail
  it('displays module and function in error detail', async () => {
    const err = makeError({
      id: 'err-mod',
      module: 'integrations.carjam',
      function_name: 'lookup_vehicle',
    })
    setupMocks(makeSummaries(), makeErrorList([err]), err)
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
