/**
 * Active Staff Widget
 *
 * Displays a list of clocked-in staff with name and clock-in time.
 * Header summary shows total count of active staff.
 *
 * Requirements: 10.1, 10.2, 10.3, 10.4
 */

import { WidgetCard } from './WidgetCard'
import type { ActiveStaffMember, WidgetDataSection } from './types'

interface ActiveStaffWidgetProps {
  data: WidgetDataSection<ActiveStaffMember> | undefined | null
  isLoading: boolean
  error: string | null
}

function UsersClockIcon({ className }: { className?: string }) {
  return (
    <svg className={className} fill="none" viewBox="0 0 24 24" stroke="currentColor" aria-hidden="true">
      <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5} d="M15.75 6a3.75 3.75 0 11-7.5 0 3.75 3.75 0 017.5 0zM4.501 20.118a7.5 7.5 0 0114.998 0A17.933 17.933 0 0112 21.75c-2.676 0-5.216-.584-7.499-1.632z" />
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

export function ActiveStaffWidget({ data, isLoading, error }: ActiveStaffWidgetProps) {
  const items = data?.items ?? []
  const total = data?.total ?? items.length

  return (
    <WidgetCard
      title="Active Staff"
      icon={UsersClockIcon}
      isLoading={isLoading}
      error={error}
    >
      {items.length === 0 ? (
        <p className="text-sm text-gray-500">No staff currently clocked in</p>
      ) : (
        <div>
          <div className="mb-3 flex items-center gap-2">
            <span className="inline-flex items-center justify-center rounded-full bg-green-100 px-2.5 py-0.5 text-xs font-medium text-green-700">
              {(total ?? 0).toLocaleString()} active
            </span>
          </div>
          <ul className="divide-y divide-gray-100">
            {items.map((staff) => (
              <li
                key={staff?.staff_id ?? Math.random()}
                className="flex items-center justify-between py-2"
              >
                <div className="flex items-center gap-2 min-w-0">
                  <span className="inline-flex h-7 w-7 items-center justify-center rounded-full bg-blue-100 text-xs font-medium text-blue-700">
                    {(staff?.name ?? '?').charAt(0).toUpperCase()}
                  </span>
                  <p className="text-sm font-medium text-gray-900 truncate">
                    {staff?.name ?? 'Unknown'}
                  </p>
                </div>
                <span className="shrink-0 text-xs text-gray-500">
                  Clocked in {formatTime(staff?.clock_in_time)}
                </span>
              </li>
            ))}
          </ul>
        </div>
      )}
    </WidgetCard>
  )
}
