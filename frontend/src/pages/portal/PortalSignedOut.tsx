/**
 * Portal "Signed Out" confirmation page.
 *
 * Displayed after the customer clicks "Sign Out" in the portal header.
 * Shows a confirmation message and explains how to re-access the portal.
 *
 * Requirements: 40.1, 40.2
 */

export function PortalSignedOut() {
  return (
    <div className="flex min-h-[60vh] items-center justify-center px-4">
      <div className="max-w-md text-center">
        <div className="mx-auto mb-4 flex h-16 w-16 items-center justify-center rounded-full bg-green-100">
          <svg
            xmlns="http://www.w3.org/2000/svg"
            className="h-8 w-8 text-green-600"
            fill="none"
            viewBox="0 0 24 24"
            stroke="currentColor"
            strokeWidth={2}
          >
            <path strokeLinecap="round" strokeLinejoin="round" d="M5 13l4 4L19 7" />
          </svg>
        </div>
        <h1 className="text-2xl font-semibold text-gray-900">
          You have been signed out
        </h1>
        <p className="mt-3 text-sm text-gray-500">
          Your portal session has been ended. To access the portal again,
          use the link provided by your service provider.
        </p>
      </div>
    </div>
  )
}
