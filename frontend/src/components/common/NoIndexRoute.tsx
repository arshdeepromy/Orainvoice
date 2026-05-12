import { Outlet } from 'react-router-dom'
import { usePageMeta } from '@/hooks/usePageMeta'

/**
 * Route-level wrapper that adds `<meta name="robots" content="noindex, nofollow">`
 * to every nested route. Use this for:
 *   - Authentication pages (login, signup, MFA, password reset, email verification)
 *   - Customer portal pages (token-based, not meant for crawling)
 *   - Invoice payment pages (token-based, not meant for crawling)
 *   - Kiosk page
 *   - Any other route that should be excluded from search engines.
 *
 * Public marketing pages (landing, /trades, /privacy) should NOT be wrapped in this.
 */
export function NoIndexRoute() {
  usePageMeta({ noindex: true })
  return <Outlet />
}

export default NoIndexRoute
