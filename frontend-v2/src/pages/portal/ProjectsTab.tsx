import { useState, useEffect } from 'react'
import apiClient from '@/api/client'
import { Badge, Spinner, AlertBanner } from '@/components/ui'
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

const STATUS_CONFIG: Record<string, { label: string; variant: 'success' | 'warn' | 'danger' | 'info' | 'neutral' }> = {
  active: { label: 'Active', variant: 'info' },
  completed: { label: 'Completed', variant: 'success' },
  on_hold: { label: 'On Hold', variant: 'warn' },
  cancelled: { label: 'Cancelled', variant: 'danger' },
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
  if (projects.length === 0) return <p className="py-8 text-center text-sm text-muted">No projects found.</p>

  return (
    <div className="space-y-4">
      {projects.map((project) => {
        const statusCfg = STATUS_CONFIG[project.status] ?? { label: project.status, variant: 'neutral' as const }
        return (
          <div key={project.id} className="rounded-card border border-border bg-card shadow-card p-4">
            <div className="flex items-center justify-between mb-2">
              <div className="flex items-center gap-2">
                <Badge variant={statusCfg.variant}>{statusCfg.label}</Badge>
                <span className="text-sm font-semibold text-text">{project.name}</span>
              </div>
              <span className="text-xs text-muted-2">{formatDate(project.created_at, locale)}</span>
            </div>

            {project.description && (
              <p className="text-sm text-text mb-2">{project.description}</p>
            )}

            <div className="flex flex-wrap gap-x-4 gap-y-1 text-xs text-muted">
              {project.contract_value != null && (
                <span>Contract: <span className="text-text">{formatCurrency(project.contract_value ?? 0, locale)}</span></span>
              )}
              {project.budget_amount != null && (
                <span>Budget: <span className="text-text">{formatCurrency(project.budget_amount ?? 0, locale)}</span></span>
              )}
              {project.start_date && (
                <span>Start: <span className="text-text">{formatDate(project.start_date, locale)}</span></span>
              )}
              {project.target_end_date && (
                <span>Target end: <span className="text-text">{formatDate(project.target_end_date, locale)}</span></span>
              )}
            </div>
          </div>
        )
      })}
    </div>
  )
}
