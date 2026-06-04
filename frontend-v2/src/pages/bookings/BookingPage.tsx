/**
 * BookingPage — Task 28 port of frontend/src/pages/bookings/BookingPage.tsx.
 *
 * Public-facing booking page (no auth) with org branding, date + slot picker,
 * and the customer details form. ALL logic copied VERBATIM: org page-data fetch
 * (GET /api/v2/public/bookings/:slug), available-slot fetch on date change,
 * submit (POST /api/v2/public/bookings/:slug), success state. Presentation
 * remapped onto the design tokens (FR-2b) while keeping the org's primary colour
 * for the header + CTA (public branded surface).
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

const FIELD_CLS = 'w-full rounded-ctl border border-border bg-card px-3 py-2 text-[13.5px] text-text focus:border-accent focus:outline-none focus:shadow-[0_0_0_3px_var(--accent-soft)]'

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
      setSlots(res.data?.slots ?? [])
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
      <div className="flex min-h-screen items-center justify-center" role="status" aria-label="Loading booking page">
        <p className="text-muted">Loading…</p>
      </div>
    )
  }

  if (!pageData) {
    return (
      <div className="flex min-h-screen items-center justify-center">
        <p className="text-danger">{error || 'Booking page not found.'}</p>
      </div>
    )
  }

  const primaryColour = pageData.primary_colour ?? 'var(--accent)'

  if (success) {
    return (
      <div className="flex min-h-screen items-center justify-center bg-canvas">
        <div className="w-full max-w-md rounded-card bg-card p-8 text-center shadow-pop">
          {pageData.logo_url && (
            <img src={pageData.logo_url} alt={`${pageData.org_name} logo`} className="mx-auto mb-4 h-12" />
          )}
          <h1 className="mb-2 text-2xl font-semibold text-text">Booking Confirmed</h1>
          <p className="text-muted">
            Thank you, {name}! Your booking has been submitted. You will receive a confirmation shortly.
          </p>
        </div>
      </div>
    )
  }

  const availableSlots = slots.filter((s) => s.available)

  return (
    <div className="min-h-screen bg-canvas">
      {/* Header with org branding */}
      <header
        className="px-4 py-6 text-center text-white"
        style={{ backgroundColor: primaryColour }}
      >
        {pageData.logo_url && (
          <img src={pageData.logo_url} alt={`${pageData.org_name} logo`} className="mx-auto mb-2 h-10" />
        )}
        <h1 className="text-2xl font-bold">{pageData.org_name}</h1>
        <p className="mt-1 text-sm opacity-90">Book an appointment</p>
      </header>

      <main className="mx-auto max-w-lg px-4 py-8">
        {error && (
          <div className="mb-4 rounded-ctl border border-danger/30 bg-danger-soft px-4 py-3 text-[13px] text-danger" role="alert">
            {error}
          </div>
        )}

        <form onSubmit={handleSubmit} className="space-y-6">
          {/* Date picker */}
          <div>
            <label htmlFor="booking-date" className="mb-1 block text-[12.5px] font-medium text-text">
              Select Date
            </label>
            <input
              id="booking-date"
              type="date"
              value={selectedDate}
              onChange={(e) => setSelectedDate(e.target.value)}
              className={FIELD_CLS}
              required
            />
          </div>

          {/* Slot picker */}
          <div>
            <label className="mb-2 block text-[12.5px] font-medium text-text">
              Available Times
            </label>
            {slotsLoading && <p className="text-[13px] text-muted" role="status" aria-label="Loading slots">Loading slots…</p>}
            {!slotsLoading && availableSlots.length === 0 && (
              <p className="text-[13px] text-muted">No available slots for this date.</p>
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
                    className={`rounded-ctl border px-3 py-2 text-[13px] font-medium transition-colors ${
                      selectedSlot?.start_time === slot.start_time
                        ? 'border-accent bg-accent-soft text-accent'
                        : 'border-border bg-card text-text hover:bg-canvas'
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
            <label htmlFor="customer-name" className="mb-1 block text-[12.5px] font-medium text-text">
              Your Name *
            </label>
            <input
              id="customer-name"
              type="text"
              value={name}
              onChange={(e) => setName(e.target.value)}
              className={FIELD_CLS}
              required
            />
          </div>

          <div>
            <label htmlFor="customer-email" className="mb-1 block text-[12.5px] font-medium text-text">
              Email
            </label>
            <input
              id="customer-email"
              type="email"
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              className={FIELD_CLS}
            />
          </div>

          <div>
            <label htmlFor="customer-phone" className="mb-1 block text-[12.5px] font-medium text-text">
              Phone
            </label>
            <input
              id="customer-phone"
              type="tel"
              value={phone}
              onChange={(e) => setPhone(e.target.value)}
              className={FIELD_CLS}
            />
          </div>

          <div>
            <label htmlFor="booking-notes" className="mb-1 block text-[12.5px] font-medium text-text">
              Notes
            </label>
            <textarea
              id="booking-notes"
              value={notes}
              onChange={(e) => setNotes(e.target.value)}
              rows={3}
              className={FIELD_CLS}
            />
          </div>

          <button
            type="submit"
            disabled={!selectedSlot || !name.trim() || submitting}
            className="w-full rounded-ctl px-4 py-2 text-sm font-medium text-white disabled:opacity-50"
            style={{ backgroundColor: primaryColour }}
          >
            {submitting ? 'Submitting…' : 'Book Appointment'}
          </button>
        </form>
      </main>
    </div>
  )
}
