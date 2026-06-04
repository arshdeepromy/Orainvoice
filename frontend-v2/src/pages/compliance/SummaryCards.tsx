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
      className="mb-6 grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-4"
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
            className="rounded-card border border-border bg-card p-4 shadow-card"
            data-testid="total-count"
          >
            <p className="text-sm font-medium text-muted">Total Documents</p>
            <p className="mt-1 text-2xl font-semibold text-text">
              {summary?.total_documents ?? 0}
            </p>
          </div>

          {/* Valid */}
          <div
            className="rounded-card border border-border bg-ok-soft p-4 shadow-card"
            data-testid="valid-count"
          >
            <p className="text-sm font-medium text-ok">Valid</p>
            <p className="mt-1 text-2xl font-semibold text-ok">
              {summary?.valid_documents ?? 0}
            </p>
          </div>

          {/* Expiring Soon */}
          <div
            className="rounded-card border border-border bg-warn-soft p-4 shadow-card"
            data-testid="expiring-count"
          >
            <p className="text-sm font-medium text-warn">Expiring Soon</p>
            <p className="mt-1 text-2xl font-semibold text-warn">
              {summary?.expiring_soon ?? 0}
            </p>
          </div>

          {/* Expired */}
          <div
            className="rounded-card border border-border bg-danger-soft p-4 shadow-card"
            data-testid="expired-count"
          >
            <p className="text-sm font-medium text-danger">Expired</p>
            <p className="mt-1 text-2xl font-semibold text-danger">
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
    <div className="animate-pulse rounded-card border border-border bg-card p-4 shadow-card">
      <div className="mb-2 h-4 w-24 rounded bg-border" />
      <div className="h-7 w-12 rounded bg-border" />
    </div>
  )
}
