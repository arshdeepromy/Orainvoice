/**
 * RecurringList — schedule management page for recurring invoices.
 *
 * Displays a table of recurring schedules with status, frequency,
 * next generation date, and CRUD actions.
 *
 * Validates: Recurring Module — Task 34.8
 */

import { useCallback, useEffect, useState } from 'react'
import apiClient from '@/api/client'

/* ------------------------------------------------------------------ */
/*  Types                                                              */
/* ------------------------------------------------------------------ */

interface LineItem {
  description: string
  quantity: string
  unit_price: string
  tax_rate?: string | null
}

interface RecurringSchedule {
  id: string
  org_id: string
  customer_id: string
  line_items: LineItem[]
  frequency: string
  start_date: string
  end_date: string | null
  next_generation_date: string
  auto_issue: boolean
  auto_email: boolean
  status: string
  created_at: string
  updated_at: string
}

interface DashboardData {
  active_count: number
  paused_count: number
  due_today: number
  due_this_week: number
}

type Frequency = 'weekly' | 'fortnightly' | 'monthly' | 'quarterly' | 'annually'
type ScheduleStatus = 'active' | 'paused' | 'completed' | 'cancelled'

const FREQUENCY_LABELS: Record<Frequency, string> = {
  weekly: 'Weekly',
  fortnightly: 'Fortnightly',
  monthly: 'Monthly',
  quarterly: 'Quarterly',
  annually: 'Annually',
}

const STATUS_TEXT_CLASSES: Record<ScheduleStatus, string> = {
  active: 'text-ok',
  paused: 'text-warn',
  completed: 'text-muted',
  cancelled: 'text-danger',
}

/* ------------------------------------------------------------------ */
/*  Component                                                          */
/* ------------------------------------------------------------------ */

export default function RecurringList() {
  const [schedules, setSchedules] = useState<RecurringSchedule[]>([])
  const [dashboard, setDashboard] = useState<DashboardData | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [statusFilter, setStatusFilter] = useState<string>('')
  const [showCreateForm, setShowCreateForm] = useState(false)

  /* -- Form state -- */
  const [formCustomerId, setFormCustomerId] = useState('')
  const [formFrequency, setFormFrequency] = useState<Frequency>('monthly')
  const [formStartDate, setFormStartDate] = useState('')
  const [formEndDate, setFormEndDate] = useState('')
  const [formAutoIssue, setFormAutoIssue] = useState(false)
  const [formAutoEmail, setFormAutoEmail] = useState(false)
  const [formDescription, setFormDescription] = useState('')
  const [formUnitPrice, setFormUnitPrice] = useState('')

  const fetchSchedules = useCallback(async () => {
    setLoading(true)
    setError(null)
    try {
      const params = statusFilter ? `?status=${statusFilter}` : ''
      const res = await apiClient.get(`/api/v2/recurring/${params}`)
      setSchedules(res.data?.schedules ?? [])
    } catch {
      setError('Failed to load recurring schedules')
    } finally {
      setLoading(false)
    }
  }, [statusFilter])

  const fetchDashboard = useCallback(async () => {
    try {
      const res = await apiClient.get('/api/v2/recurring/dashboard')
      setDashboard(res.data)
    } catch {
      /* dashboard is non-critical */
    }
  }, [])

  useEffect(() => {
    fetchSchedules()
    fetchDashboard()
  }, [fetchSchedules, fetchDashboard])

  const handleCreate = async (e: React.FormEvent) => {
    e.preventDefault()
    try {
      await apiClient.post('/api/v2/recurring/', {
        customer_id: formCustomerId,
        frequency: formFrequency,
        start_date: formStartDate,
        end_date: formEndDate || null,
        auto_issue: formAutoIssue,
        auto_email: formAutoEmail,
        line_items: [
          {
            description: formDescription,
            quantity: '1',
            unit_price: formUnitPrice,
          },
        ],
      })
      setShowCreateForm(false)
      fetchSchedules()
      fetchDashboard()
    } catch {
      setError('Failed to create schedule')
    }
  }

  const handleDelete = async (id: string) => {
    try {
      await apiClient.delete(`/api/v2/recurring/${id}`)
      fetchSchedules()
      fetchDashboard()
    } catch {
      setError('Failed to cancel schedule')
    }
  }

  const handlePause = async (schedule: RecurringSchedule) => {
    const newStatus = schedule.status === 'paused' ? 'active' : 'paused'
    try {
      await apiClient.put(`/api/v2/recurring/${schedule.id}`, {
        status: newStatus,
      })
      fetchSchedules()
      fetchDashboard()
    } catch {
      setError('Failed to update schedule')
    }
  }

  return (
    <div className="px-4 py-6 sm:px-6 lg:px-8" data-testid="recurring-list-page">
      <header className="mb-6 flex items-center justify-between">
        <h1 className="text-2xl font-semibold text-text">Recurring Invoices</h1>
        <button
          data-testid="create-schedule-btn"
          onClick={() => setShowCreateForm(true)}
          className="inline-flex h-10 items-center rounded-ctl bg-accent px-4 text-sm font-semibold text-white shadow-card hover:bg-accent-press focus:outline-none focus-visible:ring-2 focus-visible:ring-accent"
        >
          New Schedule
        </button>
      </header>

      {/* Dashboard summary */}
      {dashboard && (
        <section
          data-testid="recurring-dashboard"
          aria-label="Recurring dashboard"
          className="mb-6 grid grid-cols-2 gap-4 sm:grid-cols-4"
        >
          <div
            data-testid="dashboard-active"
            className="rounded-card border border-border bg-card p-4 text-sm text-muted shadow-card"
          >
            Active: <span className="mono font-semibold text-text">{dashboard.active_count}</span>
          </div>
          <div
            data-testid="dashboard-paused"
            className="rounded-card border border-border bg-card p-4 text-sm text-muted shadow-card"
          >
            Paused: <span className="mono font-semibold text-text">{dashboard.paused_count}</span>
          </div>
          <div
            data-testid="dashboard-due-today"
            className="rounded-card border border-border bg-card p-4 text-sm text-muted shadow-card"
          >
            Due today: <span className="mono font-semibold text-text">{dashboard.due_today}</span>
          </div>
          <div
            data-testid="dashboard-due-week"
            className="rounded-card border border-border bg-card p-4 text-sm text-muted shadow-card"
          >
            Due this week: <span className="mono font-semibold text-text">{dashboard.due_this_week}</span>
          </div>
        </section>
      )}

      {/* Status filter */}
      <div className="mb-4 flex items-center gap-2">
        <label htmlFor="status-filter" className="text-sm font-medium text-text">
          Filter by status:
        </label>
        <select
          id="status-filter"
          data-testid="status-filter"
          value={statusFilter}
          onChange={(e) => setStatusFilter(e.target.value)}
          className="h-10 rounded-ctl border border-border bg-card px-3 text-sm text-text focus:outline-none focus:ring-2 focus:ring-accent"
        >
          <option value="">All</option>
          <option value="active">Active</option>
          <option value="paused">Paused</option>
          <option value="completed">Completed</option>
          <option value="cancelled">Cancelled</option>
        </select>
      </div>

      {error && (
        <div
          data-testid="error-message"
          role="alert"
          className="mb-4 rounded-ctl border border-danger/40 bg-danger-soft px-4 py-3 text-sm text-danger"
        >
          {error}
        </div>
      )}

      {loading ? (
        <div data-testid="loading-indicator" className="py-8 text-center text-sm text-muted">
          Loading…
        </div>
      ) : (
        <div className="overflow-hidden rounded-card border border-border bg-card shadow-card">
          <table data-testid="schedules-table" role="table" className="min-w-full text-sm">
            <thead>
              <tr>
                <th className="mono border-b border-border px-4 py-3 text-left text-[10.5px] font-medium uppercase tracking-[0.08em] text-muted-2">Customer</th>
                <th className="mono border-b border-border px-4 py-3 text-left text-[10.5px] font-medium uppercase tracking-[0.08em] text-muted-2">Frequency</th>
                <th className="mono border-b border-border px-4 py-3 text-left text-[10.5px] font-medium uppercase tracking-[0.08em] text-muted-2">Next Generation</th>
                <th className="mono border-b border-border px-4 py-3 text-left text-[10.5px] font-medium uppercase tracking-[0.08em] text-muted-2">Status</th>
                <th className="mono border-b border-border px-4 py-3 text-left text-[10.5px] font-medium uppercase tracking-[0.08em] text-muted-2">Auto Issue</th>
                <th className="mono border-b border-border px-4 py-3 text-left text-[10.5px] font-medium uppercase tracking-[0.08em] text-muted-2">Auto Email</th>
                <th className="mono border-b border-border px-4 py-3 text-left text-[10.5px] font-medium uppercase tracking-[0.08em] text-muted-2">Actions</th>
              </tr>
            </thead>
            <tbody>
              {schedules.length === 0 ? (
                <tr>
                  <td colSpan={7} data-testid="empty-state" className="px-4 py-8 text-center text-sm text-muted-2">
                    No recurring schedules found
                  </td>
                </tr>
              ) : (
                schedules.map((s) => (
                  <tr
                    key={s.id}
                    data-testid={`schedule-row-${s.id}`}
                    className="border-b border-border last:border-b-0 hover:bg-canvas"
                  >
                    <td data-testid="schedule-customer" className="mono px-4 py-3 text-text">{s.customer_id}</td>
                    <td data-testid="schedule-frequency" className="px-4 py-3 text-text">
                      {FREQUENCY_LABELS[s.frequency as Frequency] ?? s.frequency}
                    </td>
                    <td data-testid="schedule-next-date" className="mono px-4 py-3 text-muted">{s.next_generation_date}</td>
                    <td data-testid="schedule-status" className="px-4 py-3">
                      <span className={`font-semibold ${STATUS_TEXT_CLASSES[s.status as ScheduleStatus] ?? 'text-text'}`}>
                        {s.status}
                      </span>
                    </td>
                    <td data-testid="schedule-auto-issue" className="px-4 py-3 text-text">{s.auto_issue ? 'Yes' : 'No'}</td>
                    <td data-testid="schedule-auto-email" className="px-4 py-3 text-text">{s.auto_email ? 'Yes' : 'No'}</td>
                    <td className="px-4 py-3">
                      {(s.status === 'active' || s.status === 'paused') && (
                        <div className="flex gap-2">
                          <button
                            data-testid={`pause-btn-${s.id}`}
                            onClick={() => handlePause(s)}
                            className="inline-flex h-9 items-center rounded-ctl border border-border px-3 text-xs font-medium text-text hover:bg-canvas"
                          >
                            {s.status === 'paused' ? 'Resume' : 'Pause'}
                          </button>
                          <button
                            data-testid={`cancel-btn-${s.id}`}
                            onClick={() => handleDelete(s.id)}
                            className="inline-flex h-9 items-center rounded-ctl border border-danger/40 px-3 text-xs font-medium text-danger hover:bg-danger-soft"
                          >
                            Cancel
                          </button>
                        </div>
                      )}
                    </td>
                  </tr>
                ))
              )}
            </tbody>
          </table>
        </div>
      )}

      {/* Create form dialog */}
      {showCreateForm && (
        <div className="fixed inset-0 z-50 flex items-start justify-center overflow-y-auto bg-ink/50 px-4 py-[5vh]">
          <dialog
            open
            data-testid="create-schedule-dialog"
            aria-label="Create recurring schedule"
            className="relative w-full max-w-lg rounded-card border border-border bg-card p-6 text-text shadow-pop"
          >
            <h2 className="mb-4 text-[15px] font-semibold text-text">New Recurring Schedule</h2>
            <form onSubmit={handleCreate} data-testid="create-schedule-form" className="space-y-4">
              <div>
                <label htmlFor="customer-id" className="mb-1 block text-sm font-medium text-text">Customer ID</label>
                <input
                  id="customer-id"
                  data-testid="input-customer-id"
                  value={formCustomerId}
                  onChange={(e) => setFormCustomerId(e.target.value)}
                  required
                  className="h-10 w-full rounded-ctl border border-border bg-card px-3 text-sm text-text focus:outline-none focus:ring-2 focus:ring-accent"
                />
              </div>
              <div>
                <label htmlFor="frequency" className="mb-1 block text-sm font-medium text-text">Frequency</label>
                <select
                  id="frequency"
                  data-testid="input-frequency"
                  value={formFrequency}
                  onChange={(e) => setFormFrequency(e.target.value as Frequency)}
                  className="h-10 w-full rounded-ctl border border-border bg-card px-3 text-sm text-text focus:outline-none focus:ring-2 focus:ring-accent"
                >
                  {Object.entries(FREQUENCY_LABELS).map(([val, label]) => (
                    <option key={val} value={val}>{label}</option>
                  ))}
                </select>
              </div>
              <div>
                <label htmlFor="start-date" className="mb-1 block text-sm font-medium text-text">Start Date</label>
                <input
                  id="start-date"
                  type="date"
                  data-testid="input-start-date"
                  value={formStartDate}
                  onChange={(e) => setFormStartDate(e.target.value)}
                  required
                  className="h-10 w-full rounded-ctl border border-border bg-card px-3 text-sm text-text focus:outline-none focus:ring-2 focus:ring-accent"
                />
              </div>
              <div>
                <label htmlFor="end-date" className="mb-1 block text-sm font-medium text-text">End Date (optional)</label>
                <input
                  id="end-date"
                  type="date"
                  data-testid="input-end-date"
                  value={formEndDate}
                  onChange={(e) => setFormEndDate(e.target.value)}
                  className="h-10 w-full rounded-ctl border border-border bg-card px-3 text-sm text-text focus:outline-none focus:ring-2 focus:ring-accent"
                />
              </div>
              <div>
                <label htmlFor="description" className="mb-1 block text-sm font-medium text-text">Line Item Description</label>
                <input
                  id="description"
                  data-testid="input-description"
                  value={formDescription}
                  onChange={(e) => setFormDescription(e.target.value)}
                  required
                  className="h-10 w-full rounded-ctl border border-border bg-card px-3 text-sm text-text focus:outline-none focus:ring-2 focus:ring-accent"
                />
              </div>
              <div>
                <label htmlFor="unit-price" className="mb-1 block text-sm font-medium text-text">Unit Price</label>
                <input
                  id="unit-price"
                  type="number"
                  step="0.01"
                  data-testid="input-unit-price"
                  value={formUnitPrice}
                  onChange={(e) => setFormUnitPrice(e.target.value)}
                  required
                  className="mono h-10 w-full rounded-ctl border border-border bg-card px-3 text-sm text-text focus:outline-none focus:ring-2 focus:ring-accent"
                />
              </div>
              <div>
                <label className="flex items-center gap-2 text-sm text-text">
                  <input
                    type="checkbox"
                    data-testid="input-auto-issue"
                    checked={formAutoIssue}
                    onChange={(e) => setFormAutoIssue(e.target.checked)}
                  />
                  Auto-issue invoices
                </label>
              </div>
              <div>
                <label className="flex items-center gap-2 text-sm text-text">
                  <input
                    type="checkbox"
                    data-testid="input-auto-email"
                    checked={formAutoEmail}
                    onChange={(e) => setFormAutoEmail(e.target.checked)}
                  />
                  Auto-email invoices
                </label>
              </div>
              <div className="flex gap-2 pt-2">
                <button
                  type="submit"
                  data-testid="submit-create"
                  className="inline-flex h-10 items-center rounded-ctl bg-accent px-4 text-sm font-semibold text-white shadow-card hover:bg-accent-press focus:outline-none focus-visible:ring-2 focus-visible:ring-accent"
                >
                  Create
                </button>
                <button
                  type="button"
                  data-testid="cancel-create"
                  onClick={() => setShowCreateForm(false)}
                  className="inline-flex h-10 items-center rounded-ctl border border-border bg-card px-4 text-sm font-medium text-text hover:bg-canvas"
                >
                  Cancel
                </button>
              </div>
            </form>
          </dialog>
        </div>
      )}
    </div>
  )
}
