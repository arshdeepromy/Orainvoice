import { render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, it, expect, vi, beforeEach } from 'vitest'

/**
 * Validates: Requirements 51.4
 * - 51.4: Global_Admins can view platform-wide audit logs; search/filter by user, action, entity, date range
 * - 51.2: Each audit entry shows who, what, before/after values, timestamp, IP, device
 */

vi.mock('@/api/client', () => {
  const mockGet = vi.fn()
  return {
    default: { get: mockGet },
  }
})

import apiClient from '@/api/client'
import { AuditLog } from '../pages/admin/AuditLog'
import type { AuditEntry, AuditLogResponse } from '../pages/admin/AuditLog'

/* ── Test data factories ── */

function makeEntry(overrides: Partial<AuditEntry> = {}): AuditEntry {
  return {
    id: 'audit-001',
    timestamp: new Date().toISOString(),
    user_id: 'user-123',
    user_email: 'admin@example.com',
    action: 'update',
    entity_type: 'Invoice',
    entity_id: 'inv-456',
    description: 'Updated invoice status to Issued',
    before_value: '{"status": "Draft"}',
    after_value: '{"status": "Issued"}',
    ip_address: '192.168.1.100',
    device_info: 'Chrome 120 / macOS',
    org_id: 'org-abc',
    org_name: 'Test Workshop',
    ...overrides,
  }
}

function makeAuditList(items: AuditEntry[] = [makeEntry()]): AuditLogResponse {
  return { entries: items, total: items.length }
}

function setupMocks(
  auditList: AuditLogResponse = makeAuditList(),
  detail?: AuditEntry,
) {
  ;(apiClient.get as ReturnType<typeof vi.fn>).mockImplementation((url: string) => {
    if (url === '/admin/audit-log') {
      return Promise.resolve({ data: auditList })
    }
    if (url.startsWith('/admin/audit-log/')) {
      return Promise.resolve({ data: detail ?? auditList.entries[0] })
    }
    return Promise.reject(new Error('Unknown URL'))
  })
}

describe('Admin Audit Log page', () => {
  beforeEach(() => {
    vi.clearAllMocks()
  })

  // 51.4: Renders the audit log table with entries
  it('renders audit log table with entries', async () => {
    const entries = [
      makeEntry({ id: 'a1', user_email: 'alice@test.com', description: 'Created customer record' }),
      makeEntry({ id: 'a2', user_email: 'bob@test.com', action: 'delete', description: 'Voided invoice INV-001' }),
    ]
    setupMocks(makeAuditList(entries))
    render(<AuditLog />)

    expect(await screen.findByText('Created customer record')).toBeInTheDocument()
    expect(screen.getByText('Voided invoice INV-001')).toBeInTheDocument()
    expect(screen.getByText('2 entries found')).toBeInTheDocument()
  })

  // 51.4: Search input present for filtering by user/action/entity
  it('renders search input for user, action, and entity filtering', async () => {
    setupMocks()
    render(<AuditLog />)

    expect(await screen.findByLabelText('Search')).toBeInTheDocument()
    expect(screen.getByPlaceholderText(/search by user, action, or entity/i)).toBeInTheDocument()
  })

  // 51.4: Action filter dropdown with all action types
  it('renders action filter with all action types', async () => {
    setupMocks()
    render(<AuditLog />)

    await screen.findByLabelText('Action')
    const select = screen.getByLabelText('Action')
    const options = within(select).getAllByRole('option')
    const labels = options.map((o) => o.textContent)

    expect(labels).toContain('All actions')
    expect(labels).toContain('Create')
    expect(labels).toContain('Update')
    expect(labels).toContain('Delete')
    expect(labels).toContain('Login')
    expect(labels).toContain('Payment')
    expect(labels).toContain('Void')
    expect(labels).toContain('Settings Change')
  })

  // 51.4: Date range filters present
  it('renders date range filter inputs', async () => {
    setupMocks()
    render(<AuditLog />)

    expect(await screen.findByLabelText('From')).toBeInTheDocument()
    expect(screen.getByLabelText('To')).toBeInTheDocument()
  })

  // 51.4: Filters are sent as query params
  it('sends filter params when action filter is changed', async () => {
    setupMocks()
    const user = userEvent.setup()
    render(<AuditLog />)

    await screen.findByLabelText('Action')
    await user.selectOptions(screen.getByLabelText('Action'), 'login')

    const getCalls = (apiClient.get as ReturnType<typeof vi.fn>).mock.calls
    const auditCalls = getCalls.filter(
      (c: unknown[]) =>
        c[0] === '/admin/audit-log' &&
        (c[1] as Record<string, unknown>)?.params &&
        ((c[1] as Record<string, Record<string, string>>).params?.action === 'login'),
    )
    expect(auditCalls.length).toBeGreaterThanOrEqual(1)
  })

  // 51.2: Detail modal shows who, what, before/after, timestamp, IP, device
  it('opens detail modal showing full audit entry with before/after diff', async () => {
    const entry = makeEntry({
      id: 'audit-detail',
      user_email: 'admin@workshop.co.nz',
      action: 'update',
      entity_type: 'Invoice',
      description: 'Changed invoice status',
      before_value: '{"status": "Draft"}',
      after_value: '{"status": "Issued"}',
      ip_address: '10.0.0.1',
      device_info: 'Firefox 121 / Windows',
    })
    setupMocks(makeAuditList([entry]), entry)
    const user = userEvent.setup()
    render(<AuditLog />)

    await screen.findByText('Changed invoice status')
    await user.click(screen.getByRole('button', { name: 'View' }))

    // Modal should show
    expect(await screen.findByText('Audit Entry Detail')).toBeInTheDocument()
    expect(screen.getByText('audit-detail')).toBeInTheDocument()
    // Email appears in both table and modal — use getAllByText
    const emails = screen.getAllByText('admin@workshop.co.nz')
    expect(emails.length).toBeGreaterThanOrEqual(2)
    // IP appears in both table and modal
    const ips = screen.getAllByText('10.0.0.1')
    expect(ips.length).toBeGreaterThanOrEqual(2)
    expect(screen.getByText('Firefox 121 / Windows')).toBeInTheDocument()
    // Before/after values
    expect(screen.getByText('{"status": "Draft"}')).toBeInTheDocument()
    expect(screen.getByText('{"status": "Issued"}')).toBeInTheDocument()
  })

  // 51.2: Detail modal shows organisation context
  it('displays organisation context in detail modal', async () => {
    const entry = makeEntry({ id: 'audit-org', org_id: 'org-xyz', org_name: 'Kiwi Motors' })
    setupMocks(makeAuditList([entry]), entry)
    const user = userEvent.setup()
    render(<AuditLog />)

    await screen.findByText(entry.description)
    await user.click(screen.getByRole('button', { name: 'View' }))

    expect(await screen.findByText('Kiwi Motors')).toBeInTheDocument()
    expect(screen.getByText('org-xyz')).toBeInTheDocument()
  })

  // Action badges displayed in table
  it('displays action badges in the audit log table', async () => {
    const entries = [
      makeEntry({ id: 'a1', action: 'create', description: 'Created record' }),
      makeEntry({ id: 'a2', action: 'delete', description: 'Deleted record' }),
    ]
    setupMocks(makeAuditList(entries))
    render(<AuditLog />)

    await screen.findByText('Created record')
    const table = screen.getByRole('grid', { name: /audit log entries/i })
    expect(within(table).getByText('Create')).toBeInTheDocument()
    expect(within(table).getByText('Delete')).toBeInTheDocument()
  })

  // User email displayed in table rows
  it('displays user email in table rows', async () => {
    const entries = [
      makeEntry({ id: 'a1', user_email: 'alice@test.com', description: 'Action by Alice' }),
    ]
    setupMocks(makeAuditList(entries))
    render(<AuditLog />)

    await screen.findByText('Action by Alice')
    expect(screen.getByText('alice@test.com')).toBeInTheDocument()
  })

  // IP address displayed in table rows
  it('displays IP address in table rows', async () => {
    const entries = [
      makeEntry({ id: 'a1', ip_address: '203.0.113.42', description: 'Some action' }),
    ]
    setupMocks(makeAuditList(entries))
    render(<AuditLog />)

    await screen.findByText('Some action')
    expect(screen.getByText('203.0.113.42')).toBeInTheDocument()
  })

  // Empty state
  it('shows empty state when no audit entries found', async () => {
    setupMocks(makeAuditList([]))
    render(<AuditLog />)

    expect(await screen.findByText('No audit entries found')).toBeInTheDocument()
    expect(screen.getByText('0 entries found')).toBeInTheDocument()
  })

  // Loading state
  it('shows loading spinner while fetching audit log', () => {
    ;(apiClient.get as ReturnType<typeof vi.fn>).mockReturnValue(new Promise(() => {}))
    render(<AuditLog />)

    expect(screen.getByRole('status', { name: /loading audit log/i })).toBeInTheDocument()
  })

  // Error state
  it('shows error banner when audit log fails to load', async () => {
    ;(apiClient.get as ReturnType<typeof vi.fn>).mockRejectedValue(new Error('Network error'))
    render(<AuditLog />)

    expect(await screen.findByText(/Could not load audit log/)).toBeInTheDocument()
  })

  // Singular entry count
  it('shows singular entry count for one result', async () => {
    setupMocks(makeAuditList([makeEntry()]))
    render(<AuditLog />)

    expect(await screen.findByText('1 entry found')).toBeInTheDocument()
  })
})
