import { useState, useEffect } from 'react'
import apiClient from '@/api/client'
import { Badge } from '@/components/ui/Badge'
import { Spinner } from '@/components/ui/Spinner'
import { AlertBanner } from '@/components/ui/AlertBanner'
import { usePortalLocale } from './PortalLocaleContext'
import { formatDate } from './portalFormatters'

export interface PortalJob {
  id: string
  status: string
  description: string | null
  assigned_staff_name: string | null
  vehicle_rego: string | null
  linked_invoice_number: string | null
  estimated_completion: string | null
  created_at: string
}

interface JobsTabProps {
  token: string
}

const STATUS_CONFIG: Record<string, { label: string; variant: 'success' | 'warning' | 'error' | 'info' | 'neutral' }> = {
  open: { label: 'Pending', variant: 'warning' },
  in_progress: { label: 'In Progress', variant: 'info' },
  completed: { label: 'Completed', variant: 'success' },
  invoiced: { label: 'Invoiced', variant: 'neutral' },
}

export function JobsTab({ token }: JobsTabProps) {
  const locale = usePortalLocale()
  const [jobs, setJobs] = useState<PortalJob[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')

  useEffect(() => {
    const controller = new AbortController()
    const fetchJobs = async () => {
      setLoading(true)
      setError('')
      try {
        const res = await apiClient.get(`/portal/${token}/jobs`, { signal: controller.signal })
        setJobs(res.data?.jobs ?? [])
      } catch (err) {
        if (!controller.signal.aborted) setError('Failed to load jobs.')
      } finally {
        if (!controller.signal.aborted) setLoading(false)
      }
    }
    fetchJobs()
    return () => controller.abort()
  }, [token])

  if (loading) return <div className="py-8"><Spinner label="Loading jobs" /></div>
  if (error) return <AlertBanner variant="error">{error}</AlertBanner>
  if (jobs.length === 0) return <p className="py-8 text-center text-sm text-gray-500">No jobs found.</p>

  return (
    <div className="space-y-4">
      {jobs.map((job) => {
        const statusCfg = STATUS_CONFIG[job.status] ?? { label: job.status, variant: 'neutral' as const }
        return (
          <div key={job.id} className="rounded-lg border border-gray-200 bg-white p-4">
            <div className="flex items-center justify-between mb-2">
              <div className="flex items-center gap-2">
                <Badge variant={statusCfg.variant}>{statusCfg.label}</Badge>
                {job.vehicle_rego && (
                  <span className="text-sm font-medium text-gray-700">{job.vehicle_rego}</span>
                )}
              </div>
              <span className="text-xs text-gray-400">{formatDate(job.created_at, locale)}</span>
            </div>

            {job.description && (
              <p className="text-sm text-gray-700 mb-2">{job.description}</p>
            )}

            <div className="flex flex-wrap gap-x-4 gap-y-1 text-xs text-gray-500">
              {job.assigned_staff_name && (
                <span>Assigned to: <span className="text-gray-700">{job.assigned_staff_name}</span></span>
              )}
              {job.linked_invoice_number && (
                <span>Invoice: <span className="text-gray-700">{job.linked_invoice_number}</span></span>
              )}
              {job.estimated_completion && (
                <span>Est. completion: <span className="text-gray-700">{formatDate(job.estimated_completion, locale)}</span></span>
              )}
            </div>
          </div>
        )
      })}
    </div>
  )
}
