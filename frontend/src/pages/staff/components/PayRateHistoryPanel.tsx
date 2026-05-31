/**
 * PayRateHistoryPanel
 *
 * Collapsible read-only panel that lists a staff member's pay rate
 * history. Lazy-fetches `GET /api/v2/staff/:id/pay-rates` only when the
 * user expands the panel, so the network call doesn't run on every
 * Overview tab render.
 *
 * Rendered at the bottom of the Tax & Pay section on the Overview tab
 * (see design §6.2 + §10.2).
 *
 * Refs: Staff Management Phase 1 — R3.5
 */

import React, { useEffect, useState } from 'react'
import apiClient from '@/api/client'

interface PayRate {
  id: string
  effective_from: string
  hourly_rate: string | null
  overtime_rate: string | null
  change_reason: string | null
  changed_by_email: string | null
}

interface PayRateListResponse {
  items: PayRate[]
  total: number
}

interface Props {
  staffId: string
}

export default function PayRateHistoryPanel({ staffId }: Props) {
  const [expanded, setExpanded] = useState(false)
  const [items, setItems] = useState<PayRate[]>([])
  const [hasFetched, setHasFetched] = useState(false)
  const [isLoading, setIsLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    if (!expanded || hasFetched) return
    const controller = new AbortController()
    const fetchHistory = async () => {
      setIsLoading(true)
      setError(null)
      try {
        const res = await apiClient.get<PayRateListResponse>(
          `/api/v2/staff/${staffId}/pay-rates`,
          { signal: controller.signal },
        )
        if (controller.signal.aborted) return
        setItems(res.data?.items ?? [])
        setHasFetched(true)
      } catch (err) {
        if (controller.signal.aborted) return
        setError('Failed to load pay rate history.')
      } finally {
        if (!controller.signal.aborted) setIsLoading(false)
      }
    }
    fetchHistory()
    return () => controller.abort()
  }, [expanded, hasFetched, staffId])

  return (
    <div className="border border-gray-200 dark:border-gray-700 rounded mt-4">
      <button
        type="button"
        className="w-full px-4 py-3 min-h-[44px] text-left text-sm font-medium text-gray-900 dark:text-gray-100 hover:bg-gray-50 dark:hover:bg-gray-800 flex justify-between items-center"
        onClick={() => setExpanded((v) => !v)}
        aria-expanded={expanded}
      >
        <span>Pay rate history</span>
        <span aria-hidden="true">{expanded ? '−' : '+'}</span>
      </button>
      {expanded && (
        <div className="px-4 py-3 border-t border-gray-200 dark:border-gray-700">
          {isLoading && (
            <p className="text-sm text-gray-500 dark:text-gray-400">Loading…</p>
          )}
          {error && !isLoading && (
            <p className="text-sm text-red-600 dark:text-red-400">{error}</p>
          )}
          {!isLoading && !error && (items ?? []).length === 0 && (
            <p className="text-sm text-gray-500 dark:text-gray-400">
              No pay rate changes yet.
            </p>
          )}
          {!isLoading && !error && (items ?? []).length > 0 && (
            <table className="w-full text-sm">
              <thead>
                <tr className="text-left text-xs uppercase text-gray-500 dark:text-gray-400">
                  <th className="py-2 pr-2 font-medium">Effective from</th>
                  <th className="py-2 pr-2 font-medium">Hourly</th>
                  <th className="py-2 pr-2 font-medium">Overtime</th>
                  <th className="py-2 pr-2 font-medium">Change</th>
                  <th className="py-2 font-medium">By</th>
                </tr>
              </thead>
              <tbody>
                {(items ?? []).map((row) => (
                  <tr
                    key={row.id}
                    className="border-t border-gray-100 dark:border-gray-800"
                  >
                    <td className="py-2 pr-2 text-gray-900 dark:text-gray-100">
                      {row.effective_from}
                    </td>
                    <td className="py-2 pr-2 text-gray-900 dark:text-gray-100">
                      {row.hourly_rate ?? '—'}
                    </td>
                    <td className="py-2 pr-2 text-gray-900 dark:text-gray-100">
                      {row.overtime_rate ?? '—'}
                    </td>
                    <td className="py-2 pr-2 text-gray-700 dark:text-gray-300">
                      {row.change_reason ?? '—'}
                    </td>
                    <td className="py-2 text-gray-700 dark:text-gray-300">
                      {row.changed_by_email ?? 'system'}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </div>
      )}
    </div>
  )
}
