import { useState, useEffect, useCallback } from 'react'
import Button from '@/components/ui/Button'
import Badge from '@/components/ui/Badge'
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
  org_name?: string | null
  user_email?: string | null
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

const SEVERITY_BADGE_VARIANT: Record<Severity, 'info' | 'warn' | 'danger'> = {
  Info: 'info',
  Warning: 'warn',
  Error: 'danger',
  Critical: 'danger',
}

const SEVERITY_ROW_CLASS: Record<Severity, string> = {
  Info: 'border-l-4 border-l-accent/60 bg-accent-soft/40',
  Warning: 'border-l-4 border-l-warn/60 bg-warn-soft/40',
  Error: 'border-l-4 border-l-danger/60 bg-danger-soft/40',
  Critical: 'border-l-4 border-l-danger bg-danger-soft/60',
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
    Critical: 'border-l-danger bg-danger-soft',
    Error: 'border-l-danger/60 bg-danger-soft',
    Warning: 'border-l-warn/60 bg-warn-soft',
    Info: 'border-l-accent/60 bg-accent-soft',
  }

  return (
    <div className="grid grid-cols-2 md:grid-cols-4 gap-4 mb-6" role="region" aria-label="Error count summary">
      {ordered.map((s) => (
        <div key={s.severity} className={`rounded-card border-l-4 p-4 shadow-card ${cardColour[s.severity]}`}>
          <h3 className="text-sm font-medium text-muted">{s.severity}</h3>
          <div className="mt-2 grid grid-cols-3 gap-2 text-center">
            <div>
              <p className="mono text-lg font-bold text-text">{s.last_hour}</p>
              <p className="text-xs text-muted">1h</p>
            </div>
            <div>
              <p className="mono text-lg font-bold text-text">{s.last_24h}</p>
              <p className="text-xs text-muted">24h</p>
            </div>
            <div>
              <p className="mono text-lg font-bold text-text">{s.last_7d}</p>
              <p className="text-xs text-muted">7d</p>
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
          <span className="text-sm text-muted">{formatTimestamp(error.timestamp)}</span>
        </div>

        {/* Error ID */}
        <div>
          <h4 className="text-xs font-medium text-muted uppercase">Error ID</h4>
          <p className="mono text-sm text-text">{error.id}</p>
        </div>

        {/* Message */}
        <div>
          <h4 className="text-xs font-medium text-muted uppercase">Message</h4>
          <p className="text-sm text-text">{error.message}</p>
        </div>

        {/* Module / Function */}
        <div className="grid grid-cols-2 gap-4">
          <div>
            <h4 className="text-xs font-medium text-muted uppercase">Module</h4>
            <p className="text-sm text-text">{error.module}</p>
          </div>
          <div>
            <h4 className="text-xs font-medium text-muted uppercase">Function</h4>
            <p className="text-sm text-text">{error.function_name}</p>
          </div>
        </div>

        {/* Context */}
        {(error.org_id || error.user_id) && (
          <div className="grid grid-cols-2 gap-4">
            {error.org_id && (
              <div>
                <h4 className="text-xs font-medium text-muted uppercase">Organisation</h4>
                <p className="text-sm text-text">{error.org_name || error.org_id}</p>
              </div>
            )}
            {error.user_id && (
              <div>
                <h4 className="text-xs font-medium text-muted uppercase">User</h4>
                <p className="text-sm text-text">{error.user_email || error.user_id}</p>
              </div>
            )}
          </div>
        )}

        {/* HTTP details */}
        {error.http_method && (
          <div>
            <h4 className="text-xs font-medium text-muted uppercase">Request</h4>
            <p className="mono text-sm text-text">
              {error.http_method} {error.http_endpoint}
            </p>
          </div>
        )}

        {error.request_body && (
          <div>
            <h4 className="text-xs font-medium text-muted uppercase">Request Body</h4>
            <pre className="mono mt-1 max-h-32 overflow-auto rounded bg-canvas p-3 text-xs text-text">
              {error.request_body}
            </pre>
          </div>
        )}

        {error.response_body && (
          <div>
            <h4 className="text-xs font-medium text-muted uppercase">Response Body</h4>
            <pre className="mono mt-1 max-h-32 overflow-auto rounded bg-canvas p-3 text-xs text-text">
              {error.response_body}
            </pre>
          </div>
        )}

        {/* Stack trace */}
        <div>
          <h4 className="text-xs font-medium text-muted uppercase">Stack Trace</h4>
          <pre className="mono mt-1 max-h-48 overflow-auto rounded bg-ink p-3 text-xs text-ok-soft whitespace-pre-wrap">
            {error.stack_trace}
          </pre>
        </div>

        {/* Status management */}
        <div className="border-t border-border pt-4 space-y-3">
          <Select
            label="Status"
            options={STATUS_OPTIONS}
            value={status}
            onChange={(e) => setStatus(e.target.value as ErrorStatus)}
          />
          <div className="flex flex-col gap-1">
            <label htmlFor="error-notes" className="text-[12.5px] font-medium text-text">
              Notes
            </label>
            <textarea
              id="error-notes"
              className="rounded-ctl border border-border bg-card px-3 py-2 text-sm text-text
                focus:outline-none focus:border-accent focus:shadow-[0_0_0_3px_var(--accent-soft)]"
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
            <Button variant="ghost" onClick={onClose}>
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
  const fetchSummary = useCallback(async (signal?: AbortSignal) => {
    setSummaryLoading(true)
    try {
      const res = await apiClient.get<{
        by_severity: Array<{ label: string; count_1h: number; count_24h: number; count_7d: number }>
      }>('/admin/errors/dashboard', { signal })
      const mapped: ErrorSummary[] = (res.data?.by_severity ?? []).map((s) => ({
        severity: (s.label.charAt(0).toUpperCase() + s.label.slice(1)) as Severity,
        last_hour: s.count_1h,
        last_24h: s.count_24h,
        last_7d: s.count_7d,
      }))
      setSummaries(mapped)
    } catch {
      // Summary failure is non-blocking
    } finally {
      if (!signal?.aborted) setSummaryLoading(false)
    }
  }, [])

  /* ── Fetch error list ── */
  const fetchErrors = useCallback(async (signal?: AbortSignal) => {
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
      }>('/admin/errors', { params, signal })
      const mapped: ErrorRecord[] = (res.data?.errors ?? []).map((e) => ({
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
      setTotal(res.data?.total ?? 0)

      // Check for critical errors in the last hour for push notification
      // Backend returns lowercase severity values
      const criticals = (res.data?.errors ?? []).filter(
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
      if (signal?.aborted) return
      setListError(true)
    } finally {
      if (!signal?.aborted) setListLoading(false)
    }
  }, [search, severityFilter, categoryFilter])

  useEffect(() => {
    const controller = new AbortController()
    fetchSummary(controller.signal)
    fetchErrors(controller.signal)
    return () => controller.abort()
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
        org_name: e.org_name ?? null,
        user_email: e.user_email ?? null,
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
      <h1 className="text-2xl font-semibold text-text mb-6">Error Log</h1>
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
          <p className="text-sm text-muted mb-2">{total} error{total !== 1 ? 's' : ''} found</p>
          <div className="overflow-x-auto rounded-card border border-border bg-card shadow-card">
            <table className="min-w-full" role="grid" aria-label="Error log feed">
              <thead>
                <tr>
                  <th scope="col" className="mono border-b border-border px-4 py-3 text-left text-[10.5px] font-medium uppercase tracking-[0.08em] text-muted-2">
                    Time
                  </th>
                  <th scope="col" className="mono border-b border-border px-4 py-3 text-left text-[10.5px] font-medium uppercase tracking-[0.08em] text-muted-2">
                    Severity
                  </th>
                  <th scope="col" className="mono border-b border-border px-4 py-3 text-left text-[10.5px] font-medium uppercase tracking-[0.08em] text-muted-2">
                    Category
                  </th>
                  <th scope="col" className="mono border-b border-border px-4 py-3 text-left text-[10.5px] font-medium uppercase tracking-[0.08em] text-muted-2">
                    Module
                  </th>
                  <th scope="col" className="mono border-b border-border px-4 py-3 text-left text-[10.5px] font-medium uppercase tracking-[0.08em] text-muted-2">
                    Message
                  </th>
                  <th scope="col" className="mono border-b border-border px-4 py-3 text-left text-[10.5px] font-medium uppercase tracking-[0.08em] text-muted-2">
                    Status
                  </th>
                  <th scope="col" className="mono border-b border-border px-4 py-3 text-left text-[10.5px] font-medium uppercase tracking-[0.08em] text-muted-2">
                    <span className="sr-only">Actions</span>
                  </th>
                </tr>
              </thead>
              <tbody>
                {errors.length === 0 ? (
                  <tr>
                    <td colSpan={7} className="px-4 py-8 text-center text-sm text-muted">
                      No errors found
                    </td>
                  </tr>
                ) : (
                  errors.map((err) => (
                    <tr
                      key={err.id}
                      className={`border-b border-border last:border-b-0 hover:bg-canvas cursor-pointer ${SEVERITY_ROW_CLASS[err.severity]}`}
                      onClick={() => openDetail(err.id)}
                    >
                      <td className="mono whitespace-nowrap px-4 py-3 text-xs text-muted">
                        {formatTimestamp(err.timestamp)}
                      </td>
                      <td className="whitespace-nowrap px-4 py-3">
                        <Badge variant={SEVERITY_BADGE_VARIANT[err.severity]}>
                          {err.severity}
                        </Badge>
                      </td>
                      <td className="whitespace-nowrap px-4 py-3 text-sm text-text">
                        {err.category}
                      </td>
                      <td className="mono whitespace-nowrap px-4 py-3 text-sm text-text">
                        {err.module}
                      </td>
                      <td className="px-4 py-3 text-sm text-text max-w-xs truncate">
                        {err.message}
                      </td>
                      <td className="whitespace-nowrap px-4 py-3">
                        <Badge
                          variant={
                            err.status === 'Resolved'
                              ? 'success'
                              : err.status === 'Investigating'
                                ? 'warn'
                                : 'neutral'
                          }
                        >
                          {err.status}
                        </Badge>
                      </td>
                      <td className="whitespace-nowrap px-4 py-3">
                        <Button
                          variant="ghost"
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
