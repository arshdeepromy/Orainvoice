import { useState, useEffect, useCallback } from 'react'
import apiClient from '@/api/client'
import { Button, Select, Spinner } from '@/components/ui'

interface Schedule {
  id: string
  report_type: string
  frequency: string
  recipients: string[]
  is_active: boolean
  last_generated_at: string | null
  created_at: string
}

const REPORT_OPTIONS = [
  { value: 'stock_valuation', label: 'Stock Valuation' },
  { value: 'job_profitability', label: 'Job Profitability' },
  { value: 'project_profitability', label: 'Project Profitability' },
  { value: 'daily_sales_summary', label: 'Daily Sales Summary' },
  { value: 'gst_return', label: 'GST Return (NZ)' },
  { value: 'bas_return', label: 'BAS Return (AU)' },
  { value: 'vat_return', label: 'VAT Return (UK)' },
  { value: 'staff_utilisation', label: 'Staff Utilisation' },
  { value: 'retention_summary', label: 'Retention Summary' },
]

const FREQUENCY_OPTIONS = [
  { value: 'daily', label: 'Daily' },
  { value: 'weekly', label: 'Weekly' },
  { value: 'monthly', label: 'Monthly' },
]

/**
 * Scheduled reports management — create, list, delete report schedules.
 * Requirements: Task 54.19
 */
export default function ScheduledReports() {
  const [schedules, setSchedules] = useState<Schedule[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')

  // New schedule form
  const [reportType, setReportType] = useState(REPORT_OPTIONS[0].value)
  const [frequency, setFrequency] = useState('daily')
  const [recipients, setRecipients] = useState('')
  const [creating, setCreating] = useState(false)

  const fetchSchedules = useCallback(async () => {
    setLoading(true)
    setError('')
    try {
      const res = await apiClient.get<Schedule[]>('/reports/schedules')
      setSchedules(res.data ?? [])
    } catch {
      setError('Failed to load schedules.')
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => { fetchSchedules() }, [fetchSchedules])

  const handleCreate = async () => {
    setCreating(true)
    try {
      await apiClient.post('/reports/schedule', {
        report_type: reportType,
        frequency,
        recipients: recipients.split(',').map((r) => r.trim()).filter(Boolean),
        filters: {},
        is_active: true,
      })
      setRecipients('')
      await fetchSchedules()
    } catch {
      setError('Failed to create schedule.')
    } finally {
      setCreating(false)
    }
  }

  const handleDelete = async (id: string) => {
    try {
      await apiClient.delete(`/reports/schedule/${id}`)
      setSchedules((prev) => prev.filter((s) => s.id !== id))
    } catch {
      setError('Failed to delete schedule.')
    }
  }

  return (
    <div>
      <h2 className="text-lg font-semibold text-text mb-4">Scheduled Reports</h2>

      {/* Create form */}
      <div className="rounded-card border border-border bg-card p-4 mb-6 shadow-card">
        <h3 className="text-sm font-medium text-text mb-3">New Schedule</h3>
        <div className="grid grid-cols-1 sm:grid-cols-4 gap-3 items-end">
          <Select
            label="Report"
            value={reportType}
            onChange={(e) => setReportType(e.target.value)}
            options={REPORT_OPTIONS}
          />
          <Select
            label="Frequency"
            value={frequency}
            onChange={(e) => setFrequency(e.target.value)}
            options={FREQUENCY_OPTIONS}
          />
          <div>
            <label htmlFor="recipients" className="block text-sm font-medium text-text mb-1">
              Recipients (comma-separated)
            </label>
            <input
              id="recipients"
              type="text"
              value={recipients}
              onChange={(e) => setRecipients(e.target.value)}
              placeholder="email@example.com"
              className="w-full rounded-ctl border border-border bg-card px-3 py-2 text-sm text-text focus:outline-none focus:border-accent focus:shadow-[0_0_0_3px_var(--accent-soft)]"
            />
          </div>
          <Button onClick={handleCreate} loading={creating}>
            Create Schedule
          </Button>
        </div>
      </div>

      {error && <div className="mb-4 rounded-ctl border border-danger-soft bg-danger-soft px-4 py-3 text-sm text-danger" role="alert">{error}</div>}
      {loading && <div className="py-8"><Spinner label="Loading schedules" /></div>}

      {!loading && (
        <div className="overflow-hidden rounded-card border border-border bg-card shadow-card">
          <table className="min-w-full" role="grid">
            <caption className="sr-only">Scheduled reports</caption>
            <thead>
              <tr>
                <th scope="col" className="mono border-b border-border px-4 py-3 text-left text-[10.5px] font-medium uppercase tracking-[0.08em] text-muted-2">Report</th>
                <th scope="col" className="mono border-b border-border px-4 py-3 text-left text-[10.5px] font-medium uppercase tracking-[0.08em] text-muted-2">Frequency</th>
                <th scope="col" className="mono border-b border-border px-4 py-3 text-left text-[10.5px] font-medium uppercase tracking-[0.08em] text-muted-2">Recipients</th>
                <th scope="col" className="mono border-b border-border px-4 py-3 text-left text-[10.5px] font-medium uppercase tracking-[0.08em] text-muted-2">Last Run</th>
                <th scope="col" className="mono border-b border-border px-4 py-3 text-right text-[10.5px] font-medium uppercase tracking-[0.08em] text-muted-2">Actions</th>
              </tr>
            </thead>
            <tbody>
              {(schedules ?? []).length === 0 ? (
                <tr><td colSpan={5} className="px-4 py-12 text-center text-sm text-muted">No scheduled reports.</td></tr>
              ) : (
                (schedules ?? []).map((s, i) => (
                  <tr key={s.id || i} className="border-b border-border last:border-b-0 hover:bg-canvas">
                    <td className="px-4 py-3 text-sm text-text">{(s.report_type ?? '').replace(/_/g, ' ')}</td>
                    <td className="px-4 py-3 text-sm text-muted capitalize">{s.frequency}</td>
                    <td className="px-4 py-3 text-sm text-muted">{(s.recipients ?? []).join(', ') || '—'}</td>
                    <td className="px-4 py-3 text-sm text-muted-2 mono">{s.last_generated_at ? new Date(s.last_generated_at).toLocaleDateString() : 'Never'}</td>
                    <td className="px-4 py-3 text-right">
                      <Button
                        variant="danger"
                        size="sm"
                        onClick={() => handleDelete(s.id)}
                        aria-label={`Delete ${s.report_type} schedule`}
                      >
                        Delete
                      </Button>
                    </td>
                  </tr>
                ))
              )}
            </tbody>
          </table>
        </div>
      )}
    </div>
  )
}
