import { useState, useEffect, useCallback } from 'react'
import { Navigate, useNavigate } from 'react-router-dom'
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
      <div className="flex items-center justify-between mb-6">
        <div>
          <h1 className="text-2xl font-semibold text-gray-900">GST Filing Periods</h1>
          <p className="text-sm text-gray-500 mt-1">{(total ?? 0).toLocaleString()} period{total !== 1 ? 's' : ''}</p>
        </div>
        <Button onClick={handleGenerate} disabled={generating}>
          {generating ? 'Generating…' : '+ Generate Periods'}
        </Button>
      </div>

      {error && <div className="rounded-md bg-red-50 p-3 text-sm text-red-700 mb-4">{error}</div>}

      {loading ? (
        <div className="py-8 text-center"><Spinner label="Loading GST periods" /></div>
      ) : (periods ?? []).length === 0 ? (
        <div className="rounded-lg border border-gray-200 bg-white p-8 text-center text-gray-500">
          No GST filing periods found. Click "Generate Periods" to create them.
        </div>
      ) : (
        <div className="overflow-x-auto rounded-lg border border-gray-200 bg-white">
          <table className="min-w-full divide-y divide-gray-200">
            <thead className="bg-gray-50">
              <tr>
                <th className="px-4 py-3 text-left text-xs font-medium uppercase tracking-wider text-gray-500">Period</th>
                <th className="px-4 py-3 text-left text-xs font-medium uppercase tracking-wider text-gray-500">Type</th>
                <th className="px-4 py-3 text-left text-xs font-medium uppercase tracking-wider text-gray-500">Due Date</th>
                <th className="px-4 py-3 text-left text-xs font-medium uppercase tracking-wider text-gray-500">Status</th>
                <th className="px-4 py-3 text-left text-xs font-medium uppercase tracking-wider text-gray-500">Filed At</th>
                <th className="px-4 py-3 text-right text-xs font-medium uppercase tracking-wider text-gray-500">Actions</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-gray-200">
              {(periods ?? []).map(period => (
                <tr
                  key={period.id}
                  className="hover:bg-gray-50 cursor-pointer"
                  onClick={() => navigate(`/tax/gst-periods/${period.id}`)}
                >
                  <td className="px-4 py-3 text-sm font-medium text-gray-900">
                    {new Date(period.period_start).toLocaleDateString('en-NZ')} — {new Date(period.period_end).toLocaleDateString('en-NZ')}
                  </td>
                  <td className="whitespace-nowrap px-4 py-3 text-sm text-gray-700 capitalize">
                    {(period.period_type ?? '').replace(/_/g, ' ')}
                  </td>
                  <td className="whitespace-nowrap px-4 py-3 text-sm text-gray-700">
                    {new Date(period.due_date).toLocaleDateString('en-NZ')}
                  </td>
                  <td className="whitespace-nowrap px-4 py-3 text-sm">
                    <Badge variant={STATUS_BADGE[period.status] ?? 'neutral'}>
                      {(period.status ?? 'unknown').charAt(0).toUpperCase() + (period.status ?? 'unknown').slice(1)}
                    </Badge>
                  </td>
                  <td className="whitespace-nowrap px-4 py-3 text-sm text-gray-500">
                    {period.filed_at ? new Date(period.filed_at).toLocaleDateString('en-NZ') : '—'}
                  </td>
                  <td className="whitespace-nowrap px-4 py-3 text-sm text-right">
                    <Button
                      size="sm"
                      variant="secondary"
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
