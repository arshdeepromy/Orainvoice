/**
 * Recent Claims Widget
 *
 * Displays the 10 most recent claims with reference, customer name,
 * date, and colour-coded status badge. Each entry navigates to the
 * claim detail page.
 *
 * Ported from frontend/src/pages/dashboard/widgets/RecentClaimsWidget.tsx
 * (Task 18). Logic — the status→badge config map (resolved/investigating/
 * approved/rejected/open), `formatDate`, the `/claims/:id` link and the action
 * link — preserved verbatim (FR-1); presentation remapped onto the redesign
 * tokens (FR-2): the status pill colours use the ok/warn/danger/neutral soft
 * tones from ds.css.
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
  const config: Record<string, { cls: string; label: string }> = {
    resolved:      { cls: 'bg-ok-soft text-ok',          label: 'Resolved' },
    investigating: { cls: 'bg-warn-soft text-warn',      label: 'Investigating' },
    approved:      { cls: 'bg-warn-soft text-warn',      label: 'Approved' },
    rejected:      { cls: 'bg-danger-soft text-danger',  label: 'Rejected' },
    open:          { cls: 'bg-[#EEF0F4] text-muted',     label: 'Open' },
  }
  const c = config[s] ?? config.open
  return (
    <span className={`inline-flex items-center rounded-full px-2 py-0.5 text-[11.5px] font-medium ${c.cls}`}>
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
        <p className="text-[13px] text-muted">No recent claims</p>
      ) : (
        <ul className="divide-y divide-border">
          {items.map((claim) => (
            <li key={claim?.claim_id ?? Math.random()}>
              <Link
                to={`/claims/${claim?.claim_id}`}
                className="-mx-5 flex items-center justify-between px-5 py-2 transition-colors hover:bg-canvas"
              >
                <div className="min-w-0">
                  <div className="flex items-center gap-2">
                    <p className="text-[13.5px] font-medium text-text">
                      {claim?.reference ?? 'N/A'}
                    </p>
                    {statusBadge(claim?.status)}
                  </div>
                  <p className="mt-0.5 text-[12px] text-muted">
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
