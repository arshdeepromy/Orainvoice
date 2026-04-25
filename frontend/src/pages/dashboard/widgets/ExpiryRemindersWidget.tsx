/**
 * WOF/Service Expiry Reminders Widget
 *
 * Displays vehicles with upcoming WOF/service expiry. Provides
 * "Mark Reminder Sent" and "Dismiss" buttons with local state
 * tracking and backend persistence.
 *
 * Requirements: 11.1, 11.2, 11.3, 11.4, 11.5, 11.6, 11.7, 11.10
 */

import { useState } from 'react'
import apiClient from '@/api/client'
import { WidgetCard } from './WidgetCard'
import type { ExpiryReminder, WidgetDataSection } from './types'

interface ExpiryRemindersWidgetProps {
  data: WidgetDataSection<ExpiryReminder> | undefined | null
  isLoading: boolean
  error: string | null
}

function BellIcon({ className }: { className?: string }) {
  return (
    <svg className={className} fill="none" viewBox="0 0 24 24" stroke="currentColor" aria-hidden="true">
      <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5} d="M14.857 17.082a23.848 23.848 0 005.454-1.31A8.967 8.967 0 0118 9.75v-.7V9A6 6 0 006 9v.75a8.967 8.967 0 01-2.312 6.022c1.733.64 3.56 1.085 5.455 1.31m5.714 0a24.255 24.255 0 01-5.714 0m5.714 0a3 3 0 11-5.714 0" />
    </svg>
  )
}

function formatDate(iso: string | null | undefined): string {
  if (!iso) return ''
  try {
    return new Date(iso).toLocaleDateString('en-NZ', {
      day: 'numeric',
      month: 'short',
      year: 'numeric',
    })
  } catch {
    return iso
  }
}

/** Unique key for tracking dismissed/sent items locally */
function reminderKey(item: ExpiryReminder): string {
  return `${item?.vehicle_id ?? ''}-${item?.expiry_type ?? ''}-${item?.expiry_date ?? ''}`
}

export function ExpiryRemindersWidget({ data, isLoading, error }: ExpiryRemindersWidgetProps) {
  const items = data?.items ?? []

  // Local state to track dismissed and sent items
  const [dismissed, setDismissed] = useState<Set<string>>(new Set())
  const [sent, setSent] = useState<Set<string>>(new Set())
  const [actionLoading, setActionLoading] = useState<Set<string>>(new Set())

  async function handleAction(item: ExpiryReminder, action: 'dismiss' | 'mark_sent') {
    const key = reminderKey(item)
    setActionLoading((prev) => new Set(prev).add(key))

    try {
      await apiClient.post(`/dashboard/reminders/${item?.expiry_type ?? 'wof'}/dismiss`, {
        vehicle_id: item?.vehicle_id,
        expiry_date: item?.expiry_date,
        action,
      })

      if (action === 'dismiss') {
        setDismissed((prev) => new Set(prev).add(key))
      } else {
        setSent((prev) => new Set(prev).add(key))
      }
    } catch {
      // Silently fail — the item stays visible so the user can retry
    } finally {
      setActionLoading((prev) => {
        const next = new Set(prev)
        next.delete(key)
        return next
      })
    }
  }

  // Filter out dismissed items from the visible list
  const visibleItems = items.filter((item) => !dismissed.has(reminderKey(item)))

  return (
    <WidgetCard
      title="WOF / Service Expiry Reminders"
      icon={BellIcon}
      isLoading={isLoading}
      error={error}
    >
      {visibleItems.length === 0 ? (
        <p className="text-sm text-gray-500">No upcoming WOF or service expiries</p>
      ) : (
        <div className="overflow-x-auto -mx-4">
          <table className="min-w-full text-left text-sm">
            <thead>
              <tr className="border-b border-gray-100">
                <th className="px-4 py-2 text-xs font-medium text-gray-500">Rego</th>
                <th className="px-4 py-2 text-xs font-medium text-gray-500">Vehicle</th>
                <th className="px-4 py-2 text-xs font-medium text-gray-500">Type</th>
                <th className="px-4 py-2 text-xs font-medium text-gray-500">Expiry</th>
                <th className="px-4 py-2 text-xs font-medium text-gray-500">Customer</th>
                <th className="px-4 py-2 text-xs font-medium text-gray-500 text-right">Actions</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-gray-50">
              {visibleItems.map((item) => {
                const key = reminderKey(item)
                const isSent = sent.has(key)
                const isActioning = actionLoading.has(key)

                return (
                  <tr key={key} className="hover:bg-gray-50">
                    <td className="px-4 py-2 font-medium text-gray-900 whitespace-nowrap">
                      {item?.vehicle_rego ?? '—'}
                    </td>
                    <td className="px-4 py-2 text-gray-600 whitespace-nowrap">
                      {[item?.vehicle_make, item?.vehicle_model].filter(Boolean).join(' ') || '—'}
                    </td>
                    <td className="px-4 py-2 whitespace-nowrap">
                      <span className={`inline-flex rounded-full px-2 py-0.5 text-xs font-medium ${
                        item?.expiry_type === 'wof'
                          ? 'bg-blue-100 text-blue-700'
                          : 'bg-purple-100 text-purple-700'
                      }`}>
                        {(item?.expiry_type ?? 'wof').toUpperCase()}
                      </span>
                    </td>
                    <td className="px-4 py-2 text-gray-600 whitespace-nowrap">
                      {formatDate(item?.expiry_date)}
                    </td>
                    <td className="px-4 py-2 text-gray-600 whitespace-nowrap">
                      {item?.customer_name ?? 'Unknown'}
                    </td>
                    <td className="px-4 py-2 text-right whitespace-nowrap">
                      {isSent ? (
                        <span className="inline-flex items-center rounded-full bg-green-100 px-2 py-0.5 text-xs font-medium text-green-700">
                          Sent
                        </span>
                      ) : (
                        <div className="flex items-center justify-end gap-1">
                          <button
                            type="button"
                            disabled={isActioning}
                            onClick={() => handleAction(item, 'mark_sent')}
                            className="rounded px-2 py-1 text-xs font-medium text-blue-600 hover:bg-blue-50 disabled:opacity-50 transition-colors"
                          >
                            {isActioning ? '…' : 'Mark Sent'}
                          </button>
                          <button
                            type="button"
                            disabled={isActioning}
                            onClick={() => handleAction(item, 'dismiss')}
                            className="rounded px-2 py-1 text-xs font-medium text-gray-500 hover:bg-gray-100 disabled:opacity-50 transition-colors"
                          >
                            Dismiss
                          </button>
                        </div>
                      )}
                    </td>
                  </tr>
                )
              })}
            </tbody>
          </table>
        </div>
      )}
    </WidgetCard>
  )
}
