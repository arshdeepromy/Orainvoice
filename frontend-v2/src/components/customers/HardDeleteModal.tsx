import { useEffect, useState } from 'react'
import apiClient from '@/api/client'
import { Modal, Button, Input, Badge, Spinner } from '@/components/ui'

/**
 * HardDeleteModal — guarded customer hard delete (customer-hard-delete spec,
 * Task 6.1). Colocated with CustomerEditModal / VehiclePickerModal.
 *
 * Two states drive the body:
 *   • Blocking   (can_delete === false): lists the legally-retained documents
 *     that must be removed/resolved first (issued invoices, claims, job cards,
 *     fleet-checklist submissions), the deletable draft invoices (each with a
 *     "Delete draft" action), and a "Re-check" button. The destructive button
 *     is disabled.
 *   • Deletable  (can_delete === true): shows the NZ IRD retention warning, the
 *     orphan-vehicle preview, a mandatory reason textarea, and a type-to-confirm
 *     input. The destructive "Hard Delete" button enables only when the reason
 *     is non-empty AND the confirmation matches the customer name (case-
 *     insensitive, trimmed) or the literal word "DELETE".
 *
 * Safe-API-consumption (NFR3): typed generics, optional chaining, `?? []` on
 * every array, default scalars, AbortController cleanup, no `as any`.
 */

/* ------------------------------------------------------------------ */
/*  Types — field names match the backend Pydantic schema exactly      */
/*  (CustomerDeletionPreflightResponse, NFR3.2).                       */
/* ------------------------------------------------------------------ */

interface PreflightInvoice {
  id: string
  invoice_number: string | null
  status: string
}

interface PreflightVehicle {
  id: string
  rego: string | null
  make: string | null
  model: string | null
  source: 'global' | 'org'
}

interface PreflightClaim {
  id: string
  claim_number: string | null
  status: string
}

interface PreflightJobCard {
  id: string
  status: string
}

interface PreflightFleetChecklist {
  id: string
  vehicle_rego: string | null
}

interface DeletionPreflight {
  can_delete: boolean
  blocking_invoices: PreflightInvoice[]
  blocking_invoice_count: number
  blocking_claims: PreflightClaim[]
  blocking_job_cards: PreflightJobCard[]
  blocking_fleet_checklists: PreflightFleetChecklist[]
  draft_invoices: PreflightInvoice[]
  orphan_vehicles: PreflightVehicle[]
  nz_retention_warning: string
}

interface HardDeleteModalProps {
  customerId: string
  customerName: string
  open: boolean
  onClose: () => void
  onDeleted: () => void
}

/**
 * Fallback NZ IRD retention warning used when the backend does not supply one.
 * Mentions the ~7-year IRD record-keeping obligation (R3).
 */
const DEFAULT_NZ_WARNING =
  'New Zealand tax law (IRD) requires tax invoices and business records to be ' +
  'kept for approximately 7 years. Deleting issued invoices or a customer with ' +
  'issued invoices may breach your record-keeping obligations. This action ' +
  'cannot be undone.'

/** Shape we narrow a caught axios-style error to (NOT `as any`, per NFR3). */
type ApiError = {
  response?: {
    status?: number
    data?: {
      detail?: string
      blocking?: Partial<DeletionPreflight>
    }
  }
}

export function HardDeleteModal({
  customerId,
  customerName,
  open,
  onClose,
  onDeleted,
}: HardDeleteModalProps) {
  const [loading, setLoading] = useState(false)
  const [preflight, setPreflight] = useState<DeletionPreflight | null>(null)
  const [error, setError] = useState<string | null>(null)

  // Deletable-state form fields.
  const [reason, setReason] = useState('')
  const [confirmation, setConfirmation] = useState('')
  const [submitting, setSubmitting] = useState(false)

  // Track in-flight draft deletions so individual buttons can show progress.
  const [deletingDraftId, setDeletingDraftId] = useState<string | null>(null)
  const [rechecking, setRechecking] = useState(false)

  /* ------------------------------------------------------------ */
  /*  Reset internal state whenever the modal opens or closes.     */
  /* ------------------------------------------------------------ */
  useEffect(() => {
    setReason('')
    setConfirmation('')
    setError(null)
  }, [open])

  /* ------------------------------------------------------------ */
  /*  Fetch preflight on open (with AbortController cleanup).      */
  /* ------------------------------------------------------------ */
  useEffect(() => {
    const controller = new AbortController()

    const run = async () => {
      setLoading(true)
      setError(null)
      try {
        const res = await apiClient.get<DeletionPreflight>(
          `/customers/${customerId}/deletion-preflight`,
          { signal: controller.signal },
        )
        const data = res.data
        setPreflight({
          can_delete: data?.can_delete ?? false,
          blocking_invoices: data?.blocking_invoices ?? [],
          blocking_invoice_count: data?.blocking_invoice_count ?? 0,
          blocking_claims: data?.blocking_claims ?? [],
          blocking_job_cards: data?.blocking_job_cards ?? [],
          blocking_fleet_checklists: data?.blocking_fleet_checklists ?? [],
          draft_invoices: data?.draft_invoices ?? [],
          orphan_vehicles: data?.orphan_vehicles ?? [],
          nz_retention_warning: data?.nz_retention_warning ?? DEFAULT_NZ_WARNING,
        })
      } catch {
        if (!controller.signal.aborted) {
          setError('Failed to load deletion preflight.')
        }
      } finally {
        if (!controller.signal.aborted) setLoading(false)
      }
    }

    if (open) run()

    return () => controller.abort()
  }, [open, customerId])

  /* ------------------------------------------------------------ */
  /*  Re-run the preflight check (used by "Re-check" + after a      */
  /*  draft delete). Not abort-bound — short, user-initiated.      */
  /* ------------------------------------------------------------ */
  const runPreflight = async () => {
    setRechecking(true)
    setError(null)
    try {
      const res = await apiClient.get<DeletionPreflight>(
        `/customers/${customerId}/deletion-preflight`,
      )
      const data = res.data
      setPreflight({
        can_delete: data?.can_delete ?? false,
        blocking_invoices: data?.blocking_invoices ?? [],
        blocking_invoice_count: data?.blocking_invoice_count ?? 0,
        blocking_claims: data?.blocking_claims ?? [],
        blocking_job_cards: data?.blocking_job_cards ?? [],
        blocking_fleet_checklists: data?.blocking_fleet_checklists ?? [],
        draft_invoices: data?.draft_invoices ?? [],
        orphan_vehicles: data?.orphan_vehicles ?? [],
        nz_retention_warning: data?.nz_retention_warning ?? DEFAULT_NZ_WARNING,
      })
    } catch {
      setError('Failed to re-check deletion preflight.')
    } finally {
      setRechecking(false)
    }
  }

  const handleDeleteDraft = async (draftId: string) => {
    setDeletingDraftId(draftId)
    setError(null)
    try {
      await apiClient.delete(`/invoices/${draftId}`)
      await runPreflight()
    } catch {
      setError('Failed to delete draft invoice.')
    } finally {
      setDeletingDraftId(null)
    }
  }

  /* ------------------------------------------------------------ */
  /*  Confirmation predicate — extracted so it is testable.        */
  /* ------------------------------------------------------------ */
  const reasonValid = reason.trim().length > 0
  const confirmationValid =
    confirmation.trim().toLowerCase() === customerName.trim().toLowerCase() ||
    confirmation.trim().toUpperCase() === 'DELETE'
  const canSubmit = reasonValid && confirmationValid

  const handleConfirmDelete = async () => {
    if (!canSubmit) return
    setSubmitting(true)
    setError(null)
    try {
      await apiClient.post(`/customers/${customerId}/hard-delete`, {
        reason,
        confirmation,
      })
      onDeleted()
    } catch (err) {
      const apiErr = err as ApiError
      const status = apiErr.response?.status
      if (status === 409) {
        // Blocking documents appeared (or a race) — re-render blocking state
        // from the returned payload.
        const blocking = apiErr.response?.data?.blocking
        setPreflight({
          can_delete: false,
          blocking_invoices: blocking?.blocking_invoices ?? [],
          blocking_invoice_count: blocking?.blocking_invoice_count ?? 0,
          blocking_claims: blocking?.blocking_claims ?? [],
          blocking_job_cards: blocking?.blocking_job_cards ?? [],
          blocking_fleet_checklists: blocking?.blocking_fleet_checklists ?? [],
          draft_invoices: blocking?.draft_invoices ?? [],
          orphan_vehicles: blocking?.orphan_vehicles ?? [],
          nz_retention_warning:
            blocking?.nz_retention_warning ??
            preflight?.nz_retention_warning ??
            DEFAULT_NZ_WARNING,
        })
        setError(
          apiErr.response?.data?.detail ??
            'This customer can no longer be deleted. Resolve the items below first.',
        )
      } else {
        setError(
          apiErr.response?.data?.detail ?? 'Failed to hard delete customer.',
        )
      }
    } finally {
      setSubmitting(false)
    }
  }

  /* ------------------------------------------------------------ */
  /*  Derived view data (all guarded).                             */
  /* ------------------------------------------------------------ */
  const canDelete = preflight?.can_delete ?? false
  const warning = preflight?.nz_retention_warning ?? DEFAULT_NZ_WARNING
  const blockingInvoices = preflight?.blocking_invoices ?? []
  const blockingClaims = preflight?.blocking_claims ?? []
  const blockingJobCards = preflight?.blocking_job_cards ?? []
  const blockingFleetChecklists = preflight?.blocking_fleet_checklists ?? []
  const draftInvoices = preflight?.draft_invoices ?? []
  const orphanVehicles = preflight?.orphan_vehicles ?? []
  const orphanCount = orphanVehicles.length

  return (
    <Modal open={open} onClose={onClose} title="Hard Delete Customer" className="max-w-2xl">
      {loading ? (
        <div className="py-12">
          <Spinner label="Loading deletion preflight" />
        </div>
      ) : (
        <div className="space-y-5">
          {/* NZ IRD retention warning */}
          <div className="rounded-ctl border border-warn/30 bg-warn-soft px-4 py-3 text-[13px] text-warn">
            {warning}
          </div>

          {error && (
            <p className="text-[13px] text-danger" role="alert">
              {error}
            </p>
          )}

          {!canDelete ? (
            /* ---------------------------------------------------- */
            /*  Blocking state                                       */
            /* ---------------------------------------------------- */
            <div className="space-y-5">
              <p className="text-[13px] text-text">
                This customer cannot be deleted yet. Resolve or remove the
                following before continuing.
              </p>

              {(blockingInvoices ?? []).length > 0 && (
                <section className="space-y-2">
                  <h3 className="text-[13px] font-semibold text-text">
                    Issued invoices ({(blockingInvoices ?? []).length})
                  </h3>
                  <ul className="space-y-1.5">
                    {blockingInvoices.map((inv) => (
                      <li
                        key={inv.id}
                        className="flex items-center justify-between rounded-ctl border border-border bg-card px-3 py-2 text-[13px] text-text"
                      >
                        <span>{inv.invoice_number ?? 'Unnumbered invoice'}</span>
                        <Badge variant="overdue">{inv.status}</Badge>
                      </li>
                    ))}
                  </ul>
                </section>
              )}

              {(blockingClaims ?? []).length > 0 && (
                <section className="space-y-2">
                  <h3 className="text-[13px] font-semibold text-text">
                    Claims ({(blockingClaims ?? []).length})
                  </h3>
                  <ul className="space-y-1.5">
                    {blockingClaims.map((claim) => (
                      <li
                        key={claim.id}
                        className="flex items-center justify-between rounded-ctl border border-border bg-card px-3 py-2 text-[13px] text-text"
                      >
                        <span>{claim.claim_number ?? 'Unnumbered claim'}</span>
                        <Badge variant="warn">{claim.status}</Badge>
                      </li>
                    ))}
                  </ul>
                </section>
              )}

              {(blockingJobCards ?? []).length > 0 && (
                <section className="space-y-2">
                  <h3 className="text-[13px] font-semibold text-text">
                    Job cards ({(blockingJobCards ?? []).length})
                  </h3>
                  <ul className="space-y-1.5">
                    {blockingJobCards.map((jc) => (
                      <li
                        key={jc.id}
                        className="flex items-center justify-between rounded-ctl border border-border bg-card px-3 py-2 text-[13px] text-text"
                      >
                        <span className="font-mono text-[12px] text-muted">{jc.id}</span>
                        <Badge variant="warn">{jc.status}</Badge>
                      </li>
                    ))}
                  </ul>
                </section>
              )}

              {(blockingFleetChecklists ?? []).length > 0 && (
                <section className="space-y-2">
                  <h3 className="text-[13px] font-semibold text-text">
                    Fleet checklist submissions ({(blockingFleetChecklists ?? []).length})
                  </h3>
                  <ul className="space-y-1.5">
                    {blockingFleetChecklists.map((fc) => (
                      <li
                        key={fc.id}
                        className="rounded-ctl border border-border bg-card px-3 py-2 text-[13px] text-text"
                      >
                        {fc.vehicle_rego ?? 'Unknown vehicle'}
                      </li>
                    ))}
                  </ul>
                </section>
              )}

              {(draftInvoices ?? []).length > 0 && (
                <section className="space-y-2">
                  <h3 className="text-[13px] font-semibold text-text">
                    Draft invoices ({(draftInvoices ?? []).length})
                  </h3>
                  <p className="text-[12px] text-muted">
                    Drafts are not legally retained and can be deleted here.
                  </p>
                  <ul className="space-y-1.5">
                    {draftInvoices.map((draft) => (
                      <li
                        key={draft.id}
                        className="flex items-center justify-between rounded-ctl border border-border bg-card px-3 py-2 text-[13px] text-text"
                      >
                        <span className="flex items-center gap-2">
                          {draft.invoice_number ?? 'Unnumbered draft'}
                          <Badge variant="draft">{draft.status}</Badge>
                        </span>
                        <Button
                          variant="ghost"
                          size="sm"
                          loading={deletingDraftId === draft.id}
                          onClick={() => handleDeleteDraft(draft.id)}
                        >
                          Delete draft
                        </Button>
                      </li>
                    ))}
                  </ul>
                </section>
              )}

              <div className="flex justify-end gap-3 border-t border-border pt-4">
                <Button variant="ghost" onClick={onClose}>
                  Cancel
                </Button>
                <Button variant="ghost" loading={rechecking} onClick={runPreflight}>
                  Re-check
                </Button>
                <Button variant="danger" disabled>
                  Hard Delete
                </Button>
              </div>
            </div>
          ) : (
            /* ---------------------------------------------------- */
            /*  Deletable state                                      */
            /* ---------------------------------------------------- */
            <div className="space-y-5">
              {/* Orphan-vehicle preview */}
              <section className="space-y-2">
                <p className="text-[13px] font-medium text-text">
                  {orphanCount} vehicle{orphanCount === 1 ? '' : 's'} will be
                  unlinked but preserved
                </p>
                {orphanCount > 0 && (
                  <ul className="space-y-1.5">
                    {orphanVehicles.map((v) => (
                      <li
                        key={v.id}
                        className="rounded-ctl border border-border bg-card px-3 py-2 text-[13px] text-text"
                      >
                        {[v.rego, v.make, v.model].filter(Boolean).join(' · ') ||
                          'Vehicle'}
                      </li>
                    ))}
                  </ul>
                )}
              </section>

              {/* Mandatory reason */}
              <div className="flex flex-col gap-[7px]">
                <label
                  htmlFor="hard-delete-reason"
                  className="text-[12.5px] font-medium text-text"
                >
                  Reason for deletion *
                </label>
                <textarea
                  id="hard-delete-reason"
                  value={reason}
                  onChange={(e) => setReason(e.target.value)}
                  rows={3}
                  className="w-full rounded-ctl border border-border bg-card px-3 py-2 text-[13.5px] text-text placeholder:text-muted-2 focus:outline-none focus:border-accent focus:shadow-[0_0_0_3px_var(--accent-soft)]"
                  placeholder="Why is this customer being permanently deleted?"
                />
              </div>

              {/* Type-to-confirm */}
              <Input
                label="Type to confirm"
                value={confirmation}
                onChange={(e) => setConfirmation(e.target.value)}
                helperText={`Type the customer name "${customerName}" or the word DELETE to confirm.`}
                placeholder={customerName || 'DELETE'}
              />

              <div className="flex justify-end gap-3 border-t border-border pt-4">
                <Button variant="ghost" onClick={onClose}>
                  Cancel
                </Button>
                <Button
                  variant="danger"
                  disabled={!canSubmit}
                  loading={submitting}
                  onClick={handleConfirmDelete}
                >
                  Hard Delete
                </Button>
              </div>
            </div>
          )}
        </div>
      )}
    </Modal>
  )
}

export default HardDeleteModal
