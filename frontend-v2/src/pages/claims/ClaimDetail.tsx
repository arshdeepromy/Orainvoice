/**
 * Claim Detail page — full claim view with status actions, timeline, and resolution.
 *
 * Requirements: 2.1-2.5, 3.1-3.7, 7.1-7.5
 */

import { useState } from 'react'
import { useParams, useNavigate, Link } from 'react-router-dom'
import { Badge, Button, Spinner } from '@/components/ui'
import type { BadgeVariant } from '@/components/ui'
import { ClaimResolveModal } from '@/components/claims/ClaimResolveModal'
import { ClaimNoteModal } from '@/components/claims/ClaimNoteModal'
import {
  useClaimDetail,
  useUpdateClaimStatus,
  useResolveClaim,
  useAddClaimNote,
} from '@/hooks/useClaims'

/* ------------------------------------------------------------------ */
/*  Constants                                                          */
/* ------------------------------------------------------------------ */

const STATUS_CONFIG: Record<string, { label: string; variant: BadgeVariant }> = {
  open: { label: 'Open', variant: 'info' },
  investigating: { label: 'Investigating', variant: 'warn' },
  approved: { label: 'Approved', variant: 'success' },
  rejected: { label: 'Rejected', variant: 'danger' },
  resolved: { label: 'Resolved', variant: 'neutral' },
}

/* ------------------------------------------------------------------ */
/*  Helpers                                                            */
/* ------------------------------------------------------------------ */

function formatDateTime(dateStr: string | null | undefined): string {
  if (!dateStr) return '—'
  return new Intl.DateTimeFormat('en-NZ', {
    day: '2-digit', month: 'short', year: 'numeric',
    hour: '2-digit', minute: '2-digit', hour12: true,
  }).format(new Date(dateStr))
}

function formatCost(amount: number | string | null | undefined): string {
  const num = Number(amount ?? 0)
  if (isNaN(num)) return '$0.00'
  return `${num.toLocaleString('en-NZ', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`
}

function formatClaimType(type: string): string {
  return type.replace(/_/g, ' ').replace(/\b\w/g, c => c.toUpperCase())
}

function formatResolutionType(type: string | null | undefined): string {
  if (!type) return '—'
  return type.replace(/_/g, ' ').replace(/\b\w/g, c => c.toUpperCase())
}

/* ------------------------------------------------------------------ */
/*  Component                                                          */
/* ------------------------------------------------------------------ */

export default function ClaimDetail() {
  const { id } = useParams<{ id: string }>()
  const navigate = useNavigate()
  const { claim, loading, error, refetch } = useClaimDetail(id)
  const { updateStatus, loading: statusLoading } = useUpdateClaimStatus()
  const { resolve, loading: resolveLoading } = useResolveClaim()
  const { addNote, loading: noteLoading } = useAddClaimNote()

  const [resolveModalOpen, setResolveModalOpen] = useState(false)
  const [noteModalOpen, setNoteModalOpen] = useState(false)
  const [actionError, setActionError] = useState<string | null>(null)

  /* Status transition handlers */
  const handleStatusChange = async (newStatus: string) => {
    if (!claim) return
    setActionError(null)
    const result = await updateStatus(claim.id, newStatus)
    if (result) {
      refetch()
    } else {
      setActionError('Failed to update status.')
    }
  }

  const handleResolve = async (payload: {
    resolution_type: string
    resolution_amount?: number | null
    resolution_notes?: string | null
    return_stock_item_ids?: string[]
  }) => {
    if (!claim) return
    setActionError(null)
    const result = await resolve(claim.id, payload)
    if (result) {
      setResolveModalOpen(false)
      refetch()
    } else {
      setActionError('Failed to resolve claim.')
    }
  }

  const handleAddNote = async (notes: string) => {
    if (!claim) return
    setActionError(null)
    const result = await addNote(claim.id, notes)
    if (result) {
      setNoteModalOpen(false)
      refetch()
    } else {
      setActionError('Failed to add note.')
    }
  }

  /* Loading / error states */
  if (loading) {
    return (
      <div className="flex items-center justify-center py-16">
        <Spinner label="Loading claim" />
      </div>
    )
  }

  if (error || !claim) {
    return (
      <div className="space-y-4 px-4 py-6 sm:px-6 lg:px-8">
        <button onClick={() => navigate('/claims')} className="text-sm text-accent hover:underline">
          ← Back to Claims
        </button>
        <div className="rounded-card border border-danger/30 bg-danger-soft p-4 text-sm text-danger">
          {error || 'Claim not found.'}
        </div>
      </div>
    )
  }

  const statusCfg = STATUS_CONFIG[claim.status] ?? { label: claim.status, variant: 'neutral' as BadgeVariant }
  const customerName = claim.customer
    ? `${claim.customer.first_name} ${claim.customer.last_name}`
    : '—'

  return (
    <div className="space-y-6 px-4 py-6 sm:px-6 lg:px-8">
      {/* Back link */}
      <button onClick={() => navigate('/claims')} className="text-sm text-accent hover:underline">
        ← Back to Claims
      </button>

      {/* Header */}
      <div className="flex flex-wrap items-start justify-between gap-4 rounded-card border border-border bg-card p-6 shadow-card">
        <div>
          <div className="mb-2 flex items-center gap-3">
            <h1 className="text-xl font-bold text-text">Claim</h1>
            <Badge variant={statusCfg.variant}>{statusCfg.label}</Badge>
          </div>
          <p className="mono text-sm text-muted">{claim.claim_number ?? ''}</p>
          <div className="mt-2 space-y-1 text-sm text-text">
            <p><span className="font-medium">Customer:</span> {customerName}</p>
            <p><span className="font-medium">Type:</span> {formatClaimType(claim.claim_type)}</p>
            <p><span className="font-medium">Created:</span> {formatDateTime(claim.created_at)}</p>
          </div>
        </div>

        {/* Action buttons */}
        <div className="flex flex-wrap gap-2">
          {claim.status === 'open' && (
            <Button size="sm" onClick={() => handleStatusChange('investigating')} loading={statusLoading}>
              Start Investigation
            </Button>
          )}
          {claim.status === 'investigating' && (
            <>
              <Button size="sm" onClick={() => handleStatusChange('approved')} loading={statusLoading}>
                Approve
              </Button>
              <Button size="sm" variant="danger" onClick={() => handleStatusChange('rejected')} loading={statusLoading}>
                Reject
              </Button>
            </>
          )}
          {(claim.status === 'approved' || claim.status === 'rejected') && (
            <Button size="sm" onClick={() => setResolveModalOpen(true)}>
              Resolve
            </Button>
          )}
          {claim.status !== 'resolved' && (
            <Button size="sm" variant="ghost" onClick={() => setNoteModalOpen(true)}>
              Add Note
            </Button>
          )}
        </div>
      </div>

      {actionError && (
        <div className="rounded-card border border-danger/30 bg-danger-soft p-3 text-sm text-danger">{actionError}</div>
      )}

      {/* Description */}
      <section className="rounded-card border border-border bg-card p-6 shadow-card">
        <h2 className="mb-2 text-sm font-semibold uppercase tracking-wider text-muted">Description</h2>
        <p className="whitespace-pre-wrap text-sm text-text">{claim.description}</p>
      </section>

      {/* Original Transaction */}
      <section className="rounded-card border border-border bg-card p-6 shadow-card">
        <h2 className="mb-3 text-sm font-semibold uppercase tracking-wider text-muted">Original Transaction</h2>
        <div className="grid grid-cols-1 gap-4 text-sm sm:grid-cols-2">
          {claim.invoice && (
            <div>
              <span className="font-medium text-muted">Invoice:</span>{' '}
              <Link to={`/invoices/${claim.invoice.id}`} className="text-accent hover:underline">
                {claim.invoice.invoice_number ?? claim.invoice.id.slice(0, 8)}
              </Link>
              {claim.invoice.total != null && (
                <span className="ml-2 text-muted">({formatCost(claim.invoice.total)})</span>
              )}
            </div>
          )}
          {claim.job_card && (
            <div>
              <span className="font-medium text-muted">Job Card:</span>{' '}
              <Link to={`/job-cards/${claim.job_card.id}`} className="text-accent hover:underline">
                {claim.job_card.description ?? claim.job_card.id.slice(0, 8)}
              </Link>
              {claim.job_card.vehicle_rego && (
                <span className="ml-2 text-muted">({claim.job_card.vehicle_rego})</span>
              )}
            </div>
          )}
          {!claim.invoice && !claim.job_card && (
            <p className="text-muted-2">No linked transaction</p>
          )}
        </div>
      </section>

      {/* Resolution (if resolved) */}
      {claim.resolution_type && (
        <section className="rounded-card border border-border bg-card p-6 shadow-card">
          <h2 className="mb-3 text-sm font-semibold uppercase tracking-wider text-muted">Resolution</h2>
          <div className="grid grid-cols-1 gap-3 text-sm sm:grid-cols-2">
            <div><span className="font-medium text-muted">Type:</span> {formatResolutionType(claim.resolution_type)}</div>
            {claim.resolution_amount != null && (
              <div><span className="font-medium text-muted">Amount:</span> {formatCost(claim.resolution_amount)}</div>
            )}
            {claim.resolved_at && (
              <div><span className="font-medium text-muted">Resolved:</span> {formatDateTime(claim.resolved_at)}</div>
            )}
            {claim.resolution_notes && (
              <div className="sm:col-span-2">
                <span className="font-medium text-muted">Notes:</span>
                <p className="mt-1 whitespace-pre-wrap text-text">{claim.resolution_notes}</p>
              </div>
            )}
          </div>
          {/* Related entities */}
          <div className="mt-4 flex flex-wrap gap-4 text-sm">
            {claim.refund_id && (
              <span className="text-muted">Refund: <span className="mono text-xs">{claim.refund_id.slice(0, 8)}…</span></span>
            )}
            {claim.credit_note_id && (
              <span className="text-muted">Credit Note: <span className="mono text-xs">{claim.credit_note_id.slice(0, 8)}…</span></span>
            )}
            {claim.warranty_job_id && (
              <Link to={`/job-cards/${claim.warranty_job_id}`} className="text-accent hover:underline">
                Warranty Job Card
              </Link>
            )}
            {(claim.return_movement_ids ?? []).length > 0 && (
              <span className="text-muted">
                Stock Returns: {(claim.return_movement_ids ?? []).length}
              </span>
            )}
          </div>
        </section>
      )}

      {/* Cost Breakdown */}
      <section className="rounded-card border border-border bg-card p-6 shadow-card">
        <h2 className="mb-3 text-sm font-semibold uppercase tracking-wider text-muted">Cost to Business</h2>
        <div className="grid grid-cols-2 gap-4 text-sm sm:grid-cols-4">
          <div>
            <p className="text-muted">Labour</p>
            <p className="mono font-semibold text-text">{formatCost(claim.cost_breakdown?.labour_cost)}</p>
          </div>
          <div>
            <p className="text-muted">Parts</p>
            <p className="mono font-semibold text-text">{formatCost(claim.cost_breakdown?.parts_cost)}</p>
          </div>
          <div>
            <p className="text-muted">Write-off</p>
            <p className="mono font-semibold text-text">{formatCost(claim.cost_breakdown?.write_off_cost)}</p>
          </div>
          <div>
            <p className="text-muted">Total</p>
            <p className="mono font-bold text-text">{formatCost(claim.cost_to_business)}</p>
          </div>
        </div>
      </section>

      {/* Timeline */}
      <section className="rounded-card border border-border bg-card p-6 shadow-card">
        <h2 className="mb-3 text-sm font-semibold uppercase tracking-wider text-muted">Timeline</h2>
        {(claim.actions ?? []).length === 0 ? (
          <p className="text-sm text-muted-2">No actions recorded yet.</p>
        ) : (
          <div className="space-y-3">
            {(claim.actions ?? []).map(action => (
              <div key={action.id} className="flex gap-3 border-l-2 border-border py-1 pl-4 text-sm">
                <div className="flex-1">
                  <p className="font-medium text-text">
                    {action.action_type === 'status_change' && (
                      <>Status changed: {action.from_status} → {action.to_status}</>
                    )}
                    {action.action_type === 'note_added' && 'Note added'}
                    {action.action_type === 'resolution_applied' && 'Resolution applied'}
                    {action.action_type === 'cost_updated' && 'Cost updated'}
                    {!['status_change', 'note_added', 'resolution_applied', 'cost_updated'].includes(action.action_type) && action.action_type}
                  </p>
                  {action.notes && (
                    <p className="mt-0.5 whitespace-pre-wrap text-muted">{action.notes}</p>
                  )}
                  <p className="mt-0.5 text-xs text-muted-2">
                    {action.performed_by_name ?? action.performed_by.slice(0, 8)} · {formatDateTime(action.performed_at)}
                  </p>
                </div>
              </div>
            ))}
          </div>
        )}
      </section>

      {/* Modals */}
      <ClaimResolveModal
        open={resolveModalOpen}
        onClose={() => setResolveModalOpen(false)}
        onSubmit={handleResolve}
        loading={resolveLoading}
      />
      <ClaimNoteModal
        open={noteModalOpen}
        onClose={() => setNoteModalOpen(false)}
        onSubmit={handleAddNote}
        loading={noteLoading}
      />
    </div>
  )
}
