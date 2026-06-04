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

import { useEffect, useState } from 'react'
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
    <div className="mt-4 rounded-card border border-border">
      <button
        type="button"
        className="flex min-h-[44px] w-full items-center justify-between px-4 py-3 text-left text-[13.5px] font-medium text-text hover:bg-canvas"
        onClick={() => setExpanded((v) => !v)}
        aria-expanded={expanded}
      >
        <span>Pay rate history</span>
        <span aria-hidden="true">{expanded ? '−' : '+'}</span>
      </button>
      {expanded && (
        <div className="border-t border-border px-4 py-3">
          {isLoading && (
            <p className="text-[13px] text-muted">Loading…</p>
          )}
          {error && !isLoading && (
            <p className="text-[13px] text-danger">{error}</p>
          )}
          {!isLoading && !error && (items ?? []).length === 0 && (
            <p className="text-[13px] text-muted">
              No pay rate changes yet.
            </p>
          )}
          {!isLoading && !error && (items ?? []).length > 0 && (
            <table className="w-full text-sm">
              <thead>
                <tr className="mono text-left text-[10.5px] uppercase tracking-[0.08em] text-muted-2">
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
                    className="border-t border-border"
                  >
                    <td className="mono py-2 pr-2 text-text">
                      {row.effective_from}
                    </td>
                    <td className="mono py-2 pr-2 text-text">
                      {row.hourly_rate ?? '—'}
                    </td>
                    <td className="mono py-2 pr-2 text-text">
                      {row.overtime_rate ?? '—'}
                    </td>
                    <td className="py-2 pr-2 text-muted">
                      {row.change_reason ?? '—'}
                    </td>
                    <td className="py-2 text-muted">
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
