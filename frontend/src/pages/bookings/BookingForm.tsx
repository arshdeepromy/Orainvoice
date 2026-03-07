import { useState, useEffect } from 'react'
import apiClient from '../../api/client'
import { Button, Input, Select, Modal, Spinner } from '../../components/ui'
import type { BookingSearchResult } from './BookingCalendar'

/* ------------------------------------------------------------------ */
/*  Types                                                              */
/* ------------------------------------------------------------------ */

interface BookingDetail {
  id: string
  org_id: string
  customer_id: string | null
  customer_name: string | null
  vehicle_rego: string | null
  branch_id: string | null
  service_type: string | null
  scheduled_at: string
  duration_minutes: number
  notes: string | null
  status: string
  reminder_sent: boolean
  assigned_to: string | null
  created_by: string
  created_at: string
  updated_at: string
}

interface CustomerOption {
  id: string
  first_name: string
  last_name: string
  email: string | null
  phone: string | null
}

interface BookingFormProps {
  open: boolean
  onClose: () => void
  onSaved: () => void
  editBooking?: BookingSearchResult | null
}

/* ------------------------------------------------------------------ */
/*  Helpers                                                            */
/* ------------------------------------------------------------------ */

const STATUS_OPTIONS = [
  { value: 'scheduled', label: 'Scheduled' },
  { value: 'confirmed', label: 'Confirmed' },
  { value: 'completed', label: 'Completed' },
  { value: 'cancelled', label: 'Cancelled' },
  { value: 'no_show', label: 'No Show' },
]

const DURATION_OPTIONS = [
  { value: '15', label: '15 min' },
  { value: '30', label: '30 min' },
  { value: '45', label: '45 min' },
  { value: '60', label: '1 hour' },
  { value: '90', label: '1.5 hours' },
  { value: '120', label: '2 hours' },
  { value: '180', label: '3 hours' },
  { value: '240', label: '4 hours' },
  { value: '480', label: 'Full day (8h)' },
]

function toLocalDatetimeStr(dateStr: string): string {
  const d = new Date(dateStr)
  const pad = (n: number) => n.toString().padStart(2, '0')
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}T${pad(d.getHours())}:${pad(d.getMinutes())}`
}

function nowLocalStr(): string {
  return toLocalDatetimeStr(new Date().toISOString())
}

/* ------------------------------------------------------------------ */
/*  Component                                                          */
/* ------------------------------------------------------------------ */

/**
 * Modal form for creating or editing a booking/appointment.
 * Links to a customer and optionally a vehicle, with date/time/duration/service type.
 * Supports optional confirmation email/SMS on creation.
 *
 * Requirements: 64.2, 64.3
 */
export default function BookingForm({ open, onClose, onSaved, editBooking }: BookingFormProps) {
  const isEdit = !!editBooking

  /* Form state */
  const [customerId, setCustomerId] = useState('')
  const [customerSearch, setCustomerSearch] = useState('')
  const [customerResults, setCustomerResults] = useState<CustomerOption[]>([])
  const [searchingCustomers, setSearchingCustomers] = useState(false)
  const [showCustomerDropdown, setShowCustomerDropdown] = useState(false)

  const [vehicleRego, setVehicleRego] = useState('')
  const [serviceType, setServiceType] = useState('')
  const [scheduledAt, setScheduledAt] = useState(nowLocalStr())
  const [durationMinutes, setDurationMinutes] = useState('60')
  const [notes, setNotes] = useState('')
  const [status, setStatus] = useState('scheduled')
  const [sendConfirmation, setSendConfirmation] = useState(false)

  const [saving, setSaving] = useState(false)
  const [loadingDetail, setLoadingDetail] = useState(false)
  const [error, setError] = useState('')

  /* Load booking detail when editing */
  useEffect(() => {
    if (!open) return
    if (editBooking) {
      setLoadingDetail(true)
      apiClient.get<BookingDetail>(`/bookings/${editBooking.id}`)
        .then((res) => {
          const b = res.data
          setCustomerId(b.customer_id ?? '')
          setCustomerSearch(b.customer_name ?? '')
          setVehicleRego(b.vehicle_rego ?? '')
          setServiceType(b.service_type ?? '')
          setScheduledAt(toLocalDatetimeStr(b.scheduled_at))
          setDurationMinutes(String(b.duration_minutes))
          setNotes(b.notes ?? '')
          setStatus(b.status)
        })
        .catch(() => setError('Failed to load booking details.'))
        .finally(() => setLoadingDetail(false))
    } else {
      // Reset form for new booking
      setCustomerId('')
      setCustomerSearch('')
      setVehicleRego('')
      setServiceType('')
      setScheduledAt(nowLocalStr())
      setDurationMinutes('60')
      setNotes('')
      setStatus('scheduled')
      setSendConfirmation(false)
      setError('')
    }
  }, [open, editBooking])

  /* Customer search */
  useEffect(() => {
    if (!customerSearch.trim() || customerSearch.length < 2) {
      setCustomerResults([])
      setShowCustomerDropdown(false)
      return
    }
    const timer = setTimeout(async () => {
      setSearchingCustomers(true)
      try {
        const res = await apiClient.get<{ items?: CustomerOption[]; results?: CustomerOption[] }>('/customers', {
          params: { search: customerSearch, page_size: 8 },
        })
        const items = res.data.items ?? res.data.results ?? []
        setCustomerResults(items)
        setShowCustomerDropdown(items.length > 0)
      } catch {
        setCustomerResults([])
      } finally {
        setSearchingCustomers(false)
      }
    }, 300)
    return () => clearTimeout(timer)
  }, [customerSearch])

  /* Submit */
  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault()
    if (!customerId) {
      setError('Please select a customer.')
      return
    }

    setSaving(true)
    setError('')

    try {
      if (isEdit) {
        await apiClient.put(`/bookings/${editBooking!.id}`, {
          customer_id: customerId,
          vehicle_rego: vehicleRego || null,
          service_type: serviceType || null,
          scheduled_at: new Date(scheduledAt).toISOString(),
          duration_minutes: parseInt(durationMinutes, 10),
          notes: notes || null,
          status,
        })
      } else {
        await apiClient.post('/bookings', {
          customer_id: customerId,
          vehicle_rego: vehicleRego || null,
          service_type: serviceType || null,
          scheduled_at: new Date(scheduledAt).toISOString(),
          duration_minutes: parseInt(durationMinutes, 10),
          notes: notes || null,
          send_confirmation: sendConfirmation,
        })
      }
      onSaved()
      onClose()
    } catch (err: unknown) {
      const detail = (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail
      setError(detail ?? 'Failed to save booking.')
    } finally {
      setSaving(false)
    }
  }

  return (
    <Modal open={open} onClose={onClose} title={isEdit ? 'Edit Booking' : 'New Booking'} className="max-w-xl">
      {loadingDetail ? (
        <div className="py-8"><Spinner label="Loading booking" /></div>
      ) : (
        <form onSubmit={handleSubmit} className="space-y-4">
          {error && (
            <div className="rounded-md border border-red-200 bg-red-50 px-3 py-2 text-sm text-red-700" role="alert">{error}</div>
          )}

          {/* Customer search */}
          <div className="relative">
            <Input
              label="Customer *"
              placeholder="Search by name, phone, or email…"
              value={customerSearch}
              onChange={(e) => {
                setCustomerSearch(e.target.value)
                if (!e.target.value.trim()) setCustomerId('')
              }}
              onFocus={() => { if (customerResults.length > 0) setShowCustomerDropdown(true) }}
              aria-label="Search customer"
              aria-expanded={showCustomerDropdown}
              aria-autocomplete="list"
              role="combobox"
            />
            {searchingCustomers && (
              <div className="absolute right-3 top-8">
                <Spinner label="" />
              </div>
            )}
            {showCustomerDropdown && (
              <ul
                className="absolute z-10 mt-1 w-full rounded-md border border-gray-200 bg-white shadow-lg max-h-48 overflow-auto"
                role="listbox"
              >
                {customerResults.map((c) => (
                  <li
                    key={c.id}
                    role="option"
                    aria-selected={customerId === c.id}
                    className="cursor-pointer px-3 py-2 text-sm hover:bg-blue-50 focus:bg-blue-50"
                    onClick={() => {
                      setCustomerId(c.id)
                      setCustomerSearch(`${c.first_name} ${c.last_name}`)
                      setShowCustomerDropdown(false)
                    }}
                    onKeyDown={(e) => {
                      if (e.key === 'Enter') {
                        setCustomerId(c.id)
                        setCustomerSearch(`${c.first_name} ${c.last_name}`)
                        setShowCustomerDropdown(false)
                      }
                    }}
                    tabIndex={0}
                  >
                    <span className="font-medium">{c.first_name} {c.last_name}</span>
                    {c.phone && <span className="ml-2 text-gray-500">{c.phone}</span>}
                    {c.email && <span className="ml-2 text-gray-400">{c.email}</span>}
                  </li>
                ))}
              </ul>
            )}
          </div>

          {/* Vehicle rego */}
          <Input
            label="Vehicle Rego"
            placeholder="e.g. ABC123"
            value={vehicleRego}
            onChange={(e) => setVehicleRego(e.target.value.toUpperCase())}
          />

          {/* Service type */}
          <Input
            label="Service Type"
            placeholder="e.g. WOF, Full Service, Brake Repair"
            value={serviceType}
            onChange={(e) => setServiceType(e.target.value)}
          />

          {/* Date/time and duration */}
          <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
            <Input
              label="Date & Time *"
              type="datetime-local"
              value={scheduledAt}
              onChange={(e) => setScheduledAt(e.target.value)}
              required
            />
            <Select
              label="Duration"
              options={DURATION_OPTIONS}
              value={durationMinutes}
              onChange={(e) => setDurationMinutes(e.target.value)}
            />
          </div>

          {/* Status (edit only) */}
          {isEdit && (
            <Select
              label="Status"
              options={STATUS_OPTIONS}
              value={status}
              onChange={(e) => setStatus(e.target.value)}
            />
          )}

          {/* Notes */}
          <div className="flex flex-col gap-1">
            <label htmlFor="booking-notes" className="text-sm font-medium text-gray-700">Notes</label>
            <textarea
              id="booking-notes"
              className="rounded-md border border-gray-300 px-3 py-2 text-gray-900 shadow-sm focus:outline-none focus:ring-2 focus:ring-blue-500 focus:border-blue-500"
              rows={3}
              placeholder="Additional notes…"
              value={notes}
              onChange={(e) => setNotes(e.target.value)}
            />
          </div>

          {/* Send confirmation (create only) */}
          {!isEdit && (
            <label className="flex items-center gap-2 text-sm text-gray-700 cursor-pointer">
              <input
                type="checkbox"
                checked={sendConfirmation}
                onChange={(e) => setSendConfirmation(e.target.checked)}
                className="rounded border-gray-300 text-blue-600 focus:ring-blue-500"
              />
              Send confirmation email/SMS to customer
            </label>
          )}

          {/* Actions */}
          <div className="flex justify-end gap-3 pt-2 border-t border-gray-100">
            <Button type="button" variant="secondary" onClick={onClose} disabled={saving}>
              Cancel
            </Button>
            <Button type="submit" disabled={saving}>
              {saving ? 'Saving…' : isEdit ? 'Update Booking' : 'Create Booking'}
            </Button>
          </div>
        </form>
      )}
    </Modal>
  )
}
