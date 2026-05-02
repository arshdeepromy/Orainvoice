import { useState, useEffect } from 'react'
import apiClient from '@/api/client'
import { Badge } from '@/components/ui/Badge'
import { Spinner } from '@/components/ui/Spinner'
import { AlertBanner } from '@/components/ui/AlertBanner'
import { usePortalLocale } from './PortalLocaleContext'
import { formatDate, formatCurrency } from './portalFormatters'

export interface PortalRecurringLineItem {
  description: string
  quantity: number
  unit_price: number
  total?: number
}

export interface PortalRecurringSchedule {
  id: string
  frequency: string
  next_generation_date: string
  status: string
  line_items: PortalRecurringLineItem[]
  start_date: string
  end_date: string | null
  auto_issue: boolean
  created_at: string
}

interface RecurringTabProps {
  token: string
}

const STATUS_CONFIG: Record<string, { label: string; variant: 'success' | 'warning' | 'error' | 'info' | 'neutral' }> = {
  active: { label: 'Active', variant: 'success' },
  paused: { label: 'Paused', variant: 'warning' },
  completed: { label: 'Completed', variant: 'neutral' },
  cancelled: { label: 'Cancelled', variant: 'error' },
}

const FREQUENCY_LABELS: Record<string, string> = {
  weekly: 'Weekly',
  fortnightly: 'Fortnightly',
  monthly: 'Monthly',
  quarterly: 'Quarterly',
  annually: 'Annually',
}

function computeScheduleTotal(lineItems: PortalRecurringLineItem[]): number {
  return (lineItems ?? []).reduce((sum, li) => sum + ((li.total ?? 0) || (li.quantity ?? 0) * (li.unit_price ?? 0)), 0)
}

export function RecurringTab({ token }: RecurringTabProps) {
  const locale = usePortalLocale()
  const [schedules, setSchedules] = useState<PortalRecurringSchedule[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')

  useEffect(() => {
    const controller = new AbortController()
    const fetchRecurring = async () => {
      setLoading(true)
      setError('')
      try {
        const res = await apiClient.get(`/portal/${token}/recurring`, { signal: controller.signal })
        setSchedules(res.data?.schedules ?? [])
      } catch (err) {
        if (!controller.signal.aborted) setError('Failed to load recurring schedules.')
      } finally {
        if (!controller.signal.aborted) setLoading(false)
      }
    }
    fetchRecurring()
    return () => controller.abort()
  }, [token])

  if (loading) return <div className="py-8"><Spinner label="Loading recurring schedules" /></div>
  if (error) return <AlertBanner variant="error">{error}</AlertBanner>
  if (schedules.length === 0) return <p className="py-8 text-center text-sm text-gray-500">No recurring schedules found.</p>

  return (
    <div className="space-y-4">
      {schedules.map((sched) => {
        const statusCfg = STATUS_CONFIG[sched.status] ?? { label: sched.status, variant: 'neutral' as const }
        const freqLabel = FREQUENCY_LABELS[sched.frequency] ?? sched.frequency
        const total = computeScheduleTotal(sched.line_items ?? [])
        const summary = (sched.line_items ?? [])
          .map((li) => li.description)
          .filter(Boolean)
          .join(', ')

        return (
          <div key={sched.id} className="rounded-lg border border-gray-200 bg-white p-4">
            <div className="flex items-center justify-between mb-2">
              <div className="flex items-center gap-2">
                <Badge variant={statusCfg.variant}>{statusCfg.label}</Badge>
                <span className="text-sm font-semibold text-gray-900">{freqLabel}</span>
              </div>
              <span className="text-sm font-semibold text-gray-900">
                {formatCurrency(total ?? 0, locale)}
              </span>
            </div>

            {summary && (
              <p className="text-sm text-gray-700 mb-2">{summary}</p>
            )}

            <div className="flex flex-wrap gap-x-4 gap-y-1 text-xs text-gray-500">
              <span>
                Next billing: <span className="text-gray-700">{formatDate(sched.next_generation_date, locale)}</span>
              </span>
              <span>
                Started: <span className="text-gray-700">{formatDate(sched.start_date, locale)}</span>
              </span>
              {sched.end_date && (
                <span>
                  Ends: <span className="text-gray-700">{formatDate(sched.end_date, locale)}</span>
                </span>
              )}
              {sched.auto_issue && (
                <span className="text-green-600">Auto-issue</span>
              )}
            </div>
          </div>
        )
      })}
    </div>
  )
}
