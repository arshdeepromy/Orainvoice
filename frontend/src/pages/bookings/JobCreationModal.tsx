/**
 * JobCreationModal — converts a booking into a job card with staff assignment.
 *
 * Pre-fills customer name, vehicle rego, service type, and notes from the booking.
 * - org_admin: shows StaffPicker to assign any active staff member (defaults to self)
 * - non-admin: shows current user name as read-only assignee
 *
 * Requirements: 3.2, 3.3, 3.4, 3.5, 3.6, 3.7, 3.8
 */

import { useState } from 'react'
import apiClient from '../../api/client'
import { Button, Modal, useToast } from '../../components/ui'
import { useAuth } from '../../contexts/AuthContext'
import StaffPicker from '../../components/StaffPicker'
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
            <div className="h-16 w-16 rounded-full bg-green-100 flex items-center justify-center animate-[scale-in_0.3s_ease-out]">
              <svg
                className="h-8 w-8 text-green-600"
                fill="none"
                viewBox="0 0 24 24"
                stroke="currentColor"
                strokeWidth={3}
              >
                <path
                  strokeLinecap="round"
                  strokeLinejoin="round"
                  d="M5 13l4 4L19 7"
                  className="animate-[draw-check_0.4s_ease-out_0.2s_both]"
                  style={{
                    strokeDasharray: 24,
                    strokeDashoffset: 24,
                    animation: 'draw-check 0.4s ease-out 0.2s forwards',
                  }}
                />
              </svg>
            </div>
          </div>
          <p className="text-lg font-medium text-gray-900">Job Card Created</p>
          <p className="text-sm text-gray-500 mt-1">Booking updated successfully</p>
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
              <label className="block text-sm font-medium text-gray-700">Customer</label>
              <p className="mt-1 text-sm text-gray-900">{booking.customer_name ?? '—'}</p>
            </div>

            <div>
              <label className="block text-sm font-medium text-gray-700">Vehicle Rego</label>
              <p className="mt-1 text-sm text-gray-900">{booking.vehicle_rego ?? '—'}</p>
            </div>

            <div>
              <label className="block text-sm font-medium text-gray-700">Service Type</label>
              <p className="mt-1 text-sm text-gray-900">{booking.service_type ?? '—'}</p>
            </div>

            <div>
              <label className="block text-sm font-medium text-gray-700">Notes</label>
              <p className="mt-1 text-sm text-gray-900 whitespace-pre-wrap">
                {booking.notes ?? '—'}
              </p>
            </div>
          </div>

          {/* Assignee selection */}
          <div className="border-t border-gray-200 pt-4">
            {isOrgAdmin ? (
              <StaffPicker
                value={assignedTo}
                onChange={setAssignedTo}
                disabled={submitting}
              />
            ) : (
              <div>
                <label className="block text-sm font-medium text-gray-700">
                  Assigned To
                </label>
                <p className="mt-1 text-sm text-gray-900">
                  {user?.name ?? 'You'}
                </p>
              </div>
            )}
          </div>

          {/* Actions */}
          <div className="flex justify-end gap-3 border-t border-gray-200 pt-4">
            <Button
              type="button"
              variant="secondary"
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
