import { useState, useCallback, useRef } from 'react'
import apiClient from '../../api/client'
import { Button, Select, Spinner, AlertBanner } from '../../components/ui'

/* ------------------------------------------------------------------ */
/*  Types                                                              */
/* ------------------------------------------------------------------ */

type ImportType = 'customers' | 'vehicles'

interface FieldMapping {
  csvHeader: string
  targetField: string
}

interface ValidationRow {
  row: number
  data: Record<string, string>
  errors: string[]
  valid: boolean
}

interface ImportResult {
  total: number
  imported: number
  skipped: number
  errors: { row: number; reason: string }[]
}

type ImportStep = 'upload' | 'mapping' | 'preview' | 'importing' | 'results'

const CUSTOMER_FIELDS = [
  { value: '', label: '— Skip —' },
  { value: 'first_name', label: 'First Name' },
  { value: 'last_name', label: 'Last Name' },
  { value: 'email', label: 'Email' },
  { value: 'phone', label: 'Phone' },
  { value: 'address', label: 'Address' },
  { value: 'notes', label: 'Notes' },
]

const VEHICLE_FIELDS = [
  { value: '', label: '— Skip —' },
  { value: 'rego', label: 'Registration' },
  { value: 'make', label: 'Make' },
  { value: 'model', label: 'Model' },
  { value: 'year', label: 'Year' },
  { value: 'colour', label: 'Colour' },
  { value: 'body_type', label: 'Body Type' },
  { value: 'fuel_type', label: 'Fuel Type' },
  { value: 'engine_size', label: 'Engine Size' },
]

/* ------------------------------------------------------------------ */
/*  Helpers                                                            */
/* ------------------------------------------------------------------ */

function parseCSV(text: string): { headers: string[]; rows: string[][] } {
  const lines = text.split(/\r?\n/).filter((l) => l.trim())
  if (lines.length === 0) return { headers: [], rows: [] }
  const headers = lines[0].split(',').map((h) => h.trim().replace(/^"|"$/g, ''))
  const rows = lines.slice(1).map((line) =>
    line.split(',').map((c) => c.trim().replace(/^"|"$/g, '')),
  )
  return { headers, rows }
}

function autoMapFields(headers: string[], targetFields: { value: string; label: string }[]): FieldMapping[] {
  return headers.map((h) => {
    const lower = h.toLowerCase().replace(/[_\s-]+/g, '')
    const match = targetFields.find((f) => {
      if (!f.value) return false
      const fieldLower = f.value.toLowerCase().replace(/[_\s-]+/g, '')
      const labelLower = f.label.toLowerCase().replace(/[_\s-]+/g, '')
      return fieldLower === lower || labelLower === lower
    })
    return { csvHeader: h, targetField: match?.value || '' }
  })
}

/**
 * Data import component — CSV upload, field mapping, validation preview,
 * batch import with progress, and error report download.
 *
 * Requirements: 69.1, 69.2, 69.3, 69.5, 78.2, 78.3
 */
export default function DataImport() {
  const [importType, setImportType] = useState<ImportType>('customers')
  const [step, setStep] = useState<ImportStep>('upload')
  const [csvHeaders, setCsvHeaders] = useState<string[]>([])
  const [csvRows, setCsvRows] = useState<string[][]>([])
  const [mappings, setMappings] = useState<FieldMapping[]>([])
  const [validationRows, setValidationRows] = useState<ValidationRow[]>([])
  const [importProgress, setImportProgress] = useState(0)
  const [importResult, setImportResult] = useState<ImportResult | null>(null)
  const [error, setError] = useState('')
  const [fileName, setFileName] = useState('')
  const fileInputRef = useRef<HTMLInputElement>(null)

  const targetFields = importType === 'customers' ? CUSTOMER_FIELDS : VEHICLE_FIELDS

  const reset = useCallback(() => {
    setStep('upload')
    setCsvHeaders([])
    setCsvRows([])
    setMappings([])
    setValidationRows([])
    setImportProgress(0)
    setImportResult(null)
    setError('')
    setFileName('')
    if (fileInputRef.current) fileInputRef.current.value = ''
  }, [])

  /* ---- Step 1: File upload ---- */
  const handleFileSelect = useCallback(
    (e: React.ChangeEvent<HTMLInputElement>) => {
      const file = e.target.files?.[0]
      if (!file) return
      if (!file.name.endsWith('.csv')) {
        setError('Please select a CSV file.')
        return
      }
      setError('')
      setFileName(file.name)

      const reader = new FileReader()
      reader.onload = (ev) => {
        const text = ev.target?.result as string
        const { headers, rows } = parseCSV(text)
        if (headers.length === 0) {
          setError('CSV file is empty or has no headers.')
          return
        }
        setCsvHeaders(headers)
        setCsvRows(rows)
        setMappings(autoMapFields(headers, targetFields))
        setStep('mapping')
      }
      reader.onerror = () => setError('Failed to read file.')
      reader.readAsText(file)
    },
    [targetFields],
  )

  /* ---- Step 2: Field mapping ---- */
  const updateMapping = (index: number, targetField: string) => {
    setMappings((prev) => prev.map((m, i) => (i === index ? { ...m, targetField } : m)))
  }

  const handleValidate = useCallback(() => {
    const activeMappings = mappings.filter((m) => m.targetField)
    if (activeMappings.length === 0) {
      setError('Please map at least one field.')
      return
    }
    setError('')

    const preview: ValidationRow[] = csvRows.map((row, idx) => {
      const data: Record<string, string> = {}
      const errors: string[] = []

      mappings.forEach((m, colIdx) => {
        if (m.targetField) {
          data[m.targetField] = row[colIdx] || ''
        }
      })

      // Basic validation
      if (importType === 'customers') {
        if (!data.first_name?.trim()) errors.push('First name is required')
        if (!data.last_name?.trim()) errors.push('Last name is required')
        if (data.email && !/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(data.email)) errors.push('Invalid email format')
      } else {
        if (!data.rego?.trim()) errors.push('Registration is required')
        if (data.year && (isNaN(Number(data.year)) || Number(data.year) < 1900)) errors.push('Invalid year')
      }

      return { row: idx + 2, data, errors, valid: errors.length === 0 }
    })

    setValidationRows(preview)
    setStep('preview')
  }, [mappings, csvRows, importType])

  /* ---- Step 3: Import ---- */
  const handleImport = useCallback(async () => {
    setStep('importing')
    setImportProgress(0)
    setError('')

    const activeMappings = mappings.filter((m) => m.targetField)
    const fieldMap: Record<string, string> = {}
    activeMappings.forEach((m) => {
      fieldMap[m.csvHeader] = m.targetField
    })

    try {
      // Build CSV content with mapped headers
      const mappedHeaders = csvHeaders
        .map((h) => fieldMap[h] || h)
        .join(',')
      const mappedRows = csvRows.map((row) => row.join(','))
      const csvContent = [mappedHeaders, ...mappedRows].join('\n')

      const blob = new Blob([csvContent], { type: 'text/csv' })
      const formData = new FormData()
      formData.append('file', blob, fileName)
      formData.append('field_mapping', JSON.stringify(fieldMap))

      // Simulate progress during upload
      const progressInterval = setInterval(() => {
        setImportProgress((prev) => Math.min(prev + 10, 90))
      }, 300)

      const res = await apiClient.post<ImportResult>(
        `/data/import/${importType}`,
        formData,
        { headers: { 'Content-Type': 'multipart/form-data' } },
      )

      clearInterval(progressInterval)
      setImportProgress(100)
      setImportResult(res.data)
      setStep('results')
    } catch {
      setError('Import failed. Please try again.')
      setStep('preview')
    }
  }, [mappings, csvHeaders, csvRows, importType, fileName])

  /* ---- Error report download ---- */
  const downloadErrorReport = useCallback(() => {
    if (!importResult?.errors.length) return
    const lines = ['Row,Reason', ...importResult.errors.map((e) => `${e.row},"${e.reason}"`)]
    const blob = new Blob([lines.join('\n')], { type: 'text/csv' })
    const url = URL.createObjectURL(blob)
    const a = document.createElement('a')
    a.href = url
    a.download = `import-errors-${importType}-${Date.now()}.csv`
    a.click()
    URL.revokeObjectURL(url)
  }, [importResult, importType])

  /* ---- Render ---- */
  const validCount = validationRows.filter((r) => r.valid).length
  const invalidCount = validationRows.filter((r) => !r.valid).length

  return (
    <div>
      <p className="text-sm text-gray-500 mb-6">
        Import customer or vehicle records from a CSV file. Map fields, preview data, and review validation before committing.
      </p>

      {error && (
        <AlertBanner variant="error" onDismiss={() => setError('')} className="mb-4">
          {error}
        </AlertBanner>
      )}

      {/* Import type selector */}
      {step === 'upload' && (
        <div className="space-y-4">
          <div className="flex gap-4 items-end">
            <Select
              label="Import Type"
              options={[
                { value: 'customers', label: 'Customers' },
                { value: 'vehicles', label: 'Vehicles' },
              ]}
              value={importType}
              onChange={(e) => {
                setImportType(e.target.value as ImportType)
                reset()
              }}
            />
          </div>

          <div
            className="border-2 border-dashed border-gray-300 rounded-lg p-8 text-center hover:border-blue-400 transition-colors cursor-pointer"
            onClick={() => fileInputRef.current?.click()}
            onKeyDown={(e) => { if (e.key === 'Enter' || e.key === ' ') fileInputRef.current?.click() }}
            role="button"
            tabIndex={0}
            aria-label="Upload CSV file"
          >
            <svg className="mx-auto h-12 w-12 text-gray-400" fill="none" viewBox="0 0 24 24" stroke="currentColor" aria-hidden="true">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5} d="M7 16a4 4 0 01-.88-7.903A5 5 0 1115.9 6L16 6a5 5 0 011 9.9M15 13l-3-3m0 0l-3 3m3-3v12" />
            </svg>
            <p className="mt-2 text-sm text-gray-600">Click to upload or drag and drop</p>
            <p className="text-xs text-gray-400">CSV files only</p>
            <input
              ref={fileInputRef}
              type="file"
              accept=".csv"
              onChange={handleFileSelect}
              className="hidden"
              aria-label="Select CSV file"
            />
          </div>
        </div>
      )}

      {/* Step 2: Field mapping */}
      {step === 'mapping' && (
        <div className="space-y-4">
          <div className="flex items-center justify-between">
            <div>
              <h3 className="text-lg font-medium text-gray-900">Map Fields</h3>
              <p className="text-sm text-gray-500">
                File: {fileName} — {csvRows.length} rows detected
              </p>
            </div>
            <Button variant="secondary" size="sm" onClick={reset}>
              Start Over
            </Button>
          </div>

          <div className="rounded-lg border border-gray-200 bg-white divide-y divide-gray-100">
            {mappings.map((m, idx) => (
              <div key={m.csvHeader} className="flex items-center gap-4 px-4 py-3">
                <span className="text-sm font-medium text-gray-700 w-40 truncate" title={m.csvHeader}>
                  {m.csvHeader}
                </span>
                <span className="text-gray-400" aria-hidden="true">→</span>
                <Select
                  label={`Map ${m.csvHeader}`}
                  options={targetFields}
                  value={m.targetField}
                  onChange={(e) => updateMapping(idx, e.target.value)}
                  className="flex-1"
                />
              </div>
            ))}
          </div>

          <div className="flex gap-3">
            <Button onClick={handleValidate}>Validate &amp; Preview</Button>
            <Button variant="secondary" onClick={reset}>Cancel</Button>
          </div>
        </div>
      )}

      {/* Step 3: Validation preview */}
      {step === 'preview' && (
        <div className="space-y-4">
          <div className="flex items-center justify-between">
            <div>
              <h3 className="text-lg font-medium text-gray-900">Validation Preview</h3>
              <p className="text-sm text-gray-500">
                {validCount} valid, {invalidCount} with errors — invalid rows will be skipped
              </p>
            </div>
            <div className="flex gap-2">
              <Button variant="secondary" size="sm" onClick={() => setStep('mapping')}>
                Back to Mapping
              </Button>
              <Button variant="secondary" size="sm" onClick={reset}>
                Start Over
              </Button>
            </div>
          </div>

          <div className="overflow-x-auto rounded-lg border border-gray-200">
            <table className="min-w-full divide-y divide-gray-200" role="grid" aria-label="Validation preview">
              <thead className="bg-gray-50">
                <tr role="row">
                  <th scope="col" className="px-4 py-2 text-left text-xs font-medium text-gray-500 uppercase">Row</th>
                  <th scope="col" className="px-4 py-2 text-left text-xs font-medium text-gray-500 uppercase">Status</th>
                  {mappings.filter((m) => m.targetField).map((m) => (
                    <th key={m.targetField} scope="col" className="px-4 py-2 text-left text-xs font-medium text-gray-500 uppercase">
                      {targetFields.find((f) => f.value === m.targetField)?.label || m.targetField}
                    </th>
                  ))}
                  <th scope="col" className="px-4 py-2 text-left text-xs font-medium text-gray-500 uppercase">Errors</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-gray-100 bg-white">
                {validationRows.slice(0, 50).map((vr) => (
                  <tr key={vr.row} role="row" className={vr.valid ? '' : 'bg-red-50'}>
                    <td className="px-4 py-2 text-sm text-gray-700">{vr.row}</td>
                    <td className="px-4 py-2 text-sm">
                      {vr.valid ? (
                        <span className="text-green-600 font-medium">Valid</span>
                      ) : (
                        <span className="text-red-600 font-medium">Error</span>
                      )}
                    </td>
                    {mappings.filter((m) => m.targetField).map((m) => (
                      <td key={m.targetField} className="px-4 py-2 text-sm text-gray-700 max-w-[200px] truncate">
                        {vr.data[m.targetField] || '—'}
                      </td>
                    ))}
                    <td className="px-4 py-2 text-sm text-red-600">
                      {vr.errors.join('; ')}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>

          {validationRows.length > 50 && (
            <p className="text-sm text-gray-500">Showing first 50 of {validationRows.length} rows.</p>
          )}

          <div className="flex gap-3">
            <Button onClick={handleImport} disabled={validCount === 0}>
              Import {validCount} Records
            </Button>
            <Button variant="secondary" onClick={reset}>Cancel</Button>
          </div>
        </div>
      )}

      {/* Step 4: Importing with progress */}
      {step === 'importing' && (
        <div className="space-y-6 py-8 text-center">
          <Spinner size="lg" label="Importing records" />
          <div>
            <p className="text-sm font-medium text-gray-700 mb-2">
              Importing {importType}…
            </p>
            <div className="mx-auto max-w-md">
              <div
                className="h-3 w-full rounded-full bg-gray-200 overflow-hidden"
                role="progressbar"
                aria-valuenow={importProgress}
                aria-valuemin={0}
                aria-valuemax={100}
                aria-label="Import progress"
              >
                <div
                  className="h-full rounded-full bg-blue-600 transition-all duration-300"
                  style={{ width: `${importProgress}%` }}
                />
              </div>
              <p className="text-xs text-gray-500 mt-1">{importProgress}% complete</p>
            </div>
          </div>
        </div>
      )}

      {/* Step 5: Results summary */}
      {step === 'results' && importResult && (
        <div className="space-y-4">
          <h3 className="text-lg font-medium text-gray-900">Import Complete</h3>

          <div className="grid grid-cols-1 sm:grid-cols-3 gap-4">
            <div className="rounded-lg border border-gray-200 bg-white p-4 text-center">
              <p className="text-2xl font-bold text-gray-900">{importResult.total}</p>
              <p className="text-sm text-gray-500">Total Rows</p>
            </div>
            <div className="rounded-lg border border-green-200 bg-green-50 p-4 text-center">
              <p className="text-2xl font-bold text-green-700">{importResult.imported}</p>
              <p className="text-sm text-green-600">Imported</p>
            </div>
            <div className="rounded-lg border border-red-200 bg-red-50 p-4 text-center">
              <p className="text-2xl font-bold text-red-700">{importResult.skipped}</p>
              <p className="text-sm text-red-600">Skipped</p>
            </div>
          </div>

          {importResult.errors.length > 0 && (
            <AlertBanner variant="warning" title="Some rows were skipped">
              <p>{importResult.errors.length} rows had errors and were not imported.</p>
              <Button
                variant="secondary"
                size="sm"
                onClick={downloadErrorReport}
                className="mt-2"
              >
                Download Error Report
              </Button>
            </AlertBanner>
          )}

          {importResult.errors.length === 0 && (
            <AlertBanner variant="success">
              All records imported successfully.
            </AlertBanner>
          )}

          <Button onClick={reset}>Import More</Button>
        </div>
      )}
    </div>
  )
}
