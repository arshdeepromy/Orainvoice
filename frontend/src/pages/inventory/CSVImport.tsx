import { useState, useRef } from 'react'
import apiClient from '../../api/client'
import { Button } from '../../components/ui'

/* ------------------------------------------------------------------ */
/*  Types                                                              */
/* ------------------------------------------------------------------ */

interface CSVImportPreview {
  total_rows: number
  valid_rows: number
  error_rows: number
  errors: Array<{ row: number; field: string; message: string }>
  preview_data: Array<Record<string, string>>
}

interface CSVImportResult {
  imported_count: number
  skipped_count: number
  error_count: number
  errors: Array<{ row: number; field: string; message: string }>
}

interface FieldMapping {
  source_column: string
  target_field: string
}

const TARGET_FIELDS = [
  { value: '', label: 'Skip this column' },
  { value: 'name', label: 'Product Name' },
  { value: 'sku', label: 'SKU' },
  { value: 'barcode', label: 'Barcode' },
  { value: 'description', label: 'Description' },
  { value: 'unit_of_measure', label: 'Unit of Measure' },
  { value: 'sale_price', label: 'Sale Price' },
  { value: 'cost_price', label: 'Cost Price' },
  { value: 'stock_quantity', label: 'Stock Quantity' },
  { value: 'low_stock_threshold', label: 'Low Stock Threshold' },
  { value: 'reorder_quantity', label: 'Reorder Quantity' },
]

type Step = 'upload' | 'preview' | 'results'

/**
 * CSV product import with 3 steps: upload → preview/map fields → results.
 *
 * Validates: Requirement 9.9
 */
export default function CSVImport() {
  const [step, setStep] = useState<Step>('upload')
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')

  // Upload step
  const fileRef = useRef<HTMLInputElement>(null)
  const [fileName, setFileName] = useState('')
  const [csvHeaders, setCsvHeaders] = useState<string[]>([])
  const [csvRows, setCsvRows] = useState<Array<Record<string, string>>>([])

  // Preview step
  const [fieldMappings, setFieldMappings] = useState<FieldMapping[]>([])
  const [preview, setPreview] = useState<CSVImportPreview | null>(null)

  // Results step
  const [result, setResult] = useState<CSVImportResult | null>(null)

  const parseCSV = (text: string): { headers: string[]; rows: Array<Record<string, string>> } => {
    const lines = text.split('\n').filter((l) => l.trim())
    if (lines.length < 2) return { headers: [], rows: [] }

    const headers = lines[0].split(',').map((h) => h.trim().replace(/^"|"$/g, ''))
    const rows = lines.slice(1).map((line) => {
      const values = line.split(',').map((v) => v.trim().replace(/^"|"$/g, ''))
      const row: Record<string, string> = {}
      headers.forEach((h, i) => { row[h] = values[i] || '' })
      return row
    })
    return { headers, rows }
  }

  const autoMapField = (header: string): string => {
    const h = header.toLowerCase().replace(/[_\s-]/g, '')
    if (h.includes('name') || h.includes('product')) return 'name'
    if (h === 'sku' || h.includes('sku')) return 'sku'
    if (h.includes('barcode') || h.includes('ean') || h.includes('upc')) return 'barcode'
    if (h.includes('description') || h.includes('desc')) return 'description'
    if (h.includes('saleprice') || h.includes('price') || h.includes('retail')) return 'sale_price'
    if (h.includes('costprice') || h.includes('cost')) return 'cost_price'
    if (h.includes('stock') || h.includes('quantity') || h.includes('qty')) return 'stock_quantity'
    if (h.includes('unit') || h.includes('uom')) return 'unit_of_measure'
    return ''
  }

  const handleFileSelect = (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0]
    if (!file) return
    setFileName(file.name)
    setError('')

    const reader = new FileReader()
    reader.onload = (ev) => {
      const text = ev.target?.result as string
      const { headers, rows } = parseCSV(text)
      if (headers.length === 0) {
        setError('Could not parse CSV file. Ensure it has a header row.')
        return
      }
      setCsvHeaders(headers)
      setCsvRows(rows)
      setFieldMappings(headers.map((h) => ({ source_column: h, target_field: autoMapField(h) })))
      setStep('preview')
    }
    reader.readAsText(file)
  }

  const updateMapping = (index: number, targetField: string) => {
    setFieldMappings((prev) => prev.map((m, i) => i === index ? { ...m, target_field: targetField } : m))
  }

  const handlePreview = async () => {
    setLoading(true)
    setError('')
    try {
      const activeMappings = fieldMappings.filter((m) => m.target_field)
      const res = await apiClient.post<CSVImportPreview>('/v2/products/csv-import', {
        data: csvRows,
        field_mapping: activeMappings,
        preview_only: true,
      })
      setPreview(res.data)
    } catch {
      setError('Failed to preview import.')
    } finally {
      setLoading(false)
    }
  }

  const handleImport = async () => {
    setLoading(true)
    setError('')
    try {
      const activeMappings = fieldMappings.filter((m) => m.target_field)
      const res = await apiClient.post<CSVImportResult>('/v2/products/csv-import', {
        data: csvRows,
        field_mapping: activeMappings,
        preview_only: false,
      })
      setResult(res.data)
      setStep('results')
    } catch {
      setError('Failed to import products.')
    } finally {
      setLoading(false)
    }
  }

  const handleReset = () => {
    setStep('upload')
    setFileName('')
    setCsvHeaders([])
    setCsvRows([])
    setFieldMappings([])
    setPreview(null)
    setResult(null)
    setError('')
    if (fileRef.current) fileRef.current.value = ''
  }

  return (
    <div>
      {/* Step indicator */}
      <div className="flex items-center gap-2 mb-6" role="navigation" aria-label="Import steps">
        {(['upload', 'preview', 'results'] as Step[]).map((s, i) => (
          <div key={s} className="flex items-center gap-2">
            {i > 0 && <span className="text-gray-300">→</span>}
            <span className={`text-sm font-medium px-3 py-1 rounded-full ${step === s ? 'bg-blue-100 text-blue-700' : 'text-gray-500'}`}>
              {i + 1}. {s === 'upload' ? 'Upload' : s === 'preview' ? 'Preview & Map' : 'Results'}
            </span>
          </div>
        ))}
      </div>

      {error && (
        <div className="mb-4 rounded-md border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700" role="alert">{error}</div>
      )}

      {/* Step 1: Upload */}
      {step === 'upload' && (
        <div className="max-w-lg">
          <p className="text-sm text-gray-500 mb-4">
            Upload a CSV file with product data. The first row should contain column headers.
          </p>
          <div className="border-2 border-dashed border-gray-300 rounded-lg p-8 text-center">
            <input
              ref={fileRef}
              type="file"
              accept=".csv,text/csv"
              onChange={handleFileSelect}
              className="hidden"
              id="csv-upload"
              aria-label="Upload CSV file"
            />
            <label htmlFor="csv-upload" className="cursor-pointer">
              <div className="text-4xl mb-2">📄</div>
              <p className="text-sm font-medium text-blue-600 hover:text-blue-800">
                Click to select a CSV file
              </p>
              <p className="text-xs text-gray-400 mt-1">or drag and drop</p>
            </label>
          </div>
        </div>
      )}

      {/* Step 2: Preview & Map */}
      {step === 'preview' && (
        <div>
          <div className="flex items-center justify-between mb-4">
            <div>
              <p className="text-sm font-medium text-gray-900">{fileName}</p>
              <p className="text-xs text-gray-500">{csvRows.length} rows, {csvHeaders.length} columns</p>
            </div>
            <div className="flex gap-2">
              <Button variant="secondary" onClick={handleReset}>Start Over</Button>
              <Button onClick={handlePreview} loading={loading}>Validate</Button>
              <Button onClick={handleImport} loading={loading} disabled={csvRows.length === 0}>
                Import {preview ? preview.valid_rows : csvRows.length} Products
              </Button>
            </div>
          </div>

          {/* Field mapping */}
          <div className="mb-6">
            <h3 className="text-sm font-semibold text-gray-900 mb-2">Field Mapping</h3>
            <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-3">
              {fieldMappings.map((m, i) => (
                <div key={m.source_column} className="flex items-center gap-2">
                  <span className="text-sm text-gray-700 w-32 truncate" title={m.source_column}>{m.source_column}</span>
                  <span className="text-gray-400">→</span>
                  <select
                    className="flex-1 rounded-md border border-gray-300 px-2 py-1 text-sm"
                    value={m.target_field}
                    onChange={(e) => updateMapping(i, e.target.value)}
                    aria-label={`Map ${m.source_column} to`}
                  >
                    {TARGET_FIELDS.map((f) => (
                      <option key={f.value} value={f.value}>{f.label}</option>
                    ))}
                  </select>
                </div>
              ))}
            </div>
          </div>

          {/* Preview validation results */}
          {preview && (
            <div className="mb-4 grid grid-cols-3 gap-4">
              <div className="rounded-lg border border-green-200 bg-green-50 p-3">
                <p className="text-sm text-green-700">Valid rows</p>
                <p className="text-xl font-semibold text-green-800">{preview.valid_rows}</p>
              </div>
              <div className="rounded-lg border border-red-200 bg-red-50 p-3">
                <p className="text-sm text-red-700">Error rows</p>
                <p className="text-xl font-semibold text-red-800">{preview.error_rows}</p>
              </div>
              <div className="rounded-lg border border-gray-200 bg-gray-50 p-3">
                <p className="text-sm text-gray-500">Total rows</p>
                <p className="text-xl font-semibold text-gray-900">{preview.total_rows}</p>
              </div>
            </div>
          )}

          {/* Preview errors */}
          {preview && preview.errors.length > 0 && (
            <div className="mb-4">
              <h3 className="text-sm font-semibold text-red-700 mb-2">Validation Errors</h3>
              <div className="max-h-40 overflow-y-auto rounded border border-red-200 bg-red-50 p-3 text-sm text-red-700">
                {preview.errors.slice(0, 20).map((err, i) => (
                  <p key={i}>Row {err.row}: {err.field} — {err.message}</p>
                ))}
                {preview.errors.length > 20 && <p>…and {preview.errors.length - 20} more</p>}
              </div>
            </div>
          )}

          {/* Data preview table */}
          <div className="overflow-x-auto rounded-lg border border-gray-200">
            <table className="min-w-full divide-y divide-gray-200" role="grid">
              <caption className="sr-only">CSV data preview</caption>
              <thead className="bg-gray-50">
                <tr>
                  <th scope="col" className="px-3 py-2 text-left text-xs font-medium uppercase text-gray-500">#</th>
                  {csvHeaders.map((h) => (
                    <th key={h} scope="col" className="px-3 py-2 text-left text-xs font-medium uppercase text-gray-500">{h}</th>
                  ))}
                </tr>
              </thead>
              <tbody className="divide-y divide-gray-200 bg-white">
                {csvRows.slice(0, 10).map((row, i) => (
                  <tr key={i} className="hover:bg-gray-50">
                    <td className="px-3 py-2 text-xs text-gray-400">{i + 1}</td>
                    {csvHeaders.map((h) => (
                      <td key={h} className="px-3 py-2 text-sm text-gray-700 max-w-xs truncate">{row[h] || ''}</td>
                    ))}
                  </tr>
                ))}
              </tbody>
            </table>
            {csvRows.length > 10 && (
              <p className="px-3 py-2 text-xs text-gray-400 bg-gray-50">Showing first 10 of {csvRows.length} rows</p>
            )}
          </div>
        </div>
      )}

      {/* Step 3: Results */}
      {step === 'results' && result && (
        <div className="max-w-lg">
          <div className="rounded-lg border border-gray-200 bg-white p-6 space-y-4">
            <h3 className="text-lg font-semibold text-gray-900">Import Complete</h3>
            <div className="grid grid-cols-3 gap-4">
              <div className="text-center">
                <p className="text-2xl font-semibold text-green-700">{result.imported_count}</p>
                <p className="text-sm text-gray-500">Imported</p>
              </div>
              <div className="text-center">
                <p className="text-2xl font-semibold text-amber-700">{result.skipped_count}</p>
                <p className="text-sm text-gray-500">Skipped</p>
              </div>
              <div className="text-center">
                <p className="text-2xl font-semibold text-red-700">{result.error_count}</p>
                <p className="text-sm text-gray-500">Errors</p>
              </div>
            </div>

            {result.errors.length > 0 && (
              <div className="rounded border border-red-200 bg-red-50 p-3 text-sm text-red-700 max-h-40 overflow-y-auto">
                {result.errors.map((err, i) => (
                  <p key={i}>Row {err.row}: {err.field} — {err.message}</p>
                ))}
              </div>
            )}

            <Button onClick={handleReset} className="w-full">Import Another File</Button>
          </div>
        </div>
      )}
    </div>
  )
}
