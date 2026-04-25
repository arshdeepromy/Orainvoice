import { MobileSpinner } from '@/components/ui'
import { useState, useEffect, useRef } from 'react'
import apiClient from '@/api/client'

export interface PDFViewerProps {
  /** URL of the PDF to display (backend endpoint) */
  url: string
  /** Title for accessibility */
  title?: string
}

/**
 * Full-screen PDF viewer component.
 *
 * Fetches the PDF as a blob via apiClient (which injects the Bearer token),
 * creates an object URL, and displays it in an iframe. This avoids CSP
 * blocks and authentication issues with direct iframe src loading.
 *
 * Requirements: 8.7
 */
export function PDFViewer({ url, title = 'PDF Document' }: PDFViewerProps) {
  const [isLoading, setIsLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [blobUrl, setBlobUrl] = useState<string | null>(null)
  const blobUrlRef = useRef<string | null>(null)

  useEffect(() => {
    let cancelled = false

    async function fetchPdf() {
      setIsLoading(true)
      setError(null)

      try {
        const response = await apiClient.get(url, { responseType: 'blob' })
        if (cancelled) return

        const objectUrl = URL.createObjectURL(response.data as Blob)
        blobUrlRef.current = objectUrl
        setBlobUrl(objectUrl)
      } catch {
        if (!cancelled) setError('Failed to load PDF')
      } finally {
        if (!cancelled) setIsLoading(false)
      }
    }

    fetchPdf()

    return () => {
      cancelled = true
      if (blobUrlRef.current) {
        URL.revokeObjectURL(blobUrlRef.current)
        blobUrlRef.current = null
      }
    }
  }, [url])

  return (
    <div className="relative flex h-full w-full flex-col">
      {isLoading && (
        <div className="absolute inset-0 z-10 flex items-center justify-center bg-white dark:bg-gray-900">
          <MobileSpinner size="md" />
        </div>
      )}
      {error && (
        <div className="flex flex-1 items-center justify-center p-4 text-center text-red-600 dark:text-red-400">
          <p>{error}</p>
        </div>
      )}
      {blobUrl && (
        <iframe
          src={blobUrl}
          title={title}
          className="h-full w-full flex-1 border-0"
          style={{ minHeight: '100vh' }}
        />
      )}
    </div>
  )
}
