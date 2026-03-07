/**
 * Weekly timesheet view with daily/weekly totals.
 *
 * Displays time entries grouped by day in a grid layout with
 * daily and weekly hour totals.
 *
 * Validates: Requirement 13.5
 */

import { useEffect, useState, useCallback } from 'react'
import apiClient from '@/api/client'

interface TimeEntryData {
  id: string
  description: string | null
  start_time: string
  end_time: string | null
  duration_minutes: number | null
  is_billable: boolean
  hourly_rate: string | null
  is_invoiced: boolean
  job_id: string | null
  project_id: string | null
}

interface TimesheetDay {
  date: string
  entries: TimeEntryData[]
  total_minutes: number
  billable_minutes: number
}

interface TimesheetData {
  week_start: string
  week_end: string
  days: TimesheetDay[]
  weekly_total_minutes: number
  weekly_billable_minutes: number
}

function formatMinutes(minutes: number): string {
  const h = Math.floor(minutes / 60)
  const m = minutes % 60
  return `${h}h ${m}m`
}

function formatTime(iso: string): string {
  return new Date(iso).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })
}

function getMonday(d: Date): string {
  const date = new Date(d)
  const day = date.getDay()
  const diff = date.getDate() - day + (day === 0 ? -6 : 1)
  date.setDate(diff)
  return date.toISOString().split('T')[0]
}

const DAY_NAMES = ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun']

export default function TimeSheet() {
  const [timesheet, setTimesheet] = useState<TimesheetData | null>(null)
  const [loading, setLoading] = useState(true)
  const [weekStart, setWeekStart] = useState(() => getMonday(new Date()))

  const fetchTimesheet = useCallback(async () => {
    setLoading(true)
    try {
      const res = await apiClient.get(`/api/v2/time-entries/timesheet?week_start=${weekStart}`)
      setTimesheet(res.data)
    } catch {
      setTimesheet(null)
    } finally {
      setLoading(false)
    }
  }, [weekStart])

  useEffect(() => { fetchTimesheet() }, [fetchTimesheet])

  const navigateWeek = (offset: number) => {
    const d = new Date(weekStart)
    d.setDate(d.getDate() + offset * 7)
    setWeekStart(d.toISOString().split('T')[0])
  }

  if (loading) {
    return <div role="status" aria-label="Loading timesheet">Loading timesheet…</div>
  }

  if (!timesheet) {
    return <div role="alert">Failed to load timesheet</div>
  }

  return (
    <div>
      <h1>Weekly Timesheet</h1>

      <nav aria-label="Week navigation" style={{ display: 'flex', gap: '1rem', alignItems: 'center', margin: '1rem 0' }}>
        <button onClick={() => navigateWeek(-1)} aria-label="Previous week">← Prev</button>
        <span>{timesheet.week_start} — {timesheet.week_end}</span>
        <button onClick={() => navigateWeek(1)} aria-label="Next week">Next →</button>
      </nav>

      <table role="table" aria-label="Weekly timesheet">
        <thead>
          <tr>
            <th>Day</th>
            <th>Entries</th>
            <th>Total</th>
            <th>Billable</th>
          </tr>
        </thead>
        <tbody>
          {timesheet.days.map((day, idx) => (
            <tr key={day.date}>
              <td>
                <strong>{DAY_NAMES[idx]}</strong>
                <br />
                <small>{day.date}</small>
              </td>
              <td>
                {day.entries.length === 0 ? (
                  <span style={{ color: '#999' }}>—</span>
                ) : (
                  <ul style={{ listStyle: 'none', padding: 0, margin: 0 }}>
                    {day.entries.map((entry) => (
                      <li key={entry.id}>
                        {entry.description || 'Untitled'}{' '}
                        <small>
                          ({formatTime(entry.start_time)}
                          {entry.end_time ? ` – ${formatTime(entry.end_time)}` : ' (running)'}
                          )
                        </small>
                        {entry.is_billable && <span title="Billable"> 💰</span>}
                      </li>
                    ))}
                  </ul>
                )}
              </td>
              <td>{formatMinutes(day.total_minutes)}</td>
              <td>{formatMinutes(day.billable_minutes)}</td>
            </tr>
          ))}
        </tbody>
        <tfoot>
          <tr>
            <td colSpan={2}><strong>Weekly Total</strong></td>
            <td><strong>{formatMinutes(timesheet.weekly_total_minutes)}</strong></td>
            <td><strong>{formatMinutes(timesheet.weekly_billable_minutes)}</strong></td>
          </tr>
        </tfoot>
      </table>
    </div>
  )
}
