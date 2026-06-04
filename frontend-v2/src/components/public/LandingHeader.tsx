import { useState } from 'react'
import { Link } from 'react-router-dom'
import { usePlatformBranding } from '@/contexts/PlatformBrandingContext'

const NAV_LINKS = [
  { label: 'Features', href: '#features', type: 'anchor' as const },
  { label: 'Trades', href: '/trades', type: 'route' as const },
  { label: 'Pricing', href: '#pricing', type: 'anchor' as const },
  { label: 'Privacy', href: '/privacy', type: 'route' as const },
]

export function LandingHeader() {
  const { branding } = usePlatformBranding()
  const [mobileMenuOpen, setMobileMenuOpen] = useState(false)

  const platformName = branding.platform_name || 'OraInvoice'

  return (
    <nav
      className="fixed top-0 left-0 right-0 z-50 bg-slate-900 shadow-lg"
      aria-label="Main navigation"
    >
      <div className="mx-auto max-w-7xl px-4 sm:px-6 lg:px-8">
        <div className="flex h-16 items-center justify-between">
          {/* Logo / Brand */}
          <div className="flex-shrink-0">
            <Link to="/" className="flex items-center gap-2" aria-label={`${platformName} home`}>
              {(branding.dark_logo_url || branding.logo_url) ? (
                <img
                  src={branding.dark_logo_url || branding.logo_url || ''}
                  alt={platformName}
                  className="h-12 w-auto object-contain"
                />
              ) : (
                <span className="text-xl font-bold text-white">
                  {platformName}
                </span>
              )}
            </Link>
          </div>

          {/* Desktop navigation links */}
          <div className="hidden md:flex md:items-center md:gap-6">
            {NAV_LINKS.map((link) =>
              link.type === 'anchor' ? (
                <a
                  key={link.label}
                  href={link.href}
                  className="text-sm font-medium text-gray-300 transition-colors hover:text-white"
                >
                  {link.label}
                </a>
              ) : (
                <Link
                  key={link.label}
                  to={link.href}
                  className="text-sm font-medium text-gray-300 transition-colors hover:text-white"
                >
                  {link.label}
                </Link>
              )
            )}
          </div>

          {/* Desktop auth buttons */}
          <div className="hidden md:flex md:items-center md:gap-3">
            <Link
              to="/login"
              className="rounded-md px-4 py-2 text-sm font-medium text-gray-300 transition-colors hover:text-white"
            >
              Login
            </Link>
            <Link
              to="/signup"
              className="rounded-md bg-blue-600 px-4 py-2 text-sm font-medium text-white transition-colors hover:bg-blue-500"
            >
              Sign Up
            </Link>
          </div>

          {/* Mobile hamburger button */}
          <button
            type="button"
            className="inline-flex items-center justify-center rounded-md p-2 text-gray-400 transition-colors hover:bg-slate-800 hover:text-white md:hidden"
            aria-expanded={mobileMenuOpen}
            aria-controls="mobile-nav-panel"
            aria-label={mobileMenuOpen ? 'Close navigation menu' : 'Open navigation menu'}
            onClick={() => setMobileMenuOpen((prev) => !prev)}
          >
            {mobileMenuOpen ? (
              /* Close icon (X) */
              <svg className="h-6 w-6" fill="none" viewBox="0 0 24 24" strokeWidth={1.5} stroke="currentColor" aria-hidden="true">
                <path strokeLinecap="round" strokeLinejoin="round" d="M6 18L18 6M6 6l12 12" />
              </svg>
            ) : (
              /* Hamburger icon */
              <svg className="h-6 w-6" fill="none" viewBox="0 0 24 24" strokeWidth={1.5} stroke="currentColor" aria-hidden="true">
                <path strokeLinecap="round" strokeLinejoin="round" d="M3.75 6.75h16.5M3.75 12h16.5m-16.5 5.25h16.5" />
              </svg>
            )}
          </button>
        </div>
      </div>

      {/* Mobile slide-out nav panel */}
      <div
        id="mobile-nav-panel"
        className={`overflow-hidden transition-all duration-300 ease-in-out md:hidden ${
          mobileMenuOpen ? 'max-h-96 opacity-100' : 'max-h-0 opacity-0'
        }`}
        role="region"
        aria-label="Mobile navigation"
      >
        <div className="border-t border-slate-700 bg-slate-900 px-4 pb-4 pt-2">
          <div className="flex flex-col gap-1">
            {NAV_LINKS.map((link) =>
              link.type === 'anchor' ? (
                <a
                  key={link.label}
                  href={link.href}
                  className="rounded-md px-3 py-2 text-base font-medium text-gray-300 transition-colors hover:bg-slate-800 hover:text-white"
                  onClick={() => setMobileMenuOpen(false)}
                >
                  {link.label}
                </a>
              ) : (
                <Link
                  key={link.label}
                  to={link.href}
                  className="rounded-md px-3 py-2 text-base font-medium text-gray-300 transition-colors hover:bg-slate-800 hover:text-white"
                  onClick={() => setMobileMenuOpen(false)}
                >
                  {link.label}
                </Link>
              )
            )}
          </div>

          <div className="mt-3 flex flex-col gap-2 border-t border-slate-700 pt-3">
            <Link
              to="/login"
              className="rounded-md px-3 py-2 text-base font-medium text-gray-300 transition-colors hover:bg-slate-800 hover:text-white"
              onClick={() => setMobileMenuOpen(false)}
            >
              Login
            </Link>
            <Link
              to="/signup"
              className="rounded-md bg-blue-600 px-3 py-2 text-center text-base font-medium text-white transition-colors hover:bg-blue-500"
              onClick={() => setMobileMenuOpen(false)}
            >
              Sign Up
            </Link>
          </div>
        </div>
      </div>
    </nav>
  )
}
