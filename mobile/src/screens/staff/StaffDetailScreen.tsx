import { useParams, useNavigate } from 'react-router-dom'
import type { StaffMember } from '@shared/types/staff'
import { useApiDetail } from '@/hooks/useApiDetail'
import { MobileCard, MobileButton, MobileSpinner, MobileBadge } from '@/components/ui'

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

/**
 * Staff detail screen — full profile, assigned branches, role information.
 *
 * Requirements: 18.2
 */
export default function StaffDetailScreen() {
  const { id } = useParams<{ id: string }>()
  const navigate = useNavigate()

  const { data: staff, isLoading, error } = useApiDetail<StaffMember>({
    endpoint: `/api/v2/staff/${id}`,
    enabled: !!id,
  })

  if (isLoading) {
    return (
      <div className="flex h-64 items-center justify-center">
        <MobileSpinner size="md" />
      </div>
    )
  }

  if (error || !staff) {
    return (
      <div className="flex flex-col items-center gap-4 p-8">
        <p className="text-gray-500 dark:text-gray-400">
          {error ?? 'Staff member not found'}
        </p>
        <MobileButton variant="secondary" onClick={() => navigate(-1)}>
          Go Back
        </MobileButton>
      </div>
    )
  }

  const branches = staff.branches ?? []

  return (
    <div className="flex flex-col gap-4 p-4">
      {/* Back button */}
      <button
        type="button"
        onClick={() => navigate(-1)}
        className="flex min-h-[44px] items-center gap-1 self-start text-blue-600 dark:text-blue-400"
        aria-label="Back"
      >
        <svg
          className="h-5 w-5"
          viewBox="0 0 24 24"
          fill="none"
          stroke="currentColor"
          strokeWidth="2"
          strokeLinecap="round"
          strokeLinejoin="round"
          aria-hidden="true"
        >
          <path d="m15 18-6-6 6-6" />
        </svg>
        Back
      </button>

      {/* Header */}
      <div className="flex items-start justify-between">
        <div>
          <h1 className="text-xl font-semibold text-gray-900 dark:text-gray-100">
            {displayName(staff)}
          </h1>
          <p className="text-sm text-gray-500 dark:text-gray-400">
            {roleLabel(staff.role)}
          </p>
        </div>
        <MobileBadge
          label={staff.is_active ? 'Active' : 'Inactive'}
          variant={staff.is_active ? 'active' : 'cancelled'}
        />
      </div>

      {/* Contact details */}
      <MobileCard>
        <h2 className="mb-3 text-base font-semibold text-gray-900 dark:text-gray-100">
          Contact
        </h2>
        <div className="flex flex-col gap-3">
          {staff.email && (
            <div className="flex items-start justify-between gap-2">
              <span className="text-sm text-gray-500 dark:text-gray-400">Email</span>
              <a
                href={`mailto:${staff.email}`}
                className="text-sm font-medium text-blue-600 dark:text-blue-400"
              >
                {staff.email}
              </a>
            </div>
          )}
          {staff.phone && (
            <div className="flex items-start justify-between gap-2">
              <span className="text-sm text-gray-500 dark:text-gray-400">Phone</span>
              <a
                href={`tel:${staff.phone}`}
                className="text-sm font-medium text-blue-600 dark:text-blue-400"
              >
                {staff.phone}
              </a>
            </div>
          )}
          {!staff.email && !staff.phone && (
            <p className="text-sm text-gray-400 dark:text-gray-500">
              No contact details
            </p>
          )}
        </div>
      </MobileCard>

      {/* Quick actions */}
      <div className="flex gap-2">
        {staff.phone && (
          <MobileButton
            variant="secondary"
            size="sm"
            onClick={() => window.open(`tel:${staff.phone}`, '_system')}
          >
            Call
          </MobileButton>
        )}
        {staff.email && (
          <MobileButton
            variant="secondary"
            size="sm"
            onClick={() => window.open(`mailto:${staff.email}`, '_system')}
          >
            Email
          </MobileButton>
        )}
      </div>

      {/* Assigned branches */}
      <MobileCard>
        <h2 className="mb-3 text-base font-semibold text-gray-900 dark:text-gray-100">
          Assigned Branches
        </h2>
        {branches.length === 0 ? (
          <p className="text-sm text-gray-400 dark:text-gray-500">
            No branches assigned
          </p>
        ) : (
          <div className="flex flex-wrap gap-2">
            {branches.map((branch) => (
              <span
                key={branch}
                className="rounded-full bg-blue-50 px-3 py-1 text-xs font-medium text-blue-700 dark:bg-blue-900/30 dark:text-blue-300"
              >
                {branch}
              </span>
            ))}
          </div>
        )}
      </MobileCard>
    </div>
  )
}
