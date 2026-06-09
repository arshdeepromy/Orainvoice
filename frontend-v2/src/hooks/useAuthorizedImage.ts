/**
 * useAuthorizedImage — fetch an image behind the JWT-protected /api/v2/uploads/
 * route and surface it as an object URL the browser can render with `<img src>`.
 *
 * Why this exists
 * ---------------
 * The platform's `apiClient` keeps the access token in JS memory (set on the
 * Authorization header by an axios request interceptor). Plain `<img>` tags
 * fire a vanilla browser request that bypasses axios entirely, so any image
 * URL behind the JWT-only `/api/v2/uploads/...` route 401s.
 *
 * The cleanest fix that doesn't require server-side cookie auth or
 * presigned-URL infrastructure is: fetch the image as a Blob through axios,
 * convert to an object URL, and feed THAT to `<img src>`. Browser caches the
 * decoded bitmap in-process; we cache the blob URL until the source URL
 * changes or the component unmounts.
 *
 * Public URLs (http://, https://, data:) and absolute paths under
 * `/api/v1/...` (the legacy non-uploads paths) pass through untouched.
 */

import { useEffect, useState } from 'react'
import apiClient from '@/api/client'

interface UseAuthorizedImageState {
  /** The renderable URL — either the original src (for public URLs) or a
   *  blob: object URL the browser can decode synchronously after fetch. */
  src: string | null
  /** True while the underlying axios fetch is in-flight. */
  loading: boolean
  /** True if the fetch failed (network, 401, 403, 404). The avatar caller
   *  should show its initials fallback in this case. */
  error: boolean
}

/**
 * Resolve a candidate image URL into a renderable `<img src>`:
 *   - `null` / empty → `null` (caller renders fallback)
 *   - `data:` / `http://` / `https://` → pass-through
 *   - `/api/v2/uploads/...` → fetch as blob via axios, return object URL
 *   - `<bare-file-key>` → prefixed with `/api/v2/uploads/` then fetched
 */
export function useAuthorizedImage(
  src: string | null | undefined,
): UseAuthorizedImageState {
  const [state, setState] = useState<UseAuthorizedImageState>({
    src: null,
    loading: false,
    error: false,
  })

  useEffect(() => {
    // Reset on src change.
    if (!src || !src.trim()) {
      setState({ src: null, loading: false, error: false })
      return
    }
    const trimmed = src.trim()

    // Public URL or data URI — render directly, no axios round-trip.
    if (
      trimmed.startsWith('http://') ||
      trimmed.startsWith('https://') ||
      trimmed.startsWith('data:') ||
      trimmed.startsWith('blob:')
    ) {
      setState({ src: trimmed, loading: false, error: false })
      return
    }

    // Normalise bare file_keys to the upload-route URL.
    const fetchUrl = trimmed.startsWith('/api/')
      ? trimmed
      : `/api/v2/uploads/${trimmed.replace(/^\/+/, '')}`

    // Only authorise the uploads route. Other absolute /api/ paths
    // (legacy routes that may be public or use a different auth mode)
    // pass through to the browser-default fetch.
    if (!fetchUrl.startsWith('/api/v2/uploads/')) {
      setState({ src: fetchUrl, loading: false, error: false })
      return
    }

    let cancelled = false
    const controller = new AbortController()
    let objectUrl: string | null = null

    setState({ src: null, loading: true, error: false })

    apiClient
      .get<Blob>(fetchUrl, { responseType: 'blob', signal: controller.signal })
      .then((res) => {
        if (cancelled) return
        if (!res.data) {
          setState({ src: null, loading: false, error: true })
          return
        }
        objectUrl = URL.createObjectURL(res.data)
        setState({ src: objectUrl, loading: false, error: false })
      })
      .catch((err: unknown) => {
        if (cancelled) return
        // axios CanceledError throws an Error subclass — silently swallow it
        // because StrictMode double-mount triggers harmless cancellations.
        const name =
          err && typeof err === 'object' && 'name' in err
            ? String((err as { name?: string }).name)
            : ''
        if (name === 'CanceledError' || name === 'AbortError') return
        setState({ src: null, loading: false, error: true })
      })

    return () => {
      cancelled = true
      controller.abort()
      if (objectUrl) {
        URL.revokeObjectURL(objectUrl)
      }
    }
  }, [src])

  return state
}

export default useAuthorizedImage
