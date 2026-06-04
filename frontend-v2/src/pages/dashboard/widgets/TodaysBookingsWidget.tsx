/**
 * Today's Bookings Widget
 *
 * Displays today's bookings sorted by time ascending with time,
 * customer name, and vehicle rego. Each entry navigates to the
 * booking detail page.
 *
 * Ported from frontend/src/pages/dashboard/widgets/TodaysBookingsWidget.tsx
 * (Task 18). Logic, inline icon, the `/bookings/:id` link and the empty-state
 * copy are preserved verbatim (FR-1); presentation remapped onto the redesign
 * tokens (FR-2): accent time label, `.mono` rego chip, token dividers.
 *
 * Requirements: 5.1, 5.2, 5.3, 5.4, 5.5
 */

import { Link } from 'react-router-dom'
import { WidgetCard } from './WidgetCard'
import type { TodayBooking, WidgetDataSection } from './types'

interface TodaysBookingsWidgetProps {
  data: WidgetDataSection<TodayBooking> | undefined | null
  isLoading: boolean
  error: string | null
}

function CalendarIcon({ className }: { className?: string }) {
  return (
    <svg className={className} fill="none" viewBox="0 0 24 24" stroke="currentColor" aria-hidden="true">
      <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5} d="M6.75 3v2.25M17.25 3v2.25M3 18.75V7.5a2.25 2.25 0 012.25-2.25h13.5A2.25 2.25 0 0121 7.5v11.25m-18 0A2.25 2.25 0 005.25 21h13.5A2.25 2.25 0 0021 18.75m-18 0v-7.5A2.25 2.25 0 015.25 9h13.5A2.25 2.25 0 0121 11.25v7.5" />
    </svg>
  )
}

function formatTime(iso: string | null | undefined): string {
  if (!iso) return ''
  try {
    return new Date(iso).toLocaleTimeString('en-NZ', {
      hour: '2-digit',
      minute: '2-digit',
    })
  } catch {
    return iso
  }
}

export function TodaysBookingsWidget({ data, isLoading, error }: TodaysBookingsWidgetProps) {
  const items = data?.items ?? []

  return (
    <WidgetCard
      title="Today's Bookings"
      icon={CalendarIcon}
      actionLink={{ label: 'View all', to: '/bookings' }}
      isLoading={isLoading}
      error={error}
    >
      {items.length === 0 ? (
        <p className="text-[13px] text-muted">No bookings for today</p>
      ) : (
        <ul className="divide-y divide-border">
          {items.map((booking) => (
            <li key={booking?.booking_id ?? Math.random()}>
              <Link
                to={`/bookings/${booking?.booking_id}`}
                className="-mx-5 flex items-center justify-between px-5 py-2 transition-colors hover:bg-canvas"
              >
                <div className="flex min-w-0 items-center gap-3">
                  <span className="mono shrink-0 text-[13px] font-medium text-accent">
                    {formatTime(booking?.scheduled_time)}
                  </span>
                  <div className="min-w-0">
                    <p className="truncate text-[13.5px] font-medium text-text">
                      {booking?.customer_name ?? 'Unknown'}
                    </p>
                  </div>
                </div>
                {booking?.vehicle_rego && (
                  <span className="mono ml-2 shrink-0 rounded-chip bg-canvas px-2 py-0.5 text-[12px] font-medium text-muted">
                    {booking.vehicle_rego}
                  </span>
                )}
              </Link>
            </li>
          ))}
        </ul>
      )}
    </WidgetCard>
  )
}
