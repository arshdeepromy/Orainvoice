/**
 * Job card sorting utilities.
 *
 * Sorts job cards by status priority (in_progress first, open/pending second,
 * completed/invoiced last), then by created_at descending within each group.
 *
 * Requirements: 25.1, 56.3
 */

export interface SortableJobCard {
  status: string
  created_at: string
  [key: string]: unknown
}

/**
 * Status priority order.
 * Lower number = higher priority (appears first).
 */
export const STATUS_ORDER: Record<string, number> = {
  in_progress: 0,
  pending: 1,
  open: 1,
  completed: 2,
  invoiced: 2,
  cancelled: 3,
}

/**
 * Sort job cards by status priority then by created_at descending.
 *
 * - in_progress jobs appear first
 * - open/pending jobs appear second
 * - completed/invoiced jobs appear last
 * - Within each status group, most recent (by created_at) first
 */
export function sortJobCards<T extends SortableJobCard>(cards: T[]): T[] {
  return [...cards].sort((a, b) => {
    const orderA = STATUS_ORDER[a.status ?? 'pending'] ?? 99
    const orderB = STATUS_ORDER[b.status ?? 'pending'] ?? 99
    if (orderA !== orderB) return orderA - orderB
    // Within same status group, sort by created_at descending
    return (b.created_at ?? '').localeCompare(a.created_at ?? '')
  })
}
