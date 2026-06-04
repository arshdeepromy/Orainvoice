import { useState, useCallback } from 'react'
import apiClient from '@/api/client'
import { Button, AlertBanner } from '@/components/ui'

/* ------------------------------------------------------------------ */
/*  Types                                                              */
/* ------------------------------------------------------------------ */

type ExportType = 'customers' | 'vehicles' | 'invoices'

interface ExportOption {
  type: ExportType
  label: string
  description: string
  endpoint: string
}

const EXPORT_OPTIONS: ExportOption[] = [
  {
    type: 'customers',
    label: 'Customers',
    description: 'Export all customer records including name, email, phone, and address.',
    endpoint: '/data/export/customers',
  },
  {
    type: 'vehicles',
    label: 'Vehicles',
    description: 'Export all vehicle records including registration, make, model, and year.',
    endpoint: '/data/export/vehicles',
  },
  {
    type: 'invoices',
    label: 'Invoices',
    description: 'Export all invoice records including number, customer, total, status, and dates.',
    endpoint: '/data/export/invoices',
  },
]

/**
 * Data export component — CSV export buttons for customers, vehicles, and invoices.
 *
 * Requirements: 69.4
 */
export default function DataExport() {
  const [exporting, setExporting] = useState<ExportType | null>(null)
  const [error, setError] = useState('')
  const [success, setSuccess] = useState('')

  const handleExport = useCallback(async (option: ExportOption) => {
    setExporting(option.type)
    setError('')
    setSuccess('')

    try {
      const res = await apiClient.get(option.endpoint, { responseType: 'blob' })
      const blob = new Blob([res.data], { type: 'text/csv' })
      const url = URL.createObjectURL(blob)
      const a = document.createElement('a')
      a.href = url
      a.download = `${option.type}-export-${new Date().toISOString().slice(0, 10)}.csv`
      a.click()
      URL.revokeObjectURL(url)
      setSuccess(`${option.label} exported successfully.`)
    } catch {
      setError(`Failed to export ${option.label.toLowerCase()}. Please try again.`)
    } finally {
      setExporting(null)
    }
  }, [])

  return (
    <div>
      <p className="mb-6 text-sm text-muted">
        Export your data as CSV files for migration, backup, or reporting purposes.
      </p>

      {error && (
        <AlertBanner variant="error" onDismiss={() => setError('')} className="mb-4">
          {error}
        </AlertBanner>
      )}

      {success && (
        <AlertBanner variant="success" onDismiss={() => setSuccess('')} className="mb-4">
          {success}
        </AlertBanner>
      )}

      <div className="grid grid-cols-1 gap-4 sm:grid-cols-3">
        {EXPORT_OPTIONS.map((option) => (
          <div
            key={option.type}
            className="flex flex-col items-center rounded-card border border-border bg-card p-6 text-center shadow-card"
          >
            <svg className="mb-3 h-10 w-10 text-muted-2" fill="none" viewBox="0 0 24 24" stroke="currentColor" aria-hidden="true">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5} d="M12 10v6m0 0l-3-3m3 3l3-3m2 8H7a2 2 0 01-2-2V5a2 2 0 012-2h5.586a1 1 0 01.707.293l5.414 5.414a1 1 0 01.293.707V19a2 2 0 01-2 2z" />
            </svg>
            <h3 className="mb-1 text-base font-medium text-text">{option.label}</h3>
            <p className="mb-4 text-sm text-muted">{option.description}</p>
            <Button
              size="sm"
              loading={exporting === option.type}
              disabled={exporting !== null}
              onClick={() => handleExport(option)}
            >
              Export CSV
            </Button>
          </div>
        ))}
      </div>
    </div>
  )
}
