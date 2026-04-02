/**
 * Claim Detail page — full claim view with status actions, timeline, and resolution.
 *
 * Requirements: 2.1-2.5, 3.1-3.7, 7.1-7.5
 */

import { useState } from 'react'
import { useParams, useNavigate, Link } from 'react-router-dom'
import { Badge, Button, Spinner } from '../../components/ui'
import { ClaimResolveModal } from '../../components/claims/ClaimResolveModal'
import { ClaimNoteModal } from '../../components/claims/ClaimNoteModal'
import {
  useClaimDetail,
  useUpdateClaimStatus,
  useResolveClaim,
  useAddClaimNote,
} from '../../hooks/useClaims'

/* ------------------------------------------------------------------ */
/*  Constants                                                          */
/* ------------------------------------------------------------------ */

type BadgeVariant = 'success' | 'warning' | 'error' | 'info' | 'neutral'

const STATUS_CONFIG: Record<string, { label: string; variant: BadgeVariant }> = {
  open: { label: 'Open', variant: 'info' },
  investigating: { label: 'Investigating', variant: 'warning' },
  approved: { label: 'Approved', variant: 'success' },
  rejected: { label: 'Rejected', variant: 'error' },
  resolved: { label: 'Resolved', variant: 'neutral' },
}

/* ------------------------------------------------------------------ */
/*  Helpers                                                            */
/* ------------------------------------------------------------------ */

function formatDate(dateStr: string | null | undefined): string {
  if (!dateStr) return '—'
  return new Intl.DateTimeFormat('en-NZ', { day: '2-digit', month: 'short', year: 'numeric' }).format(new Date(dateStr))
}

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
  return `$${num.toLocaleString('en-NZ', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`
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
      <div className="space-y-4">
        <button onClick={() => navigate('/claims')} className="text-sm text-blue-600 hover:underline">
          ← Back to Claims
        </button>
        <div className="rounded-lg border border-red-200 bg-red-50 p-4 text-sm text-red-700">
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
    <div className="space-y-6">
      {/* Back link */}
      <button onClick={() => navigate('/claims')} className="text-sm text-blue-600 hover:underline">
        ← Back to Claims
      </button>

      {/* Header */}
      <div className="flex flex-wrap items-start justify-between gap-4 rounded-lg border border-gray-200 bg-white p-6">
        <div>
          <div className="flex items-center gap-3 mb-2">
            <h1 className="text-xl font-bold text-gray-900">Claim</h1>
            <Badge variant={statusCfg.variant}>{statusCfg.label}</Badge>
          </div>
          <p className="text-sm text-gray-500 font-mono">{claim.id}</p>
          <div className="mt-2 space-y-1 text-sm text-gray-700">
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
            <Button size="sm" variant="secondary" onClick={() => setNoteModalOpen(true)}>
              Add Note
            </Button>
          )}
        </div>
      </div>

      {actionError && (
        <div className="rounded-lg border border-red-200 bg-red-50 p-3 text-sm text-red-700">{actionError}</div>
      )}

      {/* Description */}
      <section className="rounded-lg border border-gray-200 bg-white p-6">
        <h2 className="text-sm font-semibold text-gray-500 uppercase tracking-wider mb-2">Description</h2>
        <p className="text-sm text-gray-800 whitespace-pre-wrap">{claim.description}</p>
      </section>

      {/* Original Transaction */}
      <section className="rounded-lg border border-gray-200 bg-white p-6">
        <h2 className="text-sm font-semibold text-gray-500 uppercase tracking-wider mb-3">Original Transaction</h2>
        <div className="grid grid-cols-1 sm:grid-cols-2 gap-4 text-sm">
          {claim.invoice && (
            <div>
              <span className="font-medium text-gray-600">Invoice:</span>{' '}
              <Link to={`/invoices/${claim.invoice.id}`} className="text-blue-600 hover:underline">
                {claim.invoice.invoice_number ?? claim.invoice.id.slice(0, 8)}
              </Link>
              {claim.invoice.total != null && (
                <span className="text-gray-500 ml-2">({formatCost(claim.invoice.total)})</span>
              )}
            </div>
          )}
          {claim.job_card && (
            <div>
              <span className="font-medium text-gray-600">Job Card:</span>{' '}
              <Link to={`/job-cards/${claim.job_card.id}`} className="text-blue-600 hover:underline">
                {claim.job_card.description ?? claim.job_card.id.slice(0, 8)}
              </Link>
              {claim.job_card.vehicle_rego && (
                <span className="text-gray-500 ml-2">({claim.job_card.vehicle_rego})</span>
              )}
            </div>
          )}
          {!claim.invoice && !claim.job_card && (
            <p className="text-gray-400">No linked transaction</p>
          )}
        </div>
      </section>

      {/* Resolution (if resolved) */}
      {claim.resolution_type && (
        <section className="rounded-lg border border-gray-200 bg-white p-6">
          <h2 className="text-sm font-semibold text-gray-500 uppercase tracking-wider mb-3">Resolution</h2>
          <div className="grid grid-cols-1 sm:grid-cols-2 gap-3 text-sm">
            <div><span className="font-medium text-gray-600">Type:</span> {formatResolutionType(claim.resolution_type)}</div>
            {claim.resolution_amount != null && (
              <div><span className="font-medium text-gray-600">Amount:</span> {formatCost(claim.resolution_amount)}</div>
            )}
            {claim.resolved_at && (
              <div><span className="font-medium text-gray-600">Resolved:</span> {formatDateTime(claim.resolved_at)}</div>
            )}
            {claim.resolution_notes && (
              <div className="sm:col-span-2">
                <span className="font-medium text-gray-600">Notes:</span>
                <p className="mt-1 text-gray-700 whitespace-pre-wrap">{claim.resolution_notes}</p>
              </div>
            )}
          </div>
          {/* Related entities */}
          <div className="mt-4 flex flex-wrap gap-4 text-sm">
            {claim.refund_id && (
              <span className="text-gray-600">Refund: <span className="font-mono text-xs">{claim.refund_id.slice(0, 8)}…</span></span>
            )}
            {claim.credit_note_id && (
              <span className="text-gray-600">Credit Note: <span className="font-mono text-xs">{claim.credit_note_id.slice(0, 8)}…</span></span>
            )}
            {claim.warranty_job_id && (
              <Link to={`/job-cards/${claim.warranty_job_id}`} className="text-blue-600 hover:underline">
                Warranty Job Card
              </Link>
            )}
            {(claim.return_movement_ids ?? []).length > 0 && (
              <span className="text-gray-600">
                Stock Returns: {(claim.return_movement_ids ?? []).length}
              </span>
            )}
          </div>
        </section>
      )}

      {/* Cost Breakdown */}
      <section className="rounded-lg border border-gray-200 bg-white p-6">
        <h2 className="text-sm font-semibold text-gray-500 uppercase tracking-wider mb-3">Cost to Business</h2>
        <div className="grid grid-cols-2 sm:grid-cols-4 gap-4 text-sm">
          <div>
            <p className="text-gray-500">Labour</p>
            <p className="font-semibold text-gray-900">{formatCost(claim.cost_breakdown?.labour_cost)}</p>
          </div>
          <div>
            <p className="text-gray-500">Parts</p>
            <p className="font-semibold text-gray-900">{formatCost(claim.cost_breakdown?.parts_cost)}</p>
          </div>
          <div>
            <p className="text-gray-500">Write-off</p>
            <p className="font-semibold text-gray-900">{formatCost(claim.cost_breakdown?.write_off_cost)}</p>
          </div>
          <div>
            <p className="text-gray-500">Total</p>
            <p className="font-bold text-gray-900">{formatCost(claim.cost_to_business)}</p>
          </div>
        </div>
      </section>

      {/* Timeline */}
      <section className="rounded-lg border border-gray-200 bg-white p-6">
        <h2 className="text-sm font-semibold text-gray-500 uppercase tracking-wider mb-3">Timeline</h2>
        {(claim.actions ?? []).length === 0 ? (
          <p className="text-sm text-gray-400">No actions recorded yet.</p>
        ) : (
          <div className="space-y-3">
            {(claim.actions ?? []).map(action => (
              <div key={action.id} className="flex gap-3 text-sm border-l-2 border-gray-200 pl-4 py-1">
                <div className="flex-1">
                  <p className="font-medium text-gray-800">
                    {action.action_type === 'status_change' && (
                      <>Status changed: {action.from_status} → {action.to_status}</>
                    )}
                    {action.action_type === 'note_added' && 'Note added'}
                    {action.action_type === 'resolution_applied' && 'Resolution applied'}
                    {action.action_type === 'cost_updated' && 'Cost updated'}
                    {!['status_change', 'note_added', 'resolution_applied', 'cost_updated'].includes(action.action_type) && action.action_type}
                  </p>
                  {action.notes && (
                    <p className="text-gray-600 mt-0.5 whitespace-pre-wrap">{action.notes}</p>
                  )}
                  <p className="text-xs text-gray-400 mt-0.5">
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
