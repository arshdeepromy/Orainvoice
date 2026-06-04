import { Link } from 'react-router-dom'

/**
 * FeatureNotAvailable — Task 21 port of
 * frontend/src/pages/common/FeatureNotAvailable.tsx.
 *
 * Shown when a user navigates directly to a disabled module/feature URL (e.g.
 * /quotes with the `quotes` module turned off). Logic copied VERBATIM; restyled
 * onto the design-system tokens (FR-2b) — the `var(--color-primary)` button
 * becomes the `accent` token, neutral grays become muted/text tokens.
 */
export default function FeatureNotAvailable() {
  return (
    <div
      className="flex flex-col items-center justify-center min-h-[60vh] text-center px-4"
      data-testid="feature-not-available"
    >
      <div className="mb-6">
        <svg
          className="h-16 w-16 text-muted-2 mx-auto"
          fill="none"
          viewBox="0 0 24 24"
          stroke="currentColor"
          aria-hidden="true"
        >
          <path
            strokeLinecap="round"
            strokeLinejoin="round"
            strokeWidth={1.5}
            d="M18.364 18.364A9 9 0 005.636 5.636m12.728 12.728A9 9 0 015.636 5.636m12.728 12.728L5.636 5.636"
          />
        </svg>
      </div>
      <h1 className="text-2xl font-semibold text-text mb-2">
        Feature not available
      </h1>
      <p className="text-muted mb-6 max-w-md">
        This feature is not currently enabled for your organisation. Please contact your administrator if you believe this is an error.
      </p>
      <Link
        to="/dashboard"
        className="inline-flex items-center gap-2 rounded-ctl bg-accent px-4 py-2 text-sm font-medium text-white hover:bg-accent-press transition-colors min-h-[44px]"
        data-testid="back-to-dashboard-link"
      >
        ← Back to Dashboard
      </Link>
    </div>
  )
}
