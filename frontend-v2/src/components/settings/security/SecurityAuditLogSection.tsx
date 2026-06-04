import { useState, useEffect, useCallback } from 'react'
import { Pagination, useToast, ToastContainer } from '@/components/ui'
import apiClient from '@/api/client'

interface AuditLogEntry {
  id: string
  timestamp: string
  user_email: string | null
  action: string
  action_description: string
  ip_address: string | null
  browser: string | null
  os: string | null
  entity_type: string | null
  entity_id: string | null
  before_value: Record<string, unknown> | null
  after_value: Record<string, unknown> | null
}

const PAGE_SIZES = [25, 50, 100]

const ACTION_TYPES = [
  { value: '', label: 'All Actions' },
  { value: 'auth.login_success', label: 'Successful Login' },
  { value: 'auth.login_failed_invalid_password', label: 'Failed Login — Invalid Password' },
  { value: 'auth.login_failed_unknown_email', label: 'Failed Login — Unknown Email' },
  { value: 'auth.login_failed_account_locked', label: 'Failed Login — Account Locked' },
  { value: 'auth.mfa_verified', label: 'MFA Verified' },
  { value: 'auth.mfa_failed', label: 'MFA Failed' },
  { value: 'auth.password_changed', label: 'Password Changed' },
  { value: 'auth.password_reset', label: 'Password Reset' },
  { value: 'auth.session_revoked', label: 'Session Revoked' },
  { value: 'org.security_settings_updated', label: 'Security Settings Updated' },
  { value: 'org.custom_role_created', label: 'Custom Role Created' },
  { value: 'org.custom_role_updated', label: 'Custom Role Updated' },
  { value: 'org.custom_role_deleted', label: 'Custom Role Deleted' },
]

export function SecurityAuditLogSection() {
  const [entries, setEntries] = useState<AuditLogEntry[]>([])
  const [total, setTotal] = useState(0)
  const [truncated, setTruncated] = useState(false)
  const [page, setPage] = useState(1)
  const [pageSize, setPageSize] = useState(25)
  const [startDate, setStartDate] = useState('')
  const [endDate, setEndDate] = useState('')
  const [actionFilter, setActionFilter] = useState('')
  const [userFilter, setUserFilter] = useState('')
  const [loading, setLoading] = useState(true)
  const { toasts, addToast, dismissToast } = useToast()

  const fetchLog = useCallback(async (signal?: AbortSignal) => {
    setLoading(true)
    try {
      const params: Record<string, string | number> = { page, page_size: pageSize }
      if (startDate) params.start_date = new Date(startDate).toISOString()
      if (endDate) params.end_date = new Date(endDate).toISOString()
      if (actionFilter) params.action = actionFilter
      if (userFilter.trim()) params.user_id = userFilter.trim()

      const res = await apiClient.get('/org/security-audit-log', { params, signal })
      setEntries(res.data?.items ?? [])
      setTotal(res.data?.total ?? 0)
      setTruncated(res.data?.truncated ?? false)
    } catch (err) {
      if (!(signal && signal.aborted)) {
        addToast('error', 'Failed to load audit log')
      }
    } finally {
      setLoading(false)
    }
  }, [page, pageSize, startDate, endDate, actionFilter, userFilter]) // eslint-disable-line react-hooks/exhaustive-deps

  useEffect(() => {
    const controller = new AbortController()
    fetchLog(controller.signal)
    return () => controller.abort()
  }, [fetchLog])

  const totalPages = Math.max(1, Math.ceil((total ?? 0) / pageSize))

  const handlePageSizeChange = (size: number) => {
    setPageSize(size)
    setPage(1)
  }

  const formatTimestamp = (ts: string) => {
    try {
      return new Date(ts).toLocaleString()
    } catch {
      return ts ?? ''
    }
  }

  return (
    <div className="space-y-4">
      <ToastContainer toasts={toasts} onDismiss={dismissToast} />

      {/* Filters */}
      <div className="flex flex-wrap gap-3 items-end">
        <div className="flex flex-col gap-1">
          <label className="text-xs font-medium text-muted">Start Date</label>
          <input
            type="date"
            value={startDate}
            onChange={(e) => { setStartDate(e.target.value); setPage(1) }}
            className="rounded-ctl border border-border bg-card px-2 py-1.5 text-sm text-text focus:border-accent focus:outline-none focus:shadow-[0_0_0_3px_var(--accent-soft)]"
          />
        </div>
        <div className="flex flex-col gap-1">
          <label className="text-xs font-medium text-muted">End Date</label>
          <input
            type="date"
            value={endDate}
            onChange={(e) => { setEndDate(e.target.value); setPage(1) }}
            className="rounded-ctl border border-border bg-card px-2 py-1.5 text-sm text-text focus:border-accent focus:outline-none focus:shadow-[0_0_0_3px_var(--accent-soft)]"
          />
        </div>
        <div className="flex flex-col gap-1">
          <label className="text-xs font-medium text-muted">Action</label>
          <select
            value={actionFilter}
            onChange={(e) => { setActionFilter(e.target.value); setPage(1) }}
            className="rounded-ctl border border-border px-2 py-1.5 text-sm bg-card text-text focus:border-accent focus:outline-none focus:shadow-[0_0_0_3px_var(--accent-soft)]"
          >
            {ACTION_TYPES.map((a) => (
              <option key={a.value} value={a.value}>{a.label}</option>
            ))}
          </select>
        </div>
        <div className="flex flex-col gap-1">
          <label className="text-xs font-medium text-muted">User ID</label>
          <input
            type="text"
            value={userFilter}
            onChange={(e) => { setUserFilter(e.target.value); setPage(1) }}
            placeholder="Filter by user ID"
            className="rounded-ctl border border-border bg-card px-2 py-1.5 text-sm text-text focus:border-accent focus:outline-none focus:shadow-[0_0_0_3px_var(--accent-soft)]"
          />
        </div>
        <div className="flex flex-col gap-1">
          <label className="text-xs font-medium text-muted">Per Page</label>
          <select
            value={pageSize}
            onChange={(e) => handlePageSizeChange(Number(e.target.value))}
            className="rounded-ctl border border-border px-2 py-1.5 text-sm bg-card text-text focus:border-accent focus:outline-none focus:shadow-[0_0_0_3px_var(--accent-soft)]"
          >
            {PAGE_SIZES.map((s) => (
              <option key={s} value={s}>{s}</option>
            ))}
          </select>
        </div>
      </div>

      {truncated && (
        <div className="rounded-ctl bg-warn-soft border border-warn px-4 py-2 text-sm text-warn">
          Results limited to the most recent 10,000 entries. Narrow your filters for more specific results.
        </div>
      )}

      {/* Table */}
      <div className="overflow-x-auto rounded-card border border-border bg-card shadow-card">
        <table className="min-w-full divide-y divide-border text-sm">
          <thead className="bg-canvas">
            <tr>
              <th className="mono px-4 py-3 text-left text-[10.5px] font-medium uppercase tracking-[0.08em] text-muted-2">Timestamp</th>
              <th className="mono px-4 py-3 text-left text-[10.5px] font-medium uppercase tracking-[0.08em] text-muted-2">User</th>
              <th className="mono px-4 py-3 text-left text-[10.5px] font-medium uppercase tracking-[0.08em] text-muted-2">Action</th>
              <th className="mono px-4 py-3 text-left text-[10.5px] font-medium uppercase tracking-[0.08em] text-muted-2">IP Address</th>
              <th className="mono px-4 py-3 text-left text-[10.5px] font-medium uppercase tracking-[0.08em] text-muted-2">Browser</th>
              <th className="mono px-4 py-3 text-left text-[10.5px] font-medium uppercase tracking-[0.08em] text-muted-2">OS</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-border">
            {loading ? (
              <tr><td colSpan={6} className="px-4 py-8 text-center text-muted-2">Loading…</td></tr>
            ) : (entries ?? []).length === 0 ? (
              <tr><td colSpan={6} className="px-4 py-8 text-center text-muted-2">No audit log entries found.</td></tr>
            ) : (
              (entries ?? []).map((entry) => (
                <tr key={entry.id} className="border-b border-border last:border-b-0 hover:bg-canvas">
                  <td className="mono px-4 py-2 whitespace-nowrap text-muted">{formatTimestamp(entry.timestamp)}</td>
                  <td className="px-4 py-2 text-muted">{entry.user_email ?? '—'}</td>
                  <td className="px-4 py-2 text-text">{entry.action_description ?? entry.action ?? '—'}</td>
                  <td className="mono px-4 py-2 text-muted-2 text-xs">{entry.ip_address ?? '—'}</td>
                  <td className="px-4 py-2 text-muted-2 text-xs">{entry.browser ?? '—'}</td>
                  <td className="px-4 py-2 text-muted-2 text-xs">{entry.os ?? '—'}</td>
                </tr>
              ))
            )}
          </tbody>
        </table>
      </div>

      {/* Pagination */}
      <div className="flex items-center justify-between">
        <p className="text-sm text-muted-2">
          {(total ?? 0).toLocaleString()} total entries
        </p>
        <Pagination currentPage={page} totalPages={totalPages} onPageChange={setPage} />
      </div>
    </div>
  )
}
