/**
 * Project dashboard with profitability chart, progress bar, and linked entities.
 *
 * Validates: Requirement 14.1 (Project Module)
 */

import { useEffect, useState } from 'react'
import apiClient from '@/api/client'
import RetentionSummary from '@/pages/construction/RetentionSummary'

interface Project {
  id: string
  name: string
  customer_id: string | null
  description: string | null
  status: string
  contract_value: string | null
  revised_contract_value: string | null
  budget_amount: string | null
  retention_percentage: string
  start_date: string | null
  target_end_date: string | null
}

interface Profitability {
  revenue: number
  expense_costs: number
  labour_costs: number
  total_costs: number
  profit: number
  margin_percentage: number | null
}

interface Progress {
  contract_value: number | null
  invoiced_amount: number
  progress_percentage: number
}

interface ActivityItem {
  entity_type: string
  entity_id: string
  title: string
  status: string | null
  created_at: string
}

interface Props {
  projectId: string
}

const tabBase =
  'min-h-[44px] rounded-ctl px-4 py-2 text-sm font-medium transition-colors'

export default function ProjectDashboard({ projectId }: Props) {
  const [project, setProject] = useState<Project | null>(null)
  const [profitability, setProfitability] = useState<Profitability | null>(null)
  const [progress, setProgress] = useState<Progress | null>(null)
  const [activity, setActivity] = useState<ActivityItem[]>([])
  const [loading, setLoading] = useState(true)
  const [activeTab, setActiveTab] = useState<'activity' | 'jobs' | 'quotes' | 'time' | 'retention'>('activity')

  useEffect(() => {
    const controller = new AbortController()
    async function fetchData() {
      setLoading(true)
      try {
        const [projRes, profRes, progRes, actRes] = await Promise.all([
          apiClient.get(`/api/v2/projects/${projectId}`, { signal: controller.signal }),
          apiClient.get(`/api/v2/projects/${projectId}/profitability`, { signal: controller.signal }),
          apiClient.get(`/api/v2/projects/${projectId}/progress`, { signal: controller.signal }),
          apiClient.get(`/api/v2/projects/${projectId}/activity`, { signal: controller.signal }),
        ])
        setProject(projRes.data)
        setProfitability(profRes.data)
        setProgress(progRes.data)
        setActivity(actRes.data?.items ?? [])
      } catch {
        // Error handled by empty state
      } finally {
        setLoading(false)
      }
    }
    fetchData()
    return () => controller.abort()
  }, [projectId])

  if (loading) {
    return <div role="status" aria-label="Loading project" className="py-12 text-center text-sm text-muted">Loading project…</div>
  }

  if (!project) {
    return <p className="px-4 py-6 text-sm text-muted">Project not found.</p>
  }

  const contractValue = project.revised_contract_value
    ? Number(project.revised_contract_value)
    : project.contract_value ? Number(project.contract_value) : null

  return (
    <div className="space-y-5 px-4 py-6 sm:px-6 lg:px-8">
      <h1 className="text-2xl font-semibold text-text">{project.name}</h1>
      <p>
        <span className={`inline-block rounded-ctl bg-accent-soft px-2.5 py-1 text-xs font-medium text-accent status-badge status-${project.status}`}>
          {project.status.replace('_', ' ')}
        </span>
      </p>
      {project.description && <p className="text-sm text-muted">{project.description}</p>}

      {/* Progress bar */}
      {progress && (
        <section aria-label="Project progress" className="space-y-2">
          <h2 className="text-base font-semibold text-text">Progress</h2>
          <div
            role="progressbar"
            aria-valuenow={Number(progress.progress_percentage)}
            aria-valuemin={0}
            aria-valuemax={100}
            aria-label="Project completion"
            className="h-6 w-full overflow-hidden rounded-ctl bg-canvas"
          >
            <div
              className="h-full transition-[width] duration-300"
              style={{
                width: `${Math.min(Number(progress.progress_percentage), 100)}%`,
                backgroundColor: Number(progress.progress_percentage) >= 100 ? 'var(--ok)' : 'var(--accent)',
              }}
            />
          </div>
          <p className="text-sm text-muted">
            {Number(progress.progress_percentage).toFixed(1)}% complete
            {progress.contract_value && (
              <> — <span className="mono">${Number(progress.invoiced_amount).toLocaleString()}</span> of <span className="mono">${Number(progress.contract_value).toLocaleString()}</span> invoiced</>
            )}
          </p>
        </section>
      )}

      {/* Profitability chart */}
      {profitability && (
        <section aria-label="Profitability" className="space-y-3">
          <h2 className="text-base font-semibold text-text">Profitability</h2>
          <div role="table" aria-label="Profitability breakdown" className="overflow-hidden rounded-card border border-border bg-card shadow-card">
            <div role="rowgroup">
              <div role="row" className="flex items-center justify-between border-b border-border px-4 py-3">
                <span role="rowheader" className="text-sm text-muted">Revenue</span>
                <span role="cell" className="mono text-sm text-text">${Number(profitability.revenue).toLocaleString()}</span>
              </div>
              <div role="row" className="flex items-center justify-between border-b border-border px-4 py-3">
                <span role="rowheader" className="text-sm text-muted">Labour Costs</span>
                <span role="cell" className="mono text-sm text-text">${Number(profitability.labour_costs).toLocaleString()}</span>
              </div>
              <div role="row" className="flex items-center justify-between border-b border-border px-4 py-3">
                <span role="rowheader" className="text-sm text-muted">Expense Costs</span>
                <span role="cell" className="mono text-sm text-text">${Number(profitability.expense_costs).toLocaleString()}</span>
              </div>
              <div role="row" className="flex items-center justify-between border-b border-border px-4 py-3">
                <span role="rowheader" className="text-sm text-muted">Total Costs</span>
                <span role="cell" className="mono text-sm text-text">${Number(profitability.total_costs).toLocaleString()}</span>
              </div>
              <div role="row" className="flex items-center justify-between border-b border-border px-4 py-3 last:border-b-0">
                <span role="rowheader" className="text-sm text-muted">Profit</span>
                <span
                  role="cell"
                  className={`mono text-sm font-semibold ${profitability.profit >= 0 ? 'text-ok' : 'text-danger'}`}
                >
                  ${Number(profitability.profit).toLocaleString()}
                </span>
              </div>
              {profitability.margin_percentage !== null && (
                <div role="row" className="flex items-center justify-between px-4 py-3">
                  <span role="rowheader" className="text-sm text-muted">Margin</span>
                  <span role="cell" className="mono text-sm text-text">{Number(profitability.margin_percentage).toFixed(1)}%</span>
                </div>
              )}
            </div>
          </div>

          {/* Simple bar chart for revenue vs costs */}
          <div aria-label="Profitability chart" className="flex h-[120px] items-end gap-4">
            {(() => {
              const maxVal = Math.max(profitability.revenue, profitability.total_costs, 1)
              return (
                <>
                  <div className="flex-1 text-center">
                    <div
                      aria-label={`Revenue: ${Number(profitability.revenue).toLocaleString()}`}
                      className="rounded-t-ctl bg-ok"
                      style={{ height: `${(profitability.revenue / maxVal) * 100}px` }}
                    />
                    <span className="text-sm text-muted">Revenue</span>
                  </div>
                  <div className="flex-1 text-center">
                    <div
                      aria-label={`Costs: ${Number(profitability.total_costs).toLocaleString()}`}
                      className="rounded-t-ctl bg-danger"
                      style={{ height: `${(profitability.total_costs / maxVal) * 100}px` }}
                    />
                    <span className="text-sm text-muted">Costs</span>
                  </div>
                </>
              )
            })()}
          </div>
        </section>
      )}

      {/* Linked entities tabs */}
      <section aria-label="Linked entities" className="space-y-3">
        <h2 className="text-base font-semibold text-text">Linked Entities</h2>
        <div role="tablist" aria-label="Entity tabs" className="flex flex-wrap gap-2 border-b border-border pb-2">
          <button
            role="tab"
            aria-selected={activeTab === 'activity'}
            onClick={() => setActiveTab('activity')}
            className={`${tabBase} ${activeTab === 'activity' ? 'bg-accent text-white' : 'text-muted hover:bg-canvas hover:text-text'}`}
          >
            Activity
          </button>
          <button
            role="tab"
            aria-selected={activeTab === 'jobs'}
            onClick={() => setActiveTab('jobs')}
            className={`${tabBase} ${activeTab === 'jobs' ? 'bg-accent text-white' : 'text-muted hover:bg-canvas hover:text-text'}`}
          >
            Jobs
          </button>
          <button
            role="tab"
            aria-selected={activeTab === 'quotes'}
            onClick={() => setActiveTab('quotes')}
            className={`${tabBase} ${activeTab === 'quotes' ? 'bg-accent text-white' : 'text-muted hover:bg-canvas hover:text-text'}`}
          >
            Quotes
          </button>
          <button
            role="tab"
            aria-selected={activeTab === 'time'}
            onClick={() => setActiveTab('time')}
            className={`${tabBase} ${activeTab === 'time' ? 'bg-accent text-white' : 'text-muted hover:bg-canvas hover:text-text'}`}
          >
            Time Entries
          </button>
          {Number(project.retention_percentage) > 0 && (
            <button
              role="tab"
              aria-selected={activeTab === 'retention'}
              onClick={() => setActiveTab('retention')}
              className={`${tabBase} ${activeTab === 'retention' ? 'bg-accent text-white' : 'text-muted hover:bg-canvas hover:text-text'}`}
            >
              Retention
            </button>
          )}
        </div>

        <div role="tabpanel" aria-label={`${activeTab} panel`}>
          {activeTab === 'activity' && (
            activity.length === 0 ? (
              <p className="text-sm text-muted">No activity yet.</p>
            ) : (
              <ul aria-label="Activity feed" className="space-y-2">
                {activity.map(item => (
                  <li key={item.entity_id} className="rounded-card border border-border bg-card px-4 py-3 text-sm text-text shadow-card">
                    <span className={`mr-1 inline-block rounded-ctl bg-canvas px-2 py-0.5 text-xs text-muted entity-type entity-${item.entity_type}`}>
                      {item.entity_type}
                    </span>
                    {' '}{item.title}
                    {item.status && (
                      <span className={`ml-1 inline-block rounded-ctl bg-accent-soft px-2 py-0.5 text-xs text-accent status-badge status-${item.status}`}>
                        {' '}{item.status}
                      </span>
                    )}
                    <time dateTime={item.created_at} className="ml-1 text-muted">
                      {' '}{new Date(item.created_at).toLocaleDateString()}
                    </time>
                  </li>
                ))}
              </ul>
            )
          )}

          {activeTab === 'jobs' && (
            <ul aria-label="Linked jobs" className="space-y-2 text-sm text-text">
              {activity.filter(i => i.entity_type === 'job').length === 0 ? (
                <li className="text-muted">No linked jobs.</li>
              ) : (
                activity.filter(i => i.entity_type === 'job').map(item => (
                  <li key={item.entity_id}>{item.title} — {item.status}</li>
                ))
              )}
            </ul>
          )}

          {activeTab === 'quotes' && (
            <ul aria-label="Linked quotes" className="space-y-2 text-sm text-text">
              {activity.filter(i => i.entity_type === 'quote').length === 0 ? (
                <li className="text-muted">No linked quotes.</li>
              ) : (
                activity.filter(i => i.entity_type === 'quote').map(item => (
                  <li key={item.entity_id}>{item.title} — {item.status}</li>
                ))
              )}
            </ul>
          )}

          {activeTab === 'time' && (
            <ul aria-label="Linked time entries" className="space-y-2 text-sm text-text">
              {activity.filter(i => i.entity_type === 'time_entry').length === 0 ? (
                <li className="text-muted">No linked time entries.</li>
              ) : (
                activity.filter(i => i.entity_type === 'time_entry').map(item => (
                  <li key={item.entity_id}>{item.title} — {item.status}</li>
                ))
              )}
            </ul>
          )}

          {activeTab === 'retention' && (
            <RetentionSummary projectId={projectId} />
          )}
        </div>
      </section>

      {/* Project details */}
      <section aria-label="Project details" className="space-y-3">
        <h2 className="text-base font-semibold text-text">Details</h2>
        <dl className="overflow-hidden rounded-card border border-border bg-card shadow-card">
          {contractValue !== null && (
            <div className="flex items-center justify-between border-b border-border px-4 py-3 last:border-b-0">
              <dt className="text-sm text-muted">Contract Value</dt>
              <dd className="mono text-sm text-text">${contractValue.toLocaleString()}</dd>
            </div>
          )}
          {project.budget_amount && (
            <div className="flex items-center justify-between border-b border-border px-4 py-3 last:border-b-0">
              <dt className="text-sm text-muted">Budget</dt>
              <dd className="mono text-sm text-text">${Number(project.budget_amount).toLocaleString()}</dd>
            </div>
          )}
          {Number(project.retention_percentage) > 0 && (
            <div className="flex items-center justify-between border-b border-border px-4 py-3 last:border-b-0">
              <dt className="text-sm text-muted">Retention</dt>
              <dd className="mono text-sm text-text">{project.retention_percentage}%</dd>
            </div>
          )}
          {project.start_date && (
            <div className="flex items-center justify-between border-b border-border px-4 py-3 last:border-b-0">
              <dt className="text-sm text-muted">Start Date</dt>
              <dd className="mono text-sm text-text">{new Date(project.start_date).toLocaleDateString()}</dd>
            </div>
          )}
          {project.target_end_date && (
            <div className="flex items-center justify-between border-b border-border px-4 py-3 last:border-b-0">
              <dt className="text-sm text-muted">Target End Date</dt>
              <dd className="mono text-sm text-text">{new Date(project.target_end_date).toLocaleDateString()}</dd>
            </div>
          )}
        </dl>
      </section>
    </div>
  )
}
