/**
 * JobCreationModal — Task 28 port of frontend/src/pages/bookings/JobCreationModal.tsx.
 *
 * Converts a booking into a job card with staff assignment. ALL logic copied
 * VERBATIM: the pre-filled read-only booking details, org-admin StaffPicker vs
 * non-admin read-only assignee, the convert call (POST /bookings/:id/convert
 * target=job_card { assigned_to }), the success animation before onSuccess, and
 * the exported pure `mapBookingToJobPreFill`. Presentation remapped onto the
 * design tokens (FR-2b); `secondary`→`ghost`.
 *
 * Requirements: 3.2–3.8
 */

import { useState } from 'react'
import apiClient from '@/api/client'
import { Button, Modal, useToast } from '@/components/ui'
import { useAuth } from '@/contexts/AuthContext'
import { useTenant } from '@/contexts/TenantContext'
import StaffPicker from '@/components/StaffPicker'
import type { BookingListItem } from './BookingListPanel'

/* ------------------------------------------------------------------ */
/*  Types                                                              */
/* ------------------------------------------------------------------ */

interface JobCreationModalProps {
  booking: BookingListItem
  isOpen: boolean
  onClose: () => void
  onSuccess: (jobCardId: string) => void
}

interface ConvertResponse {
  booking_id: string
  target: string
  created_id: string
  message: string
}

/* ------------------------------------------------------------------ */
/*  Pure mapping: booking → job card pre-fill data                     */
/* ------------------------------------------------------------------ */

/**
 * Maps booking fields to the job card fields that will be pre-populated
 * when converting a booking to a job card.
 *
 * This mirrors the backend `convert_booking_to_job_card` mapping:
 *   - description ← booking.service_type
 *   - notes       ← booking.notes
 *   - vehicle_rego← booking.vehicle_rego
 */
export interface JobPreFillData {
  description: string | null
  notes: string | null
  vehicle_rego: string | null
}

export function mapBookingToJobPreFill(booking: BookingListItem): JobPreFillData {
  return {
    description: booking.service_type,
    notes: booking.notes,
    vehicle_rego: booking.vehicle_rego,
  }
}

/* ------------------------------------------------------------------ */
/*  Component                                                          */
/* ------------------------------------------------------------------ */

export default function JobCreationModal({
  booking,
  isOpen,
  onClose,
  onSuccess,
}: JobCreationModalProps) {
  const { user, isOrgAdmin } = useAuth()
  const { tradeFamily } = useTenant()
  const isAutomotive = (tradeFamily ?? 'automotive-transport') === 'automotive-transport'
  const { addToast } = useToast()
  const [assignedTo, setAssignedTo] = useState<string>('')
  const [submitting, setSubmitting] = useState(false)
  const [showSuccess, setShowSuccess] = useState(false)
  const createdIdRef = useState<string | null>(null)

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault()
    setSubmitting(true)
    try {
      const res = await apiClient.post<ConvertResponse>(
        `/bookings/${booking.id}/convert`,
        { assigned_to: assignedTo || undefined },
        { params: { target: 'job_card' } },
      )
      // Show success animation briefly before closing
      createdIdRef[1](res.data.created_id)
      setShowSuccess(true)
      setTimeout(() => {
        setShowSuccess(false)
        onSuccess(res.data.created_id)
      }, 1200)
    } catch (err: unknown) {
      const detail =
        (err as { response?: { data?: { detail?: string } } })?.response?.data
          ?.detail
      addToast('error', detail ?? 'Failed to create job card.')
    } finally {
      setSubmitting(false)
    }
  }

  return (
    <Modal open={isOpen} onClose={showSuccess ? () => {} : onClose} title={showSuccess ? '' : 'Create Job from Booking'}>
      {showSuccess ? (
        <div className="flex flex-col items-center justify-center py-8">
          {/* Animated success checkmark */}
          <div className="relative mb-4">
            <div className="flex h-16 w-16 items-center justify-center rounded-full bg-ok-soft">
              <svg
                className="h-8 w-8 text-ok"
                fill="none"
                viewBox="0 0 24 24"
                stroke="currentColor"
                strokeWidth={3}
              >
                <path
                  strokeLinecap="round"
                  strokeLinejoin="round"
                  d="M5 13l4 4L19 7"
                  style={{
                    strokeDasharray: 24,
                    strokeDashoffset: 24,
                    animation: 'draw-check 0.4s ease-out 0.2s forwards',
                  }}
                />
              </svg>
            </div>
          </div>
          <p className="text-[15px] font-medium text-text">Job Card Created</p>
          <p className="mt-1 text-[13px] text-muted">Booking updated successfully</p>
          <style>{`
            @keyframes draw-check {
              to { stroke-dashoffset: 0; }
            }
          `}</style>
        </div>
      ) : (
        <form onSubmit={handleSubmit} className="space-y-4">
          {/* Pre-filled booking details (read-only) */}
          <div className="space-y-3">
            <div>
              <label className="block text-[12.5px] font-medium text-text">Customer</label>
              <p className="mt-1 text-[13.5px] text-text">{booking.customer_name ?? '—'}</p>
            </div>

            {isAutomotive && (
            <div>
              <label className="block text-[12.5px] font-medium text-text">Vehicle Rego</label>
              <p className="mono mt-1 text-[13.5px] text-text">{booking.vehicle_rego ?? '—'}</p>
            </div>
            )}

            <div>
              <label className="block text-[12.5px] font-medium text-text">Service Type</label>
              <p className="mt-1 text-[13.5px] text-text">{booking.service_type ?? '—'}</p>
            </div>

            <div>
              <label className="block text-[12.5px] font-medium text-text">Notes</label>
              <p className="mt-1 whitespace-pre-wrap text-[13.5px] text-text">
                {booking.notes ?? '—'}
              </p>
            </div>
          </div>

          {/* Assignee selection */}
          <div className="border-t border-border pt-4">
            {isOrgAdmin ? (
              <StaffPicker
                value={assignedTo}
                onChange={setAssignedTo}
                disabled={submitting}
              />
            ) : (
              <div>
                <label className="block text-[12.5px] font-medium text-text">
                  Assigned To
                </label>
                <p className="mt-1 text-[13.5px] text-text">
                  {user?.name ?? 'You'}
                </p>
              </div>
            )}
          </div>

          {/* Actions */}
          <div className="flex justify-end gap-3 border-t border-border pt-4">
            <Button
              type="button"
              variant="ghost"
              onClick={onClose}
              disabled={submitting}
            >
              Cancel
            </Button>
            <Button type="submit" disabled={submitting}>
              {submitting ? 'Creating…' : 'Create Job'}
            </Button>
          </div>
        </form>
      )}
    </Modal>
  )
}
