import { useEffect, useState } from 'react'
import apiClient from '@/api/client'
import type { ClockedInResponse } from './types'

export default function ClockedInTab() {
  const [data, setData] = useState<ClockedInResponse | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    const controller = new AbortController()
    const fetchData = async () => {
      try {
        setLoading(true)
        const res = await apiClient.get<ClockedInResponse>('/api/v2/clocked-in', {
          signal: controller.signal,
        })
        setData(res.data)
        setError(null)
      } catch (err: unknown) {
        if (!controller.signal.aborted) {
          setError('Failed to load clocked-in data')
        }
      } finally {
        if (!controller.signal.aborted) setLoading(false)
      }
    }
    fetchData()
    // Auto-refresh every 30s
    const interval = setInterval(fetchData, 30000)
    return () => {
      controller.abort()
      clearInterval(interval)
    }
  }, [])

  if (loading && !data) {
    return (
      <div className="animate-pulse space-y-3">
        {[1, 2, 3].map((i) => (
          <div key={i} className="h-12 rounded bg-muted/20" />
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
  const total = data?.total ?? 0

  if (items.length === 0) {
    return (
      <div className="rounded-lg border border-border p-8 text-center">
        <p className="text-muted">No staff currently clocked in</p>
      </div>
    )
  }

  return (
    <div className="space-y-4">
      <div className="flex items-center gap-2">
        <span className="inline-flex h-6 w-6 items-center justify-center rounded-full bg-accent/10 text-xs font-semibold text-accent">
          {total}
        </span>
        <span className="text-sm text-muted">staff clocked in</span>
      </div>

      <div className="divide-y divide-border rounded-lg border border-border">
        {items.map((entry) => (
          <div key={entry.id} className="flex items-center justify-between px-4 py-3">
            <div>
              <p className="font-medium text-text">{entry.staff_name}</p>
              <p className="text-xs text-muted">
                {entry.position ?? 'Staff'} • {entry.clock_in_branch_name}
              </p>
            </div>
            <div className="text-right">
              <p className="text-sm font-mono text-text">{entry.elapsed_minutes} min</p>
              <p className="text-xs text-muted">{entry.source}</p>
            </div>
          </div>
        ))}
      </div>
    </div>
  )
}
