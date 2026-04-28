import { Link } from 'react-router-dom'
import { usePlatformBranding } from '@/contexts/PlatformBrandingContext'

const PRODUCT_LINKS = [
  { label: 'Features', href: '/#features', type: 'anchor' as const },
  { label: 'Pricing', href: '/#pricing', type: 'anchor' as const },
  { label: 'Trades', href: '/trades', type: 'route' as const },
]

const LEGAL_LINKS = [
  { label: 'Privacy Policy', href: '/privacy', type: 'route' as const },
  { label: 'Terms of Service', href: '/privacy', type: 'route' as const }, // placeholder — links to /privacy until /terms exists
]

export function LandingFooter() {
  const { branding } = usePlatformBranding()

  const platformName = branding.platform_name || 'OraInvoice'
  const currentYear = new Date().getFullYear()

  return (
    <footer className="bg-slate-900 text-gray-300">
      <div className="mx-auto max-w-7xl px-4 py-12 sm:px-6 lg:px-8">
        {/* Footer columns — grid on desktop, stacked on mobile */}
        <div className="grid grid-cols-1 gap-8 md:grid-cols-4">
          {/* Brand column */}
          <div>
            <Link to="/" className="text-lg font-bold text-white">
              {platformName}
            </Link>
            <p className="mt-2 text-sm text-gray-400">
              Purpose-built invoicing and business management for trade businesses.
            </p>
          </div>

          {/* Product column */}
          <div>
            <h3 className="text-sm font-semibold uppercase tracking-wider text-white">
              Product
            </h3>
            <ul className="mt-3 space-y-2">
              {PRODUCT_LINKS.map((link) => (
                <li key={link.label}>
                  {link.type === 'anchor' ? (
                    <a
                      href={link.href}
                      className="text-sm text-gray-400 transition-colors hover:text-white"
                    >
                      {link.label}
                    </a>
                  ) : (
                    <Link
                      to={link.href}
                      className="text-sm text-gray-400 transition-colors hover:text-white"
                    >
                      {link.label}
                    </Link>
                  )}
                </li>
              ))}
            </ul>
          </div>

          {/* Legal column */}
          <div>
            <h3 className="text-sm font-semibold uppercase tracking-wider text-white">
              Legal
            </h3>
            <ul className="mt-3 space-y-2">
              {LEGAL_LINKS.map((link) => (
                <li key={link.label}>
                  <Link
                    to={link.href}
                    className="text-sm text-gray-400 transition-colors hover:text-white"
                  >
                    {link.label}
                  </Link>
                </li>
              ))}
            </ul>
          </div>

          {/* Contact column */}
          <div>
            <h3 className="text-sm font-semibold uppercase tracking-wider text-white">
              Contact
            </h3>
            <ul className="mt-3 space-y-2">
              <li>
                <a
                  href="mailto:arshdeep.romy@gmail.com"
                  className="text-sm text-gray-400 transition-colors hover:text-white"
                >
                  arshdeep.romy@gmail.com
                </a>
              </li>
            </ul>
          </div>
        </div>

        {/* Divider + Copyright */}
        <div className="mt-10 border-t border-slate-700 pt-6 text-center text-sm text-gray-400">
          © {currentYear} {platformName || 'Oraflows Ltd'}. All rights reserved.
        </div>
      </div>
    </footer>
  )
}
