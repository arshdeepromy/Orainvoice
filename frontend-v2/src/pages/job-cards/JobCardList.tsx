/**
 * JobCardList — Task 27 port of frontend/src/pages/job-cards/JobCardList.tsx.
 *
 * ALL logic copied VERBATIM: the paginated/searchable/status-filtered fetch
 * (GET /job-cards limit/offset, with response-shape normalisation), per-row
 * live timers (fetched per open/in-progress card via GET /job-cards/:id/timer),
 * the inline AssigneeCell (StaffPicker reassign), Start/Stop timer + Cancel
 * (with 405 → complete fallback) actions, and debounced search. Safe-API
 * consumption preserved. Presentation remapped onto the design tokens (FR-2b):
 * `page page-wide` head, token toolbar inputs, a card-wrapped token table with
 * Badge status pills, ds.css pagination. `warning`→`warn`, `secondary`→`ghost`.
 */

import { useState, useEffect, useRef, useCallback } from 'react'
import apiClient from '@/api/client'
import { Button, Input, Select, Badge, Spinner, Pagination, useToast, ToastContainer } from '@/components/ui'
import type { BadgeVariant } from '@/components/ui'
import StaffPicker from '@/components/StaffPicker'
import { useTenant } from '@/contexts/TenantContext'
import { useBranch } from '@/contexts/BranchContext'

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
  branch_id?: string | null
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
  in_progress: { label: 'In Progress', variant: 'warn' },
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
  const intervalRef = useRef<ReturnType<typeof setInterval>>(undefined)

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
    <span className="mono inline-flex items-center gap-1.5 text-[12px] font-medium text-danger">
      <span className="h-1.5 w-1.5 animate-pulse rounded-full bg-danger" />
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
          className="mt-1 text-[12px] text-muted hover:text-text"
          onClick={(e) => { e.stopPropagation(); setEditing(false) }}
        >
          Cancel
        </button>
      </div>
    )
  }

  return (
    <span
      className={`${editable ? 'cursor-pointer hover:text-accent hover:underline' : ''}`}
      onClick={(e) => {
        if (!editable) return
        e.stopPropagation()
        setEditing(true)
      }}
      title={editable ? 'Click to change assignee' : undefined}
    >
      {assignedToName ? (
        assignedToName
      ) : editable ? (
        <span className="inline-flex items-center gap-1 text-[13.5px] font-medium text-accent">
          <svg className="h-4 w-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2} aria-hidden="true">
            <path strokeLinecap="round" strokeLinejoin="round" d="M12 4.5v15m7.5-7.5h-15" />
          </svg>
          Assign
        </span>
      ) : (
        <span className="text-muted-2">Unassigned</span>
      )}
    </span>
  )
}

/* ------------------------------------------------------------------ */
/*  Main component                                                     */
/* ------------------------------------------------------------------ */

export default function JobCardList() {
  const { tradeFamily } = useTenant()
  const { branches: branchList } = useBranch()
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
  const debounceRef = useRef<ReturnType<typeof setTimeout>>(undefined)
  const abortRef = useRef<AbortController>(undefined)

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

  const TH = 'mono border-b border-border px-4 py-3 text-left text-[10.5px] font-medium uppercase tracking-[0.08em] text-muted-2'

  return (
    <div className="page page-wide">
      {/* Header */}
      <div className="page-head">
        <div>
          <div className="eyebrow">Work</div>
          <h1>Job Cards</h1>
        </div>
        <div className="head-actions">
          <Button
            leftIcon={
              <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={2.2}>
                <path strokeLinecap="round" strokeLinejoin="round" d="M12 5v14M5 12h14" />
              </svg>
            }
            onClick={() => { window.location.href = '/job-cards/new' }}
          >
            New Job Card
          </Button>
        </div>
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
            <span className="text-[13px] text-muted">
              {data ? `${data.total} result${data.total !== 1 ? 's' : ''}` : 'Filtering…'}
            </span>
            <button
              onClick={clearFilters}
              className="rounded text-[13px] text-accent hover:text-accent-press focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent"
            >
              Clear filters
            </button>
          </div>
        )}
      </div>

      {/* Error */}
      {error && (
        <div className="mb-4 rounded-ctl border border-danger/30 bg-danger-soft px-4 py-3 text-[13px] text-danger" role="alert">
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
          <section className="overflow-hidden rounded-card border border-border bg-card shadow-card">
            <div className="overflow-x-auto">
              <table className="w-full border-collapse" role="grid">
                <caption className="sr-only">Job card list</caption>
                <thead>
                  <tr>
                    <th scope="col" className={TH}>Customer</th>
                    {isAutomotive && <th scope="col" className={TH}>Rego</th>}
                    <th scope="col" className={TH}>Branch</th>
                    <th scope="col" className={TH}>Description</th>
                    <th scope="col" className={TH}>Assigned To</th>
                    <th scope="col" className={TH}>Status</th>
                    <th scope="col" className={TH}>Created</th>
                    <th scope="col" className={TH}>Actions</th>
                  </tr>
                </thead>
                <tbody>
                  {data.items.length === 0 ? (
                    <tr>
                      <td colSpan={isAutomotive ? 8 : 7} className="px-4 py-12 text-center text-[13px] text-muted">
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
                          className="cursor-pointer border-b border-border transition-colors last:border-b-0 hover:bg-canvas"
                          onClick={() => { window.location.href = `/job-cards/${jc.id}` }}
                        >
                          <td className="whitespace-nowrap px-4 py-3 text-[13.5px] text-text">{jc.customer_name}</td>
                          {isAutomotive && <td className="mono whitespace-nowrap px-4 py-3 text-[13.5px] text-muted">{rego || '—'}</td>}
                          <td className="whitespace-nowrap px-4 py-3 text-[13.5px] text-muted">
                            {jc.branch_id ? ((branchList ?? []).find(b => b.id === jc.branch_id)?.name ?? '—') : '—'}
                          </td>
                          <td className="max-w-xs truncate px-4 py-3 text-[13.5px] text-muted">{jc.description || '—'}</td>
                          <td className="whitespace-nowrap px-4 py-3 text-[13.5px] text-text">
                            <AssigneeCell
                              jobId={jc.id}
                              assignedTo={jc.assigned_to}
                              assignedToName={jc.assigned_to_name}
                              status={jc.status}
                              onUpdated={refetch}
                            />
                          </td>
                          <td className="whitespace-nowrap px-4 py-3 text-[13px]">
                            <div className="flex items-center gap-2">
                              <Badge variant={cfg.variant}>{cfg.label}</Badge>
                              <TimerCell jobId={jc.id} isActive={timerRunning} startedAt={activeTimers[jc.id] ?? null} />
                            </div>
                          </td>
                          <td className="mono whitespace-nowrap px-4 py-3 text-[13px] text-muted">{formatDate(jc.created_at)}</td>
                          <td className="whitespace-nowrap px-4 py-3 text-[13px]" onClick={(e) => e.stopPropagation()}>
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
                                  variant="ghost"
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
          </section>

          {data.total_pages > 1 && (
            <div className="mt-4 flex items-center justify-between">
              <p className="text-[12.5px] text-muted">
                Showing <span className="mono text-text">{(page - 1) * PAGE_SIZE + 1}–{Math.min(page * PAGE_SIZE, data.total)}</span> of <span className="mono text-text">{data.total}</span>
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
