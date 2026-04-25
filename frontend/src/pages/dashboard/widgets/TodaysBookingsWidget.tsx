/**
 * Today's Bookings Widget
 *
 * Displays today's bookings sorted by time ascending with time,
 * customer name, and vehicle rego. Each entry navigates to the
 * booking detail page.
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
        <p className="text-sm text-gray-500">No bookings for today</p>
      ) : (
        <ul className="divide-y divide-gray-100">
          {items.map((booking) => (
            <li key={booking?.booking_id ?? Math.random()}>
              <Link
                to={`/bookings/${booking?.booking_id}`}
                className="flex items-center justify-between py-2 hover:bg-gray-50 -mx-4 px-4 transition-colors"
              >
                <div className="flex items-center gap-3 min-w-0">
                  <span className="shrink-0 text-sm font-medium text-blue-600">
                    {formatTime(booking?.scheduled_time)}
                  </span>
                  <div className="min-w-0">
                    <p className="text-sm font-medium text-gray-900 truncate">
                      {booking?.customer_name ?? 'Unknown'}
                    </p>
                  </div>
                </div>
                {booking?.vehicle_rego && (
                  <span className="ml-2 shrink-0 rounded bg-gray-100 px-2 py-0.5 text-xs font-medium text-gray-700">
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
