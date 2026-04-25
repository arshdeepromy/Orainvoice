import { useCallback } from 'react'
import { useNavigate } from 'react-router-dom'
import type { StaffMember } from '@shared/types/staff'
import { useApiList } from '@/hooks/useApiList'
import { MobileList, MobileListItem, MobileBadge } from '@/components/ui'
import { SwipeAction } from '@/components/gestures/SwipeAction'
import { PullRefresh } from '@/components/gestures/PullRefresh'

/* ------------------------------------------------------------------ */
/* Inline SVG icon components for swipe actions                       */
/* ------------------------------------------------------------------ */

function PhoneIcon({ className }: { className?: string }) {
  return (
    <svg
      className={className}
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="2"
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
    >
      <path d="M22 16.92v3a2 2 0 0 1-2.18 2 19.79 19.79 0 0 1-8.63-3.07 19.5 19.5 0 0 1-6-6 19.79 19.79 0 0 1-3.07-8.67A2 2 0 0 1 4.11 2h3a2 2 0 0 1 2 1.72c.127.96.361 1.903.7 2.81a2 2 0 0 1-.45 2.11L8.09 9.91a16 16 0 0 0 6 6l1.27-1.27a2 2 0 0 1 2.11-.45c.907.339 1.85.573 2.81.7A2 2 0 0 1 22 16.92z" />
    </svg>
  )
}

function MailIcon({ className }: { className?: string }) {
  return (
    <svg
      className={className}
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="2"
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
    >
      <rect width="20" height="16" x="2" y="4" rx="2" />
      <path d="m22 7-8.97 5.7a1.94 1.94 0 0 1-2.06 0L2 7" />
    </svg>
  )
}

/* ------------------------------------------------------------------ */
/* Helpers                                                            */
/* ------------------------------------------------------------------ */

function displayName(s: StaffMember): string {
  const parts = [s.first_name, s.last_name].filter(Boolean)
  return parts.join(' ') || 'Unnamed'
}

function roleLabel(role: string): string {
  return (role ?? 'staff').replace(/_/g, ' ').replace(/\b\w/g, (c) => c.toUpperCase())
}

export function handleCall(phone: string | null) {
  if (!phone) return
  window.open(`tel:${phone}`, '_system')
}

export function handleEmail(email: string | null) {
  if (!email) return
  window.open(`mailto:${email}`, '_system')
}

/**
 * Staff list screen — list with name, role, contact details.
 * Swipe actions for Call and Email. Pull-to-refresh.
 * Wrapped in ModuleGate at the route level.
 *
 * Requirements: 18.1, 18.3
 */
export default function StaffListScreen() {
  const navigate = useNavigate()

  const {
    items,
    isLoading,
    isRefreshing,
    hasMore,
    search,
    setSearch,
    refresh,
    loadMore,
  } = useApiList<StaffMember>({
    endpoint: '/api/v2/staff',
    dataKey: 'items',
  })

  const handleTap = useCallback(
    (staff: StaffMember) => {
      navigate(`/staff/${staff.id}`)
    },
    [navigate],
  )

  const renderItem = useCallback(
    (staff: StaffMember) => {
      const rightActions = [
        ...(staff.phone
          ? [
              {
                label: 'Call',
                icon: PhoneIcon,
                color: 'bg-green-500',
                onAction: () => handleCall(staff.phone),
              },
            ]
          : []),
        ...(staff.email
          ? [
              {
                label: 'Email',
                icon: MailIcon,
                color: 'bg-purple-500',
                onAction: () => handleEmail(staff.email),
              },
            ]
          : []),
      ]

      return (
        <SwipeAction rightActions={rightActions}>
          <MobileListItem
            title={displayName(staff)}
            subtitle={staff.email ?? staff.phone ?? undefined}
            trailing={
              <MobileBadge
                label={roleLabel(staff.role)}
                variant={staff.is_active ? 'active' : 'cancelled'}
              />
            }
            onTap={() => handleTap(staff)}
          />
        </SwipeAction>
      )
    },
    [handleTap],
  )

  return (
    <PullRefresh onRefresh={refresh} isRefreshing={isRefreshing}>
      <div className="flex flex-col">
        <div className="px-4 pb-1 pt-4">
          <h1 className="text-xl font-semibold text-gray-900 dark:text-gray-100">
            Staff
          </h1>
        </div>

        <MobileList<StaffMember>
          items={items}
          renderItem={renderItem}
          onRefresh={refresh}
          onLoadMore={loadMore}
          isLoading={isLoading}
          isRefreshing={isRefreshing}
          hasMore={hasMore}
          emptyMessage="No staff members found"
          searchValue={search}
          onSearchChange={setSearch}
          searchPlaceholder="Search staff…"
          keyExtractor={(s) => s.id}
        />
      </div>
    </PullRefresh>
  )
}
