import { useState, useRef } from 'react'
import apiClient from '@/api/client'
import { Button, Spinner } from '@/components/ui'

type EntityType = 'customers' | 'vehicles'

interface BulkImportError {
  index: number
  field: string | null
  error: string
}

interface BulkImportResult {
  imported_count: number
  skipped_count: number
  total_submitted: number
  errors: BulkImportError[]
}

const inputClass =
  'block w-48 min-h-[44px] rounded-ctl border border-border bg-card px-3 py-2 text-sm text-text outline-none focus:border-accent focus:ring-1 focus:ring-accent'

export default function JsonBulkImport() {
  const [entityType, setEntityType] = useState<EntityType>('customers')
  const [jsonData, setJsonData] = useState<unknown[] | null>(null)
  const [parseError, setParseError] = useState('')
  const [result, setResult] = useState<BulkImportResult | null>(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')
  const fileRef = useRef<HTMLInputElement>(null)

  const handleFileUpload = (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0]
    if (!file) return
    setParseError('')
    setResult(null)
    setError('')

    if (!file.name.endsWith('.json')) {
      setParseError('Please upload a .json file')
      return
    }

    const reader = new FileReader()
    reader.onload = (ev) => {
      try {
        const parsed = JSON.parse(ev.target?.result as string)
        if (!Array.isArray(parsed)) {
          setParseError('JSON file must contain an array of objects. Download the sample template to see the expected format.')
          return
        }
        if (parsed.length === 0) {
          setParseError('JSON array is empty — nothing to import.')
          return
        }
        if (parsed.length > 1000) {
          setParseError('Maximum 1000 records per import. Please split your file.')
          return
        }
        setJsonData(parsed)
      } catch {
        setParseError('Invalid JSON file. Please check the format and try again.')
      }
    }
    reader.readAsText(file)
  }

  const handleImport = async () => {
    if (!jsonData) return
    setLoading(true)
    setError('')
    setResult(null)
    try {
      const res = await apiClient.post<BulkImportResult>(
        `/data/import/json/${entityType}`,
        jsonData,
      )
      setResult(res.data)
    } catch (err: any) {
      setError(err?.response?.data?.detail || 'Import failed. Please try again.')
    } finally {
      setLoading(false)
    }
  }

  const handleDownloadSample = async () => {
    try {
      const res = await apiClient.get(`/data/import/json/sample/${entityType}`)
      const blob = new Blob([JSON.stringify(res.data, null, 2)], { type: 'application/json' })
      const url = URL.createObjectURL(blob)
      const a = document.createElement('a')
      a.href = url
      a.download = `sample-${entityType}.json`
      a.click()
      URL.revokeObjectURL(url)
    } catch {
      setError('Failed to download sample template.')
    }
  }

  const handleReset = () => {
    setJsonData(null)
    setResult(null)
    setError('')
    setParseError('')
    if (fileRef.current) fileRef.current.value = ''
  }

  return (
    <div>
      <p className="mb-6 text-sm text-muted">
        Import customers or vehicles in bulk by uploading a JSON file. Download the sample template to see the expected format.
      </p>

      {/* Entity type selector + sample download */}
      <div className="mb-6 flex flex-wrap items-end gap-4">
        <div>
          <label htmlFor="json-entity-type" className="mb-1 block text-sm font-medium text-text">
            Import Type
          </label>
          <select
            id="json-entity-type"
            value={entityType}
            onChange={(e) => { setEntityType(e.target.value as EntityType); handleReset() }}
            className={inputClass}
          >
            <option value="customers">Customers</option>
            <option value="vehicles">Vehicles</option>
          </select>
        </div>
        <Button variant="ghost" onClick={handleDownloadSample}>
          Download Sample JSON
        </Button>
      </div>

      {/* File upload */}
      {!result && (
        <div className="mb-6 rounded-card border-2 border-dashed border-border p-6 text-center">
          <label htmlFor="json-file-upload" className="cursor-pointer">
            <div className="mb-2 text-muted">
              <svg className="mx-auto h-10 w-10" fill="none" viewBox="0 0 24 24" stroke="currentColor" aria-hidden="true">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5} d="M12 16v-8m0 0l-3 3m3-3l3 3M4 16v2a2 2 0 002 2h12a2 2 0 002-2v-2" />
              </svg>
            </div>
            <span className="text-sm font-medium text-accent hover:text-accent-press">
              Choose a JSON file
            </span>
            <span className="text-sm text-muted"> or drag and drop</span>
            <p className="mt-1 text-xs text-muted-2">JSON files up to 1000 records</p>
          </label>
          <input
            ref={fileRef}
            id="json-file-upload"
            type="file"
            accept=".json,application/json"
            className="sr-only"
            onChange={handleFileUpload}
            aria-label="Select JSON file"
          />
        </div>
      )}

      {/* Parse error */}
      {parseError && (
        <div className="mb-6 rounded-ctl bg-danger-soft p-4" role="alert">
          <p className="text-sm text-danger">{parseError}</p>
        </div>
      )}

      {/* Preview */}
      {jsonData && !result && (
        <div className="mb-6 rounded-card bg-canvas p-4">
          <h3 className="mb-2 text-sm font-medium text-text">
            Ready to import {jsonData.length} {entityType}
          </h3>
          <div className="max-h-60 overflow-auto rounded-card border border-border bg-card">
            <table className="min-w-full text-xs">
              <thead className="bg-canvas">
                <tr>
                  <th className="px-3 py-2 text-left font-medium text-muted">#</th>
                  {entityType === 'customers' ? (
                    <>
                      <th className="px-3 py-2 text-left font-medium text-muted">First Name</th>
                      <th className="px-3 py-2 text-left font-medium text-muted">Last Name</th>
                      <th className="px-3 py-2 text-left font-medium text-muted">Email</th>
                      <th className="px-3 py-2 text-left font-medium text-muted">Phone</th>
                      <th className="px-3 py-2 text-left font-medium text-muted">Company</th>
                      <th className="px-3 py-2 text-left font-medium text-muted">Type</th>
                    </>
                  ) : (
                    <>
                      <th className="px-3 py-2 text-left font-medium text-muted">Rego</th>
                      <th className="px-3 py-2 text-left font-medium text-muted">Make</th>
                      <th className="px-3 py-2 text-left font-medium text-muted">Model</th>
                      <th className="px-3 py-2 text-left font-medium text-muted">Year</th>
                      <th className="px-3 py-2 text-left font-medium text-muted">Colour</th>
                      <th className="px-3 py-2 text-left font-medium text-muted">VIN</th>
                      <th className="px-3 py-2 text-left font-medium text-muted">Transmission</th>
                      <th className="px-3 py-2 text-left font-medium text-muted">WOF Expiry</th>
                      <th className="px-3 py-2 text-left font-medium text-muted">COF Expiry</th>
                      <th className="px-3 py-2 text-left font-medium text-muted">Inspection Type</th>
                    </>
                  )}
                </tr>
              </thead>
              <tbody>
                {jsonData.slice(0, 20).map((item: any, idx) => (
                  <tr key={idx} className={idx % 2 === 0 ? 'bg-card' : 'bg-canvas'}>
                    <td className="px-3 py-1.5 text-muted">{idx + 1}</td>
                    {entityType === 'customers' ? (
                      <>
                        <td className="px-3 py-1.5 text-text">{item.first_name || '—'}</td>
                        <td className="px-3 py-1.5 text-text">{item.last_name || '—'}</td>
                        <td className="px-3 py-1.5 text-text">{item.email || '—'}</td>
                        <td className="px-3 py-1.5 text-text">{item.phone || item.mobile_phone || '—'}</td>
                        <td className="px-3 py-1.5 text-text">{item.company_name || '—'}</td>
                        <td className="px-3 py-1.5 text-text">{item.customer_type || '—'}</td>
                      </>
                    ) : (
                      <>
                        <td className="px-3 py-1.5 text-text">{item?.rego || '—'}</td>
                        <td className="px-3 py-1.5 text-text">{item?.make || '—'}</td>
                        <td className="px-3 py-1.5 text-text">{item?.model || '—'}</td>
                        <td className="px-3 py-1.5 text-text">{item?.year || '—'}</td>
                        <td className="px-3 py-1.5 text-text">{item?.colour || '—'}</td>
                        <td className="px-3 py-1.5 text-text">{item?.vin || '—'}</td>
                        <td className="px-3 py-1.5 text-text">{item?.transmission || '—'}</td>
                        <td className="px-3 py-1.5 text-text">{item?.wof_expiry || '—'}</td>
                        <td className="px-3 py-1.5 text-text">{item?.cof_expiry || '—'}</td>
                        <td className="px-3 py-1.5 text-text">{item?.inspection_type || '—'}</td>
                      </>
                    )}
                  </tr>
                ))}
              </tbody>
            </table>
            {jsonData.length > 20 && (
              <p className="p-2 text-center text-xs text-muted-2">
                Showing first 20 of {jsonData.length} records
              </p>
            )}
          </div>
          <div className="mt-4 flex gap-3">
            <Button variant="ghost" onClick={handleReset}>Cancel</Button>
            <Button onClick={handleImport} loading={loading}>
              Import {jsonData.length} {entityType}
            </Button>
          </div>
        </div>
      )}

      {/* Loading */}
      {loading && (
        <div className="flex items-center gap-2 text-sm text-muted">
          <Spinner size="sm" /> Importing...
        </div>
      )}

      {/* Error */}
      {error && (
        <div className="mb-6 rounded-ctl bg-danger-soft p-4" role="alert">
          <p className="text-sm text-danger">{error}</p>
        </div>
      )}

      {/* Results */}
      {result && (
        <div className="space-y-4">
          <div className={`rounded-card p-4 ${result.skipped_count > 0 ? 'bg-warn-soft' : 'bg-ok-soft'}`}>
            <h3 className={`text-sm font-semibold ${result.skipped_count > 0 ? 'text-warn' : 'text-ok'}`}>
              Import Complete
            </h3>
            <div className="mt-2 grid grid-cols-3 gap-4 text-sm">
              <div>
                <span className="text-muted">Submitted:</span>{' '}
                <span className="mono font-medium text-text">{result.total_submitted}</span>
              </div>
              <div>
                <span className="text-muted">Imported:</span>{' '}
                <span className="mono font-medium text-ok">{result.imported_count}</span>
              </div>
              <div>
                <span className="text-muted">Skipped:</span>{' '}
                <span className="mono font-medium text-danger">{result.skipped_count}</span>
              </div>
            </div>
          </div>

          {(result.errors ?? []).length > 0 && (
            <div className="overflow-hidden rounded-card border border-danger">
              <div className="bg-danger-soft px-4 py-2">
                <h4 className="text-sm font-medium text-danger">
                  {(result.errors ?? []).length} validation error{(result.errors ?? []).length !== 1 ? 's' : ''}
                </h4>
              </div>
              <div className="max-h-48 overflow-auto">
                <table className="min-w-full text-xs">
                  <thead className="bg-canvas">
                    <tr>
                      <th className="px-3 py-2 text-left font-medium text-muted">Row</th>
                      <th className="px-3 py-2 text-left font-medium text-muted">Field</th>
                      <th className="px-3 py-2 text-left font-medium text-muted">Error</th>
                    </tr>
                  </thead>
                  <tbody>
                    {(result.errors ?? []).map((err, idx) => (
                      <tr key={idx} className={idx % 2 === 0 ? 'bg-card' : 'bg-canvas'}>
                        <td className="mono px-3 py-1.5 text-muted">{err.index + 1}</td>
                        <td className="mono px-3 py-1.5 text-text">{err.field || '—'}</td>
                        <td className="px-3 py-1.5 text-danger">{err.error}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </div>
          )}

          <Button variant="ghost" onClick={handleReset}>Import More</Button>
        </div>
      )}
    </div>
  )
}
