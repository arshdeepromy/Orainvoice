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

const STATUS_COLOURS: Record<ScheduleStatus, string> = {
  active: '#16a34a',
  paused: '#ca8a04',
  completed: '#6b7280',
  cancelled: '#dc2626',
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
    <div data-testid="recurring-list-page">
      <header style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
        <h1>Recurring Invoices</h1>
        <button
          data-testid="create-schedule-btn"
          onClick={() => setShowCreateForm(true)}
        >
          New Schedule
        </button>
      </header>

      {/* Dashboard summary */}
      {dashboard && (
        <section data-testid="recurring-dashboard" aria-label="Recurring dashboard">
          <div data-testid="dashboard-active">Active: {dashboard.active_count}</div>
          <div data-testid="dashboard-paused">Paused: {dashboard.paused_count}</div>
          <div data-testid="dashboard-due-today">Due today: {dashboard.due_today}</div>
          <div data-testid="dashboard-due-week">Due this week: {dashboard.due_this_week}</div>
        </section>
      )}

      {/* Status filter */}
      <div>
        <label htmlFor="status-filter">Filter by status:</label>
        <select
          id="status-filter"
          data-testid="status-filter"
          value={statusFilter}
          onChange={(e) => setStatusFilter(e.target.value)}
        >
          <option value="">All</option>
          <option value="active">Active</option>
          <option value="paused">Paused</option>
          <option value="completed">Completed</option>
          <option value="cancelled">Cancelled</option>
        </select>
      </div>

      {error && <div data-testid="error-message" role="alert">{error}</div>}

      {loading ? (
        <div data-testid="loading-indicator">Loading…</div>
      ) : (
        <table data-testid="schedules-table" role="table">
          <thead>
            <tr>
              <th>Customer</th>
              <th>Frequency</th>
              <th>Next Generation</th>
              <th>Status</th>
              <th>Auto Issue</th>
              <th>Auto Email</th>
              <th>Actions</th>
            </tr>
          </thead>
          <tbody>
            {schedules.length === 0 ? (
              <tr>
                <td colSpan={7} data-testid="empty-state">
                  No recurring schedules found
                </td>
              </tr>
            ) : (
              schedules.map((s) => (
                <tr key={s.id} data-testid={`schedule-row-${s.id}`}>
                  <td data-testid="schedule-customer">{s.customer_id}</td>
                  <td data-testid="schedule-frequency">
                    {FREQUENCY_LABELS[s.frequency as Frequency] ?? s.frequency}
                  </td>
                  <td data-testid="schedule-next-date">{s.next_generation_date}</td>
                  <td data-testid="schedule-status">
                    <span
                      style={{
                        color: STATUS_COLOURS[s.status as ScheduleStatus] ?? '#000',
                        fontWeight: 600,
                      }}
                    >
                      {s.status}
                    </span>
                  </td>
                  <td data-testid="schedule-auto-issue">{s.auto_issue ? 'Yes' : 'No'}</td>
                  <td data-testid="schedule-auto-email">{s.auto_email ? 'Yes' : 'No'}</td>
                  <td>
                    {(s.status === 'active' || s.status === 'paused') && (
                      <>
                        <button
                          data-testid={`pause-btn-${s.id}`}
                          onClick={() => handlePause(s)}
                        >
                          {s.status === 'paused' ? 'Resume' : 'Pause'}
                        </button>
                        <button
                          data-testid={`cancel-btn-${s.id}`}
                          onClick={() => handleDelete(s.id)}
                        >
                          Cancel
                        </button>
                      </>
                    )}
                  </td>
                </tr>
              ))
            )}
          </tbody>
        </table>
      )}

      {/* Create form dialog */}
      {showCreateForm && (
        <dialog open data-testid="create-schedule-dialog" aria-label="Create recurring schedule">
          <h2>New Recurring Schedule</h2>
          <form onSubmit={handleCreate} data-testid="create-schedule-form">
            <div>
              <label htmlFor="customer-id">Customer ID</label>
              <input
                id="customer-id"
                data-testid="input-customer-id"
                value={formCustomerId}
                onChange={(e) => setFormCustomerId(e.target.value)}
                required
              />
            </div>
            <div>
              <label htmlFor="frequency">Frequency</label>
              <select
                id="frequency"
                data-testid="input-frequency"
                value={formFrequency}
                onChange={(e) => setFormFrequency(e.target.value as Frequency)}
              >
                {Object.entries(FREQUENCY_LABELS).map(([val, label]) => (
                  <option key={val} value={val}>{label}</option>
                ))}
              </select>
            </div>
            <div>
              <label htmlFor="start-date">Start Date</label>
              <input
                id="start-date"
                type="date"
                data-testid="input-start-date"
                value={formStartDate}
                onChange={(e) => setFormStartDate(e.target.value)}
                required
              />
            </div>
            <div>
              <label htmlFor="end-date">End Date (optional)</label>
              <input
                id="end-date"
                type="date"
                data-testid="input-end-date"
                value={formEndDate}
                onChange={(e) => setFormEndDate(e.target.value)}
              />
            </div>
            <div>
              <label htmlFor="description">Line Item Description</label>
              <input
                id="description"
                data-testid="input-description"
                value={formDescription}
                onChange={(e) => setFormDescription(e.target.value)}
                required
              />
            </div>
            <div>
              <label htmlFor="unit-price">Unit Price</label>
              <input
                id="unit-price"
                type="number"
                step="0.01"
                data-testid="input-unit-price"
                value={formUnitPrice}
                onChange={(e) => setFormUnitPrice(e.target.value)}
                required
              />
            </div>
            <div>
              <label>
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
              <label>
                <input
                  type="checkbox"
                  data-testid="input-auto-email"
                  checked={formAutoEmail}
                  onChange={(e) => setFormAutoEmail(e.target.checked)}
                />
                Auto-email invoices
              </label>
            </div>
            <div style={{ display: 'flex', gap: '8px', marginTop: '16px' }}>
              <button type="submit" data-testid="submit-create">Create</button>
              <button
                type="button"
                data-testid="cancel-create"
                onClick={() => setShowCreateForm(false)}
              >
                Cancel
              </button>
            </div>
          </form>
        </dialog>
      )}
    </div>
  )
}
