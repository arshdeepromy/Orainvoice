/**
 * Public-facing booking page with org branding, slot picker, and booking form.
 * Accessible via /book/{org_slug} without authentication.
 *
 * Validates: Requirement 19 — Booking Module — Task 26.9
 */

import { useEffect, useState, useCallback } from 'react'
import apiClient from '@/api/client'

interface BookingRule {
  duration_minutes: number
  min_advance_hours: number
  max_advance_days: number
  buffer_minutes: number
  available_days: number[]
  available_hours: { start: string; end: string }
}

interface PageData {
  org_name: string
  org_slug: string
  logo_url: string | null
  primary_colour: string | null
  services: string[]
  booking_rules: BookingRule | null
}

interface TimeSlot {
  start_time: string
  end_time: string
  available: boolean
}

interface BookingPageProps {
  orgSlug: string
}

function formatSlotTime(iso: string): string {
  return new Intl.DateTimeFormat('en-NZ', {
    hour: '2-digit',
    minute: '2-digit',
    hour12: true,
  }).format(new Date(iso))
}

function getTomorrowDate(): string {
  const d = new Date()
  d.setDate(d.getDate() + 1)
  return d.toISOString().split('T')[0]
}

export default function BookingPage({ orgSlug }: BookingPageProps) {
  const [pageData, setPageData] = useState<PageData | null>(null)
  const [slots, setSlots] = useState<TimeSlot[]>([])
  const [selectedDate, setSelectedDate] = useState(getTomorrowDate())
  const [selectedSlot, setSelectedSlot] = useState<TimeSlot | null>(null)
  const [loading, setLoading] = useState(true)
  const [slotsLoading, setSlotsLoading] = useState(false)
  const [error, setError] = useState('')
  const [success, setSuccess] = useState(false)
  const [submitting, setSubmitting] = useState(false)

  // Form fields
  const [name, setName] = useState('')
  const [email, setEmail] = useState('')
  const [phone, setPhone] = useState('')
  const [notes, setNotes] = useState('')

  // Fetch org page data
  useEffect(() => {
    async function load() {
      try {
        const res = await apiClient.get(`/api/v2/public/bookings/${orgSlug}`)
        setPageData(res.data)
      } catch {
        setError('Unable to load booking page.')
      } finally {
        setLoading(false)
      }
    }
    load()
  }, [orgSlug])

  // Fetch available slots when date changes
  const fetchSlots = useCallback(async () => {
    if (!selectedDate) return
    setSlotsLoading(true)
    try {
      const res = await apiClient.get(
        `/api/v2/public/bookings/${orgSlug}/slots?date=${selectedDate}`,
      )
      setSlots(res.data.slots)
      setSelectedSlot(null)
    } catch {
      setSlots([])
    } finally {
      setSlotsLoading(false)
    }
  }, [orgSlug, selectedDate])

  useEffect(() => { fetchSlots() }, [fetchSlots])

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault()
    if (!selectedSlot || !name.trim()) return

    setSubmitting(true)
    setError('')
    try {
      await apiClient.post(`/api/v2/public/bookings/${orgSlug}`, {
        customer_name: name.trim(),
        customer_email: email.trim() || null,
        customer_phone: phone.trim() || null,
        start_time: selectedSlot.start_time,
        notes: notes.trim() || null,
      })
      setSuccess(true)
    } catch {
      setError('Failed to submit booking. Please try again.')
    } finally {
      setSubmitting(false)
    }
  }

  if (loading) {
    return (
      <div className="min-h-screen flex items-center justify-center" role="status" aria-label="Loading booking page">
        <p className="text-gray-500">Loading…</p>
      </div>
    )
  }

  if (!pageData) {
    return (
      <div className="min-h-screen flex items-center justify-center">
        <p className="text-red-600">{error || 'Booking page not found.'}</p>
      </div>
    )
  }

  const primaryColour = pageData.primary_colour ?? '#2563eb'

  if (success) {
    return (
      <div className="min-h-screen flex items-center justify-center bg-gray-50">
        <div className="max-w-md w-full bg-white rounded-lg shadow-md p-8 text-center">
          {pageData.logo_url && (
            <img src={pageData.logo_url} alt={`${pageData.org_name} logo`} className="h-12 mx-auto mb-4" />
          )}
          <h1 className="text-2xl font-semibold text-gray-900 mb-2">Booking Confirmed</h1>
          <p className="text-gray-600">
            Thank you, {name}! Your booking has been submitted. You will receive a confirmation shortly.
          </p>
        </div>
      </div>
    )
  }

  const availableSlots = slots.filter((s) => s.available)

  return (
    <div className="min-h-screen bg-gray-50">
      {/* Header with org branding */}
      <header
        className="py-6 px-4 text-white text-center"
        style={{ backgroundColor: primaryColour }}
      >
        {pageData.logo_url && (
          <img src={pageData.logo_url} alt={`${pageData.org_name} logo`} className="h-10 mx-auto mb-2" />
        )}
        <h1 className="text-2xl font-bold">{pageData.org_name}</h1>
        <p className="text-sm opacity-90 mt-1">Book an appointment</p>
      </header>

      <main className="max-w-lg mx-auto py-8 px-4">
        {error && (
          <div className="mb-4 rounded-md border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700" role="alert">
            {error}
          </div>
        )}

        <form onSubmit={handleSubmit} className="space-y-6">
          {/* Date picker */}
          <div>
            <label htmlFor="booking-date" className="block text-sm font-medium text-gray-700 mb-1">
              Select Date
            </label>
            <input
              id="booking-date"
              type="date"
              value={selectedDate}
              onChange={(e) => setSelectedDate(e.target.value)}
              className="w-full rounded-md border border-gray-300 px-3 py-2 text-sm"
              required
            />
          </div>

          {/* Slot picker */}
          <div>
            <label className="block text-sm font-medium text-gray-700 mb-2">
              Available Times
            </label>
            {slotsLoading && <p className="text-sm text-gray-500" role="status" aria-label="Loading slots">Loading slots…</p>}
            {!slotsLoading && availableSlots.length === 0 && (
              <p className="text-sm text-gray-500">No available slots for this date.</p>
            )}
            {!slotsLoading && availableSlots.length > 0 && (
              <div className="grid grid-cols-3 gap-2" role="radiogroup" aria-label="Available time slots">
                {availableSlots.map((slot) => (
                  <button
                    key={slot.start_time}
                    type="button"
                    role="radio"
                    aria-checked={selectedSlot?.start_time === slot.start_time}
                    onClick={() => setSelectedSlot(slot)}
                    className={`rounded-md border px-3 py-2 text-sm font-medium transition-colors ${
                      selectedSlot?.start_time === slot.start_time
                        ? 'border-blue-500 bg-blue-50 text-blue-700'
                        : 'border-gray-300 bg-white text-gray-700 hover:bg-gray-50'
                    }`}
                  >
                    {formatSlotTime(slot.start_time)}
                  </button>
                ))}
              </div>
            )}
          </div>

          {/* Customer details */}
          <div>
            <label htmlFor="customer-name" className="block text-sm font-medium text-gray-700 mb-1">
              Your Name *
            </label>
            <input
              id="customer-name"
              type="text"
              value={name}
              onChange={(e) => setName(e.target.value)}
              className="w-full rounded-md border border-gray-300 px-3 py-2 text-sm"
              required
            />
          </div>

          <div>
            <label htmlFor="customer-email" className="block text-sm font-medium text-gray-700 mb-1">
              Email
            </label>
            <input
              id="customer-email"
              type="email"
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              className="w-full rounded-md border border-gray-300 px-3 py-2 text-sm"
            />
          </div>

          <div>
            <label htmlFor="customer-phone" className="block text-sm font-medium text-gray-700 mb-1">
              Phone
            </label>
            <input
              id="customer-phone"
              type="tel"
              value={phone}
              onChange={(e) => setPhone(e.target.value)}
              className="w-full rounded-md border border-gray-300 px-3 py-2 text-sm"
            />
          </div>

          <div>
            <label htmlFor="booking-notes" className="block text-sm font-medium text-gray-700 mb-1">
              Notes
            </label>
            <textarea
              id="booking-notes"
              value={notes}
              onChange={(e) => setNotes(e.target.value)}
              rows={3}
              className="w-full rounded-md border border-gray-300 px-3 py-2 text-sm"
            />
          </div>

          <button
            type="submit"
            disabled={!selectedSlot || !name.trim() || submitting}
            className="w-full rounded-md px-4 py-2 text-sm font-medium text-white disabled:opacity-50"
            style={{ backgroundColor: primaryColour }}
          >
            {submitting ? 'Submitting…' : 'Book Appointment'}
          </button>
        </form>
      </main>
    </div>
  )
}
