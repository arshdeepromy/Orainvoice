import type { DashboardSummary } from './ComplianceDashboard'

/* ------------------------------------------------------------------ */
/*  Props                                                              */
/* ------------------------------------------------------------------ */

interface SummaryCardsProps {
  summary: DashboardSummary | null
  loading: boolean
}

/* ------------------------------------------------------------------ */
/*  Component                                                          */
/* ------------------------------------------------------------------ */

export default function SummaryCards({ summary, loading }: SummaryCardsProps) {
  return (
    <div
      className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4 mb-6"
      role="region"
      aria-label="Compliance summary"
    >
      {loading ? (
        <>
          <SkeletonCard />
          <SkeletonCard />
          <SkeletonCard />
          <SkeletonCard />
        </>
      ) : (
        <>
          {/* Total Documents */}
          <div
            className="rounded-lg border border-gray-200 bg-white p-4 shadow-sm"
            data-testid="total-count"
          >
            <p className="text-sm font-medium text-gray-500">Total Documents</p>
            <p className="mt-1 text-2xl font-semibold text-gray-900">
              {summary?.total_documents ?? 0}
            </p>
          </div>

          {/* Valid */}
          <div
            className="rounded-lg border border-green-200 bg-white p-4 shadow-sm"
            data-testid="valid-count"
          >
            <p className="text-sm font-medium text-green-600">Valid</p>
            <p className="mt-1 text-2xl font-semibold text-green-700">
              {summary?.valid_documents ?? 0}
            </p>
          </div>

          {/* Expiring Soon */}
          <div
            className="rounded-lg border border-amber-200 bg-white p-4 shadow-sm"
            data-testid="expiring-count"
          >
            <p className="text-sm font-medium text-amber-600">Expiring Soon</p>
            <p className="mt-1 text-2xl font-semibold text-amber-700">
              {summary?.expiring_soon ?? 0}
            </p>
          </div>

          {/* Expired */}
          <div
            className="rounded-lg border border-red-200 bg-white p-4 shadow-sm"
            data-testid="expired-count"
          >
            <p className="text-sm font-medium text-red-600">Expired</p>
            <p className="mt-1 text-2xl font-semibold text-red-700">
              {summary?.expired ?? 0}
            </p>
          </div>
        </>
      )}
    </div>
  )
}

/* ------------------------------------------------------------------ */
/*  Skeleton placeholder                                               */
/* ------------------------------------------------------------------ */

function SkeletonCard() {
  return (
    <div className="rounded-lg border border-gray-200 bg-white p-4 shadow-sm animate-pulse">
      <div className="h-4 w-24 rounded bg-gray-200 mb-2" />
      <div className="h-7 w-12 rounded bg-gray-200" />
    </div>
  )
}
