import { useState, useEffect, useRef, useCallback } from 'react'
import apiClient from '../../api/client'
import { Button, Input, Select, Badge, Spinner, Pagination, useToast, ToastContainer } from '../../components/ui'
import StaffPicker from '../../components/StaffPicker'
import { useTenant } from '../../contexts/TenantContext'

/* ------------------------------------------------------------------ */
/*  Types                                                              */
/* ------------------------------------------------------------------ */

type JobCardStatus = 'open' | 'in_progress' | 'completed' | 'invoiced'

interface JobCardSummary {
  id: string
  job_card_number: string | null
  customer_name: string
  customer_id: string
  vehicle_rego: string | null
  rego: string
  status: JobCardStatus
  description: string
  assigned_to: string | null
  assigned_to_name: string | null
  created_at: string
  updated_at: string
}

interface JobCardListResponse {
  items: JobCardSummary[]
  job_cards?: JobCardSummary[]
  total: number
  page: number
  page_size: number
  total_pages: number
  limit?: number
  offset?: number
}

type BadgeVariant = 'success' | 'warning' | 'error' | 'info' | 'neutral'

/* ------------------------------------------------------------------ */
/*  Helpers                                                            */
/* ------------------------------------------------------------------ */

function formatDate(dateStr: string | null): string {
  if (!dateStr) return '—'
  return new Intl.DateTimeFormat('en-NZ', { day: '2-digit', month: '2-digit', year: 'numeric' }).format(new Date(dateStr))
}

function formatTimer(seconds: number): string {
  const h = Math.floor(seconds / 3600)
  const m = Math.floor((seconds % 3600) / 60)
  const s = seconds % 60
  if (h > 0) return `${h}:${String(m).padStart(2, '0')}:${String(s).padStart(2, '0')}`
  return `${m}:${String(s).padStart(2, '0')}`
}

const STATUS_CONFIG: Record<JobCardStatus, { label: string; variant: BadgeVariant }> = {
  open: { label: 'Open', variant: 'info' },
  in_progress: { label: 'In Progress', variant: 'warning' },
  completed: { label: 'Completed', variant: 'success' },
  invoiced: { label: 'Invoiced', variant: 'neutral' },
}

const STATUS_OPTIONS = [
  { value: '', label: 'All statuses' },
  { value: 'open', label: 'Open' },
  { value: 'in_progress', label: 'In Progress' },
  { value: 'completed', label: 'Completed' },
  { value: 'invoiced', label: 'Invoiced' },
]

const PAGE_SIZE = 20

/* ------------------------------------------------------------------ */
/*  Inline timer hook — ticks every second for a running job           */
/* ------------------------------------------------------------------ */

function useRowTimer(jobId: string, isRunning: boolean, startedAt: string | null): number {
  const [elapsed, setElapsed] = useState(0)
  const intervalRef = useRef<ReturnType<typeof setInterval>>()

  useEffect(() => {
    if (intervalRef.current) clearInterval(intervalRef.current)
    if (!isRunning || !startedAt) { setElapsed(0); return }

    const start = new Date(startedAt).getTime()
    const tick = () => setElapsed(Math.floor((Date.now() - start) / 1000))
    tick()
    intervalRef.current = setInterval(tick, 1000)
    return () => { if (intervalRef.current) clearInterval(intervalRef.current) }
  }, [jobId, isRunning, startedAt])

  return elapsed
}

/* ------------------------------------------------------------------ */
/*  Inline timer cell component                                        */
/* ------------------------------------------------------------------ */

function TimerCell({ jobId, isActive, startedAt }: { jobId: string; isActive: boolean; startedAt: string | null }) {
  const elapsed = useRowTimer(jobId, isActive, startedAt)
  if (!isActive) return null
  return (
    <span className="inline-flex items-center gap-1.5 text-xs font-medium text-red-600 tabular-nums">
      <span className="h-1.5 w-1.5 rounded-full bg-red-500 animate-pulse" />
      {formatTimer(elapsed)}
    </span>
  )
}

/* ------------------------------------------------------------------ */
/*  Inline assignee editor                                             */
/* ------------------------------------------------------------------ */

function AssigneeCell({
  jobId,
  assignedTo,
  assignedToName,
  status,
  onUpdated,
}: {
  jobId: string
  assignedTo: string | null
  assignedToName: string | null
  status: JobCardStatus
  onUpdated: () => void
}) {
  const [editing, setEditing] = useState(false)
  const [saving, setSaving] = useState(false)
  const { addToast } = useToast()

  // Only allow editing for open/in_progress jobs
  const editable = status === 'open' || status === 'in_progress'

  const handleChange = async (staffId: string) => {
    if (!staffId || staffId === assignedTo) { setEditing(false); return }
    setSaving(true)
    try {
      await apiClient.put(`/job-cards/${jobId}/assign`, { new_assignee_id: staffId })
      setEditing(false)
      onUpdated()
    } catch (err: unknown) {
      const detail = (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail
      addToast('error', detail ?? 'Failed to reassign.')
    } finally {
      setSaving(false)
    }
  }

  if (editing) {
    return (
      <div className="min-w-[160px]" onClick={(e) => e.stopPropagation()}>
        <StaffPicker value={assignedTo} onChange={handleChange} disabled={saving} />
        <button
          className="mt-1 text-xs text-gray-500 hover:text-gray-700"
          onClick={(e) => { e.stopPropagation(); setEditing(false) }}
        >
          Cancel
        </button>
      </div>
    )
  }

  return (
    <span
      className={`${editable ? 'cursor-pointer hover:text-blue-600 hover:underline' : ''}`}
      onClick={(e) => {
        if (!editable) return
        e.stopPropagation()
        setEditing(true)
      }}
      title={editable ? 'Click to change assignee' : undefined}
    >
      {assignedToName || '—'}
    </span>
  )
}

/* ------------------------------------------------------------------ */
/*  Main component                                                     */
/* ------------------------------------------------------------------ */

export default function JobCardList() {
  const { tradeFamily } = useTenant()
  const isAutomotive = (tradeFamily ?? 'automotive-transport') === 'automotive-transport'

  const [searchQuery, setSearchQuery] = useState('')
  const [statusFilter, setStatusFilter] = useState('')
  const [page, setPage] = useState(1)

  const [data, setData] = useState<JobCardListResponse | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')

  // Track which jobs have active timers (jobId → startedAt)
  const [activeTimers, setActiveTimers] = useState<Record<string, string>>({})
  const [actionLoading, setActionLoading] = useState<string | null>(null)

  const { toasts, addToast, dismissToast } = useToast()
  const debounceRef = useRef<ReturnType<typeof setTimeout>>()
  const abortRef = useRef<AbortController>()

  const fetchJobCards = useCallback(async (search: string, status: string, pg: number) => {
    if (abortRef.current) abortRef.current.abort()
    const controller = new AbortController()
    abortRef.current = controller

    setLoading(true)
    setError('')
    try {
      const params: Record<string, string | number> = { limit: PAGE_SIZE, offset: (pg - 1) * PAGE_SIZE }
      if (search.trim()) params.search = search.trim()
      if (status) params.status = status

      const res = await apiClient.get<JobCardListResponse>('/job-cards', {
        params,
        signal: controller.signal,
      })
      const raw = res.data
      const items = raw.items ?? raw.job_cards ?? []
      const total = raw.total ?? 0
      const pageSize = raw.page_size ?? raw.limit ?? PAGE_SIZE
      const totalPages = raw.total_pages ?? (Math.ceil(total / pageSize) || 1)
      setData({ items, total, page: pg, page_size: pageSize, total_pages: totalPages })

      // Fetch timer status for open/in_progress jobs
      const activeJobs = items.filter((j: JobCardSummary) => j.status === 'open' || j.status === 'in_progress')
      const timers: Record<string, string> = {}
      await Promise.all(
        activeJobs.map(async (j: JobCardSummary) => {
          try {
            const timerRes = await apiClient.get(`/job-cards/${j.id}/timer`)
            const timerData = timerRes.data as { entries: Array<{ started_at: string; stopped_at: string | null }>; is_active: boolean }
            if (timerData.is_active) {
              const active = timerData.entries.find((e) => !e.stopped_at)
              if (active) timers[j.id] = active.started_at
            }
          } catch { /* ignore timer fetch errors */ }
        }),
      )
      setActiveTimers(timers)
    } catch (err: unknown) {
      if ((err as { name?: string })?.name === 'CanceledError') return
      setError('Failed to load job cards. Please try again.')
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    if (debounceRef.current) clearTimeout(debounceRef.current)
    debounceRef.current = setTimeout(() => {
      setPage(1)
      fetchJobCards(searchQuery, statusFilter, 1)
    }, 300)
    return () => { if (debounceRef.current) clearTimeout(debounceRef.current) }
  }, [searchQuery, statusFilter, fetchJobCards])

  useEffect(() => {
    fetchJobCards(searchQuery, statusFilter, page)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [page])

  const refetch = () => fetchJobCards(searchQuery, statusFilter, page)

  /* ---- Start Job (start timer) ---- */
  const handleStartJob = async (jobId: string) => {
    setActionLoading(jobId)
    try {
      const res = await apiClient.post(`/job-cards/${jobId}/timer/start`)
      const entry = res.data as { started_at: string }
      setActiveTimers((prev) => ({ ...prev, [jobId]: entry.started_at }))
      // Update status in local state to in_progress
      setData((prev) => {
        if (!prev) return prev
        return {
          ...prev,
          items: prev.items.map((j) =>
            j.id === jobId ? { ...j, status: 'in_progress' as JobCardStatus } : j,
          ),
        }
      })
      addToast('success', 'Job started — timer running.')
    } catch (err: unknown) {
      const detail = (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail
      addToast('error', detail ?? 'Failed to start job.')
    } finally {
      setActionLoading(null)
    }
  }

  /* ---- Stop timer ---- */
  const handleStopTimer = async (jobId: string) => {
    setActionLoading(jobId)
    try {
      await apiClient.post(`/job-cards/${jobId}/timer/stop`)
      setActiveTimers((prev) => {
        const next = { ...prev }
        delete next[jobId]
        return next
      })
      addToast('success', 'Timer stopped.')
    } catch (err: unknown) {
      const detail = (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail
      addToast('error', detail ?? 'Failed to stop timer.')
    } finally {
      setActionLoading(null)
    }
  }

  /* ---- Cancel Job ---- */
  const handleCancelJob = async (jobId: string) => {
    if (!window.confirm('Cancel this job card? This will delete it.')) return
    setActionLoading(jobId)
    try {
      await apiClient.delete(`/job-cards/${jobId}`)
      addToast('success', 'Job card cancelled.')
      refetch()
    } catch (err: unknown) {
      const detail = (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail
      // If no delete endpoint, complete the job (stops timer + creates invoice)
      if ((err as { response?: { status?: number } })?.response?.status === 405) {
        try {
          await apiClient.post(`/job-cards/${jobId}/complete`)
          addToast('success', 'Job completed and invoice created.')
          refetch()
        } catch {
          addToast('error', 'Failed to complete job.')
        }
      } else {
        addToast('error', detail ?? 'Failed to cancel job.')
      }
    } finally {
      setActionLoading(null)
    }
  }

  const hasFilters = searchQuery || statusFilter
  const clearFilters = () => {
    setSearchQuery('')
    setStatusFilter('')
    setPage(1)
  }

  return (
    <div className="px-4 py-6 sm:px-6 lg:px-8">
      {/* Header */}
      <div className="flex flex-col gap-4 sm:flex-row sm:items-center sm:justify-between mb-6">
        <h1 className="text-2xl font-semibold text-gray-900">Job Cards</h1>
        <Button onClick={() => { window.location.href = '/job-cards/new' }}>
          + New Job Card
        </Button>
      </div>

      {/* Search & Filters */}
      <div className="mb-4 space-y-3">
        <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-3">
          <Input
            label="Search"
            placeholder="Customer name, rego, description…"
            value={searchQuery}
            onChange={(e) => setSearchQuery(e.target.value)}
            aria-label="Search job cards"
          />
          <Select
            label="Status"
            options={STATUS_OPTIONS}
            value={statusFilter}
            onChange={(e) => setStatusFilter(e.target.value)}
          />
        </div>

        {hasFilters && (
          <div className="flex items-center gap-2">
            <span className="text-sm text-gray-500">
              {data ? `${data.total} result${data.total !== 1 ? 's' : ''}` : 'Filtering…'}
            </span>
            <button
              onClick={clearFilters}
              className="text-sm text-blue-600 hover:text-blue-800 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-blue-500 rounded"
            >
              Clear filters
            </button>
          </div>
        )}
      </div>

      {/* Error */}
      {error && (
        <div className="mb-4 rounded-md border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700" role="alert">
          {error}
        </div>
      )}

      {/* Loading */}
      {loading && !data && (
        <div className="py-16">
          <Spinner label="Loading job cards" />
        </div>
      )}

      {/* Table */}
      {data && (
        <>
          <div className="overflow-x-auto rounded-lg border border-gray-200">
            <table className="min-w-full divide-y divide-gray-200" role="grid">
              <caption className="sr-only">Job card list</caption>
              <thead className="bg-gray-50">
                <tr>
                  <th scope="col" className="px-4 py-3 text-left text-xs font-medium uppercase tracking-wider text-gray-500">Customer</th>
                  {isAutomotive && <th scope="col" className="px-4 py-3 text-left text-xs font-medium uppercase tracking-wider text-gray-500">Rego</th>}
                  <th scope="col" className="px-4 py-3 text-left text-xs font-medium uppercase tracking-wider text-gray-500">Description</th>
                  <th scope="col" className="px-4 py-3 text-left text-xs font-medium uppercase tracking-wider text-gray-500">Assigned To</th>
                  <th scope="col" className="px-4 py-3 text-left text-xs font-medium uppercase tracking-wider text-gray-500">Status</th>
                  <th scope="col" className="px-4 py-3 text-left text-xs font-medium uppercase tracking-wider text-gray-500">Created</th>
                  <th scope="col" className="px-4 py-3 text-left text-xs font-medium uppercase tracking-wider text-gray-500">Actions</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-gray-200 bg-white">
                {data.items.length === 0 ? (
                  <tr>
                    <td colSpan={isAutomotive ? 7 : 6} className="px-4 py-12 text-center text-sm text-gray-500">
                      {hasFilters ? 'No job cards match your filters.' : 'No job cards yet. Create your first job card to get started.'}
                    </td>
                  </tr>
                ) : (
                  data.items.map((jc) => {
                    const cfg = STATUS_CONFIG[jc.status] ?? STATUS_CONFIG.open
                    const rego = jc.vehicle_rego || jc.rego
                    const isActive = jc.status === 'open' || jc.status === 'in_progress'
                    const timerRunning = !!activeTimers[jc.id]
                    const isLoading = actionLoading === jc.id

                    return (
                      <tr
                        key={jc.id}
                        className="hover:bg-gray-50 cursor-pointer"
                        onClick={() => { window.location.href = `/job-cards/${jc.id}` }}
                      >
                        <td className="whitespace-nowrap px-4 py-3 text-sm text-gray-900">{jc.customer_name}</td>
                        {isAutomotive && <td className="whitespace-nowrap px-4 py-3 text-sm text-gray-700 font-mono">{rego || '—'}</td>}
                        <td className="px-4 py-3 text-sm text-gray-700 max-w-xs truncate">{jc.description || '—'}</td>
                        <td className="whitespace-nowrap px-4 py-3 text-sm text-gray-700">
                          <AssigneeCell
                            jobId={jc.id}
                            assignedTo={jc.assigned_to}
                            assignedToName={jc.assigned_to_name}
                            status={jc.status}
                            onUpdated={refetch}
                          />
                        </td>
                        <td className="whitespace-nowrap px-4 py-3 text-sm">
                          <div className="flex items-center gap-2">
                            <Badge variant={cfg.variant}>{cfg.label}</Badge>
                            <TimerCell jobId={jc.id} isActive={timerRunning} startedAt={activeTimers[jc.id] ?? null} />
                          </div>
                        </td>
                        <td className="whitespace-nowrap px-4 py-3 text-sm text-gray-700">{formatDate(jc.created_at)}</td>
                        <td className="whitespace-nowrap px-4 py-3 text-sm" onClick={(e) => e.stopPropagation()}>
                          <div className="flex items-center gap-1.5">
                            {/* Start Job / Stop Timer */}
                            {isActive && !timerRunning && (
                              <Button
                                size="sm"
                                variant="primary"
                                onClick={() => handleStartJob(jc.id)}
                                loading={isLoading}
                                disabled={isLoading}
                              >
                                Start
                              </Button>
                            )}
                            {timerRunning && (
                              <Button
                                size="sm"
                                variant="danger"
                                onClick={() => handleStopTimer(jc.id)}
                                loading={isLoading}
                                disabled={isLoading}
                              >
                                Stop
                              </Button>
                            )}
                            {/* Cancel */}
                            {isActive && (
                              <Button
                                size="sm"
                                variant="secondary"
                                onClick={() => handleCancelJob(jc.id)}
                                loading={isLoading}
                                disabled={isLoading}
                              >
                                Cancel
                              </Button>
                            )}
                          </div>
                        </td>
                      </tr>
                    )
                  })
                )}
              </tbody>
            </table>
          </div>

          {data.total_pages > 1 && (
            <div className="mt-4 flex items-center justify-between">
              <p className="text-sm text-gray-500">
                Showing {(page - 1) * PAGE_SIZE + 1}–{Math.min(page * PAGE_SIZE, data.total)} of {data.total}
              </p>
              <Pagination currentPage={page} totalPages={data.total_pages} onPageChange={setPage} />
            </div>
          )}
        </>
      )}

      <ToastContainer toasts={toasts} onDismiss={dismissToast} />
    </div>
  )
}
