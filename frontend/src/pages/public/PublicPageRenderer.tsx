/**
 * PublicPageRenderer — the catch-all route component for editor-created
 * public pages.
 *
 * Mounted at the very end of the route table so it only fires when no
 * explicit React route matched. Workflow per Requirement 7.2, 7.3:
 *
 *   1. Read the current pathname → call GET /api/v2/public/pages/resolve
 *   2. If response is `{ type: 'redirect', ... }` → Navigate (relative)
 *      or window.location for absolute URLs.
 *   3. If response is `{ type: 'page', data: { published_content, ... } }`
 *      and published content is present → render via Puck `<Render>` in
 *      PageShell with `usePageMeta` for SEO.
 *   4. Otherwise → render the lightweight 404 fallback.
 *
 * Loading state shows a `PageSkeleton` placeholder.
 *
 * Requirements: 7.1, 7.2, 7.3, 7.6, 7.7, 6.2, 6.5, 6.6
 */
import { useEffect, useState } from 'react'
import { Navigate, useLocation } from 'react-router-dom'
import axios from 'axios'
import { Render } from '@puckeditor/core'
import type { Data as PuckData } from '@puckeditor/core'
import { ErrorBoundary } from '@/components/ErrorBoundary'
import { usePageMeta } from '@/hooks/usePageMeta'
import { puckConfig } from '@/admin/page-editor/puckConfig'
import { LandingHeader, LandingFooter } from '@/components/public'
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

type Resolution =
  | { kind: 'loading' }
  | { kind: 'page'; data: PublishedPageData }
  | { kind: 'redirect'; target: string; status_code: number }
  | { kind: 'not-found' }

function PageSkeleton() {
  return (
    <PageShell>
      <div className="mx-auto max-w-4xl p-8 animate-pulse">
        <div className="h-12 w-2/3 rounded bg-gray-200 mb-6" />
        <div className="h-4 w-full rounded bg-gray-100 mb-2" />
        <div className="h-4 w-5/6 rounded bg-gray-100 mb-2" />
        <div className="h-4 w-4/6 rounded bg-gray-100 mb-8" />
        <div className="h-72 w-full rounded bg-gray-100" />
      </div>
    </PageShell>
  )
}

function NotFoundPage() {
  usePageMeta({
    title: 'Page not found — OraInvoice',
    noindex: true,
  })
  return (
    <>
      <LandingHeader />
      <main className="pt-16">
        <div className="mx-auto max-w-2xl px-6 py-24 text-center">
          <p className="text-sm font-semibold text-blue-600">404</p>
          <h1 className="mt-2 text-3xl font-bold tracking-tight text-gray-900 sm:text-4xl">
            Page not found
          </h1>
          <p className="mt-4 text-base text-gray-600">
            We couldn't find the page you were looking for.
          </p>
          <div className="mt-8">
            <a
              href="/"
              className="inline-flex items-center rounded-md bg-blue-600 px-4 py-2 text-sm font-medium text-white shadow hover:bg-blue-700"
            >
              Back to home
            </a>
          </div>
        </div>
      </main>
      <LandingFooter />
    </>
  )
}

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

export function PublicPageRenderer() {
  const location = useLocation()
  const slug = location.pathname

  const [resolution, setResolution] = useState<Resolution>({ kind: 'loading' })

  useEffect(() => {
    let cancelled = false
    const controller = new AbortController()
    setResolution({ kind: 'loading' })
    ;(async () => {
      try {
        const res = await axios.get<ResolveResponse>(
          `/api/v2/public/pages/resolve`,
          {
            params: { slug },
            signal: controller.signal,
            // 404 is expected for unknown slugs — let it flow to catch
            validateStatus: (status) => status < 500,
          },
        )
        if (cancelled) return
        const body = res?.data
        const status = res?.status ?? 0

        if (status === 404 || !body) {
          setResolution({ kind: 'not-found' })
          return
        }

        if (body?.type === 'redirect' && body?.target) {
          setResolution({
            kind: 'redirect',
            target: body.target,
            status_code: body?.status_code ?? 301,
          })
          return
        }

        if (
          body?.type === 'page' &&
          body?.data?.published_content != null
        ) {
          setResolution({ kind: 'page', data: body.data })
          return
        }

        setResolution({ kind: 'not-found' })
      } catch {
        if (!cancelled) setResolution({ kind: 'not-found' })
      }
    })()
    return () => {
      cancelled = true
      controller.abort()
    }
  }, [slug])

  if (resolution.kind === 'loading') {
    return <PageSkeleton />
  }

  if (resolution.kind === 'redirect') {
    const target = resolution.target
    const isAbsolute = /^https?:\/\//i.test(target)
    if (isAbsolute) {
      // External target — full navigation. Issue inside an effect-less
      // render is safe since this component will unmount.
      window.location.href = target
      return <PageSkeleton />
    }
    return <Navigate to={target} replace />
  }

  if (resolution.kind === 'page') {
    return (
      <ErrorBoundary
        level="page"
        name={`public-page:${resolution.data.page_key}`}
      >
        <PublishedRenderer data={resolution.data} />
      </ErrorBoundary>
    )
  }

  return <NotFoundPage />
}

export default PublicPageRenderer
