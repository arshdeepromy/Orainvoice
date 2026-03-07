/**
 * Reservation management list with date filter, create form, and cancel action.
 *
 * Validates: Requirement — Table Module — Task 31.10
 */

import { useEffect, useState, useCallback } from 'react'
import apiClient from '@/api/client'

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

export default function ReservationList() {
  const [reservations, setReservations] = useState<ReservationItem[]>([])
  const [total, setTotal] = useState(0)
  const [tables, setTables] = useState<TableOption[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const [dateFilter, setDateFilter] = useState(new Date().toISOString().slice(0, 10))
  const [showForm, setShowForm] = useState(false)
  const [form, setForm] = useState(INITIAL_FORM)
  const [submitting, setSubmitting] = useState(false)

  const fetchReservations = useCallback(async () => {
    setLoading(true)
    setError('')
    try {
      const params = new URLSearchParams()
      if (dateFilter) params.set('date', dateFilter)
      const res = await apiClient.get(`/api/v2/tables/reservations?${params}`)
      setReservations(res.data.reservations)
      setTotal(res.data.total)
    } catch {
      setError('Failed to load reservations.')
      setReservations([])
    } finally {
      setLoading(false)
    }
  }, [dateFilter])

  const fetchTables = useCallback(async () => {
    try {
      const res = await apiClient.get('/api/v2/tables/tables?limit=200')
      setTables(res.data.tables)
    } catch {
      // Tables list is optional for display
    }
  }, [])

  useEffect(() => { fetchReservations() }, [fetchReservations])
  useEffect(() => { fetchTables() }, [fetchTables])

  const handleCancel = async (id: string) => {
    try {
      await apiClient.put(`/api/v2/tables/reservations/${id}/cancel`)
      fetchReservations()
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
    } catch {
      setError('Failed to create reservation.')
    } finally {
      setSubmitting(false)
    }
  }

  const getTableNumber = (tableId: string) =>
    tables.find((t) => t.id === tableId)?.table_number ?? tableId.slice(0, 8)

  return (
    <div className="p-6">
      <div className="flex items-center justify-between mb-6">
        <h1 className="text-2xl font-semibold text-gray-900">Reservations</h1>
        <button
          onClick={() => setShowForm(!showForm)}
          className="rounded-md bg-blue-600 px-4 py-2 text-sm font-medium text-white hover:bg-blue-700"
        >
          {showForm ? 'Cancel' : 'New Reservation'}
        </button>
      </div>

      {/* Date filter */}
      <div className="mb-4">
        <input
          type="date"
          aria-label="Filter by date"
          value={dateFilter}
          onChange={(e) => setDateFilter(e.target.value)}
          className="rounded-md border border-gray-300 px-3 py-2 text-sm"
        />
      </div>

      {error && (
        <div className="mb-4 rounded-md border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700" role="alert">
          {error}
        </div>
      )}

      {/* Create form */}
      {showForm && (
        <form onSubmit={handleSubmit} className="mb-6 rounded-lg border p-4 bg-white" aria-label="New reservation form">
          <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
            <div>
              <label htmlFor="res-customer" className="block text-sm font-medium text-gray-700 mb-1">Customer Name</label>
              <input
                id="res-customer"
                type="text"
                required
                value={form.customer_name}
                onChange={(e) => setForm({ ...form, customer_name: e.target.value })}
                className="w-full rounded-md border border-gray-300 px-3 py-2 text-sm"
              />
            </div>
            <div>
              <label htmlFor="res-table" className="block text-sm font-medium text-gray-700 mb-1">Table</label>
              <select
                id="res-table"
                required
                value={form.table_id}
                onChange={(e) => setForm({ ...form, table_id: e.target.value })}
                className="w-full rounded-md border border-gray-300 px-3 py-2 text-sm"
              >
                <option value="">Select table</option>
                {tables.map((t) => (
                  <option key={t.id} value={t.id}>Table {t.table_number} ({t.seat_count} seats)</option>
                ))}
              </select>
            </div>
            <div>
              <label htmlFor="res-party" className="block text-sm font-medium text-gray-700 mb-1">Party Size</label>
              <input
                id="res-party"
                type="number"
                min={1}
                required
                value={form.party_size}
                onChange={(e) => setForm({ ...form, party_size: parseInt(e.target.value) || 1 })}
                className="w-full rounded-md border border-gray-300 px-3 py-2 text-sm"
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
                className="w-full rounded-md border border-gray-300 px-3 py-2 text-sm"
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
                className="w-full rounded-md border border-gray-300 px-3 py-2 text-sm"
              />
            </div>
            <div>
              <label htmlFor="res-duration" className="block text-sm font-medium text-gray-700 mb-1">Duration (min)</label>
              <input
                id="res-duration"
                type="number"
                min={15}
                value={form.duration_minutes}
                onChange={(e) => setForm({ ...form, duration_minutes: parseInt(e.target.value) || 90 })}
                className="w-full rounded-md border border-gray-300 px-3 py-2 text-sm"
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
            />
          </div>
          <div className="mt-4">
            <button
              type="submit"
              disabled={submitting || !form.customer_name || !form.table_id || !form.reservation_date}
              className="rounded-md bg-blue-600 px-4 py-2 text-sm font-medium text-white hover:bg-blue-700 disabled:opacity-50"
            >
              {submitting ? 'Creating…' : 'Create Reservation'}
            </button>
          </div>
        </form>
      )}

      {loading && (
        <div className="py-12 text-center text-sm text-gray-500" role="status" aria-label="Loading reservations">
          Loading reservations…
        </div>
      )}

      {!loading && reservations.length === 0 && (
        <div className="py-12 text-center text-sm text-gray-500">
          No reservations found for this date.
        </div>
      )}

      {!loading && reservations.length > 0 && (
        <div className="overflow-x-auto rounded-lg border border-gray-200">
          <table className="min-w-full divide-y divide-gray-200" role="table">
            <thead className="bg-gray-50">
              <tr>
                <th scope="col" className="px-4 py-3 text-left text-xs font-medium uppercase text-gray-500">Customer</th>
                <th scope="col" className="px-4 py-3 text-left text-xs font-medium uppercase text-gray-500">Table</th>
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
                  <tr key={r.id} className="hover:bg-gray-50">
                    <td className="px-4 py-3 text-sm text-gray-900">{r.customer_name}</td>
                    <td className="px-4 py-3 text-sm text-gray-700">Table {getTableNumber(r.table_id)}</td>
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
                      }`}>
                        {badge.label}
                      </span>
                    </td>
                    <td className="px-4 py-3">
                      {r.status === 'confirmed' && (
                        <button
                          onClick={() => handleCancel(r.id)}
                          className="text-xs text-red-600 hover:text-red-800 font-medium"
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
        <div className="mt-3 text-sm text-gray-500">
          {total} reservation{total !== 1 ? 's' : ''} for {dateFilter}
        </div>
      )}
    </div>
  )
}
