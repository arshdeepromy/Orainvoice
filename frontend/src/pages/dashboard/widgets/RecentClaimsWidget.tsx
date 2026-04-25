/**
 * Recent Claims Widget
 *
 * Displays the 10 most recent claims with reference, customer name,
 * date, and colour-coded status badge. Each entry navigates to the
 * claim detail page.
 *
 * Requirements: 9.1, 9.2, 9.3, 9.4, 9.6
 */

import { Link } from 'react-router-dom'
import { WidgetCard } from './WidgetCard'
import type { RecentClaim, WidgetDataSection } from './types'

interface RecentClaimsWidgetProps {
  data: WidgetDataSection<RecentClaim> | undefined | null
  isLoading: boolean
  error: string | null
}

function ShieldIcon({ className }: { className?: string }) {
  return (
    <svg className={className} fill="none" viewBox="0 0 24 24" stroke="currentColor" aria-hidden="true">
      <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5} d="M9 12.75L11.25 15 15 9.75m-3-7.036A11.959 11.959 0 013.598 6 11.99 11.99 0 003 9.749c0 5.592 3.824 10.29 9 11.623 5.176-1.332 9-6.03 9-11.622 0-1.31-.21-2.571-.598-3.751h-.152c-3.196 0-6.1-1.248-8.25-3.285z" />
    </svg>
  )
}

function statusBadge(status: string | null | undefined) {
  const s = status ?? 'open'
  const config: Record<string, { bg: string; text: string; label: string }> = {
    resolved:      { bg: 'bg-green-100',  text: 'text-green-700',  label: 'Resolved' },
    investigating: { bg: 'bg-amber-100',  text: 'text-amber-700',  label: 'Investigating' },
    approved:      { bg: 'bg-amber-100',  text: 'text-amber-700',  label: 'Approved' },
    rejected:      { bg: 'bg-red-100',    text: 'text-red-700',    label: 'Rejected' },
    open:          { bg: 'bg-gray-100',   text: 'text-gray-700',   label: 'Open' },
  }
  const c = config[s] ?? config.open
  return (
    <span className={`inline-flex items-center rounded-full px-2 py-0.5 text-xs font-medium ${c.bg} ${c.text}`}>
      {c.label}
    </span>
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

export function RecentClaimsWidget({ data, isLoading, error }: RecentClaimsWidgetProps) {
  const items = data?.items ?? []

  return (
    <WidgetCard
      title="Recent Claims"
      icon={ShieldIcon}
      actionLink={{ label: 'View all', to: '/claims' }}
      isLoading={isLoading}
      error={error}
    >
      {items.length === 0 ? (
        <p className="text-sm text-gray-500">No recent claims</p>
      ) : (
        <ul className="divide-y divide-gray-100">
          {items.map((claim) => (
            <li key={claim?.claim_id ?? Math.random()}>
              <Link
                to={`/claims/${claim?.claim_id}`}
                className="flex items-center justify-between py-2 hover:bg-gray-50 -mx-4 px-4 transition-colors"
              >
                <div className="min-w-0">
                  <div className="flex items-center gap-2">
                    <p className="text-sm font-medium text-gray-900">
                      {claim?.reference ?? 'N/A'}
                    </p>
                    {statusBadge(claim?.status)}
                  </div>
                  <p className="text-xs text-gray-500 mt-0.5">
                    {claim?.customer_name ?? 'Unknown'} · {formatDate(claim?.claim_date)}
                  </p>
                </div>
              </Link>
            </li>
          ))}
        </ul>
      )}
    </WidgetCard>
  )
}
