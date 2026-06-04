import { useState, useRef } from 'react'
import apiClient from '@/api/client'
import { Button } from '@/components/ui'

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

const TH = 'mono border-b border-border px-3 py-2 text-left text-[10.5px] font-medium uppercase tracking-[0.08em] text-muted-2'

/**
 * CSVImport — Task 36 port of frontend/src/pages/inventory/CSVImport.tsx.
 *
 * CSV product import with 3 steps: upload → preview/map fields → results. ALL
 * logic — the CSV parser, auto field-mapping heuristics, file select +
 * FileReader, the preview POST and import POST to /v2/products/csv-import
 * (preview_only toggle), and the reset flow — copied VERBATIM. Presentation
 * remapped onto the design tokens (FR-2b); the page is wrapped in a
 * `page page-wide` + `.page-head` so it is reachable standalone.
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
    <div className="page page-wide">
      <div className="page-head">
        <div>
          <div className="eyebrow">Stock</div>
          <h1>CSV Import</h1>
          <p className="sub">Bulk import products from a CSV file</p>
        </div>
      </div>

      {/* Step indicator */}
      <div className="flex items-center gap-2 mb-6" role="navigation" aria-label="Import steps">
        {(['upload', 'preview', 'results'] as Step[]).map((s, i) => (
          <div key={s} className="flex items-center gap-2">
            {i > 0 && <span className="text-muted-2">→</span>}
            <span className={`text-sm font-medium px-3 py-1 rounded-full ${step === s ? 'bg-accent-soft text-accent' : 'text-muted'}`}>
              {i + 1}. {s === 'upload' ? 'Upload' : s === 'preview' ? 'Preview & Map' : 'Results'}
            </span>
          </div>
        ))}
      </div>

      {error && (
        <div className="mb-4 rounded-ctl border border-danger/30 bg-danger-soft px-4 py-3 text-[13px] text-danger" role="alert">{error}</div>
      )}

      {/* Step 1: Upload */}
      {step === 'upload' && (
        <div className="max-w-lg">
          <p className="text-[13px] text-muted mb-4">
            Upload a CSV file with product data. The first row should contain column headers.
          </p>
          <div className="border-2 border-dashed border-border rounded-card p-8 text-center">
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
              <p className="text-sm font-medium text-accent hover:text-accent-press">
                Click to select a CSV file
              </p>
              <p className="text-xs text-muted-2 mt-1">or drag and drop</p>
            </label>
          </div>
        </div>
      )}

      {/* Step 2: Preview & Map */}
      {step === 'preview' && (
        <div>
          <div className="flex items-center justify-between mb-4">
            <div>
              <p className="text-sm font-medium text-text">{fileName}</p>
              <p className="text-xs text-muted">{csvRows.length} rows, {csvHeaders.length} columns</p>
            </div>
            <div className="flex gap-2">
              <Button variant="ghost" onClick={handleReset}>Start Over</Button>
              <Button onClick={handlePreview} loading={loading}>Validate</Button>
              <Button onClick={handleImport} loading={loading} disabled={csvRows.length === 0}>
                Import {preview ? preview.valid_rows : csvRows.length} Products
              </Button>
            </div>
          </div>

          {/* Field mapping */}
          <div className="mb-6">
            <h3 className="text-sm font-semibold text-text mb-2">Field Mapping</h3>
            <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-3">
              {fieldMappings.map((m, i) => (
                <div key={m.source_column} className="flex items-center gap-2">
                  <span className="text-sm text-muted w-32 truncate" title={m.source_column}>{m.source_column}</span>
                  <span className="text-muted-2">→</span>
                  <select
                    className="h-[42px] flex-1 rounded-ctl border border-border bg-card px-2 text-sm text-text focus:border-accent focus:outline-none focus:shadow-[0_0_0_3px_var(--accent-soft)]"
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
              <div className="rounded-card border border-ok/30 bg-ok-soft p-3">
                <p className="text-sm text-ok">Valid rows</p>
                <p className="mono text-xl font-semibold text-ok">{preview.valid_rows}</p>
              </div>
              <div className="rounded-card border border-danger/30 bg-danger-soft p-3">
                <p className="text-sm text-danger">Error rows</p>
                <p className="mono text-xl font-semibold text-danger">{preview.error_rows}</p>
              </div>
              <div className="rounded-card border border-border bg-canvas p-3">
                <p className="text-sm text-muted">Total rows</p>
                <p className="mono text-xl font-semibold text-text">{preview.total_rows}</p>
              </div>
            </div>
          )}

          {/* Preview errors */}
          {preview && (preview.errors ?? []).length > 0 && (
            <div className="mb-4">
              <h3 className="text-sm font-semibold text-danger mb-2">Validation Errors</h3>
              <div className="max-h-40 overflow-y-auto rounded-ctl border border-danger/30 bg-danger-soft p-3 text-sm text-danger">
                {(preview.errors ?? []).slice(0, 20).map((err, i) => (
                  <p key={i}>Row {err.row}: {err.field} — {err.message}</p>
                ))}
                {(preview.errors ?? []).length > 20 && <p>…and {(preview.errors ?? []).length - 20} more</p>}
              </div>
            </div>
          )}

          {/* Data preview table */}
          <section className="overflow-hidden rounded-card border border-border bg-card shadow-card">
            <div className="overflow-x-auto">
            <table className="w-full border-collapse" role="grid">
              <caption className="sr-only">CSV data preview</caption>
              <thead>
                <tr>
                  <th scope="col" className={TH}>#</th>
                  {csvHeaders.map((h) => (
                    <th key={h} scope="col" className={TH}>{h}</th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {csvRows.slice(0, 10).map((row, i) => (
                  <tr key={i} className="border-b border-border last:border-b-0 hover:bg-canvas">
                    <td className="mono px-3 py-2 text-xs text-muted-2">{i + 1}</td>
                    {csvHeaders.map((h) => (
                      <td key={h} className="px-3 py-2 text-sm text-muted max-w-xs truncate">{row[h] || ''}</td>
                    ))}
                  </tr>
                ))}
              </tbody>
            </table>
            </div>
            {csvRows.length > 10 && (
              <p className="px-3 py-2 text-xs text-muted-2 bg-canvas">Showing first 10 of {csvRows.length} rows</p>
            )}
          </section>
        </div>
      )}

      {/* Step 3: Results */}
      {step === 'results' && result && (
        <div className="max-w-lg">
          <div className="rounded-card border border-border bg-card p-6 shadow-card space-y-4">
            <h3 className="text-lg font-semibold text-text">Import Complete</h3>
            <div className="grid grid-cols-3 gap-4">
              <div className="text-center">
                <p className="mono text-2xl font-semibold text-ok">{result.imported_count}</p>
                <p className="text-sm text-muted">Imported</p>
              </div>
              <div className="text-center">
                <p className="mono text-2xl font-semibold text-warn">{result.skipped_count}</p>
                <p className="text-sm text-muted">Skipped</p>
              </div>
              <div className="text-center">
                <p className="mono text-2xl font-semibold text-danger">{result.error_count}</p>
                <p className="text-sm text-muted">Errors</p>
              </div>
            </div>

            {(result.errors ?? []).length > 0 && (
              <div className="rounded-ctl border border-danger/30 bg-danger-soft p-3 text-sm text-danger max-h-40 overflow-y-auto">
                {(result.errors ?? []).map((err, i) => (
                  <p key={i}>Row {err.row}: {err.field} — {err.message}</p>
                ))}
              </div>
            )}

            <Button onClick={handleReset} fullWidth>Import Another File</Button>
          </div>
        </div>
      )}
    </div>
  )
}
