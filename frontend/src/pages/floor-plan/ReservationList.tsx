/**
 * Reservation management with list view, calendar view,
 * date/status filtering, and creation form.
 *
 * Validates: Requirements 14.4, 14.6
 */

import { useEffect, useState, useCallback, useMemo } from 'react'
import apiClient from '@/api/client'
import { useModuleGuard } from '@/hooks/useModuleGuard'
import { useFlag } from '@/contexts/FeatureFlagContext'
import { useTerm } from '@/contexts/TerminologyContext'

/* ── Types ── */

interface ReservationItem {
  id: string
  org_id: string
  table_id: string
  customer_name: string
  party_size: number
  reservation_date: string
  reservation_time: string
  duration_minutes: number
  notes: string | null
  status: string
  created_at: string
}

interface TableOption {
  id: string
  table_number: string
  seat_count: number
}

type BadgeVariant = 'info' | 'success' | 'warning' | 'error' | 'neutral'

const STATUS_BADGE: Record<string, { label: string; variant: BadgeVariant }> = {
  confirmed: { label: 'Confirmed', variant: 'success' },
  seated: { label: 'Seated', variant: 'info' },
  completed: { label: 'Completed', variant: 'neutral' },
  cancelled: { label: 'Cancelled', variant: 'error' },
  no_show: { label: 'No Show', variant: 'warning' },
}

const INITIAL_FORM = {
  table_id: '',
  customer_name: '',
  party_size: 2,
  reservation_date: '',
  reservation_time: '19:00',
  duration_minutes: 90,
  notes: '',
}

type ViewMode = 'list' | 'calendar'

/* ── Calendar helpers ── */

function getDaysInMonth(year: number, month: number): Date[] {
  const days: Date[] = []
  const d = new Date(year, month, 1)
  while (d.getMonth() === month) {
    days.push(new Date(d))
    d.setDate(d.getDate() + 1)
  }
  return days
}

function formatDateKey(d: Date): string {
  return d.toISOString().slice(0, 10)
}

export default function ReservationList() {
  const { isAllowed, isLoading: guardLoading, toasts, dismissToast } = useModuleGuard('tables')
  const calendarEnabled = useFlag('floor_plan')
  const tableTerm = useTerm('table', 'Table')

  const [reservations, setReservations] = useState<ReservationItem[]>([])
  const [total, setTotal] = useState(0)
  const [tables, setTables] = useState<TableOption[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const [dateFilter, setDateFilter] = useState(new Date().toISOString().slice(0, 10))
  const [statusFilter, setStatusFilter] = useState<string>('all')
  const [showForm, setShowForm] = useState(false)
  const [form, setForm] = useState(INITIAL_FORM)
  const [submitting, setSubmitting] = useState(false)
  const [viewMode, setViewMode] = useState<ViewMode>('list')

  /* Calendar state */
  const [calendarDate, setCalendarDate] = useState(() => {
    const now = new Date()
    return { year: now.getFullYear(), month: now.getMonth() }
  })
  const [calendarReservations, setCalendarReservations] = useState<ReservationItem[]>([])

  /* ── Data fetching ── */

  const fetchReservations = useCallback(async () => {
    setLoading(true)
    setError('')
    try {
      const params = new URLSearchParams()
      if (dateFilter) params.set('date', dateFilter)
      if (statusFilter !== 'all') params.set('status', statusFilter)
      const res = await apiClient.get(`/api/v2/tables/reservations?${params}`)
      setReservations(res.data.reservations)
      setTotal(res.data.total)
    } catch {
      setError('Failed to load reservations.')
      setReservations([])
    } finally {
      setLoading(false)
    }
  }, [dateFilter, statusFilter])

  const fetchTables = useCallback(async () => {
    try {
      const res = await apiClient.get('/api/v2/tables/tables?limit=200')
      setTables(res.data.tables)
    } catch {
      // Tables list is optional for display
    }
  }, [])

  const fetchCalendarReservations = useCallback(async () => {
    try {
      const startDate = `${calendarDate.year}-${String(calendarDate.month + 1).padStart(2, '0')}-01`
      const lastDay = new Date(calendarDate.year, calendarDate.month + 1, 0).getDate()
      const endDate = `${calendarDate.year}-${String(calendarDate.month + 1).padStart(2, '0')}-${String(lastDay).padStart(2, '0')}`
      const params = new URLSearchParams({ start_date: startDate, end_date: endDate })
      if (statusFilter !== 'all') params.set('status', statusFilter)
      const res = await apiClient.get(`/api/v2/tables/reservations?${params}`)
      setCalendarReservations(res.data.reservations)
    } catch {
      // Silent failure for calendar view
    }
  }, [calendarDate, statusFilter])

  useEffect(() => { fetchReservations() }, [fetchReservations])
  useEffect(() => { fetchTables() }, [fetchTables])
  useEffect(() => {
    if (viewMode === 'calendar') fetchCalendarReservations()
  }, [viewMode, fetchCalendarReservations])

  /* ── Actions ── */

  const handleCancel = async (id: string) => {
    try {
      await apiClient.put(`/api/v2/tables/reservations/${id}/cancel`)
      fetchReservations()
      if (viewMode === 'calendar') fetchCalendarReservations()
    } catch {
      setError('Failed to cancel reservation.')
    }
  }

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault()
    setSubmitting(true)
    setError('')
    try {
      await apiClient.post('/api/v2/tables/reservations', {
        table_id: form.table_id,
        customer_name: form.customer_name,
        party_size: form.party_size,
        reservation_date: form.reservation_date,
        reservation_time: form.reservation_time,
        duration_minutes: form.duration_minutes,
        notes: form.notes || null,
      })
      setForm(INITIAL_FORM)
      setShowForm(false)
      fetchReservations()
      if (viewMode === 'calendar') fetchCalendarReservations()
    } catch {
      setError('Failed to create reservation.')
    } finally {
      setSubmitting(false)
    }
  }

  const getTableNumber = (tableId: string) =>
    tables.find((t) => t.id === tableId)?.table_number ?? tableId.slice(0, 8)

  /* ── Calendar data ── */

  const calendarDays = useMemo(
    () => getDaysInMonth(calendarDate.year, calendarDate.month),
    [calendarDate],
  )

  const reservationsByDate = useMemo(() => {
    const map: Record<string, ReservationItem[]> = {}
    for (const r of calendarReservations) {
      const key = r.reservation_date
      if (!map[key]) map[key] = []
      map[key].push(r)
    }
    return map
  }, [calendarReservations])

  const monthLabel = new Date(calendarDate.year, calendarDate.month).toLocaleDateString('en-NZ', {
    month: 'long',
    year: 'numeric',
  })

  /* ── Guard / loading ── */

  if (guardLoading) {
    return (
      <div className="p-6 text-center text-sm text-gray-500" role="status" data-testid="reservation-guard-loading">
        Loading…
      </div>
    )
  }
  if (!isAllowed) return null

  /* ── Render ── */

  return (
    <div className="p-6" data-testid="reservation-list-page">
      {/* Toasts */}
      {toasts.length > 0 && (
        <div className="fixed top-4 right-4 z-50 space-y-2">
          {toasts.map((t) => (
            <div
              key={t.id}
              className="rounded-md bg-yellow-50 border border-yellow-200 px-4 py-2 text-sm text-yellow-800 shadow"
            >
              {t.message}
              <button onClick={() => dismissToast(t.id)} className="ml-2 font-bold">×</button>
            </div>
          ))}
        </div>
      )}

      {/* Header */}
      <div className="flex flex-wrap items-center justify-between gap-3 mb-6">
        <h1 className="text-2xl font-semibold text-gray-900" data-testid="reservations-heading">
          Reservations
        </h1>
        <div className="flex items-center gap-3">
          {/* View toggle — calendar gated by feature flag */}
          {calendarEnabled && (
            <div className="flex rounded-md border border-gray-300 overflow-hidden" data-testid="view-toggle">
              <button
                onClick={() => setViewMode('list')}
                className={`px-3 py-2 text-sm min-h-[44px] ${viewMode === 'list' ? 'bg-blue-600 text-white' : 'text-gray-700 hover:bg-gray-50'}`}
                aria-pressed={viewMode === 'list'}
                data-testid="view-list-btn"
              >
                List
              </button>
              <button
                onClick={() => setViewMode('calendar')}
                className={`px-3 py-2 text-sm min-h-[44px] ${viewMode === 'calendar' ? 'bg-blue-600 text-white' : 'text-gray-700 hover:bg-gray-50'}`}
                aria-pressed={viewMode === 'calendar'}
                data-testid="view-calendar-btn"
              >
                Calendar
              </button>
            </div>
          )}
          <button
            onClick={() => setShowForm(!showForm)}
            className="rounded-md bg-blue-600 px-4 py-2 text-sm font-medium text-white hover:bg-blue-700 min-h-[44px]"
            data-testid="new-reservation-btn"
          >
            {showForm ? 'Cancel' : 'New Reservation'}
          </button>
        </div>
      </div>

      {/* Filters */}
      <div className="flex flex-wrap items-center gap-3 mb-4" data-testid="reservation-filters">
        {viewMode === 'list' && (
          <input
            type="date"
            aria-label="Filter by date"
            value={dateFilter}
            onChange={(e) => setDateFilter(e.target.value)}
            className="rounded-md border border-gray-300 px-3 py-2 text-sm min-h-[44px]"
            data-testid="date-filter"
          />
        )}
        <select
          aria-label="Filter by status"
          value={statusFilter}
          onChange={(e) => setStatusFilter(e.target.value)}
          className="rounded-md border border-gray-300 px-3 py-2 text-sm min-h-[44px]"
          data-testid="status-filter"
        >
          <option value="all">All Statuses</option>
          {Object.entries(STATUS_BADGE).map(([key, { label }]) => (
            <option key={key} value={key}>{label}</option>
          ))}
        </select>
      </div>

      {error && (
        <div className="mb-4 rounded-md border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700" role="alert" data-testid="reservation-error">
          {error}
          <button onClick={() => setError('')} className="ml-2 font-bold">×</button>
        </div>
      )}

      {/* Create form */}
      {showForm && (
        <form onSubmit={handleSubmit} className="mb-6 rounded-lg border p-4 bg-white" aria-label="New reservation form" data-testid="reservation-form">
          <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
            <div>
              <label htmlFor="res-customer" className="block text-sm font-medium text-gray-700 mb-1">Customer Name</label>
              <input
                id="res-customer"
                type="text"
                required
                value={form.customer_name}
                onChange={(e) => setForm({ ...form, customer_name: e.target.value })}
                className="w-full rounded-md border border-gray-300 px-3 py-2 text-sm min-h-[44px]"
                data-testid="res-customer-input"
              />
            </div>
            <div>
              <label htmlFor="res-table" className="block text-sm font-medium text-gray-700 mb-1">{tableTerm}</label>
              <select
                id="res-table"
                required
                value={form.table_id}
                onChange={(e) => setForm({ ...form, table_id: e.target.value })}
                className="w-full rounded-md border border-gray-300 px-3 py-2 text-sm min-h-[44px]"
                data-testid="res-table-select"
              >
                <option value="">Select {tableTerm.toLowerCase()}</option>
                {tables.map((t) => (
                  <option key={t.id} value={t.id}>{tableTerm} {t.table_number} ({t.seat_count} seats)</option>
                ))}
              </select>
            </div>
            <div>
              <label htmlFor="res-party" className="block text-sm font-medium text-gray-700 mb-1">Party Size</label>
              <input
                id="res-party"
                type="number"
                inputMode="numeric"
                min={1}
                required
                value={form.party_size}
                onChange={(e) => setForm({ ...form, party_size: parseInt(e.target.value) || 1 })}
                className="w-full rounded-md border border-gray-300 px-3 py-2 text-sm min-h-[44px]"
                data-testid="res-party-input"
              />
            </div>
            <div>
              <label htmlFor="res-date" className="block text-sm font-medium text-gray-700 mb-1">Date</label>
              <input
                id="res-date"
                type="date"
                required
                value={form.reservation_date}
                onChange={(e) => setForm({ ...form, reservation_date: e.target.value })}
                className="w-full rounded-md border border-gray-300 px-3 py-2 text-sm min-h-[44px]"
                data-testid="res-date-input"
              />
            </div>
            <div>
              <label htmlFor="res-time" className="block text-sm font-medium text-gray-700 mb-1">Time</label>
              <input
                id="res-time"
                type="time"
                required
                value={form.reservation_time}
                onChange={(e) => setForm({ ...form, reservation_time: e.target.value })}
                className="w-full rounded-md border border-gray-300 px-3 py-2 text-sm min-h-[44px]"
                data-testid="res-time-input"
              />
            </div>
            <div>
              <label htmlFor="res-duration" className="block text-sm font-medium text-gray-700 mb-1">Duration (min)</label>
              <input
                id="res-duration"
                type="number"
                inputMode="numeric"
                min={15}
                value={form.duration_minutes}
                onChange={(e) => setForm({ ...form, duration_minutes: parseInt(e.target.value) || 90 })}
                className="w-full rounded-md border border-gray-300 px-3 py-2 text-sm min-h-[44px]"
                data-testid="res-duration-input"
              />
            </div>
          </div>
          <div className="mt-4">
            <label htmlFor="res-notes" className="block text-sm font-medium text-gray-700 mb-1">Notes</label>
            <textarea
              id="res-notes"
              value={form.notes}
              onChange={(e) => setForm({ ...form, notes: e.target.value })}
              className="w-full rounded-md border border-gray-300 px-3 py-2 text-sm"
              rows={2}
              data-testid="res-notes-input"
            />
          </div>
          <div className="mt-4">
            <button
              type="submit"
              disabled={submitting || !form.customer_name || !form.table_id || !form.reservation_date}
              className="rounded-md bg-blue-600 px-4 py-2 text-sm font-medium text-white hover:bg-blue-700 disabled:opacity-50 min-h-[44px]"
              data-testid="create-reservation-btn"
            >
              {submitting ? 'Creating…' : 'Create Reservation'}
            </button>
          </div>
        </form>
      )}

      {/* List view */}
      {viewMode === 'list' && (
        <>
          {loading && (
            <div className="py-12 text-center text-sm text-gray-500" role="status" aria-label="Loading reservations" data-testid="reservations-loading">
              Loading reservations…
            </div>
          )}

          {!loading && reservations.length === 0 && (
            <div className="py-12 text-center text-sm text-gray-500" data-testid="no-reservations">
              No reservations found for this date.
            </div>
          )}

          {!loading && reservations.length > 0 && (
            <div className="overflow-x-auto rounded-lg border border-gray-200" data-testid="reservation-table">
              <table className="min-w-full divide-y divide-gray-200" role="table">
                <thead className="bg-gray-50">
                  <tr>
                    <th scope="col" className="px-4 py-3 text-left text-xs font-medium uppercase text-gray-500">Customer</th>
                    <th scope="col" className="px-4 py-3 text-left text-xs font-medium uppercase text-gray-500">{tableTerm}</th>
                    <th scope="col" className="px-4 py-3 text-left text-xs font-medium uppercase text-gray-500">Party</th>
                    <th scope="col" className="px-4 py-3 text-left text-xs font-medium uppercase text-gray-500">Time</th>
                    <th scope="col" className="px-4 py-3 text-left text-xs font-medium uppercase text-gray-500">Duration</th>
                    <th scope="col" className="px-4 py-3 text-left text-xs font-medium uppercase text-gray-500">Status</th>
                    <th scope="col" className="px-4 py-3 text-left text-xs font-medium uppercase text-gray-500">Actions</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-gray-100 bg-white">
                  {reservations.map((r) => {
                    const badge = STATUS_BADGE[r.status] ?? STATUS_BADGE.confirmed
                    return (
                      <tr key={r.id} className="hover:bg-gray-50" data-testid={`reservation-row-${r.id}`}>
                        <td className="px-4 py-3 text-sm text-gray-900">{r.customer_name}</td>
                        <td className="px-4 py-3 text-sm text-gray-700">{tableTerm} {getTableNumber(r.table_id)}</td>
                        <td className="px-4 py-3 text-sm text-gray-700">{r.party_size}</td>
                        <td className="px-4 py-3 text-sm text-gray-700">{r.reservation_time}</td>
                        <td className="px-4 py-3 text-sm text-gray-700">{r.duration_minutes} min</td>
                        <td className="px-4 py-3">
                          <span className={`inline-flex rounded-full px-2 py-0.5 text-xs font-medium ${
                            badge.variant === 'success' ? 'bg-green-100 text-green-800' :
                            badge.variant === 'info' ? 'bg-blue-100 text-blue-800' :
                            badge.variant === 'warning' ? 'bg-yellow-100 text-yellow-800' :
                            badge.variant === 'error' ? 'bg-red-100 text-red-800' :
                            'bg-gray-100 text-gray-800'
                          }`} data-testid={`reservation-status-${r.id}`}>
                            {badge.label}
                          </span>
                        </td>
                        <td className="px-4 py-3">
                          {r.status === 'confirmed' && (
                            <button
                              onClick={() => handleCancel(r.id)}
                              className="text-xs text-red-600 hover:text-red-800 font-medium min-h-[44px] min-w-[44px]"
                              data-testid={`cancel-reservation-${r.id}`}
                            >
                              Cancel
                            </button>
                          )}
                        </td>
                      </tr>
                    )
                  })}
                </tbody>
              </table>
            </div>
          )}

          {!loading && total > 0 && (
            <div className="mt-3 text-sm text-gray-500" data-testid="reservation-count">
              {total} reservation{total !== 1 ? 's' : ''} for {dateFilter}
            </div>
          )}
        </>
      )}

      {/* Calendar view (Req 14.6) */}
      {viewMode === 'calendar' && (
        <div data-testid="calendar-view">
          {/* Calendar navigation */}
          <div className="flex items-center justify-between mb-4">
            <button
              onClick={() =>
                setCalendarDate((prev) => {
                  const d = new Date(prev.year, prev.month - 1)
                  return { year: d.getFullYear(), month: d.getMonth() }
                })
              }
              className="rounded-md border border-gray-300 px-3 py-2 text-sm hover:bg-gray-50 min-h-[44px] min-w-[44px]"
              aria-label="Previous month"
              data-testid="calendar-prev"
            >
              ←
            </button>
            <span className="text-lg font-medium" data-testid="calendar-month-label">{monthLabel}</span>
            <button
              onClick={() =>
                setCalendarDate((prev) => {
                  const d = new Date(prev.year, prev.month + 1)
                  return { year: d.getFullYear(), month: d.getMonth() }
                })
              }
              className="rounded-md border border-gray-300 px-3 py-2 text-sm hover:bg-gray-50 min-h-[44px] min-w-[44px]"
              aria-label="Next month"
              data-testid="calendar-next"
            >
              →
            </button>
          </div>

          {/* Day headers */}
          <div className="grid grid-cols-7 gap-1 mb-1">
            {['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun'].map((d) => (
              <div key={d} className="text-center text-xs font-medium text-gray-500 py-1">
                {d}
              </div>
            ))}
          </div>

          {/* Calendar grid */}
          <div className="grid grid-cols-7 gap-1" data-testid="calendar-grid">
            {/* Leading empty cells for alignment */}
            {(() => {
              const firstDay = calendarDays[0]?.getDay() ?? 1
              // Convert Sunday=0 to Monday-first: Mon=0, Tue=1, ..., Sun=6
              const offset = firstDay === 0 ? 6 : firstDay - 1
              return Array.from({ length: offset }, (_, i) => (
                <div key={`empty-${i}`} className="min-h-[80px]" />
              ))
            })()}
            {calendarDays.map((day) => {
              const key = formatDateKey(day)
              const dayReservations = reservationsByDate[key] ?? []
              const isToday = key === new Date().toISOString().slice(0, 10)
              return (
                <div
                  key={key}
                  className={`min-h-[80px] rounded border p-1 text-xs ${
                    isToday ? 'border-blue-400 bg-blue-50' : 'border-gray-200'
                  }`}
                  data-testid={`calendar-day-${key}`}
                  onClick={() => {
                    setDateFilter(key)
                    setViewMode('list')
                  }}
                >
                  <div className={`font-medium mb-1 ${isToday ? 'text-blue-700' : 'text-gray-700'}`}>
                    {day.getDate()}
                  </div>
                  {dayReservations.slice(0, 3).map((r) => (
                    <div
                      key={r.id}
                      className={`truncate rounded px-1 py-0.5 mb-0.5 ${
                        r.status === 'confirmed' ? 'bg-green-100 text-green-800' :
                        r.status === 'cancelled' ? 'bg-red-100 text-red-800' :
                        'bg-gray-100 text-gray-700'
                      }`}
                      title={`${r.reservation_time} - ${r.customer_name} (${r.party_size})`}
                    >
                      {r.reservation_time} {r.customer_name}
                    </div>
                  ))}
                  {dayReservations.length > 3 && (
                    <div className="text-gray-400">+{dayReservations.length - 3} more</div>
                  )}
                </div>
              )
            })}
          </div>
        </div>
      )}
    </div>
  )
}
