import { useState, useEffect, useCallback } from 'react'
import { Pagination } from '@/components/ui/Pagination'
import apiClient from '@/api/client'

interface PlatformAuditLogEntry {
  id: string
  timestamp: string
  user_email: string | null
  action: string
  action_description: string
  ip_address: string | null
  browser: string | null
  os: string | null
  org_name: string | null
  entity_type: string | null
  entity_id: string | null
  before_value: Record<string, unknown> | null
  after_value: Record<string, unknown> | null
}

interface PlatformAuditLogPage {
  items: PlatformAuditLogEntry[]
  total: number
  page: number
  page_size: number
  truncated: boolean
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

export function PlatformSecurityAuditLogSection() {
  const [entries, setEntries] = useState<PlatformAuditLogEntry[]>([])
  const [total, setTotal] = useState(0)
  const [truncated, setTruncated] = useState(false)
  const [page, setPage] = useState(1)
  const [pageSize, setPageSize] = useState(25)
  const [startDate, setStartDate] = useState('')
  const [endDate, setEndDate] = useState('')
  const [actionFilter, setActionFilter] = useState('')
  const [userFilter, setUserFilter] = useState('')
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  const fetchLog = useCallback(async (signal?: AbortSignal) => {
    setLoading(true)
    setError(null)
    try {
      const params: Record<string, string | number> = { page, page_size: pageSize }
      if (startDate) params.start_date = new Date(startDate).toISOString()
      if (endDate) params.end_date = new Date(endDate).toISOString()
      if (actionFilter) params.action = actionFilter
      if (userFilter.trim()) params.user_id = userFilter.trim()

      const res = await apiClient.get<PlatformAuditLogPage>('/admin/security-audit-log', { params, signal })
      setEntries(res.data?.items ?? [])
      setTotal(res.data?.total ?? 0)
      setTruncated(res.data?.truncated ?? false)
    } catch (err) {
      if (!(signal && signal.aborted)) {
        setError('Failed to load audit log')
      }
    } finally {
      setLoading(false)
    }
  }, [page, pageSize, startDate, endDate, actionFilter, userFilter])

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
      {/* Error banner */}
      {error && (
        <div className="rounded-md bg-red-50 border border-red-200 px-4 py-2 text-sm text-red-700">
          {error}
        </div>
      )}

      {/* Filters */}
      <div className="flex flex-wrap gap-3 items-end">
        <div className="flex flex-col gap-1">
          <label className="text-xs font-medium text-gray-600">Start Date</label>
          <input
            type="date"
            value={startDate}
            onChange={(e) => { setStartDate(e.target.value); setPage(1) }}
            className="rounded-md border border-gray-300 px-2 py-1.5 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
          />
        </div>
        <div className="flex flex-col gap-1">
          <label className="text-xs font-medium text-gray-600">End Date</label>
          <input
            type="date"
            value={endDate}
            onChange={(e) => { setEndDate(e.target.value); setPage(1) }}
            className="rounded-md border border-gray-300 px-2 py-1.5 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
          />
        </div>
        <div className="flex flex-col gap-1">
          <label className="text-xs font-medium text-gray-600">Action</label>
          <select
            value={actionFilter}
            onChange={(e) => { setActionFilter(e.target.value); setPage(1) }}
            className="rounded-md border border-gray-300 px-2 py-1.5 text-sm bg-white focus:outline-none focus:ring-2 focus:ring-blue-500"
          >
            {ACTION_TYPES.map((a) => (
              <option key={a.value} value={a.value}>{a.label}</option>
            ))}
          </select>
        </div>
        <div className="flex flex-col gap-1">
          <label className="text-xs font-medium text-gray-600">User ID</label>
          <input
            type="text"
            value={userFilter}
            onChange={(e) => { setUserFilter(e.target.value); setPage(1) }}
            placeholder="Filter by user ID"
            className="rounded-md border border-gray-300 px-2 py-1.5 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
          />
        </div>
        <div className="flex flex-col gap-1">
          <label className="text-xs font-medium text-gray-600">Per Page</label>
          <select
            value={pageSize}
            onChange={(e) => handlePageSizeChange(Number(e.target.value))}
            className="rounded-md border border-gray-300 px-2 py-1.5 text-sm bg-white focus:outline-none focus:ring-2 focus:ring-blue-500"
          >
            {PAGE_SIZES.map((s) => (
              <option key={s} value={s}>{s}</option>
            ))}
          </select>
        </div>
      </div>

      {/* Truncation warning */}
      {truncated && (
        <div className="rounded-md bg-amber-50 border border-amber-200 px-4 py-2 text-sm text-amber-800">
          Results limited to the most recent 10,000 entries. Narrow your filters for more specific results.
        </div>
      )}

      {/* Table */}
      <div className="overflow-x-auto border rounded-lg">
        <table className="min-w-full divide-y divide-gray-200 text-sm">
          <thead className="bg-gray-50">
            <tr>
              <th className="px-4 py-2 text-left font-medium text-gray-600">Timestamp</th>
              <th className="px-4 py-2 text-left font-medium text-gray-600">User</th>
              <th className="px-4 py-2 text-left font-medium text-gray-600">Action</th>
              <th className="px-4 py-2 text-left font-medium text-gray-600">Organisation</th>
              <th className="px-4 py-2 text-left font-medium text-gray-600">IP Address</th>
              <th className="px-4 py-2 text-left font-medium text-gray-600">Browser</th>
              <th className="px-4 py-2 text-left font-medium text-gray-600">OS</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-gray-100">
            {loading ? (
              <tr><td colSpan={7} className="px-4 py-8 text-center text-gray-500">Loading…</td></tr>
            ) : (entries ?? []).length === 0 ? (
              <tr><td colSpan={7} className="px-4 py-8 text-center text-gray-500">No audit log entries found.</td></tr>
            ) : (
              (entries ?? []).map((entry) => (
                <tr key={entry.id} className="hover:bg-gray-50">
                  <td className="px-4 py-2 whitespace-nowrap text-gray-700">{formatTimestamp(entry.timestamp)}</td>
                  <td className="px-4 py-2 text-gray-700">{entry.user_email ?? '—'}</td>
                  <td className="px-4 py-2 text-gray-900">{entry.action_description ?? entry.action ?? '—'}</td>
                  <td className="px-4 py-2 text-gray-700">{entry.org_name ?? 'Platform'}</td>
                  <td className="px-4 py-2 text-gray-500 font-mono text-xs">{entry.ip_address ?? '—'}</td>
                  <td className="px-4 py-2 text-gray-500 text-xs">{entry.browser ?? '—'}</td>
                  <td className="px-4 py-2 text-gray-500 text-xs">{entry.os ?? '—'}</td>
                </tr>
              ))
            )}
          </tbody>
        </table>
      </div>

      {/* Pagination */}
      <div className="flex items-center justify-between">
        <p className="text-sm text-gray-500">
          {(total ?? 0).toLocaleString()} total entries
        </p>
        <Pagination currentPage={page} totalPages={totalPages} onPageChange={setPage} />
      </div>
    </div>
  )
}
