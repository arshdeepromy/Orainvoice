import { useState, useEffect, useCallback } from 'react'
import { Navigate, useNavigate } from 'react-router-dom'
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

export default function GstPeriods() {
  const { isEnabled } = useModules()
  if (!isEnabled('accounting')) return <Navigate to="/dashboard" replace />

  const navigate = useNavigate()
  const [periods, setPeriods] = useState<GstFilingPeriod[]>([])
  const [total, setTotal] = useState(0)
  const [loading, setLoading] = useState(true)
  const [generating, setGenerating] = useState(false)
  const [error, setError] = useState('')

  const fetchPeriods = useCallback(async (signal?: AbortSignal) => {
    setLoading(true)
    try {
      const res = await apiClient.get<{ items: GstFilingPeriod[]; total: number }>('/gst/periods', { signal })
      setPeriods(res.data?.items ?? [])
      setTotal(res.data?.total ?? 0)
    } catch (err: unknown) {
      if (!(err instanceof Error && err.name === 'CanceledError')) {
        setPeriods([])
        setTotal(0)
      }
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    const controller = new AbortController()
    fetchPeriods(controller.signal)
    return () => controller.abort()
  }, [fetchPeriods])

  const handleGenerate = async () => {
    setGenerating(true)
    setError('')
    try {
      const currentYear = new Date().getFullYear()
      await apiClient.post('/gst/periods/generate', {
        period_type: 'two_monthly',
        tax_year: currentYear,
      })
      fetchPeriods()
    } catch (err: unknown) {
      const msg = (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail
      setError(msg ?? 'Failed to generate GST periods')
    } finally {
      setGenerating(false)
    }
  }

  return (
    <div className="px-4 py-6 sm:px-6 lg:px-8">
      <div className="mb-6 flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-semibold text-text">GST Filing Periods</h1>
          <p className="mt-1 text-sm text-muted">{(total ?? 0).toLocaleString()} period{total !== 1 ? 's' : ''}</p>
        </div>
        <Button onClick={handleGenerate} disabled={generating}>
          {generating ? 'Generating…' : '+ Generate Periods'}
        </Button>
      </div>

      {error && <div className="mb-4 rounded-ctl bg-danger-soft p-3 text-sm text-danger">{error}</div>}

      {loading ? (
        <div className="py-8 text-center"><Spinner label="Loading GST periods" /></div>
      ) : (periods ?? []).length === 0 ? (
        <div className="rounded-card border border-border bg-card p-8 text-center text-muted">
          No GST filing periods found. Click "Generate Periods" to create them.
        </div>
      ) : (
        <div className="overflow-x-auto rounded-card border border-border bg-card shadow-card">
          <table className="min-w-full">
            <thead>
              <tr>
                <th className={TH}>Period</th>
                <th className={TH}>Type</th>
                <th className={TH}>Due Date</th>
                <th className={TH}>Status</th>
                <th className={TH}>Filed At</th>
                <th className={TH_RIGHT}>Actions</th>
              </tr>
            </thead>
            <tbody>
              {(periods ?? []).map(period => (
                <tr
                  key={period.id}
                  className="cursor-pointer border-b border-border last:border-b-0 hover:bg-canvas"
                  onClick={() => navigate(`/tax/gst-periods/${period.id}`)}
                >
                  <td className="mono px-4 py-3 text-sm font-medium text-text">
                    {new Date(period.period_start).toLocaleDateString('en-NZ')} — {new Date(period.period_end).toLocaleDateString('en-NZ')}
                  </td>
                  <td className="whitespace-nowrap px-4 py-3 text-sm capitalize text-text">
                    {(period.period_type ?? '').replace(/_/g, ' ')}
                  </td>
                  <td className="mono whitespace-nowrap px-4 py-3 text-sm text-text">
                    {new Date(period.due_date).toLocaleDateString('en-NZ')}
                  </td>
                  <td className="whitespace-nowrap px-4 py-3 text-sm">
                    <Badge variant={STATUS_BADGE[period.status] ?? 'neutral'}>
                      {(period.status ?? 'unknown').charAt(0).toUpperCase() + (period.status ?? 'unknown').slice(1)}
                    </Badge>
                  </td>
                  <td className="mono whitespace-nowrap px-4 py-3 text-sm text-muted">
                    {period.filed_at ? new Date(period.filed_at).toLocaleDateString('en-NZ') : '—'}
                  </td>
                  <td className="whitespace-nowrap px-4 py-3 text-right text-sm">
                    <Button
                      size="sm"
                      variant="ghost"
                      onClick={(e: React.MouseEvent) => {
                        e.stopPropagation()
                        navigate(`/tax/gst-periods/${period.id}`)
                      }}
                    >
                      View
                    </Button>
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
