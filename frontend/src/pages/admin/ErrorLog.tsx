import { useState, useEffect, useCallback } from 'react'
import { Button } from '@/components/ui/Button'
import { Badge } from '@/components/ui/Badge'
import { Spinner } from '@/components/ui/Spinner'
import { AlertBanner } from '@/components/ui/AlertBanner'
import { Input } from '@/components/ui/Input'
import { Select } from '@/components/ui/Select'
import { Modal } from '@/components/ui/Modal'
import { ToastContainer, useToast } from '@/components/ui/Toast'
import apiClient from '@/api/client'

/* ── Types ── */

export type Severity = 'Info' | 'Warning' | 'Error' | 'Critical'
export type ErrorCategory =
  | 'Payment'
  | 'Integration'
  | 'Storage'
  | 'Authentication'
  | 'Data'
  | 'Background Job'
  | 'Application'
export type ErrorStatus = 'Open' | 'Investigating' | 'Resolved'

export interface ErrorSummary {
  severity: Severity
  last_hour: number
  last_24h: number
  last_7d: number
}

export interface ErrorRecord {
  id: string
  timestamp: string
  severity: Severity
  category: ErrorCategory
  module: string
  function_name: string
  message: string
  stack_trace: string
  org_id: string | null
  user_id: string | null
  http_method: string | null
  http_endpoint: string | null
  request_body: string | null
  response_body: string | null
  status: ErrorStatus
  notes: string
}

export interface ErrorLogResponse {
  errors: ErrorRecord[]
  total: number
}

/* ── Constants ── */

const SEVERITY_OPTIONS = [
  { value: '', label: 'All severities' },
  { value: 'Info', label: 'Info' },
  { value: 'Warning', label: 'Warning' },
  { value: 'Error', label: 'Error' },
  { value: 'Critical', label: 'Critical' },
]

const CATEGORY_OPTIONS = [
  { value: '', label: 'All categories' },
  { value: 'Payment', label: 'Payment' },
  { value: 'Integration', label: 'Integration' },
  { value: 'Storage', label: 'Storage' },
  { value: 'Authentication', label: 'Authentication' },
  { value: 'Data', label: 'Data' },
  { value: 'Background Job', label: 'Background Job' },
  { value: 'Application', label: 'Application' },
]

const STATUS_OPTIONS = [
  { value: 'Open', label: 'Open' },
  { value: 'Investigating', label: 'Investigating' },
  { value: 'Resolved', label: 'Resolved' },
]

const SEVERITY_BADGE_VARIANT: Record<Severity, 'info' | 'warning' | 'error'> = {
  Info: 'info',
  Warning: 'warning',
  Error: 'error',
  Critical: 'error',
}

const SEVERITY_ROW_CLASS: Record<Severity, string> = {
  Info: 'border-l-4 border-l-blue-400 bg-blue-50/40',
  Warning: 'border-l-4 border-l-amber-400 bg-amber-50/40',
  Error: 'border-l-4 border-l-red-400 bg-red-50/40',
  Critical: 'border-l-4 border-l-red-800 bg-red-100/60',
}

/* ── Helpers ── */

function formatTimestamp(iso: string): string {
  return new Date(iso).toLocaleDateString('en-NZ', {
    day: 'numeric',
    month: 'short',
    year: 'numeric',
    hour: '2-digit',
    minute: '2-digit',
    second: '2-digit',
  })
}

/* ── Summary Cards ── */

function SummaryCards({ summaries, loading }: { summaries: ErrorSummary[]; loading: boolean }) {
  if (loading) {
    return (
      <div className="flex items-center justify-center py-8">
        <Spinner label="Loading error summary" />
      </div>
    )
  }

  const severityOrder: Severity[] = ['Critical', 'Error', 'Warning', 'Info']
  const ordered = severityOrder.map(
    (s) => summaries.find((sum) => sum.severity === s) ?? { severity: s, last_hour: 0, last_24h: 0, last_7d: 0 },
  )

  const cardColour: Record<Severity, string> = {
    Critical: 'border-red-800 bg-red-50',
    Error: 'border-red-400 bg-red-50',
    Warning: 'border-amber-400 bg-amber-50',
    Info: 'border-blue-400 bg-blue-50',
  }

  return (
    <div className="grid grid-cols-2 md:grid-cols-4 gap-4 mb-6" role="region" aria-label="Error count summary">
      {ordered.map((s) => (
        <div key={s.severity} className={`rounded-lg border-l-4 p-4 shadow-sm ${cardColour[s.severity]}`}>
          <h3 className="text-sm font-medium text-gray-600">{s.severity}</h3>
          <div className="mt-2 grid grid-cols-3 gap-2 text-center">
            <div>
              <p className="text-lg font-bold text-gray-900">{s.last_hour}</p>
              <p className="text-xs text-gray-500">1h</p>
            </div>
            <div>
              <p className="text-lg font-bold text-gray-900">{s.last_24h}</p>
              <p className="text-xs text-gray-500">24h</p>
            </div>
            <div>
              <p className="text-lg font-bold text-gray-900">{s.last_7d}</p>
              <p className="text-xs text-gray-500">7d</p>
            </div>
          </div>
        </div>
      ))}
    </div>
  )
}

/* ── Error Detail Modal ── */

function ErrorDetailModal({
  error,
  open,
  onClose,
  onStatusChange,
  onNotesChange,
}: {
  error: ErrorRecord | null
  open: boolean
  onClose: () => void
  onStatusChange: (id: string, status: ErrorStatus, notes: string) => Promise<void>
  onNotesChange: () => void
}) {
  const [status, setStatus] = useState<ErrorStatus>('Open')
  const [notes, setNotes] = useState('')
  const [saving, setSaving] = useState(false)

  useEffect(() => {
    if (error) {
      setStatus(error.status)
      setNotes(error.notes)
    }
  }, [error])

  const handleSave = async () => {
    if (!error) return
    setSaving(true)
    try {
      await onStatusChange(error.id, status, notes)
      onNotesChange()
      onClose()
    } finally {
      setSaving(false)
    }
  }

  if (!error) return null

  return (
    <Modal open={open} onClose={onClose} title="Error Detail" className="max-w-2xl">
      <div className="space-y-4">
        {/* Header info */}
        <div className="flex flex-wrap gap-2">
          <Badge variant={SEVERITY_BADGE_VARIANT[error.severity]}>
            {error.severity}
          </Badge>
          <Badge variant="neutral">{error.category}</Badge>
          <span className="text-sm text-gray-500">{formatTimestamp(error.timestamp)}</span>
        </div>

        {/* Error ID */}
        <div>
          <h4 className="text-xs font-medium text-gray-500 uppercase">Error ID</h4>
          <p className="text-sm font-mono text-gray-700">{error.id}</p>
        </div>

        {/* Message */}
        <div>
          <h4 className="text-xs font-medium text-gray-500 uppercase">Message</h4>
          <p className="text-sm text-gray-900">{error.message}</p>
        </div>

        {/* Module / Function */}
        <div className="grid grid-cols-2 gap-4">
          <div>
            <h4 className="text-xs font-medium text-gray-500 uppercase">Module</h4>
            <p className="text-sm text-gray-700">{error.module}</p>
          </div>
          <div>
            <h4 className="text-xs font-medium text-gray-500 uppercase">Function</h4>
            <p className="text-sm text-gray-700">{error.function_name}</p>
          </div>
        </div>

        {/* Context */}
        {(error.org_id || error.user_id) && (
          <div className="grid grid-cols-2 gap-4">
            {error.org_id && (
              <div>
                <h4 className="text-xs font-medium text-gray-500 uppercase">Organisation</h4>
                <p className="text-sm font-mono text-gray-700">{error.org_id}</p>
              </div>
            )}
            {error.user_id && (
              <div>
                <h4 className="text-xs font-medium text-gray-500 uppercase">User</h4>
                <p className="text-sm font-mono text-gray-700">{error.user_id}</p>
              </div>
            )}
          </div>
        )}

        {/* HTTP details */}
        {error.http_method && (
          <div>
            <h4 className="text-xs font-medium text-gray-500 uppercase">Request</h4>
            <p className="text-sm font-mono text-gray-700">
              {error.http_method} {error.http_endpoint}
            </p>
          </div>
        )}

        {error.request_body && (
          <div>
            <h4 className="text-xs font-medium text-gray-500 uppercase">Request Body</h4>
            <pre className="mt-1 max-h-32 overflow-auto rounded bg-gray-100 p-3 text-xs text-gray-800">
              {error.request_body}
            </pre>
          </div>
        )}

        {error.response_body && (
          <div>
            <h4 className="text-xs font-medium text-gray-500 uppercase">Response Body</h4>
            <pre className="mt-1 max-h-32 overflow-auto rounded bg-gray-100 p-3 text-xs text-gray-800">
              {error.response_body}
            </pre>
          </div>
        )}

        {/* Stack trace */}
        <div>
          <h4 className="text-xs font-medium text-gray-500 uppercase">Stack Trace</h4>
          <pre className="mt-1 max-h-48 overflow-auto rounded bg-gray-900 p-3 text-xs text-green-300 whitespace-pre-wrap">
            {error.stack_trace}
          </pre>
        </div>

        {/* Status management */}
        <div className="border-t pt-4 space-y-3">
          <Select
            label="Status"
            options={STATUS_OPTIONS}
            value={status}
            onChange={(e) => setStatus(e.target.value as ErrorStatus)}
          />
          <div className="flex flex-col gap-1">
            <label htmlFor="error-notes" className="text-sm font-medium text-gray-700">
              Notes
            </label>
            <textarea
              id="error-notes"
              className="rounded-md border border-gray-300 px-3 py-2 text-sm text-gray-900 shadow-sm
                focus:outline-none focus:ring-2 focus:ring-blue-500 focus:border-blue-500"
              rows={3}
              value={notes}
              onChange={(e) => setNotes(e.target.value)}
              placeholder="Document investigation or fix details…"
            />
          </div>
          <div className="flex gap-3">
            <Button onClick={handleSave} loading={saving}>
              Save changes
            </Button>
            <Button variant="secondary" onClick={onClose}>
              Cancel
            </Button>
          </div>
        </div>
      </div>
    </Modal>
  )
}

/* ── Main Page ── */

export function ErrorLog() {
  const { toasts, addToast, dismissToast } = useToast()

  // Summary state
  const [summaries, setSummaries] = useState<ErrorSummary[]>([])
  const [summaryLoading, setSummaryLoading] = useState(true)

  // Error list state
  const [errors, setErrors] = useState<ErrorRecord[]>([])
  const [total, setTotal] = useState(0)
  const [listLoading, setListLoading] = useState(true)
  const [listError, setListError] = useState(false)

  // Filters
  const [search, setSearch] = useState('')
  const [severityFilter, setSeverityFilter] = useState('')
  const [categoryFilter, setCategoryFilter] = useState('')

  // Detail modal
  const [selectedError, setSelectedError] = useState<ErrorRecord | null>(null)
  const [detailOpen, setDetailOpen] = useState(false)

  // Critical notification banner
  const [criticalAlert, setCriticalAlert] = useState<string | null>(null)

  /* ── Fetch summary ── */
  const fetchSummary = useCallback(async () => {
    setSummaryLoading(true)
    try {
      const res = await apiClient.get<{
        by_severity: Array<{ label: string; count_1h: number; count_24h: number; count_7d: number }>
      }>('/admin/errors/dashboard')
      const mapped: ErrorSummary[] = (res.data.by_severity ?? []).map((s) => ({
        severity: (s.label.charAt(0).toUpperCase() + s.label.slice(1)) as Severity,
        last_hour: s.count_1h,
        last_24h: s.count_24h,
        last_7d: s.count_7d,
      }))
      setSummaries(mapped)
    } catch {
      // Summary failure is non-blocking
    } finally {
      setSummaryLoading(false)
    }
  }, [])

  /* ── Fetch error list ── */
  const fetchErrors = useCallback(async () => {
    setListLoading(true)
    setListError(false)
    try {
      const params: Record<string, string> = {}
      if (search) params.keyword = search
      if (severityFilter) params.severity = severityFilter.toLowerCase()
      if (categoryFilter) params.category = categoryFilter.toLowerCase()
      const res = await apiClient.get<{
        errors: Array<Record<string, any>>
        total: number
      }>('/admin/errors', { params })
      const mapped: ErrorRecord[] = (res.data.errors ?? []).map((e) => ({
        id: e.id,
        timestamp: e.created_at,
        severity: (e.severity ? e.severity.charAt(0).toUpperCase() + e.severity.slice(1) : 'Error') as Severity,
        category: (e.category ? e.category.charAt(0).toUpperCase() + e.category.slice(1).replace(/_/g, ' ') : 'Application') as ErrorCategory,
        module: e.module ?? '',
        function_name: e.function_name ?? '',
        message: e.message ?? '',
        stack_trace: e.stack_trace ?? '',
        org_id: e.org_id,
        user_id: e.user_id,
        http_method: e.http_method,
        http_endpoint: e.http_endpoint,
        request_body: e.request_body_sanitised ? JSON.stringify(e.request_body_sanitised) : null,
        response_body: e.response_body_sanitised ? JSON.stringify(e.response_body_sanitised) : null,
        status: (e.status ? e.status.charAt(0).toUpperCase() + e.status.slice(1) : 'Open') as ErrorStatus,
        notes: e.resolution_notes ?? '',
      }))
      setErrors(mapped)
      setTotal(res.data.total)

      // Check for critical errors in the last hour for push notification
      // Backend returns lowercase severity values
      const criticals = res.data.errors.filter(
        (e) =>
          e.severity?.toLowerCase() === 'critical' &&
          new Date(e.created_at).getTime() > Date.now() - 60 * 60 * 1000,
      )
      if (criticals.length > 0) {
        setCriticalAlert(
          `${criticals.length} critical error${criticals.length > 1 ? 's' : ''} in the last hour`,
        )
        // Trigger browser notification if permitted
        if ('Notification' in window && Notification.permission === 'granted') {
          new Notification('WorkshopPro — Critical Error', {
            body: `${criticals.length} critical error${criticals.length > 1 ? 's' : ''} detected`,
            tag: 'critical-error',
          })
        } else if ('Notification' in window && Notification.permission === 'default') {
          Notification.requestPermission()
        }
      } else {
        setCriticalAlert(null)
      }
    } catch {
      setListError(true)
    } finally {
      setListLoading(false)
    }
  }, [search, severityFilter, categoryFilter])

  useEffect(() => {
    fetchSummary()
    fetchErrors()
  }, [fetchSummary, fetchErrors])

  /* ── Status update ── */
  const handleStatusChange = async (id: string, status: ErrorStatus, notes: string) => {
    await apiClient.put(`/admin/errors/${id}/status`, {
      status: status.toLowerCase(),
      resolution_notes: notes,
    })
    addToast('success', `Error status updated to ${status}`)
    fetchErrors()
  }

  /* ── Open detail ── */
  const openDetail = async (errorId: string) => {
    try {
      const res = await apiClient.get<Record<string, any>>(`/admin/errors/${errorId}`)
      const e = res.data
      setSelectedError({
        id: e.id,
        timestamp: e.created_at,
        severity: (e.severity ? e.severity.charAt(0).toUpperCase() + e.severity.slice(1) : 'Error') as Severity,
        category: (e.category ? e.category.charAt(0).toUpperCase() + e.category.slice(1).replace(/_/g, ' ') : 'Application') as ErrorCategory,
        module: e.module ?? '',
        function_name: e.function_name ?? '',
        message: e.message ?? '',
        stack_trace: e.stack_trace ?? '',
        org_id: e.org_id,
        user_id: e.user_id,
        http_method: e.http_method,
        http_endpoint: e.http_endpoint,
        request_body: e.request_body_sanitised ? JSON.stringify(e.request_body_sanitised, null, 2) : null,
        response_body: e.response_body_sanitised ? JSON.stringify(e.response_body_sanitised, null, 2) : null,
        status: (e.status ? e.status.charAt(0).toUpperCase() + e.status.slice(1) : 'Open') as ErrorStatus,
        notes: e.resolution_notes ?? '',
      })
      setDetailOpen(true)
    } catch {
      addToast('error', 'Failed to load error details')
    }
  }

  return (
    <div>
      <h1 className="text-2xl font-semibold text-gray-900 mb-6">Error Log</h1>
      <ToastContainer toasts={toasts} onDismiss={dismissToast} />

      {/* Critical alert banner */}
      {criticalAlert && (
        <div className="mb-4">
          <AlertBanner variant="error" title="Critical Errors Detected">
            {criticalAlert}
          </AlertBanner>
        </div>
      )}

      {/* Summary cards */}
      <SummaryCards summaries={summaries} loading={summaryLoading} />

      {/* Filters */}
      <div className="flex flex-wrap gap-3 mb-4" role="search" aria-label="Error log filters">
        <div className="flex-1 min-w-[200px]">
          <Input
            label="Search"
            placeholder="Search by message or module…"
            value={search}
            onChange={(e) => setSearch(e.target.value)}
          />
        </div>
        <div className="w-44">
          <Select
            label="Severity"
            options={SEVERITY_OPTIONS}
            value={severityFilter}
            onChange={(e) => setSeverityFilter(e.target.value)}
          />
        </div>
        <div className="w-44">
          <Select
            label="Category"
            options={CATEGORY_OPTIONS}
            value={categoryFilter}
            onChange={(e) => setCategoryFilter(e.target.value)}
          />
        </div>
      </div>

      {/* Error feed */}
      {listLoading ? (
        <div className="flex items-center justify-center py-12">
          <Spinner label="Loading error log" />
        </div>
      ) : listError ? (
        <AlertBanner variant="error" title="Failed to load error log">
          Could not load error log. Please try again.
        </AlertBanner>
      ) : (
        <>
          <p className="text-sm text-gray-500 mb-2">{total} error{total !== 1 ? 's' : ''} found</p>
          <div className="overflow-x-auto rounded-lg border border-gray-200">
            <table className="min-w-full divide-y divide-gray-200" role="grid" aria-label="Error log feed">
              <thead className="bg-gray-50">
                <tr>
                  <th scope="col" className="px-4 py-3 text-left text-xs font-medium uppercase tracking-wider text-gray-500">
                    Time
                  </th>
                  <th scope="col" className="px-4 py-3 text-left text-xs font-medium uppercase tracking-wider text-gray-500">
                    Severity
                  </th>
                  <th scope="col" className="px-4 py-3 text-left text-xs font-medium uppercase tracking-wider text-gray-500">
                    Category
                  </th>
                  <th scope="col" className="px-4 py-3 text-left text-xs font-medium uppercase tracking-wider text-gray-500">
                    Module
                  </th>
                  <th scope="col" className="px-4 py-3 text-left text-xs font-medium uppercase tracking-wider text-gray-500">
                    Message
                  </th>
                  <th scope="col" className="px-4 py-3 text-left text-xs font-medium uppercase tracking-wider text-gray-500">
                    Status
                  </th>
                  <th scope="col" className="px-4 py-3 text-left text-xs font-medium uppercase tracking-wider text-gray-500">
                    <span className="sr-only">Actions</span>
                  </th>
                </tr>
              </thead>
              <tbody className="divide-y divide-gray-200 bg-white">
                {errors.length === 0 ? (
                  <tr>
                    <td colSpan={7} className="px-4 py-8 text-center text-sm text-gray-500">
                      No errors found
                    </td>
                  </tr>
                ) : (
                  errors.map((err) => (
                    <tr
                      key={err.id}
                      className={`hover:bg-gray-50 cursor-pointer ${SEVERITY_ROW_CLASS[err.severity]}`}
                      onClick={() => openDetail(err.id)}
                    >
                      <td className="whitespace-nowrap px-4 py-3 text-xs text-gray-600">
                        {formatTimestamp(err.timestamp)}
                      </td>
                      <td className="whitespace-nowrap px-4 py-3">
                        <Badge variant={SEVERITY_BADGE_VARIANT[err.severity]}>
                          {err.severity}
                        </Badge>
                      </td>
                      <td className="whitespace-nowrap px-4 py-3 text-sm text-gray-700">
                        {err.category}
                      </td>
                      <td className="whitespace-nowrap px-4 py-3 text-sm font-mono text-gray-700">
                        {err.module}
                      </td>
                      <td className="px-4 py-3 text-sm text-gray-900 max-w-xs truncate">
                        {err.message}
                      </td>
                      <td className="whitespace-nowrap px-4 py-3">
                        <Badge
                          variant={
                            err.status === 'Resolved'
                              ? 'success'
                              : err.status === 'Investigating'
                                ? 'warning'
                                : 'neutral'
                          }
                        >
                          {err.status}
                        </Badge>
                      </td>
                      <td className="whitespace-nowrap px-4 py-3">
                        <Button
                          variant="secondary"
                          size="sm"
                          onClick={(e) => {
                            e.stopPropagation()
                            openDetail(err.id)
                          }}
                        >
                          View
                        </Button>
                      </td>
                    </tr>
                  ))
                )}
              </tbody>
            </table>
          </div>
        </>
      )}

      {/* Detail modal */}
      <ErrorDetailModal
        error={selectedError}
        open={detailOpen}
        onClose={() => setDetailOpen(false)}
        onStatusChange={handleStatusChange}
        onNotesChange={fetchSummary}
      />
    </div>
  )
}
