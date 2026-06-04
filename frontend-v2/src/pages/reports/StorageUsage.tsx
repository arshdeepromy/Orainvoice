import { useState, useEffect } from 'react'
import apiClient from '@/api/client'
import { Spinner, PrintButton } from '@/components/ui'
import ExportButtons from './ExportButtons'

interface StorageData {
  quota_gb: number
  used_bytes: number
  used_gb: number
  usage_percent: number
  breakdown: { category: string; bytes: number }[]
}

function formatBytes(bytes: number): string {
  if (!bytes || bytes <= 0) return '0 B'
  if (bytes < 1024) return `${bytes} B`
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`
  if (bytes < 1024 * 1024 * 1024) return `${(bytes / (1024 * 1024)).toFixed(1)} MB`
  return `${(bytes / (1024 * 1024 * 1024)).toFixed(2)} GB`
}

function usageColour(pct: number): string {
  if (pct >= 90) return 'bg-danger'
  if (pct >= 80) return 'bg-warn'
  return 'bg-accent'
}

/**
 * Storage usage report — quota, used, breakdown by category.
 * Requirements: 45.1
 */
export default function StorageUsage() {
  const [data, setData] = useState<StorageData | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')

  useEffect(() => {
    const fetchData = async () => {
      setLoading(true)
      setError('')
      try {
        const res = await apiClient.get<StorageData>('/reports/storage')
        setData(res.data)
      } catch {
        setError('Failed to load storage report.')
      } finally {
        setLoading(false)
      }
    }
    fetchData()
  }, [])

  return (
    <div data-print-content>
      <p className="text-sm text-muted mb-4 no-print">Current storage usage and quota.</p>

      <div className="flex justify-end mb-6 no-print">
        <div className="flex items-center gap-2">
          <ExportButtons endpoint="/reports/storage" />
          <PrintButton label="Print Report" />
        </div>
      </div>

      {error && (
        <div className="mb-4 rounded-ctl border border-danger-soft bg-danger-soft px-4 py-3 text-sm text-danger" role="alert">
          {error}
        </div>
      )}

      {loading && <div className="py-16"><Spinner label="Loading storage report" /></div>}

      {!loading && data && (
        <>
          {/* Usage bar */}
          <div className="rounded-card border border-border bg-card p-4 mb-6 shadow-card">
            <div className="flex items-center justify-between mb-2">
              <p className="text-sm font-medium text-text mono">
                {data.used_gb != null ? `${data.used_gb.toFixed(2)} GB` : formatBytes(data.used_bytes ?? 0)} of {data.quota_gb ?? 0} GB used
              </p>
              <p className="text-sm text-muted mono">{data.usage_percent ?? 0}%</p>
            </div>
            <div className="h-4 bg-canvas rounded-full overflow-hidden">
              <div
                className={`h-full rounded-full transition-all duration-300 ${usageColour(data.usage_percent ?? 0)}`}
                style={{ width: `${Math.min(data.usage_percent ?? 0, 100)}%` }}
                role="progressbar"
                aria-valuenow={data.usage_percent ?? 0}
                aria-valuemin={0}
                aria-valuemax={100}
                aria-label="Storage usage"
              />
            </div>
            <div className="mt-3 text-xs text-muted-2 flex flex-wrap gap-x-4 gap-y-1">
              <span>1,024 B = 1 KB</span>
              <span>1,024 KB = 1 MB</span>
              <span>1,024 MB = 1 GB</span>
            </div>
          </div>

          {/* Breakdown */}
          <div className="overflow-hidden rounded-card border border-border bg-card shadow-card">
            <table className="min-w-full" role="grid">
              <caption className="sr-only">Storage breakdown by category</caption>
              <thead>
                <tr>
                  <th scope="col" className="mono border-b border-border px-4 py-3 text-left text-[10.5px] font-medium uppercase tracking-[0.08em] text-muted-2">Category</th>
                  <th scope="col" className="mono border-b border-border px-4 py-3 text-right text-[10.5px] font-medium uppercase tracking-[0.08em] text-muted-2">Size</th>
                </tr>
              </thead>
              <tbody>
                {!data.breakdown || data.breakdown.length === 0 ? (
                  <tr>
                    <td colSpan={2} className="px-4 py-12 text-center text-sm text-muted">
                      No storage data available.
                    </td>
                  </tr>
                ) : (
                  data.breakdown.map((b, i) => (
                    <tr key={b.category || i} className="border-b border-border last:border-b-0 hover:bg-canvas">
                      <td className="px-4 py-3 text-sm text-text">{b.category}</td>
                      <td className="px-4 py-3 text-sm text-muted text-right mono">{formatBytes(b.bytes)}</td>
                    </tr>
                  ))
                )}
              </tbody>
            </table>
          </div>
        </>
      )}
    </div>
  )
}
