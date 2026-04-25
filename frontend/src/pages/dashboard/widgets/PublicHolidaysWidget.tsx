/**
 * Public Holidays Widget
 *
 * Displays the next 5 upcoming public holidays with name and date,
 * sorted by date ascending.
 *
 * Requirements: 6.1, 6.2, 6.3, 6.4
 */

import { WidgetCard } from './WidgetCard'
import type { PublicHoliday, WidgetDataSection } from './types'

interface PublicHolidaysWidgetProps {
  data: WidgetDataSection<PublicHoliday> | undefined | null
  isLoading: boolean
  error: string | null
}

function GlobeIcon({ className }: { className?: string }) {
  return (
    <svg className={className} fill="none" viewBox="0 0 24 24" stroke="currentColor" aria-hidden="true">
      <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5} d="M12 21a9.004 9.004 0 008.716-6.747M12 21a9.004 9.004 0 01-8.716-6.747M12 21c2.485 0 4.5-4.03 4.5-9S14.485 3 12 3m0 18c-2.485 0-4.5-4.03-4.5-9S9.515 3 12 3m0 0a8.997 8.997 0 017.843 4.582M12 3a8.997 8.997 0 00-7.843 4.582m15.686 0A11.953 11.953 0 0112 10.5c-2.998 0-5.74-1.1-7.843-2.918m15.686 0A8.959 8.959 0 0121 12c0 .778-.099 1.533-.284 2.253m0 0A17.919 17.919 0 0112 16.5a17.92 17.92 0 01-8.716-2.247m0 0A9.015 9.015 0 003 12c0-1.605.42-3.113 1.157-4.418" />
    </svg>
  )
}

function formatDate(iso: string | null | undefined): string {
  if (!iso) return ''
  try {
    return new Date(iso).toLocaleDateString('en-NZ', {
      weekday: 'short',
      day: 'numeric',
      month: 'short',
      year: 'numeric',
    })
  } catch {
    return iso
  }
}

export function PublicHolidaysWidget({ data, isLoading, error }: PublicHolidaysWidgetProps) {
  const items = data?.items ?? []

  return (
    <WidgetCard
      title="Upcoming Public Holidays"
      icon={GlobeIcon}
      isLoading={isLoading}
      error={error}
    >
      {items.length === 0 ? (
        <p className="text-sm text-gray-500">No upcoming public holidays</p>
      ) : (
        <ul className="divide-y divide-gray-100">
          {items.map((holiday, idx) => (
            <li
              key={`${holiday?.holiday_date ?? idx}-${holiday?.name ?? idx}`}
              className="flex items-center justify-between py-2"
            >
              <p className="text-sm font-medium text-gray-900">
                {holiday?.name ?? 'Unknown Holiday'}
              </p>
              <span className="shrink-0 text-xs text-gray-500">
                {formatDate(holiday?.holiday_date)}
              </span>
            </li>
          ))}
        </ul>
      )}
    </WidgetCard>
  )
}
