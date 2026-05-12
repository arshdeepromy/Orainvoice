/**
 * ManagedPage — wraps a hand-coded public page so it can be rendered
 * either from published Puck content (when present) or from its
 * original React fallback component.
 *
 * Flow per Requirement 7.3, 14.4, 14.5, 14.7:
 *   1. On mount, call GET /api/v2/public/pages/resolve?slug=...
 *   2. If response is `{ type: 'page', data: { published_content, ... } }`
 *      with non-null `published_content` → render via Puck `<Render>` in
 *      PageShell, applying SEO via usePageMeta.
 *   3. Otherwise → render the FallbackPage immediately (no spinner).
 *   4. ErrorBoundary catches any Puck render failure and falls back too.
 *
 * Hand-coded routes wrap their existing component with this wrapper, e.g.
 *   <ManagedPage page_key="workshop">
 *     <WorkshopPage />
 *   </ManagedPage>
 *
 * Requirements: 7.1, 7.2, 7.3, 14.4, 14.5, 14.7
 */
import { useEffect, useState, type ReactNode } from 'react'
import axios from 'axios'
import { Render } from '@puckeditor/core'
import type { Data as PuckData } from '@puckeditor/core'
import { ErrorBoundary } from '@/components/ErrorBoundary'
import { usePageMeta } from '@/hooks/usePageMeta'
import { puckConfig } from '@/admin/page-editor/puckConfig'
import { getRegistrationByKey } from './_registry'
import { PageShell } from './PageShell'

interface PublishedPageData {
  page_key: string
  page_slug: string
  title: string
  published_content: PuckData | null
  seo: Record<string, unknown> | null
  noindex: boolean
  page_origin: 'hand-coded' | 'editor-created'
}

interface ResolveResponse {
  type: 'page' | 'redirect'
  data?: PublishedPageData
  status_code?: number
  target?: string
}

interface ManagedPageProps {
  /** Stable internal key matching `_registry.ts` and `editor_pages.page_key`. */
  page_key: string
  /**
   * The original hand-coded React page component to fall back to when
   * no published Puck content is available (or when rendering fails).
   */
  children: ReactNode
}

/**
 * Inner renderer that emits SEO meta tags from the resolved page data
 * and wraps Puck's `<Render>` in PageShell.
 */
function PublishedRenderer({ data }: { data: PublishedPageData }) {
  const seo = (data.seo ?? {}) as {
    meta_title?: string
    meta_description?: string
    canonical?: string
    og_image?: string
    og_type?: string
    twitter_card?: string
    json_ld?: object | object[]
  }

  usePageMeta({
    title: seo?.meta_title ?? data.title,
    description: seo?.meta_description,
    canonical: seo?.canonical,
    noindex: data.noindex,
    jsonLd: seo?.json_ld,
    openGraph: {
      image: seo?.og_image,
      type: seo?.og_type,
    },
  })

  return (
    <PageShell>
      <Render config={puckConfig} data={data.published_content as PuckData} />
    </PageShell>
  )
}

export function ManagedPage({ page_key, children }: ManagedPageProps) {
  const [data, setData] = useState<PublishedPageData | null>(null)
  const [resolved, setResolved] = useState(false)

  const registration = getRegistrationByKey(page_key)
  const slug = registration?.page_slug

  useEffect(() => {
    if (!slug) {
      setResolved(true)
      return
    }
    let cancelled = false
    const controller = new AbortController()
    ;(async () => {
      try {
        const res = await axios.get<ResolveResponse>(
          `/api/v2/public/pages/resolve`,
          {
            params: { slug },
            signal: controller.signal,
          },
        )
        if (cancelled) return
        const body = res?.data
        if (
          body?.type === 'page' &&
          body?.data?.published_content != null
        ) {
          setData(body.data)
        }
      } catch {
        // Network/404/anything → stay with fallback. Public pages must
        // never break for visitors; a hand-coded fallback is always
        // available.
      } finally {
        if (!cancelled) setResolved(true)
      }
    })()
    return () => {
      cancelled = true
      controller.abort()
    }
  }, [slug])

  // While the resolve request is in-flight, render the fallback
  // immediately (no spinner) so visitors see content right away —
  // Requirement 14.5 explicitly says "no spinner". The published
  // content (if any) replaces the fallback once the response lands.
  if (!resolved || !data || data.published_content == null) {
    return <>{children}</>
  }

  return (
    <ErrorBoundary level="page" name={`managed-page:${page_key}`}>
      <PublishedRenderer data={data} />
    </ErrorBoundary>
  )
}

export default ManagedPage
