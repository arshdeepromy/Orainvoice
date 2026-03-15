import { useState, useEffect } from 'react'
import apiClient from '../../api/client'
import { Spinner, PrintButton } from '../../components/ui'
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
  if (pct >= 90) return 'bg-red-500'
  if (pct >= 80) return 'bg-amber-500'
  return 'bg-blue-500'
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
      <p className="text-sm text-gray-500 mb-4 no-print">Current storage usage and quota.</p>

      <div className="flex justify-end mb-6 no-print">
        <div className="flex items-center gap-2">
          <ExportButtons endpoint="/reports/storage" />
          <PrintButton label="Print Report" />
        </div>
      </div>

      {error && (
        <div className="mb-4 rounded-md border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700" role="alert">
          {error}
        </div>
      )}

      {loading && <div className="py-16"><Spinner label="Loading storage report" /></div>}

      {!loading && data && (
        <>
          {/* Usage bar */}
          <div className="rounded-lg border border-gray-200 bg-white p-4 mb-6">
            <div className="flex items-center justify-between mb-2">
              <p className="text-sm font-medium text-gray-700">
                {formatBytes(data.used_bytes ?? 0)} of {data.quota_gb ?? 0} GB used
              </p>
              <p className="text-sm text-gray-500">{data.usage_percent ?? 0}%</p>
            </div>
            <div className="h-4 bg-gray-100 rounded-full overflow-hidden">
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
            <div className="mt-3 text-xs text-gray-400 flex flex-wrap gap-x-4 gap-y-1">
              <span>1,024 B = 1 KB</span>
              <span>1,024 KB = 1 MB</span>
              <span>1,024 MB = 1 GB</span>
            </div>
          </div>

          {/* Breakdown */}
          <div className="overflow-x-auto rounded-lg border border-gray-200">
            <table className="min-w-full divide-y divide-gray-200" role="grid">
              <caption className="sr-only">Storage breakdown by category</caption>
              <thead className="bg-gray-50">
                <tr>
                  <th scope="col" className="px-4 py-3 text-left text-xs font-medium uppercase tracking-wider text-gray-500">Category</th>
                  <th scope="col" className="px-4 py-3 text-right text-xs font-medium uppercase tracking-wider text-gray-500">Size</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-gray-200 bg-white">
                {!data.breakdown || data.breakdown.length === 0 ? (
                  <tr>
                    <td colSpan={2} className="px-4 py-12 text-center text-sm text-gray-500">
                      No storage data available.
                    </td>
                  </tr>
                ) : (
                  data.breakdown.map((b, i) => (
                    <tr key={b.category || i} className="hover:bg-gray-50">
                      <td className="px-4 py-3 text-sm text-gray-900">{b.category}</td>
                      <td className="px-4 py-3 text-sm text-gray-700 text-right">{formatBytes(b.bytes)}</td>
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
