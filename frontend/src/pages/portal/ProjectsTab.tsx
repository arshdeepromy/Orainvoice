import { useState, useEffect } from 'react'
import apiClient from '@/api/client'
import { Badge } from '@/components/ui/Badge'
import { Spinner } from '@/components/ui/Spinner'
import { AlertBanner } from '@/components/ui/AlertBanner'
import { usePortalLocale } from './PortalLocaleContext'
import { formatDate, formatCurrency } from './portalFormatters'

export interface PortalProject {
  id: string
  name: string
  status: string
  description: string | null
  budget_amount: number | null
  contract_value: number | null
  start_date: string | null
  target_end_date: string | null
  created_at: string
}

interface ProjectsTabProps {
  token: string
}

const STATUS_CONFIG: Record<string, { label: string; variant: 'success' | 'warning' | 'error' | 'info' | 'neutral' }> = {
  active: { label: 'Active', variant: 'info' },
  completed: { label: 'Completed', variant: 'success' },
  on_hold: { label: 'On Hold', variant: 'warning' },
  cancelled: { label: 'Cancelled', variant: 'error' },
}

export function ProjectsTab({ token }: ProjectsTabProps) {
  const locale = usePortalLocale()
  const [projects, setProjects] = useState<PortalProject[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')

  useEffect(() => {
    const controller = new AbortController()
    const fetchProjects = async () => {
      setLoading(true)
      setError('')
      try {
        const res = await apiClient.get(`/portal/${token}/projects`, { signal: controller.signal })
        setProjects(res.data?.projects ?? [])
      } catch (err) {
        if (!controller.signal.aborted) setError('Failed to load projects.')
      } finally {
        if (!controller.signal.aborted) setLoading(false)
      }
    }
    fetchProjects()
    return () => controller.abort()
  }, [token])

  if (loading) return <div className="py-8"><Spinner label="Loading projects" /></div>
  if (error) return <AlertBanner variant="error">{error}</AlertBanner>
  if (projects.length === 0) return <p className="py-8 text-center text-sm text-gray-500">No projects found.</p>

  return (
    <div className="space-y-4">
      {projects.map((project) => {
        const statusCfg = STATUS_CONFIG[project.status] ?? { label: project.status, variant: 'neutral' as const }
        return (
          <div key={project.id} className="rounded-lg border border-gray-200 bg-white p-4">
            <div className="flex items-center justify-between mb-2">
              <div className="flex items-center gap-2">
                <Badge variant={statusCfg.variant}>{statusCfg.label}</Badge>
                <span className="text-sm font-semibold text-gray-900">{project.name}</span>
              </div>
              <span className="text-xs text-gray-400">{formatDate(project.created_at, locale)}</span>
            </div>

            {project.description && (
              <p className="text-sm text-gray-700 mb-2">{project.description}</p>
            )}

            <div className="flex flex-wrap gap-x-4 gap-y-1 text-xs text-gray-500">
              {project.contract_value != null && (
                <span>Contract: <span className="text-gray-700">{formatCurrency(project.contract_value ?? 0, locale)}</span></span>
              )}
              {project.budget_amount != null && (
                <span>Budget: <span className="text-gray-700">{formatCurrency(project.budget_amount ?? 0, locale)}</span></span>
              )}
              {project.start_date && (
                <span>Start: <span className="text-gray-700">{formatDate(project.start_date, locale)}</span></span>
              )}
              {project.target_end_date && (
                <span>Target end: <span className="text-gray-700">{formatDate(project.target_end_date, locale)}</span></span>
              )}
            </div>
          </div>
        )
      })}
    </div>
  )
}
