import { Link } from 'react-router-dom'

/**
 * Displayed when a user navigates directly to a disabled module/feature URL.
 * Provides a friendly message and a link back to the dashboard.
 */
export default function FeatureNotAvailable() {
  return (
    <div
      className="flex flex-col items-center justify-center min-h-[60vh] text-center px-4"
      data-testid="feature-not-available"
    >
      <div className="mb-6">
        <svg
          className="h-16 w-16 text-gray-400 mx-auto"
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
      <h1 className="text-2xl font-semibold text-gray-900 mb-2">
        Feature not available
      </h1>
      <p className="text-gray-600 mb-6 max-w-md">
        This feature is not currently enabled for your organisation. Please contact your administrator if you believe this is an error.
      </p>
      <Link
        to="/dashboard"
        className="inline-flex items-center gap-2 rounded-lg bg-[var(--color-primary,#2563eb)] px-4 py-2 text-sm font-medium text-white hover:opacity-90 transition-opacity min-h-[44px]"
        data-testid="back-to-dashboard-link"
      >
        ← Back to Dashboard
      </Link>
    </div>
  )
}
