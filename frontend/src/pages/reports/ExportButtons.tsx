import { useState } from 'react'
import { Button } from '../../components/ui'
import apiClient from '../../api/client'

interface ExportButtonsProps {
  /** API endpoint path (e.g. '/reports/revenue') */
  endpoint: string
  /** Query params to include (date range, filters) */
  params?: Record<string, string>
}

/**
 * PDF and CSV export buttons for reports.
 * Requirements: 45.3
 */
export default function ExportButtons({ endpoint, params = {} }: ExportButtonsProps) {
  const [exporting, setExporting] = useState<'pdf' | 'csv' | null>(null)

  const handleExport = async (format: 'pdf' | 'csv') => {
    setExporting(format)
    try {
      const res = await apiClient.get(endpoint, {
        params: { ...params, format },
        responseType: 'blob',
      })
      const blob = new Blob([res.data])
      const url = URL.createObjectURL(blob)
      const a = document.createElement('a')
      a.href = url
      a.download = `report.${format}`
      a.click()
      URL.revokeObjectURL(url)
    } catch {
      // Silently fail — user can retry
    } finally {
      setExporting(null)
    }
  }

  return (
    <div className="flex gap-2">
      <Button
        variant="secondary"
        size="sm"
        loading={exporting === 'pdf'}
        onClick={() => handleExport('pdf')}
        aria-label="Export as PDF"
      >
        PDF
      </Button>
      <Button
        variant="secondary"
        size="sm"
        loading={exporting === 'csv'}
        onClick={() => handleExport('csv')}
        aria-label="Export as CSV"
      >
        CSV
      </Button>
    </div>
  )
}
