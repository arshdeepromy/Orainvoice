import type { ReactNode } from 'react'
import { Link } from 'react-router-dom'

/* ============================================================
   ReportTabPage — minimal page wrapper for the in-hub report
   tab components when they are reached as standalone routes
   (Task 20.1).
   ------------------------------------------------------------
   The rebuilt ReportsPage (Task 19.2) is now a landing — it no
   longer renders the Tabs UI. The grouped ReportLibrary cards
   navigate to direct child routes (e.g. /reports/revenue), so
   each tab component (RevenueSummary, InvoiceStatus, …) is
   rendered through this wrapper to give the route a back link
   and a heading. Conventions match ClaimDetail / QuoteDetail /
   InvoiceDetail (button → navigate) but use a Link for /reports
   navigation since there is no history stack guarantee.

   Tokens: page padding `px-4 py-6 sm:px-6 lg:px-8`, heading
   `text-2xl font-semibold text-text`, sub `text-sm text-muted`,
   back link `text-accent hover:underline`. The `no-print` class
   on the back link mirrors the rest of the reports pages so the
   navigation chrome is suppressed in print/export views.
   ============================================================ */

interface ReportTabPageProps {
  /** Page heading shown above the tab content. */
  title: string
  /** Optional sub-heading description (e.g. brief report description). */
  description?: string
  /** The wrapped report tab component. */
  children: ReactNode
}

/**
 * Wrap a report tab component with a back link and heading so it
 * can be rendered as a standalone route under /reports/*.
 */
export default function ReportTabPage({ title, description, children }: ReportTabPageProps) {
  return (
    <div className="px-4 py-6 sm:px-6 lg:px-8">
      <div className="mb-4 no-print">
        <Link
          to="/reports"
          className="inline-flex items-center text-sm text-accent hover:underline focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent rounded"
        >
          ← Back to Reports
        </Link>
      </div>
      <header className="mb-6">
        <h1 className="text-2xl font-semibold text-text">{title}</h1>
        {description ? (
          <p className="mt-1 text-sm text-muted">{description}</p>
        ) : null}
      </header>
      {children}
    </div>
  )
}
