import { useState, useEffect } from 'react'
import { Navigate, useParams, useNavigate } from 'react-router-dom'
import apiClient from '@/api/client'
import { Button, Spinner, Badge } from '@/components/ui'
import { useModules } from '@/contexts/ModuleContext'

interface GstFilingPeriod {
  id: string
  org_id: string
  period_type: string
  period_start: string
  period_end: string
  due_date: string
  status: string
  filed_at: string | null
  filed_by: string | null
  ird_reference: string | null
  return_data: Record<string, unknown> | null
  created_at: string
  updated_at: string
}

const STATUS_BADGE: Record<string, 'neutral' | 'warning' | 'success' | 'error'> = {
  draft: 'neutral',
  ready: 'warning',
  filed: 'success',
  accepted: 'success',
  rejected: 'error',
}

export default function GstFilingDetail() {
  const { isEnabled } = useModules()
  if (!isEnabled('accounting')) return <Navigate to="/dashboard" replace />

  const { id } = useParams<{ id: string }>()
  const navigate = useNavigate()
  const [period, setPeriod] = useState<GstFilingPeriod | null>(null)
  const [loading, setLoading] = useState(true)
  const [acting, setActing] = useState(false)
  const [error, setError] = useState('')

  useEffect(() => {
    const controller = new AbortController()
    const fetchPeriod = async () => {
      setLoading(true)
      try {
        const res = await apiClient.get<GstFilingPeriod>(`/gst/periods/${id}`, { signal: controller.signal })
        setPeriod(res.data ?? null)
      } catch (err: unknown) {
        if (!(err instanceof Error && err.name === 'CanceledError')) {
          setError('Failed to load GST period')
        }
      } finally {
        setLoading(false)
      }
    }
    fetchPeriod()
    return () => controller.abort()
  }, [id])

  const handleMarkReady = async () => {
    if (!period) return
    setActing(true)
    setError('')
    try {
      const res = await apiClient.post<GstFilingPeriod>(`/gst/periods/${period.id}/ready`)
      setPeriod(res.data ?? null)
    } catch (err: unknown) {
      const msg = (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail
      setError(msg ?? 'Failed to mark period as ready')
    } finally {
      setActing(false)
    }
  }

  const handleLock = async () => {
    if (!period) return
    if (!confirm('Lock all invoices and expenses in this period? This cannot be undone.')) return
    setActing(true)
    setError('')
    try {
      const res = await apiClient.post<GstFilingPeriod>(`/gst/periods/${period.id}/lock`)
      setPeriod(res.data ?? null)
    } catch (err: unknown) {
      const msg = (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail
      setError(msg ?? 'Failed to lock period')
    } finally {
      setActing(false)
    }
  }

  if (loading) {
    return (
      <div className="px-4 py-6 sm:px-6 lg:px-8">
        <div className="py-8 text-center"><Spinner label="Loading GST period" /></div>
      </div>
    )
  }

  if (!period) {
    return (
      <div className="px-4 py-6 sm:px-6 lg:px-8">
        <div className="rounded-lg border border-gray-200 bg-white p-8 text-center text-gray-500">
          {error || 'GST filing period not found.'}
        </div>
        <div className="mt-4">
          <Button variant="secondary" onClick={() => navigate('/tax/gst-periods')}>← Back</Button>
        </div>
      </div>
    )
  }

  const returnData = period.return_data ?? {}
  const returnEntries = Object.entries(returnData)

  return (
    <div className="px-4 py-6 sm:px-6 lg:px-8">
      <div className="mb-4">
        <button onClick={() => navigate('/tax/gst-periods')} className="text-blue-600 hover:underline text-sm">
          ← Back to GST Periods
        </button>
      </div>

      {error && <div className="rounded-md bg-red-50 p-3 text-sm text-red-700 mb-4">{error}</div>}

      <div className="bg-white rounded-lg border border-gray-200 p-6 mb-6">
        <div className="flex items-center justify-between mb-4">
          <div>
            <h1 className="text-2xl font-semibold text-gray-900">
              {new Date(period.period_start).toLocaleDateString('en-NZ')} — {new Date(period.period_end).toLocaleDateString('en-NZ')}
            </h1>
            <p className="text-sm text-gray-500 mt-1 capitalize">{(period.period_type ?? '').replace(/_/g, ' ')} period</p>
          </div>
          <div className="flex items-center gap-3">
            <Badge variant={STATUS_BADGE[period.status] ?? 'neutral'}>
              {(period.status ?? 'unknown').charAt(0).toUpperCase() + (period.status ?? 'unknown').slice(1)}
            </Badge>
            {period.status === 'draft' && (
              <Button onClick={handleMarkReady} disabled={acting}>
                {acting ? 'Updating…' : 'Mark Ready'}
              </Button>
            )}
            {(period.status === 'draft' || period.status === 'ready') && (
              <Button variant="secondary" onClick={handleLock} disabled={acting}>
                {acting ? 'Locking…' : 'Lock Period'}
              </Button>
            )}
          </div>
        </div>

        <div className="grid grid-cols-2 sm:grid-cols-4 gap-4 text-sm">
          <div>
            <span className="text-gray-500">Due Date</span>
            <p className="font-medium">{new Date(period.due_date).toLocaleDateString('en-NZ')}</p>
          </div>
          <div>
            <span className="text-gray-500">IRD Reference</span>
            <p className="font-medium">{period.ird_reference ?? '—'}</p>
          </div>
          <div>
            <span className="text-gray-500">Filed At</span>
            <p className="font-medium">{period.filed_at ? new Date(period.filed_at).toLocaleDateString('en-NZ') : '—'}</p>
          </div>
          <div>
            <span className="text-gray-500">Created</span>
            <p className="font-medium">{new Date(period.created_at).toLocaleDateString('en-NZ')}</p>
          </div>
        </div>
      </div>

      {/* Return Data */}
      <div className="bg-white rounded-lg border border-gray-200">
        <div className="px-6 py-4 border-b border-gray-200">
          <h2 className="text-lg font-semibold text-gray-900">Return Data</h2>
        </div>
        {returnEntries.length === 0 ? (
          <div className="p-6 text-center text-gray-500 text-sm">
            No return data available yet. Mark the period as ready to generate return data.
          </div>
        ) : (
          <div className="overflow-x-auto">
            <table className="min-w-full divide-y divide-gray-200">
              <thead className="bg-gray-50">
                <tr>
                  <th className="px-4 py-3 text-left text-xs font-medium uppercase tracking-wider text-gray-500">Field</th>
                  <th className="px-4 py-3 text-right text-xs font-medium uppercase tracking-wider text-gray-500">Value</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-gray-200">
                {returnEntries.map(([key, value]) => (
                  <tr key={key} className="hover:bg-gray-50">
                    <td className="px-4 py-3 text-sm font-medium text-gray-900">{key}</td>
                    <td className="whitespace-nowrap px-4 py-3 text-sm text-right text-gray-700 tabular-nums">
                      {typeof value === 'number' ? (value ?? 0).toFixed(2) : String(value ?? '—')}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>
    </div>
  )
}
