import { useState, useEffect } from 'react'
import { Navigate, useParams, useNavigate } from 'react-router-dom'
import apiClient from '@/api/client'
import { Button, Spinner, Badge } from '@/components/ui'
import type { BadgeVariant } from '@/components/ui'
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

const STATUS_BADGE: Record<string, BadgeVariant> = {
  draft: 'neutral',
  ready: 'warn',
  filed: 'success',
  accepted: 'success',
  rejected: 'danger',
}

const TH =
  'mono border-b border-border px-4 py-3 text-left text-[10.5px] font-medium uppercase tracking-[0.08em] text-muted-2'
const TH_RIGHT =
  'mono border-b border-border px-4 py-3 text-right text-[10.5px] font-medium uppercase tracking-[0.08em] text-muted-2'

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
        <div className="rounded-card border border-border bg-card p-8 text-center text-muted">
          {error || 'GST filing period not found.'}
        </div>
        <div className="mt-4">
          <Button variant="ghost" onClick={() => navigate('/tax/gst-periods')}>← Back</Button>
        </div>
      </div>
    )
  }

  const returnData = period.return_data ?? {}
  const returnEntries = Object.entries(returnData)

  return (
    <div className="px-4 py-6 sm:px-6 lg:px-8">
      <div className="mb-4">
        <button onClick={() => navigate('/tax/gst-periods')} className="text-sm text-accent hover:underline">
          ← Back to GST Periods
        </button>
      </div>

      {error && <div className="mb-4 rounded-ctl bg-danger-soft p-3 text-sm text-danger">{error}</div>}

      <div className="mb-6 rounded-card border border-border bg-card p-6 shadow-card">
        <div className="mb-4 flex items-center justify-between">
          <div>
            <h1 className="text-2xl font-semibold text-text">
              {new Date(period.period_start).toLocaleDateString('en-NZ')} — {new Date(period.period_end).toLocaleDateString('en-NZ')}
            </h1>
            <p className="mt-1 text-sm capitalize text-muted">{(period.period_type ?? '').replace(/_/g, ' ')} period</p>
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
              <Button variant="ghost" onClick={handleLock} disabled={acting}>
                {acting ? 'Locking…' : 'Lock Period'}
              </Button>
            )}
          </div>
        </div>

        <div className="grid grid-cols-2 gap-4 text-sm sm:grid-cols-4">
          <div>
            <span className="text-muted">Due Date</span>
            <p className="mono font-medium text-text">{new Date(period.due_date).toLocaleDateString('en-NZ')}</p>
          </div>
          <div>
            <span className="text-muted">IRD Reference</span>
            <p className="font-medium text-text">{period.ird_reference ?? '—'}</p>
          </div>
          <div>
            <span className="text-muted">Filed At</span>
            <p className="mono font-medium text-text">{period.filed_at ? new Date(period.filed_at).toLocaleDateString('en-NZ') : '—'}</p>
          </div>
          <div>
            <span className="text-muted">Created</span>
            <p className="mono font-medium text-text">{new Date(period.created_at).toLocaleDateString('en-NZ')}</p>
          </div>
        </div>
      </div>

      {/* Return Data */}
      <div className="overflow-hidden rounded-card border border-border bg-card shadow-card">
        <div className="border-b border-border px-6 py-4">
          <h2 className="text-lg font-semibold text-text">Return Data</h2>
        </div>
        {returnEntries.length === 0 ? (
          <div className="p-6 text-center text-sm text-muted">
            No return data available yet. Mark the period as ready to generate return data.
          </div>
        ) : (
          <div className="overflow-x-auto">
            <table className="min-w-full">
              <thead>
                <tr>
                  <th className={TH}>Field</th>
                  <th className={TH_RIGHT}>Value</th>
                </tr>
              </thead>
              <tbody>
                {returnEntries.map(([key, value]) => (
                  <tr key={key} className="border-b border-border last:border-b-0 hover:bg-canvas">
                    <td className="px-4 py-3 text-sm font-medium text-text">{key}</td>
                    <td className="mono whitespace-nowrap px-4 py-3 text-right text-sm text-text">
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
