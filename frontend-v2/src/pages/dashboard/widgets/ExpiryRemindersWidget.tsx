/**
 * WOF/Service Expiry Reminders Widget
 *
 * Displays vehicles with upcoming WOF/service expiry. Provides
 * "Mark Reminder Sent" and "Dismiss" buttons with local state
 * tracking and backend persistence.
 *
 * Ported from frontend/src/pages/dashboard/widgets/ExpiryRemindersWidget.tsx
 * (Task 18). ALL logic preserved verbatim (FR-1): the `dismissed` / `sent` /
 * `actionLoading` Sets, the `reminderKey` derivation, the
 * `POST /dashboard/reminders/{type}/dismiss` mutation (with the
 * `{ vehicle_id, expiry_date, action }` body and silent-fail/retry handling),
 * and the `visibleItems` filter. Presentation remapped onto the redesign tokens
 * (FR-2): token table borders, the WOF/service type pills (accent vs purple),
 * the "Sent" pill (ok), and accent / muted action buttons.
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
        <p className="text-[13px] text-muted">No upcoming WOF or service expiries</p>
      ) : (
        <div className="-mx-5 overflow-x-auto">
          <table className="min-w-full text-left text-[13px]">
            <thead>
              <tr className="border-b border-border">
                <th className="mono px-5 py-2 text-[10.5px] font-medium uppercase tracking-[0.08em] text-muted-2">Rego</th>
                <th className="mono px-5 py-2 text-[10.5px] font-medium uppercase tracking-[0.08em] text-muted-2">Vehicle</th>
                <th className="mono px-5 py-2 text-[10.5px] font-medium uppercase tracking-[0.08em] text-muted-2">Type</th>
                <th className="mono px-5 py-2 text-[10.5px] font-medium uppercase tracking-[0.08em] text-muted-2">Expiry</th>
                <th className="mono px-5 py-2 text-[10.5px] font-medium uppercase tracking-[0.08em] text-muted-2">Customer</th>
                <th className="mono px-5 py-2 text-right text-[10.5px] font-medium uppercase tracking-[0.08em] text-muted-2">Actions</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-border">
              {visibleItems.map((item) => {
                const key = reminderKey(item)
                const isSent = sent.has(key)
                const isActioning = actionLoading.has(key)

                return (
                  <tr key={key} className="transition-colors hover:bg-canvas">
                    <td className="mono whitespace-nowrap px-5 py-2 font-medium text-text">
                      {item?.vehicle_rego ?? '—'}
                    </td>
                    <td className="whitespace-nowrap px-5 py-2 text-muted">
                      {[item?.vehicle_make, item?.vehicle_model].filter(Boolean).join(' ') || '—'}
                    </td>
                    <td className="whitespace-nowrap px-5 py-2">
                      <span className={`inline-flex rounded-full px-2 py-0.5 text-[11.5px] font-medium ${
                        item?.expiry_type === 'wof'
                          ? 'bg-accent-soft text-accent'
                          : 'bg-purple-soft text-purple'
                      }`}>
                        {(item?.expiry_type ?? 'wof').toUpperCase()}
                      </span>
                    </td>
                    <td className="mono whitespace-nowrap px-5 py-2 text-muted">
                      {formatDate(item?.expiry_date)}
                    </td>
                    <td className="whitespace-nowrap px-5 py-2 text-muted">
                      {item?.customer_name ?? 'Unknown'}
                    </td>
                    <td className="whitespace-nowrap px-5 py-2 text-right">
                      {isSent ? (
                        <span className="inline-flex items-center rounded-full bg-ok-soft px-2 py-0.5 text-[11.5px] font-medium text-ok">
                          Sent
                        </span>
                      ) : (
                        <div className="flex items-center justify-end gap-1">
                          <button
                            type="button"
                            disabled={isActioning}
                            onClick={() => handleAction(item, 'mark_sent')}
                            className="rounded px-2 py-1 text-[12px] font-medium text-accent transition-colors hover:bg-accent-soft disabled:opacity-50"
                          >
                            {isActioning ? '…' : 'Mark Sent'}
                          </button>
                          <button
                            type="button"
                            disabled={isActioning}
                            onClick={() => handleAction(item, 'dismiss')}
                            className="rounded px-2 py-1 text-[12px] font-medium text-muted transition-colors hover:bg-canvas disabled:opacity-50"
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
