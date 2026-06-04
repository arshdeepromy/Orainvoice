/**
 * Hand-coded Page Registry
 *
 * Declares every public marketing page that has a React fallback component.
 * The backend syncs this registry on startup (see Requirement 14.3), auto-
 * creating empty `editor_pages` rows for any `page_key` not yet in the DB.
 *
 * The `PublicPageRenderer` / `ManagedPage` wrappers consult this registry:
 *   - If the backend returns published Puck content → render via <Render>
 *   - If no published content → render the `fallbackPage` component unchanged
 *
 * Adding a new hand-coded page requires only:
 *   1) Creating the React component under `frontend/src/pages/public/`
 *   2) Adding an entry below
 * The editor page list, sitemap, and robots.txt will then include it
 * automatically on next app restart.
 *
 * Related: Requirements 14.1, 14.2, 14.3, 14.8
 */

import { lazy, type ComponentType, type LazyExoticComponent } from 'react'

/* ------------------------------------------------------------------ */
/*  Fallback page components (code-split via React.lazy)               */
/* ------------------------------------------------------------------ */

const LandingPage = lazy(() => import('./LandingPage'))
const WorkshopPage = lazy(() => import('./WorkshopPage'))
const TradesPage = lazy(() => import('./TradesPage'))
const PrivacyPage = lazy(() => import('./PrivacyPage'))

/* ------------------------------------------------------------------ */
/*  Registration type                                                  */
/* ------------------------------------------------------------------ */

export interface HandCodedPageRegistration {
  /** Stable internal key used by the backend (`editor_pages.page_key`). */
  page_key: string
  /** URL path, always begins with `/`. Must match `editor_pages.page_slug`. */
  page_slug: string
  /** React component rendered when no published Puck content exists. */
  fallbackPage: LazyExoticComponent<ComponentType<unknown>>
  /** Default page/meta title seeded on first registry sync. */
  defaultTitle: string
  /** Default meta description seeded on first registry sync (0–320 chars). */
  defaultDescription: string
  /** Optional canonical URL. When omitted, no canonical is seeded. */
  defaultCanonical?: string
  /** Optional JSON-LD document (or array of documents) seeded on first sync. */
  defaultJsonLd?: Record<string, unknown> | Array<Record<string, unknown>>
}

/* ------------------------------------------------------------------ */
/*  Canonical host                                                     */
/* ------------------------------------------------------------------ */

const CANONICAL_HOST = 'https://one.oraflows.co.nz'

/* ------------------------------------------------------------------ */
/*  Registry                                                           */
/* ------------------------------------------------------------------ */

export const PAGE_REGISTRY: readonly HandCodedPageRegistration[] = [
  {
    page_key: 'landing',
    page_slug: '/',
    fallbackPage: LandingPage,
    defaultTitle: 'OraInvoice — Invoicing and Job Management for NZ Trade Businesses',
    defaultDescription:
      'Invoicing, quoting and job management for New Zealand trade businesses — workshops, mechanics, electricians, plumbers and builders. Built in NZ, 100% NZ hosted.',
    defaultCanonical: `${CANONICAL_HOST}/`,
  },
  {
    page_key: 'workshop',
    page_slug: '/workshop',
    fallbackPage: WorkshopPage,
    defaultTitle: 'Workshop Software for NZ Mechanics | OraInvoice',
    defaultDescription:
      'Workshop software for NZ mechanics, auto repair shops and service centres. CarJam lookup, WOF/COF reminders, Xero, NZ-hosted. From $60 NZD/month. 30-day free trial.',
    defaultCanonical: `${CANONICAL_HOST}/workshop`,
  },
  {
    page_key: 'trades',
    page_slug: '/trades',
    fallbackPage: TradesPage,
    defaultTitle: 'Trades Supported by OraInvoice — Automotive, Plumbing, Electrical',
    defaultDescription:
      'See the trade industries OraInvoice supports today — automotive workshops, general invoicing, plumbing and gas, electrical and mechanical. Built for NZ trade businesses.',
    defaultCanonical: `${CANONICAL_HOST}/trades`,
    defaultJsonLd: {
      '@context': 'https://schema.org',
      '@type': 'BreadcrumbList',
      itemListElement: [
        {
          '@type': 'ListItem',
          position: 1,
          name: 'Home',
          item: `${CANONICAL_HOST}/`,
        },
        {
          '@type': 'ListItem',
          position: 2,
          name: 'Trades',
          item: `${CANONICAL_HOST}/trades`,
        },
      ],
    },
  },
  {
    page_key: 'privacy',
    page_slug: '/privacy',
    fallbackPage: PrivacyPage,
    defaultTitle: 'Privacy Policy — OraInvoice',
    defaultDescription:
      'Read the OraInvoice privacy policy. How we collect, use and protect personal information under the NZ Privacy Act 2020. All data is hosted in New Zealand.',
    defaultCanonical: `${CANONICAL_HOST}/privacy`,
    defaultJsonLd: {
      '@context': 'https://schema.org',
      '@type': 'BreadcrumbList',
      itemListElement: [
        {
          '@type': 'ListItem',
          position: 1,
          name: 'Home',
          item: `${CANONICAL_HOST}/`,
        },
        {
          '@type': 'ListItem',
          position: 2,
          name: 'Privacy Policy',
          item: `${CANONICAL_HOST}/privacy`,
        },
      ],
    },
  },
]

/* ------------------------------------------------------------------ */
/*  Lookup helpers                                                     */
/* ------------------------------------------------------------------ */

/** Find a registration by its `page_key`. Returns `undefined` if not registered. */
export function getRegistrationByKey(
  key: string,
): HandCodedPageRegistration | undefined {
  return PAGE_REGISTRY.find((r) => r.page_key === key)
}

/** Find a registration by its `page_slug`. Returns `undefined` if not registered. */
export function getRegistrationBySlug(
  slug: string,
): HandCodedPageRegistration | undefined {
  return PAGE_REGISTRY.find((r) => r.page_slug === slug)
}

/** Convenience: every registered slug, useful for routing and audits. */
export const REGISTERED_SLUGS: readonly string[] = PAGE_REGISTRY.map(
  (r) => r.page_slug,
)
