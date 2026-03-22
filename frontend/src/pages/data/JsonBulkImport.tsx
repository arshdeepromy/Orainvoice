import { useState, useRef } from 'react'
import apiClient from '../../api/client'
import { Button, Spinner } from '../../components/ui'

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
      <p className="text-sm text-gray-500 mb-6">
        Import customers or vehicles in bulk by uploading a JSON file. Download the sample template to see the expected format.
      </p>

      {/* Entity type selector + sample download */}
      <div className="flex flex-wrap items-end gap-4 mb-6">
        <div>
          <label htmlFor="json-entity-type" className="block text-sm font-medium text-gray-700 mb-1">
            Import Type
          </label>
          <select
            id="json-entity-type"
            value={entityType}
            onChange={(e) => { setEntityType(e.target.value as EntityType); handleReset() }}
            className="block w-48 rounded-md border-gray-300 shadow-sm focus:border-blue-500 focus:ring-blue-500 sm:text-sm"
          >
            <option value="customers">Customers</option>
            <option value="vehicles">Vehicles</option>
          </select>
        </div>
        <Button variant="secondary" onClick={handleDownloadSample}>
          Download Sample JSON
        </Button>
      </div>

      {/* File upload */}
      {!result && (
        <div className="border-2 border-dashed border-gray-300 rounded-lg p-6 text-center mb-6">
          <label htmlFor="json-file-upload" className="cursor-pointer">
            <div className="text-gray-500 mb-2">
              <svg className="mx-auto h-10 w-10" fill="none" viewBox="0 0 24 24" stroke="currentColor" aria-hidden="true">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5} d="M12 16v-8m0 0l-3 3m3-3l3 3M4 16v2a2 2 0 002 2h12a2 2 0 002-2v-2" />
              </svg>
            </div>
            <span className="text-sm font-medium text-blue-600 hover:text-blue-500">
              Choose a JSON file
            </span>
            <span className="text-sm text-gray-500"> or drag and drop</span>
            <p className="text-xs text-gray-400 mt-1">JSON files up to 1000 records</p>
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
        <div className="rounded-md bg-red-50 p-4 mb-6" role="alert">
          <p className="text-sm text-red-700">{parseError}</p>
        </div>
      )}

      {/* Preview */}
      {jsonData && !result && (
        <div className="bg-gray-50 rounded-lg p-4 mb-6">
          <h3 className="text-sm font-medium text-gray-900 mb-2">
            Ready to import {jsonData.length} {entityType}
          </h3>
          <div className="max-h-60 overflow-auto rounded border bg-white">
            <table className="min-w-full text-xs">
              <thead className="bg-gray-100">
                <tr>
                  <th className="px-3 py-2 text-left font-medium text-gray-600">#</th>
                  {entityType === 'customers' ? (
                    <>
                      <th className="px-3 py-2 text-left font-medium text-gray-600">First Name</th>
                      <th className="px-3 py-2 text-left font-medium text-gray-600">Last Name</th>
                      <th className="px-3 py-2 text-left font-medium text-gray-600">Email</th>
                      <th className="px-3 py-2 text-left font-medium text-gray-600">Phone</th>
                      <th className="px-3 py-2 text-left font-medium text-gray-600">Company</th>
                      <th className="px-3 py-2 text-left font-medium text-gray-600">Type</th>
                    </>
                  ) : (
                    <>
                      <th className="px-3 py-2 text-left font-medium text-gray-600">Rego</th>
                      <th className="px-3 py-2 text-left font-medium text-gray-600">Make</th>
                      <th className="px-3 py-2 text-left font-medium text-gray-600">Model</th>
                      <th className="px-3 py-2 text-left font-medium text-gray-600">Year</th>
                      <th className="px-3 py-2 text-left font-medium text-gray-600">Colour</th>
                      <th className="px-3 py-2 text-left font-medium text-gray-600">VIN</th>
                      <th className="px-3 py-2 text-left font-medium text-gray-600">Transmission</th>
                      <th className="px-3 py-2 text-left font-medium text-gray-600">WOF Expiry</th>
                    </>
                  )}
                </tr>
              </thead>
              <tbody>
                {jsonData.slice(0, 20).map((item: any, idx) => (
                  <tr key={idx} className={idx % 2 === 0 ? 'bg-white' : 'bg-gray-50'}>
                    <td className="px-3 py-1.5 text-gray-500">{idx + 1}</td>
                    {entityType === 'customers' ? (
                      <>
                        <td className="px-3 py-1.5">{item.first_name || '—'}</td>
                        <td className="px-3 py-1.5">{item.last_name || '—'}</td>
                        <td className="px-3 py-1.5">{item.email || '—'}</td>
                        <td className="px-3 py-1.5">{item.phone || item.mobile_phone || '—'}</td>
                        <td className="px-3 py-1.5">{item.company_name || '—'}</td>
                        <td className="px-3 py-1.5">{item.customer_type || '—'}</td>
                      </>
                    ) : (
                      <>
                        <td className="px-3 py-1.5">{item.rego || '—'}</td>
                        <td className="px-3 py-1.5">{item.make || '—'}</td>
                        <td className="px-3 py-1.5">{item.model || '—'}</td>
                        <td className="px-3 py-1.5">{item.year || '—'}</td>
                        <td className="px-3 py-1.5">{item.colour || '—'}</td>
                        <td className="px-3 py-1.5">{item.vin || '—'}</td>
                        <td className="px-3 py-1.5">{item.transmission || '—'}</td>
                        <td className="px-3 py-1.5">{item.wof_expiry || '—'}</td>
                      </>
                    )}
                  </tr>
                ))}
              </tbody>
            </table>
            {jsonData.length > 20 && (
              <p className="text-xs text-gray-400 p-2 text-center">
                Showing first 20 of {jsonData.length} records
              </p>
            )}
          </div>
          <div className="flex gap-3 mt-4">
            <Button variant="secondary" onClick={handleReset}>Cancel</Button>
            <Button onClick={handleImport} loading={loading}>
              Import {jsonData.length} {entityType}
            </Button>
          </div>
        </div>
      )}

      {/* Loading */}
      {loading && (
        <div className="flex items-center gap-2 text-sm text-gray-500">
          <Spinner size="sm" /> Importing...
        </div>
      )}

      {/* Error */}
      {error && (
        <div className="rounded-md bg-red-50 p-4 mb-6" role="alert">
          <p className="text-sm text-red-700">{error}</p>
        </div>
      )}

      {/* Results */}
      {result && (
        <div className="space-y-4">
          <div className={`rounded-lg p-4 ${result.skipped_count > 0 ? 'bg-yellow-50' : 'bg-green-50'}`}>
            <h3 className={`text-sm font-semibold ${result.skipped_count > 0 ? 'text-yellow-800' : 'text-green-800'}`}>
              Import Complete
            </h3>
            <div className="mt-2 grid grid-cols-3 gap-4 text-sm">
              <div>
                <span className="text-gray-500">Submitted:</span>{' '}
                <span className="font-medium">{result.total_submitted}</span>
              </div>
              <div>
                <span className="text-gray-500">Imported:</span>{' '}
                <span className="font-medium text-green-700">{result.imported_count}</span>
              </div>
              <div>
                <span className="text-gray-500">Skipped:</span>{' '}
                <span className="font-medium text-red-600">{result.skipped_count}</span>
              </div>
            </div>
          </div>

          {result.errors.length > 0 && (
            <div className="rounded-lg border border-red-200 overflow-hidden">
              <div className="bg-red-50 px-4 py-2">
                <h4 className="text-sm font-medium text-red-800">
                  {result.errors.length} validation error{result.errors.length !== 1 ? 's' : ''}
                </h4>
              </div>
              <div className="max-h-48 overflow-auto">
                <table className="min-w-full text-xs">
                  <thead className="bg-gray-50">
                    <tr>
                      <th className="px-3 py-2 text-left font-medium text-gray-600">Row</th>
                      <th className="px-3 py-2 text-left font-medium text-gray-600">Field</th>
                      <th className="px-3 py-2 text-left font-medium text-gray-600">Error</th>
                    </tr>
                  </thead>
                  <tbody>
                    {result.errors.map((err, idx) => (
                      <tr key={idx} className={idx % 2 === 0 ? 'bg-white' : 'bg-gray-50'}>
                        <td className="px-3 py-1.5 text-gray-500">{err.index + 1}</td>
                        <td className="px-3 py-1.5 font-mono">{err.field || '—'}</td>
                        <td className="px-3 py-1.5 text-red-600">{err.error}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </div>
          )}

          <Button variant="secondary" onClick={handleReset}>Import More</Button>
        </div>
      )}
    </div>
  )
}
