import { Outlet } from 'react-router-dom'

interface PortalLayoutProps {
  orgName?: string
  logoUrl?: string
  primaryColor?: string
}

export function PortalLayout({
  orgName = 'Workshop',
  logoUrl,
  primaryColor = '#2563eb',
}: PortalLayoutProps) {
  return (
    <div className="flex min-h-screen flex-col bg-gray-50">
      {/* Header with org branding */}
      <header
        className="border-b bg-white px-4 py-3"
        role="banner"
        style={{ borderBottomColor: primaryColor }}
      >
        <div className="mx-auto flex max-w-3xl items-center gap-3">
          {logoUrl ? (
            <img
              src={logoUrl}
              alt={`${orgName} logo`}
              className="h-8 w-8 rounded-md object-contain"
            />
          ) : (
            <div
              className="flex h-8 w-8 items-center justify-center rounded-md text-sm font-bold text-white"
              style={{ backgroundColor: primaryColor }}
              aria-hidden="true"
            >
              {orgName.charAt(0).toUpperCase()}
            </div>
          )}
          <span className="text-lg font-semibold text-gray-900 truncate">
            {orgName}
          </span>
        </div>
      </header>

      {/* Centered content area */}
      <main
        className="mx-auto w-full max-w-3xl flex-1 px-4 py-6 lg:py-10"
        role="main"
      >
        <Outlet />
      </main>

      {/* Minimal footer */}
      <footer className="border-t border-gray-200 bg-white px-4 py-4">
        <p className="mx-auto max-w-3xl text-center text-sm text-gray-500">
          Powered by WorkshopPro NZ
        </p>
      </footer>
    </div>
  )
}
