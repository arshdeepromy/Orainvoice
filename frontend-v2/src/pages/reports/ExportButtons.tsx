import { useEffect, useRef, useState } from 'react'
import { Button, useToast, ToastContainer } from '@/components/ui'
import apiClient from '@/api/client'

interface ExportButtonsProps {
  /** API endpoint path (e.g. '/reports/revenue') */
  endpoint: string
  /** Query params to include (date range, filters) */
  params?: Record<string, string>
}

/**
 * Parse a `Content-Disposition` header for `filename="..."` (or unquoted
 * `filename=...`) and return the captured value, or `null` when no match.
 * Handles both quoted and unquoted forms; `filename*` (RFC 5987) is not
 * required by the backend's `_maybe_export` helper.
 */
function parseFilenameFromContentDisposition(header: string | undefined): string | null {
  if (!header) return null
  const match = /filename="?([^"]+)"?/.exec(header)
  return match?.[1] ?? null
}

const MIME_BY_FORMAT: Record<'pdf' | 'csv', string> = {
  pdf: 'application/pdf',
  csv: 'text/csv',
}

/**
 * PDF and CSV export buttons for reports (C1).
 *
 * Sends the canonical `export=csv|pdf` query param (NOT `format`), streams
 * the response as a Blob with the correct MIME, derives the filename from
 * the `Content-Disposition` header (falling back to `report.{fmt}`), and
 * triggers a download via a transient `<a download>` element. Each request
 * uses an `AbortController` so navigation away cancels in-flight exports.
 * Failures surface an error toast — never a silent catch.
 *
 * Requirements: 10.1, 10.2, 10.6, 10.7, 21.1
 */
export default function ExportButtons({ endpoint, params = {} }: ExportButtonsProps) {
  const [exporting, setExporting] = useState<'pdf' | 'csv' | null>(null)
  const { toasts, addToast, dismissToast } = useToast()

  // Track in-flight export requests so they can be aborted on unmount.
  const controllersRef = useRef<Set<AbortController>>(new Set())

  useEffect(() => {
    const controllers = controllersRef.current
    return () => {
      controllers.forEach((c) => c.abort())
      controllers.clear()
    }
  }, [])

  const handleExport = async (fmt: 'pdf' | 'csv') => {
    setExporting(fmt)
    const controller = new AbortController()
    controllersRef.current.add(controller)
    try {
      const res = await apiClient.get<Blob>(endpoint, {
        params: { ...params, export: fmt },
        responseType: 'blob',
        signal: controller.signal,
      })
      const cd = (res.headers as Record<string, string | undefined>)['content-disposition']
      const filename = parseFilenameFromContentDisposition(cd) ?? `report.${fmt}`
      const mime = MIME_BY_FORMAT[fmt]
      const blob = new Blob([res.data], { type: mime })
      const url = URL.createObjectURL(blob)
      const a = document.createElement('a')
      a.href = url
      a.download = filename
      document.body.appendChild(a)
      a.click()
      document.body.removeChild(a)
      URL.revokeObjectURL(url)
    } catch (err) {
      if (!controller.signal.aborted) {
        const reason = (err as Error)?.message
        addToast(
          'error',
          reason ? `Export failed: ${reason}` : 'Export failed. Please try again.',
        )
      }
    } finally {
      controllersRef.current.delete(controller)
      setExporting((curr) => (curr === fmt ? null : curr))
    }
  }

  return (
    <>
      <div className="flex gap-2">
        <Button
          variant="ghost"
          size="sm"
          loading={exporting === 'pdf'}
          onClick={() => handleExport('pdf')}
          aria-label="Export as PDF"
        >
          PDF
        </Button>
        <Button
          variant="ghost"
          size="sm"
          loading={exporting === 'csv'}
          onClick={() => handleExport('csv')}
          aria-label="Export as CSV"
        >
          CSV
        </Button>
      </div>
      <ToastContainer toasts={toasts} onDismiss={dismissToast} />
    </>
  )
}
