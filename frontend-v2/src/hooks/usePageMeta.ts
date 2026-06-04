import { useEffect } from 'react'

/**
 * Lightweight hook for managing per-page SEO metadata without a third-party
 * library (React 19 supports metadata hoisting, but we need imperative control
 * for dynamic canonical URLs and for adding `noindex` to authenticated pages).
 *
 * The hook mutates <head> directly and restores the previous values on unmount.
 *
 * Notes for authenticated pages:
 *   - Pass `noindex: true` to emit `<meta name="robots" content="noindex, nofollow">`.
 *   - The meta tag is removed on unmount so public pages are not accidentally
 *     marked noindex if the user navigates from a protected page to a public one.
 */

export interface PageMetaOptions {
  /** Full page <title>. If omitted, the existing title is preserved. */
  title?: string
  /** Meta description. Recommended 70–160 characters. */
  description?: string
  /** Canonical URL for this page. Absolute URLs are preferred. */
  canonical?: string
  /** If true, adds <meta name="robots" content="noindex, nofollow"> for this page. */
  noindex?: boolean
  /** Optional JSON-LD structured data. Will be injected as a <script type="application/ld+json"> tag. */
  jsonLd?: object | object[]
  /** Open Graph overrides. */
  openGraph?: {
    title?: string
    description?: string
    url?: string
    image?: string
    type?: string
  }
}

const MANAGED_ATTR = 'data-page-meta'

function setMetaByName(name: string, content: string): () => void {
  const existing = document.head.querySelector<HTMLMetaElement>(`meta[name="${name}"]`)
  if (existing) {
    const prev = existing.getAttribute('content') ?? ''
    existing.setAttribute('content', content)
    return () => existing.setAttribute('content', prev)
  }
  const tag = document.createElement('meta')
  tag.setAttribute('name', name)
  tag.setAttribute('content', content)
  tag.setAttribute(MANAGED_ATTR, '1')
  document.head.appendChild(tag)
  return () => tag.remove()
}

function setMetaByProperty(property: string, content: string): () => void {
  const existing = document.head.querySelector<HTMLMetaElement>(`meta[property="${property}"]`)
  if (existing) {
    const prev = existing.getAttribute('content') ?? ''
    existing.setAttribute('content', content)
    return () => existing.setAttribute('content', prev)
  }
  const tag = document.createElement('meta')
  tag.setAttribute('property', property)
  tag.setAttribute('content', content)
  tag.setAttribute(MANAGED_ATTR, '1')
  document.head.appendChild(tag)
  return () => tag.remove()
}

function setCanonical(href: string): () => void {
  const existing = document.head.querySelector<HTMLLinkElement>('link[rel="canonical"]')
  if (existing) {
    const prev = existing.getAttribute('href') ?? ''
    existing.setAttribute('href', href)
    return () => existing.setAttribute('href', prev)
  }
  const tag = document.createElement('link')
  tag.setAttribute('rel', 'canonical')
  tag.setAttribute('href', href)
  tag.setAttribute(MANAGED_ATTR, '1')
  document.head.appendChild(tag)
  return () => tag.remove()
}

function addJsonLd(data: object | object[]): () => void {
  const tag = document.createElement('script')
  tag.setAttribute('type', 'application/ld+json')
  tag.setAttribute(MANAGED_ATTR, '1')
  tag.textContent = JSON.stringify(data)
  document.head.appendChild(tag)
  return () => tag.remove()
}

export function usePageMeta(options: PageMetaOptions): void {
  const {
    title,
    description,
    canonical,
    noindex,
    jsonLd,
    openGraph,
  } = options

  useEffect(() => {
    const cleanups: Array<() => void> = []

    const prevTitle = document.title
    if (title) {
      document.title = title
      cleanups.push(() => {
        document.title = prevTitle
      })
    }

    if (description) {
      cleanups.push(setMetaByName('description', description))
      cleanups.push(setMetaByProperty('og:description', description))
      cleanups.push(setMetaByName('twitter:description', description))
    }

    if (canonical) {
      cleanups.push(setCanonical(canonical))
      cleanups.push(setMetaByProperty('og:url', canonical))
    }

    if (noindex) {
      cleanups.push(setMetaByName('robots', 'noindex, nofollow'))
      cleanups.push(setMetaByName('googlebot', 'noindex, nofollow'))
    }

    if (openGraph?.title) cleanups.push(setMetaByProperty('og:title', openGraph.title))
    if (openGraph?.description) cleanups.push(setMetaByProperty('og:description', openGraph.description))
    if (openGraph?.url) cleanups.push(setMetaByProperty('og:url', openGraph.url))
    if (openGraph?.image) cleanups.push(setMetaByProperty('og:image', openGraph.image))
    if (openGraph?.type) cleanups.push(setMetaByProperty('og:type', openGraph.type))

    if (title) {
      cleanups.push(setMetaByProperty('og:title', title))
      cleanups.push(setMetaByName('twitter:title', title))
    }

    if (jsonLd) {
      cleanups.push(addJsonLd(jsonLd))
    }

    return () => {
      // Run cleanups in reverse order so DOM state is restored consistently.
      for (let i = cleanups.length - 1; i >= 0; i--) {
        try {
          cleanups[i]!()
        } catch {
          // Ignore — cleanup should never throw.
        }
      }
    }
  }, [
    title,
    description,
    canonical,
    noindex,
    // JSON-LD and OG are object-typed — serialise to avoid re-running on
    // referentially unstable but value-equal objects.
    JSON.stringify(jsonLd ?? null),
    JSON.stringify(openGraph ?? null),
  ])
}

export default usePageMeta
