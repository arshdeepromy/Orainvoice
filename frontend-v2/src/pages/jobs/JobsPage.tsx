/**
 * JobsPage — Task 26 port of frontend/src/pages/jobs/JobsPage.tsx.
 *
 * Active job-card list with live timers, status badges and role-based actions
 * (Confirm Job Done, Assign to Me, Take Over). ALL logic copied VERBATIM: the
 * fetch (GET /job-cards with status=open,in_progress unless "show all"), the
 * exported pure helpers `sortJobCards` + `filterActiveJobs` (kept for property
 * tests), Confirm-Done → complete + navigate-to-invoice (with 500 retry path),
 * Retry Invoice, Assign-to-Me, Take-Over dialog wiring, and the embedded
 * JobTimer per active card. Presentation remapped onto design tokens (FR-2b):
 * the prototype Jobs.html is a table; this card-list view preserves production's
 * richer per-card timer/actions and is styled in the same token language.
 *
 * Requirements: 5.x, 6.x, 8.x
 */

import { useState, useEffect, useCallback } from 'react'
import { useNavigate } from 'react-router-dom'
import apiClient from '@/api/client'
import { useAuth } from '@/contexts/AuthContext'
import { Button, Badge, Spinner, ToastContainer, useToast } from '@/components/ui'
import JobTimer from './JobTimer'
import TakeOverDialog from './TakeOverDialog'

/* ------------------------------------------------------------------ */
/*  Types                                                              */
/* ------------------------------------------------------------------ */

export interface JobCard {
  id: string
  customer_name: string | null
  vehicle_rego: string | null
  status: string
  description: string | null
  assigned_to: string | null
  assigned_to_name: string | null
  assigned_to_user_id: string | null
  created_at: string
}

interface JobCardListResponse {
  job_cards: JobCard[]
  total: number
  limit: number
  offset: number
}

/* ------------------------------------------------------------------ */
/*  Pure helpers (exported for property tests — Task 11.3)             */
/* ------------------------------------------------------------------ */

/**
 * Sort job cards: in_progress first, then open, each group by created_at
 * descending.
 *
 * **Validates: Requirements 5.3**
 */
export function sortJobCards(cards: JobCard[]): JobCard[] {
  return [...cards].sort((a, b) => {
    // in_progress (priority 0) before open (priority 1), everything else after
    const statusOrder = (s: string) => (s === 'in_progress' ? 0 : s === 'open' ? 1 : 2)
    const oa = statusOrder(a.status)
    const ob = statusOrder(b.status)
    if (oa !== ob) return oa - ob
    // Within same status group, sort by created_at descending
    return new Date(b.created_at).getTime() - new Date(a.created_at).getTime()
  })
}

/**
 * Filter job cards to only active statuses (open, in_progress).
 *
 * **Validates: Requirements 5.1, 5.4**
 */
export function filterActiveJobs(cards: JobCard[]): JobCard[] {
  return cards.filter((c) => c.status === 'open' || c.status === 'in_progress')
}

/* ------------------------------------------------------------------ */
/*  Status badge helper                                                */
/* ------------------------------------------------------------------ */

function statusBadge(status: string) {
  switch (status) {
    case 'in_progress':
      return <Badge variant="warn">In Progress</Badge>
    case 'open':
      return <Badge variant="info">Open</Badge>
    case 'completed':
      return <Badge variant="success">Completed</Badge>
    case 'invoiced':
      return <Badge variant="neutral">Invoiced</Badge>
    default:
      return <Badge variant="neutral">{status}</Badge>
  }
}

/* ------------------------------------------------------------------ */
/*  Component                                                          */
/* ------------------------------------------------------------------ */

export default function JobsPage() {
  const navigate = useNavigate()
  const { user, isOrgAdmin } = useAuth()
  const { toasts, addToast, dismissToast } = useToast()

  const [jobs, setJobs] = useState<JobCard[]>([])
  const [loading, setLoading] = useState(true)
  const [showAll, setShowAll] = useState(false)
  const [completingId, setCompletingId] = useState<string | null>(null)
  const [retryInvoiceId, setRetryInvoiceId] = useState<string | null>(null)
  const [assigningId, setAssigningId] = useState<string | null>(null)

  // TakeOverDialog state
  const [takeOverJobId, setTakeOverJobId] = useState<string | null>(null)

  /* ---- Fetch jobs ---- */
  const fetchJobs = useCallback(async () => {
    setLoading(true)
    try {
      const params: Record<string, string | number> = { limit: 100, offset: 0 }
      if (!showAll) {
        params.status = 'open,in_progress'
      }
      const res = await apiClient.get<JobCardListResponse>('/job-cards', { params })
      setJobs(res.data?.job_cards ?? [])
    } catch {
      addToast('error', 'Failed to load jobs.')
      setJobs([])
    } finally {
      setLoading(false)
    }
  }, [showAll, addToast])

  useEffect(() => {
    fetchJobs()
  }, [fetchJobs])

  /* ---- Confirm Job Done ---- */
  const handleConfirmDone = async (jobId: string) => {
    setCompletingId(jobId)
    setRetryInvoiceId(null)
    try {
      const res = await apiClient.post<{ job_card_id: string; invoice_id: string }>(
        `/job-cards/${jobId}/complete`,
      )
      addToast('success', 'Job completed and invoice created.')
      navigate(`/invoices/${res.data.invoice_id}`)
    } catch (err: unknown) {
      const detail =
        (err as { response?: { data?: { detail?: string }; status?: number } })
          ?.response?.data?.detail
      const status =
        (err as { response?: { status?: number } })?.response?.status

      if (status === 500) {
        // Invoice creation failed — job is now "completed" but no invoice
        setRetryInvoiceId(jobId)
        addToast('error', detail ?? 'Invoice creation failed. You can retry.')
        fetchJobs()
      } else {
        addToast('error', detail ?? 'Failed to complete job.')
      }
    } finally {
      setCompletingId(null)
    }
  }

  /* ---- Retry Invoice ---- */
  const handleRetryInvoice = async (jobId: string) => {
    setCompletingId(jobId)
    try {
      const res = await apiClient.post<{ job_card_id: string; invoice_id: string }>(
        `/job-cards/${jobId}/complete`,
      )
      setRetryInvoiceId(null)
      addToast('success', 'Invoice created successfully.')
      navigate(`/invoices/${res.data.invoice_id}`)
    } catch (err: unknown) {
      const detail =
        (err as { response?: { data?: { detail?: string } } })?.response?.data
          ?.detail
      addToast('error', detail ?? 'Invoice creation failed again.')
    } finally {
      setCompletingId(null)
    }
  }

  /* ---- Assign to Me ---- */
  const handleAssignToMe = async (jobId: string) => {
    if (!user) return
    setAssigningId(jobId)
    try {
      await apiClient.put(`/job-cards/${jobId}/assign`, {
        new_assignee_id: user.id,
      })
      addToast('success', 'Job assigned to you.')
      fetchJobs()
    } catch (err: unknown) {
      const detail =
        (err as { response?: { data?: { detail?: string } } })?.response?.data
          ?.detail
      addToast('error', detail ?? 'Failed to assign job.')
    } finally {
      setAssigningId(null)
    }
  }

  /* ---- Sorted + filtered display ---- */
  const displayJobs = sortJobCards(showAll ? jobs : filterActiveJobs(jobs))

  const currentUserId = user?.id ?? null

  return (
    <div className="page page-wide">
      {/* Header */}
      <div className="page-head">
        <div>
          <div className="eyebrow">Work</div>
          <h1>Jobs</h1>
        </div>
        <div className="head-actions">
          <label className="flex min-h-[44px] cursor-pointer items-center gap-2 text-[13px] text-text">
            <input
              type="checkbox"
              checked={showAll}
              onChange={(e) => setShowAll(e.target.checked)}
              className="h-4 w-4 rounded border-border text-accent focus:ring-accent"
            />
            Show all jobs
          </label>
        </div>
      </div>

      <div className="space-y-4">
        {loading && jobs.length === 0 ? (
          <div className="py-16">
            <Spinner label="Loading jobs" />
          </div>
        ) : displayJobs.length === 0 && !loading ? (
          <div className="py-16 text-center">
            <p className="text-muted">No jobs found.</p>
            <p className="mt-1 text-[13px] text-muted-2">
              {showAll
                ? 'There are no job cards yet.'
                : 'No active jobs. Toggle "Show all jobs" to see completed and invoiced jobs.'}
            </p>
          </div>
        ) : (
          <div className="space-y-4">
            {displayJobs.map((job) => {
              const isAssigned = job.assigned_to_user_id != null && currentUserId === job.assigned_to_user_id
              const canControl = isOrgAdmin || isAssigned
              const isReadOnly = !isOrgAdmin && !isAssigned && job.assigned_to != null

              return (
                <div
                  key={job.id}
                  className="rounded-card border border-border bg-card p-4 shadow-card"
                  data-testid={`job-card-${job.id}`}
                >
                  {/* Top row: info + status */}
                  <div className="mb-3 flex items-start justify-between gap-4">
                    <div className="min-w-0 flex-1">
                      <div className="mb-1 flex items-center gap-2">
                        <span className="truncate font-semibold text-text">
                          {job.customer_name ?? 'Unknown Customer'}
                        </span>
                        {statusBadge(job.status)}
                      </div>
                      {job.description && (
                        <p className="truncate text-[13px] text-muted">{job.description}</p>
                      )}
                      <div className="mt-1 flex flex-wrap gap-x-4 gap-y-1 text-[12px] text-muted-2">
                        {job.vehicle_rego && (
                          <span className="mono">Rego: {job.vehicle_rego}</span>
                        )}
                        <span>
                          Assigned: {job.assigned_to_name ?? 'Unassigned'}
                        </span>
                        <span>
                          Created: {new Date(job.created_at).toLocaleDateString()}
                        </span>
                      </div>
                    </div>
                  </div>

                  {/* Read-only message for non-admin viewing someone else's job */}
                  {isReadOnly && (
                    <div
                      className="mb-3 rounded-ctl bg-canvas p-2 text-[13px] text-muted"
                      data-testid="read-only-message"
                    >
                      This job is assigned to{' '}
                      <span className="font-medium">
                        {job.assigned_to_name ?? 'another staff member'}
                      </span>
                      .
                    </div>
                  )}

                  {/* Timer */}
                  {(job.status === 'open' || job.status === 'in_progress') && (
                    <div className="mb-3">
                      <JobTimer
                        jobCardId={job.id}
                        assignedTo={job.assigned_to}
                        assignedToName={job.assigned_to_name}
                        status={job.status as 'open' | 'in_progress'}
                        onStatusChange={fetchJobs}
                      />
                    </div>
                  )}

                  {/* Action buttons */}
                  <div className="flex flex-wrap items-center gap-2">
                    {/* Confirm Job Done — visible when in_progress and user can control */}
                    {job.status === 'in_progress' && canControl && (
                      <Button
                        size="sm"
                        variant="primary"
                        onClick={() => handleConfirmDone(job.id)}
                        loading={completingId === job.id}
                        disabled={completingId === job.id}
                        data-testid="confirm-done-btn"
                      >
                        Confirm Job Done
                      </Button>
                    )}

                    {/* Retry Invoice — shown after partial failure */}
                    {retryInvoiceId === job.id && (
                      <Button
                        size="sm"
                        variant="danger"
                        onClick={() => handleRetryInvoice(job.id)}
                        loading={completingId === job.id}
                        disabled={completingId === job.id}
                        data-testid="retry-invoice-btn"
                      >
                        Retry Invoice
                      </Button>
                    )}

                    {/* Non-admin, unassigned job: Assign to Me */}
                    {!isOrgAdmin && job.assigned_to == null && (
                      <Button
                        size="sm"
                        variant="ghost"
                        onClick={() => handleAssignToMe(job.id)}
                        loading={assigningId === job.id}
                        disabled={assigningId === job.id}
                        data-testid="assign-to-me-btn"
                      >
                        Assign to Me
                      </Button>
                    )}

                    {/* Non-admin, assigned to someone else: Take Over Job */}
                    {!isOrgAdmin &&
                      job.assigned_to != null &&
                      currentUserId !== job.assigned_to && (
                        <Button
                          size="sm"
                          variant="ghost"
                          onClick={() => setTakeOverJobId(job.id)}
                          data-testid="take-over-btn"
                        >
                          Take Over Job
                        </Button>
                      )}
                  </div>
                </div>
              )
            })}
          </div>
        )}
      </div>

      {/* TakeOverDialog */}
      {takeOverJobId && (
        <TakeOverDialog
          jobCardId={takeOverJobId}
          isOpen={true}
          onClose={() => setTakeOverJobId(null)}
          onSuccess={() => {
            setTakeOverJobId(null)
            fetchJobs()
          }}
        />
      )}

      <ToastContainer toasts={toasts} onDismiss={dismissToast} />
    </div>
  )
}
