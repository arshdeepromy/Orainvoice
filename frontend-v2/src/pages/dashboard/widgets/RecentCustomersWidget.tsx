/**
 * Recent Customers Served Widget
 *
 * Displays the 10 most recently invoiced customers with name,
 * invoice date, and vehicle rego (nullable). Each entry navigates
 * to the customer profile page.
 *
 * Ported from frontend/src/pages/dashboard/widgets/RecentCustomersWidget.tsx
 * (Task 18). Data access (`data?.items ?? []`), the customer/booking links,
 * the inline SVG icon and the empty-state copy are preserved verbatim (FR-1);
 * presentation remapped onto the redesign tokens (FR-2): muted dividers, token
 * text colours, `.mono` rego chip.
 *
 * Requirements: 4.1, 4.2, 4.3, 4.4, 4.5
 */

import { Link } from 'react-router-dom'
import { WidgetCard } from './WidgetCard'
import type { RecentCustomer, WidgetDataSection } from './types'

interface RecentCustomersWidgetProps {
  data: WidgetDataSection<RecentCustomer> | undefined | null
  isLoading: boolean
  error: string | null
}

function UsersIcon({ className }: { className?: string }) {
  return (
    <svg className={className} fill="none" viewBox="0 0 24 24" stroke="currentColor" aria-hidden="true">
      <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5} d="M15 19.128a9.38 9.38 0 002.625.372 9.337 9.337 0 004.121-.952 4.125 4.125 0 00-7.533-2.493M15 19.128v-.003c0-1.113-.285-2.16-.786-3.07M15 19.128v.106A12.318 12.318 0 018.624 21c-2.331 0-4.512-.645-6.374-1.766l-.001-.109a6.375 6.375 0 0111.964-3.07M12 6.375a3.375 3.375 0 11-6.75 0 3.375 3.375 0 016.75 0zm8.25 2.25a2.625 2.625 0 11-5.25 0 2.625 2.625 0 015.25 0z" />
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

export function RecentCustomersWidget({ data, isLoading, error }: RecentCustomersWidgetProps) {
  const items = data?.items ?? []

  return (
    <WidgetCard
      title="Recent Customers"
      icon={UsersIcon}
      actionLink={{ label: 'View all', to: '/customers' }}
      isLoading={isLoading}
      error={error}
    >
      {items.length === 0 ? (
        <p className="text-[13px] text-muted">No recent customers</p>
      ) : (
        <ul className="divide-y divide-border">
          {items.map((customer) => (
            <li key={customer?.customer_id ?? Math.random()}>
              <Link
                to={`/customers/${customer?.customer_id}`}
                className="-mx-5 flex items-center justify-between px-5 py-2 transition-colors hover:bg-canvas"
              >
                <div className="min-w-0">
                  <p className="truncate text-[13.5px] font-medium text-text">
                    {customer?.customer_name ?? 'Unknown'}
                  </p>
                  <p className="mono text-[12px] text-muted">
                    {formatDate(customer?.invoice_date)}
                  </p>
                </div>
                {customer?.vehicle_rego && (
                  <span className="mono ml-2 shrink-0 rounded-chip bg-canvas px-2 py-0.5 text-[12px] font-medium text-muted">
                    {customer.vehicle_rego}
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
