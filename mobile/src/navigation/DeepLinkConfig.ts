/**
 * Deep link URL patterns with param extractors.
 *
 * Each pattern maps a URL path to a screen identifier and extracts
 * route parameters from the URL.
 *
 * Requirements: 42.1, 42.2, 42.3, 42.4
 */

export interface DeepLinkPattern {
  /** Regex pattern to match against the URL path */
  pattern: RegExp
  /** Screen identifier to navigate to */
  screen: string
  /** Extract route params from the regex match */
  paramExtractor: (match: RegExpMatchArray) => Record<string, string>
}

export interface DeepLinkResult {
  /** Screen identifier */
  screen: string
  /** Extracted route parameters */
  params: Record<string, string>
}

/**
 * Registered deep link URL patterns.
 * Order matters — first match wins.
 */
export const DEEP_LINK_PATTERNS: DeepLinkPattern[] = [
  {
    pattern: /^\/invoices\/([a-zA-Z0-9_-]+)$/,
    screen: 'InvoiceDetail',
    paramExtractor: (match) => ({ id: match[1] }),
  },
  {
    pattern: /^\/invoices\/?$/,
    screen: 'InvoiceList',
    paramExtractor: () => ({}),
  },
  {
    pattern: /^\/quotes\/([a-zA-Z0-9_-]+)$/,
    screen: 'QuoteDetail',
    paramExtractor: (match) => ({ id: match[1] }),
  },
  {
    pattern: /^\/quotes\/?$/,
    screen: 'QuoteList',
    paramExtractor: () => ({}),
  },
  {
    pattern: /^\/customers\/([a-zA-Z0-9_-]+)$/,
    screen: 'CustomerProfile',
    paramExtractor: (match) => ({ id: match[1] }),
  },
  {
    pattern: /^\/customers\/?$/,
    screen: 'CustomerList',
    paramExtractor: () => ({}),
  },
  {
    pattern: /^\/jobs\/([a-zA-Z0-9_-]+)$/,
    screen: 'JobDetail',
    paramExtractor: (match) => ({ id: match[1] }),
  },
  {
    pattern: /^\/jobs\/?$/,
    screen: 'JobList',
    paramExtractor: () => ({}),
  },
  {
    pattern: /^\/job-cards\/([a-zA-Z0-9_-]+)$/,
    screen: 'JobCardDetail',
    paramExtractor: (match) => ({ id: match[1] }),
  },
  {
    pattern: /^\/compliance\/?$/,
    screen: 'ComplianceDashboard',
    paramExtractor: () => ({}),
  },
  {
    pattern: /^\/expenses\/?$/,
    screen: 'ExpenseList',
    paramExtractor: () => ({}),
  },
  {
    pattern: /^\/bookings\/?$/,
    screen: 'BookingCalendar',
    paramExtractor: () => ({}),
  },
  {
    pattern: /^\/reports\/?$/,
    screen: 'ReportsMenu',
    paramExtractor: () => ({}),
  },
  {
    pattern: /^\/settings\/?$/,
    screen: 'Settings',
    paramExtractor: () => ({}),
  },
  {
    pattern: /^\/dashboard\/?$/,
    screen: 'Dashboard',
    paramExtractor: () => ({}),
  },
]

/** Default fallback screen when no pattern matches. */
export const FALLBACK_SCREEN = 'Dashboard'

/**
 * Resolve a deep link URL path to a screen and parameters.
 *
 * Pure function — exported for property-based testing.
 *
 * **Validates: Requirements 39.2, 42.1, 42.2, 42.3, 42.4**
 */
export function resolveDeepLink(urlPath: string): DeepLinkResult {
  // Normalise: strip leading/trailing whitespace, ensure leading slash
  const normalised = urlPath.trim()
  const path = normalised.startsWith('/') ? normalised : `/${normalised}`

  for (const pattern of DEEP_LINK_PATTERNS) {
    const match = path.match(pattern.pattern)
    if (match) {
      return {
        screen: pattern.screen,
        params: pattern.paramExtractor(match),
      }
    }
  }

  return {
    screen: FALLBACK_SCREEN,
    params: {},
  }
}

/**
 * Map a screen identifier to a React Router path.
 */
export function screenToPath(result: DeepLinkResult): string {
  switch (result.screen) {
    case 'InvoiceDetail':
      return `/invoices/${result.params.id ?? ''}`
    case 'InvoiceList':
      return '/invoices'
    case 'QuoteDetail':
      return `/quotes/${result.params.id ?? ''}`
    case 'QuoteList':
      return '/quotes'
    case 'CustomerProfile':
      return `/customers/${result.params.id ?? ''}`
    case 'CustomerList':
      return '/customers'
    case 'JobDetail':
      return `/jobs/${result.params.id ?? ''}`
    case 'JobList':
      return '/jobs'
    case 'JobCardDetail':
      return `/job-cards/${result.params.id ?? ''}`
    case 'ComplianceDashboard':
      return '/compliance'
    case 'ExpenseList':
      return '/expenses'
    case 'BookingCalendar':
      return '/bookings'
    case 'ReportsMenu':
      return '/reports'
    case 'Settings':
      return '/settings'
    case 'Dashboard':
    default:
      return '/dashboard'
  }
}
