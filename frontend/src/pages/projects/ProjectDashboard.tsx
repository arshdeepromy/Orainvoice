/**
 * Project dashboard with profitability chart, progress bar, and linked entities.
 *
 * Validates: Requirement 14.1 (Project Module)
 */

import { useEffect, useState } from 'react'
import apiClient from '@/api/client'
import RetentionSummary from '../construction/RetentionSummary'

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

export default function ProjectDashboard({ projectId }: Props) {
  const [project, setProject] = useState<Project | null>(null)
  const [profitability, setProfitability] = useState<Profitability | null>(null)
  const [progress, setProgress] = useState<Progress | null>(null)
  const [activity, setActivity] = useState<ActivityItem[]>([])
  const [loading, setLoading] = useState(true)
  const [activeTab, setActiveTab] = useState<'activity' | 'jobs' | 'quotes' | 'time' | 'retention'>('activity')

  useEffect(() => {
    async function fetchData() {
      setLoading(true)
      try {
        const [projRes, profRes, progRes, actRes] = await Promise.all([
          apiClient.get(`/api/v2/projects/${projectId}`),
          apiClient.get(`/api/v2/projects/${projectId}/profitability`),
          apiClient.get(`/api/v2/projects/${projectId}/progress`),
          apiClient.get(`/api/v2/projects/${projectId}/activity`),
        ])
        setProject(projRes.data)
        setProfitability(profRes.data)
        setProgress(progRes.data)
        setActivity(actRes.data.items || [])
      } catch {
        // Error handled by empty state
      } finally {
        setLoading(false)
      }
    }
    fetchData()
  }, [projectId])

  if (loading) {
    return <div role="status" aria-label="Loading project">Loading project…</div>
  }

  if (!project) {
    return <p>Project not found.</p>
  }

  const contractValue = project.revised_contract_value
    ? Number(project.revised_contract_value)
    : project.contract_value ? Number(project.contract_value) : null

  return (
    <div>
      <h1>{project.name}</h1>
      <p>
        <span className={`status-badge status-${project.status}`}>
          {project.status.replace('_', ' ')}
        </span>
      </p>
      {project.description && <p>{project.description}</p>}

      {/* Progress bar */}
      {progress && (
        <section aria-label="Project progress">
          <h2>Progress</h2>
          <div
            role="progressbar"
            aria-valuenow={Number(progress.progress_percentage)}
            aria-valuemin={0}
            aria-valuemax={100}
            aria-label="Project completion"
            style={{
              width: '100%',
              backgroundColor: '#e0e0e0',
              borderRadius: '4px',
              overflow: 'hidden',
              height: '24px',
            }}
          >
            <div
              style={{
                width: `${Math.min(Number(progress.progress_percentage), 100)}%`,
                backgroundColor: Number(progress.progress_percentage) >= 100 ? '#4caf50' : '#2196f3',
                height: '100%',
                transition: 'width 0.3s ease',
              }}
            />
          </div>
          <p>
            {Number(progress.progress_percentage).toFixed(1)}% complete
            {progress.contract_value && (
              <> — ${Number(progress.invoiced_amount).toLocaleString()} of ${Number(progress.contract_value).toLocaleString()} invoiced</>
            )}
          </p>
        </section>
      )}

      {/* Profitability chart */}
      {profitability && (
        <section aria-label="Profitability">
          <h2>Profitability</h2>
          <div role="table" aria-label="Profitability breakdown">
            <div role="rowgroup">
              <div role="row">
                <span role="rowheader">Revenue</span>
                <span role="cell">${Number(profitability.revenue).toLocaleString()}</span>
              </div>
              <div role="row">
                <span role="rowheader">Labour Costs</span>
                <span role="cell">${Number(profitability.labour_costs).toLocaleString()}</span>
              </div>
              <div role="row">
                <span role="rowheader">Expense Costs</span>
                <span role="cell">${Number(profitability.expense_costs).toLocaleString()}</span>
              </div>
              <div role="row">
                <span role="rowheader">Total Costs</span>
                <span role="cell">${Number(profitability.total_costs).toLocaleString()}</span>
              </div>
              <div role="row">
                <span role="rowheader">Profit</span>
                <span
                  role="cell"
                  style={{ color: profitability.profit >= 0 ? '#4caf50' : '#f44336' }}
                >
                  ${Number(profitability.profit).toLocaleString()}
                </span>
              </div>
              {profitability.margin_percentage !== null && (
                <div role="row">
                  <span role="rowheader">Margin</span>
                  <span role="cell">{Number(profitability.margin_percentage).toFixed(1)}%</span>
                </div>
              )}
            </div>
          </div>

          {/* Simple bar chart for revenue vs costs */}
          <div aria-label="Profitability chart" style={{ display: 'flex', gap: '1rem', marginTop: '1rem', alignItems: 'flex-end', height: '120px' }}>
            {(() => {
              const maxVal = Math.max(profitability.revenue, profitability.total_costs, 1)
              return (
                <>
                  <div style={{ textAlign: 'center', flex: 1 }}>
                    <div
                      aria-label={`Revenue: $${Number(profitability.revenue).toLocaleString()}`}
                      style={{
                        height: `${(profitability.revenue / maxVal) * 100}px`,
                        backgroundColor: '#4caf50',
                        borderRadius: '4px 4px 0 0',
                      }}
                    />
                    <span>Revenue</span>
                  </div>
                  <div style={{ textAlign: 'center', flex: 1 }}>
                    <div
                      aria-label={`Costs: $${Number(profitability.total_costs).toLocaleString()}`}
                      style={{
                        height: `${(profitability.total_costs / maxVal) * 100}px`,
                        backgroundColor: '#f44336',
                        borderRadius: '4px 4px 0 0',
                      }}
                    />
                    <span>Costs</span>
                  </div>
                </>
              )
            })()}
          </div>
        </section>
      )}

      {/* Linked entities tabs */}
      <section aria-label="Linked entities">
        <h2>Linked Entities</h2>
        <div role="tablist" aria-label="Entity tabs">
          <button
            role="tab"
            aria-selected={activeTab === 'activity'}
            onClick={() => setActiveTab('activity')}
          >
            Activity
          </button>
          <button
            role="tab"
            aria-selected={activeTab === 'jobs'}
            onClick={() => setActiveTab('jobs')}
          >
            Jobs
          </button>
          <button
            role="tab"
            aria-selected={activeTab === 'quotes'}
            onClick={() => setActiveTab('quotes')}
          >
            Quotes
          </button>
          <button
            role="tab"
            aria-selected={activeTab === 'time'}
            onClick={() => setActiveTab('time')}
          >
            Time Entries
          </button>
          {Number(project.retention_percentage) > 0 && (
            <button
              role="tab"
              aria-selected={activeTab === 'retention'}
              onClick={() => setActiveTab('retention')}
            >
              Retention
            </button>
          )}
        </div>

        <div role="tabpanel" aria-label={`${activeTab} panel`}>
          {activeTab === 'activity' && (
            activity.length === 0 ? (
              <p>No activity yet.</p>
            ) : (
              <ul aria-label="Activity feed">
                {activity.map(item => (
                  <li key={item.entity_id}>
                    <span className={`entity-type entity-${item.entity_type}`}>
                      {item.entity_type}
                    </span>
                    {' '}{item.title}
                    {item.status && (
                      <span className={`status-badge status-${item.status}`}>
                        {' '}{item.status}
                      </span>
                    )}
                    <time dateTime={item.created_at}>
                      {' '}{new Date(item.created_at).toLocaleDateString()}
                    </time>
                  </li>
                ))}
              </ul>
            )
          )}

          {activeTab === 'jobs' && (
            <ul aria-label="Linked jobs">
              {activity.filter(i => i.entity_type === 'job').length === 0 ? (
                <li>No linked jobs.</li>
              ) : (
                activity.filter(i => i.entity_type === 'job').map(item => (
                  <li key={item.entity_id}>{item.title} — {item.status}</li>
                ))
              )}
            </ul>
          )}

          {activeTab === 'quotes' && (
            <ul aria-label="Linked quotes">
              {activity.filter(i => i.entity_type === 'quote').length === 0 ? (
                <li>No linked quotes.</li>
              ) : (
                activity.filter(i => i.entity_type === 'quote').map(item => (
                  <li key={item.entity_id}>{item.title} — {item.status}</li>
                ))
              )}
            </ul>
          )}

          {activeTab === 'time' && (
            <ul aria-label="Linked time entries">
              {activity.filter(i => i.entity_type === 'time_entry').length === 0 ? (
                <li>No linked time entries.</li>
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
      <section aria-label="Project details">
        <h2>Details</h2>
        <dl>
          {contractValue !== null && (
            <>
              <dt>Contract Value</dt>
              <dd>${contractValue.toLocaleString()}</dd>
            </>
          )}
          {project.budget_amount && (
            <>
              <dt>Budget</dt>
              <dd>${Number(project.budget_amount).toLocaleString()}</dd>
            </>
          )}
          {Number(project.retention_percentage) > 0 && (
            <>
              <dt>Retention</dt>
              <dd>{project.retention_percentage}%</dd>
            </>
          )}
          {project.start_date && (
            <>
              <dt>Start Date</dt>
              <dd>{new Date(project.start_date).toLocaleDateString()}</dd>
            </>
          )}
          {project.target_end_date && (
            <>
              <dt>Target End Date</dt>
              <dd>{new Date(project.target_end_date).toLocaleDateString()}</dd>
            </>
          )}
        </dl>
      </section>
    </div>
  )
}
