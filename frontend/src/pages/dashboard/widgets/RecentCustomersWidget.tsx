/**
 * Recent Customers Served Widget
 *
 * Displays the 10 most recently invoiced customers with name,
 * invoice date, and vehicle rego (nullable). Each entry navigates
 * to the customer profile page.
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
        <p className="text-sm text-gray-500">No recent customers</p>
      ) : (
        <ul className="divide-y divide-gray-100">
          {items.map((customer) => (
            <li key={customer?.customer_id ?? Math.random()}>
              <Link
                to={`/customers/${customer?.customer_id}`}
                className="flex items-center justify-between py-2 hover:bg-gray-50 -mx-4 px-4 transition-colors"
              >
                <div className="min-w-0">
                  <p className="text-sm font-medium text-gray-900 truncate">
                    {customer?.customer_name ?? 'Unknown'}
                  </p>
                  <p className="text-xs text-gray-500">
                    {formatDate(customer?.invoice_date)}
                  </p>
                </div>
                {customer?.vehicle_rego && (
                  <span className="ml-2 shrink-0 rounded bg-gray-100 px-2 py-0.5 text-xs font-medium text-gray-700">
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
