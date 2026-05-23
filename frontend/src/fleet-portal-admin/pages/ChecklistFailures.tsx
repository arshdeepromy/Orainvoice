/**
 * Workshop Admin — Recent fleet checklist failures.
 *
 * Surfaces the same data the dashboard shows as a count, but as a
 * navigable feed grouped by date with rego, driver, fail counts.
 *
 * Implements: B2B Fleet Portal — Req 16.7.
 */
import { useEffect, useState, useCallback } from 'react'
import { Link } from 'react-router-dom'

import apiClient from '../../api/client'

interface FailureRow {
  submission_id: string
  fleet_account_id: string
  fleet_account_name: string | null
  rego: string | null
  driver_name: string | null
  failed_item_count: number
  passed_item_count: number
  na_item_count: number
  completed_at: string | null
}

export default function ChecklistFailures() {
  const [items, setItems] = useState<FailureRow[]>([])
  const [days, setDays] = useState(30)
  const [loading, setLoading] = useState(true)
  const [err, setErr] = useState<string | null>(null)

  const fetchData = useCallback(async (signal?: AbortSignal) => {
    setLoading(true)
    try {
      const res = await apiClient.get<{ items: FailureRow[]; total: number }>(
        '/api/v2/fleet-portal/admin/checklist-failures',
        { signal, params: { limit: 100, days } },
      )
      setItems(res.data?.items ?? [])
    } catch (e: unknown) {
      if (!(signal?.aborted ?? false)) {
        const detail =
          (e as { response?: { data?: { detail?: string } } })?.response?.data?.detail ??
          'Failed to load failures feed.'
        setErr(detail)
      }
    } finally {
      if (!(signal?.aborted ?? false)) setLoading(false)
    }
  }, [days])

  useEffect(() => {
    const c = new AbortController()
    void fetchData(c.signal)
    return () => c.abort()
  }, [fetchData])

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between">
        <h1 className="text-xl font-semibold">Checklist Failures</h1>
        <Link
          to="/fleet-portal-admin"
          className="text-sm text-indigo-600 hover:underline"
        >
          ← Fleet Portal
        </Link>
      </div>

      <div className="flex items-center gap-3">
        <label className="text-xs text-gray-500">Window:</label>
        <select
          value={days}
          onChange={(e) => setDays(parseInt(e.target.value, 10) || 30)}
          className="rounded border border-gray-300 px-2 py-1 text-sm min-h-[36px] dark:border-gray-700 dark:bg-gray-900 dark:text-white"
        >
          <option value={7}>Last 7 days</option>
          <option value={30}>Last 30 days</option>
          <option value={90}>Last 90 days</option>
          <option value={365}>Last year</option>
        </select>
      </div>

      {err ? (
        <p className="rounded border border-red-200 bg-red-50 p-2 text-xs text-red-800">
          {err}
        </p>
      ) : null}

      {loading ? (
        <div className="p-4 text-sm text-gray-500">Loading…</div>
      ) : (items ?? []).length === 0 ? (
        <div className="rounded-lg border border-dashed border-gray-300 p-6 text-center dark:border-gray-700">
          <p className="text-sm text-gray-500">No failures recorded in this window.</p>
        </div>
      ) : (
        <div className="overflow-x-auto rounded-lg border border-gray-200 dark:border-gray-800">
          <table className="min-w-full divide-y divide-gray-200 dark:divide-gray-800 text-sm">
            <thead className="bg-gray-50 dark:bg-gray-900">
              <tr>
                <th className="px-3 py-2 text-left text-xs font-medium uppercase text-gray-500">When</th>
                <th className="px-3 py-2 text-left text-xs font-medium uppercase text-gray-500">Fleet</th>
                <th className="px-3 py-2 text-left text-xs font-medium uppercase text-gray-500">Vehicle</th>
                <th className="px-3 py-2 text-left text-xs font-medium uppercase text-gray-500">Driver</th>
                <th className="px-3 py-2 text-right text-xs font-medium uppercase text-gray-500">Failed</th>
                <th className="px-3 py-2 text-right text-xs font-medium uppercase text-gray-500">Passed</th>
                <th className="px-3 py-2 text-right text-xs font-medium uppercase text-gray-500">N/A</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-gray-200 dark:divide-gray-800 bg-white dark:bg-gray-950">
              {(items ?? []).map((r) => (
                <tr key={r.submission_id}>
                  <td className="px-3 py-2 text-gray-500">
                    {r.completed_at ? new Date(r.completed_at).toLocaleString() : '—'}
                  </td>
                  <td className="px-3 py-2">{r.fleet_account_name ?? '—'}</td>
                  <td className="px-3 py-2 font-medium">{r.rego ?? '—'}</td>
                  <td className="px-3 py-2">{r.driver_name ?? '—'}</td>
                  <td className="px-3 py-2 text-right text-red-600">{r.failed_item_count ?? 0}</td>
                  <td className="px-3 py-2 text-right">{r.passed_item_count ?? 0}</td>
                  <td className="px-3 py-2 text-right text-gray-500">{r.na_item_count ?? 0}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  )
}
