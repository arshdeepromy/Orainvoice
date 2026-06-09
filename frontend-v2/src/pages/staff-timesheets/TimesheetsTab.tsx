import { useEffect, useState } from 'react'
import apiClient from '@/api/client'
import type { TimesheetListResponse } from './types'

export default function TimesheetsTab() {
  const [data, setData] = useState<TimesheetListResponse | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    const controller = new AbortController()
    const fetchData = async () => {
      try {
        setLoading(true)
        const res = await apiClient.get<TimesheetListResponse>('/api/v2/timesheets', {
          params: { pay_period_id: '00000000-0000-0000-0000-000000000000' },
          signal: controller.signal,
        })
        setData(res.data)
        setError(null)
      } catch (err: unknown) {
        if (!controller.signal.aborted) {
          setError('Failed to load timesheets')
        }
      } finally {
        if (!controller.signal.aborted) setLoading(false)
      }
    }
    fetchData()
    return () => controller.abort()
  }, [])

  if (loading && !data) {
    return (
      <div className="animate-pulse space-y-3">
        {[1, 2, 3, 4].map((i) => (
          <div key={i} className="h-14 rounded bg-muted/20" />
        ))}
      </div>
    )
  }

  if (error) {
    return (
      <div className="rounded-lg border border-danger/20 bg-danger/5 p-4">
        <p className="text-sm text-danger">{error}</p>
        <button
          onClick={() => window.location.reload()}
          className="mt-2 text-xs text-accent underline"
        >
          Retry
        </button>
      </div>
    )
  }

  const items = data?.items ?? []
  const summary = data?.period_summary

  return (
    <div className="space-y-4">
      {/* Summary cards */}
      {summary && (
        <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
          <div className="rounded-lg border border-border p-3">
            <p className="text-xs text-muted">Total Staff</p>
            <p className="text-lg font-semibold">{summary.total_staff ?? 0}</p>
          </div>
          <div className="rounded-lg border border-border p-3">
            <p className="text-xs text-muted">Approved</p>
            <p className="text-lg font-semibold text-green-600">{summary.approved_count ?? 0}</p>
          </div>
          <div className="rounded-lg border border-border p-3">
            <p className="text-xs text-muted">Pending</p>
            <p className="text-lg font-semibold text-amber-600">{summary.pending_count ?? 0}</p>
          </div>
          <div className="rounded-lg border border-border p-3">
            <p className="text-xs text-muted">Locked</p>
            <p className="text-lg font-semibold text-blue-600">{summary.locked_count ?? 0}</p>
          </div>
        </div>
      )}

      {/* Timesheets table */}
      {items.length === 0 ? (
        <div className="rounded-lg border border-border p-8 text-center">
          <p className="text-muted">No timesheets for this period</p>
        </div>
      ) : (
        <div className="overflow-x-auto rounded-lg border border-border">
          <table className="w-full text-sm">
            <thead className="border-b border-border bg-muted/5">
              <tr>
                <th className="px-4 py-2 text-left font-medium text-muted">Staff</th>
                <th className="px-4 py-2 text-left font-medium text-muted">Status</th>
                <th className="px-4 py-2 text-right font-medium text-muted">Rostered</th>
                <th className="px-4 py-2 text-right font-medium text-muted">Actual</th>
                <th className="px-4 py-2 text-right font-medium text-muted">Variance</th>
                <th className="px-4 py-2 text-center font-medium text-muted">Exceptions</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-border">
              {items.map((ts) => (
                <tr key={ts.id} className="hover:bg-muted/5">
                  <td className="px-4 py-3 font-medium">{ts.staff_name}</td>
                  <td className="px-4 py-3">
                    <span
                      className={`inline-block rounded-full px-2 py-0.5 text-xs font-medium ${
                        ts.status === 'approved'
                          ? 'bg-green-100 text-green-700'
                          : ts.status === 'locked'
                            ? 'bg-blue-100 text-blue-700'
                            : ts.status === 'pending_approval'
                              ? 'bg-amber-100 text-amber-700'
                              : 'bg-gray-100 text-gray-700'
                      }`}
                    >
                      {ts.status}
                    </span>
                  </td>
                  <td className="px-4 py-3 text-right font-mono">
                    {(ts.rostered_hours ?? 0).toFixed(1)}h
                  </td>
                  <td className="px-4 py-3 text-right font-mono">
                    {(ts.actual_hours ?? 0).toFixed(1)}h
                  </td>
                  <td
                    className={`px-4 py-3 text-right font-mono ${
                      (ts.variance_hours ?? 0) < 0 ? 'text-danger' : ''
                    }`}
                  >
                    {(ts.variance_hours ?? 0).toFixed(1)}h
                  </td>
                  <td className="px-4 py-3 text-center">
                    {(ts.exception_count ?? 0) > 0 && (
                      <span className="text-amber-500">⚠️ {ts.exception_count}</span>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  )
}
