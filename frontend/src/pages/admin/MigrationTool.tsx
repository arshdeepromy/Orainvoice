import { useState, useEffect, useCallback, useRef } from 'react'
import apiClient from '@/api/client'

/* ── Types ── */

export type MigrationMode = 'full' | 'live'
export type MigrationStatus =
  | 'pending'
  | 'validating'
  | 'in_progress'
  | 'integrity_check'
  | 'completed'
  | 'failed'
  | 'rolled_back'

export interface IntegrityCheckResult {
  passed: boolean
  record_counts: Record<string, { source: number; migrated: number }>
  financial_totals: Record<string, number>
  reference_errors: string[]
  invoice_numbering_gaps: string[]
}

export interface MigrationJob {
  id: string
  org_id: string
  mode: MigrationMode
  status: MigrationStatus
  source_format: string
  description: string | null
  records_processed: number
  records_total: number
  progress_pct: number
  integrity_check: IntegrityCheckResult | null
  error_message: string | null
  created_at: string
  updated_at: string
}

/* ── Helpers ── */

function statusBadge(status: MigrationStatus): { label: string; className: string } {
  const map: Record<MigrationStatus, { label: string; className: string }> = {
    pending: { label: 'Pending', className: 'badge-pending' },
    validating: { label: 'Validating', className: 'badge-validating' },
    in_progress: { label: 'In Progress', className: 'badge-progress' },
    integrity_check: { label: 'Checking', className: 'badge-checking' },
    completed: { label: 'Completed', className: 'badge-success' },
    failed: { label: 'Failed', className: 'badge-error' },
    rolled_back: { label: 'Rolled Back', className: 'badge-warning' },
  }
  return map[status] || { label: status, className: '' }
}

/* ── Source Upload Section ── */

interface SourceUploadProps {
  onDataLoaded: (data: Record<string, unknown[]>) => void
  sourceFormat: string
  onFormatChange: (format: string) => void
}

function SourceUpload({ onDataLoaded, sourceFormat, onFormatChange }: SourceUploadProps) {
  const fileInputRef = useRef<HTMLInputElement>(null)
  const [fileName, setFileName] = useState<string | null>(null)
  const [parseError, setParseError] = useState<string | null>(null)

  const handleFileChange = useCallback(
    async (e: React.ChangeEvent<HTMLInputElement>) => {
      const file = e.target.files?.[0]
      if (!file) return

      setFileName(file.name)
      setParseError(null)

      try {
        const text = await file.text()
        if (sourceFormat === 'json') {
          const parsed = JSON.parse(text)
          onDataLoaded(parsed)
        } else {
          // CSV: parse as simple key-value structure
          const lines = text.split('\n').filter(Boolean)
          if (lines.length < 2) {
            setParseError('CSV file must have a header row and at least one data row')
            return
          }
          const headers = lines[0].split(',').map((h) => h.trim())
          const rows = lines.slice(1).map((line) => {
            const values = line.split(',').map((v) => v.trim())
            const obj: Record<string, string> = {}
            headers.forEach((h, i) => {
              obj[h] = values[i] || ''
            })
            return obj
          })
          onDataLoaded({ imported_records: rows })
        }
      } catch (err) {
        setParseError(`Failed to parse file: ${err instanceof Error ? err.message : 'Unknown error'}`)
      }
    },
    [sourceFormat, onDataLoaded],
  )

  return (
    <div className="source-upload" role="region" aria-label="Source data upload">
      <h3>Upload Source Data</h3>
      <div className="format-selector">
        <label htmlFor="source-format">Format:</label>
        <select
          id="source-format"
          value={sourceFormat}
          onChange={(e) => onFormatChange(e.target.value)}
          aria-label="Source format"
        >
          <option value="json">JSON</option>
          <option value="csv">CSV</option>
        </select>
      </div>
      <div className="file-upload">
        <input
          ref={fileInputRef}
          type="file"
          accept={sourceFormat === 'json' ? '.json' : '.csv'}
          onChange={handleFileChange}
          aria-label="Upload source file"
        />
        {fileName && <span className="file-name">{fileName}</span>}
      </div>
      {parseError && (
        <div className="error-message" role="alert">
          {parseError}
        </div>
      )}
    </div>
  )
}

/* ── Field Mapping Section ── */

interface FieldMappingProps {
  sourceData: Record<string, unknown[]>
}

function FieldMapping({ sourceData }: FieldMappingProps) {
  const entityTypes = Object.keys(sourceData)

  return (
    <div className="field-mapping" role="region" aria-label="Field mapping">
      <h3>Data Mapping</h3>
      <table aria-label="Source data summary">
        <thead>
          <tr>
            <th>Entity Type</th>
            <th>Record Count</th>
            <th>Status</th>
          </tr>
        </thead>
        <tbody>
          {entityTypes.map((type) => (
            <tr key={type}>
              <td>{type}</td>
              <td>{Array.isArray(sourceData[type]) ? sourceData[type].length : 0}</td>
              <td>Ready</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}

/* ── Progress Tracker ── */

interface ProgressTrackerProps {
  job: MigrationJob | null
}

function ProgressTracker({ job }: ProgressTrackerProps) {
  if (!job) return null

  const badge = statusBadge(job.status)

  return (
    <div className="progress-tracker" role="region" aria-label="Migration progress">
      <h3>Migration Progress</h3>
      <div className="progress-header">
        <span className={`status-badge ${badge.className}`}>{badge.label}</span>
        <span className="progress-text">
          {job.records_processed} / {job.records_total} records
        </span>
      </div>
      <div
        className="progress-bar"
        role="progressbar"
        aria-valuenow={job.progress_pct}
        aria-valuemin={0}
        aria-valuemax={100}
        aria-label="Migration progress"
      >
        <div className="progress-fill" style={{ width: `${job.progress_pct}%` }} />
      </div>
      <span className="progress-pct">{job.progress_pct.toFixed(1)}%</span>
      {job.error_message && (
        <div className="error-message" role="alert">
          {job.error_message}
        </div>
      )}
    </div>
  )
}

/* ── Integrity Report ── */

interface IntegrityReportProps {
  result: IntegrityCheckResult
}

function IntegrityReport({ result }: IntegrityReportProps) {
  return (
    <div className="integrity-report" role="region" aria-label="Integrity check report">
      <h3>Integrity Check Report</h3>
      <div className={`integrity-status ${result.passed ? 'passed' : 'failed'}`}>
        {result.passed ? '✓ All checks passed' : '✗ Integrity check failed'}
      </div>

      <h4>Record Counts</h4>
      <table aria-label="Record count comparison">
        <thead>
          <tr>
            <th>Entity</th>
            <th>Source</th>
            <th>Migrated</th>
            <th>Match</th>
          </tr>
        </thead>
        <tbody>
          {Object.entries(result.record_counts).map(([entity, counts]) => (
            <tr key={entity}>
              <td>{entity}</td>
              <td>{counts.source}</td>
              <td>{counts.migrated}</td>
              <td>{counts.source === counts.migrated ? '✓' : '✗'}</td>
            </tr>
          ))}
        </tbody>
      </table>

      <h4>Financial Totals</h4>
      <table aria-label="Financial totals comparison">
        <thead>
          <tr>
            <th>Metric</th>
            <th>Value</th>
          </tr>
        </thead>
        <tbody>
          {Object.entries(result.financial_totals).map(([key, value]) => (
            <tr key={key}>
              <td>{key.replace(/_/g, ' ')}</td>
              <td>${value.toFixed(2)}</td>
            </tr>
          ))}
        </tbody>
      </table>

      {result.reference_errors.length > 0 && (
        <>
          <h4>Reference Errors</h4>
          <ul className="error-list" role="list" aria-label="Reference errors">
            {result.reference_errors.map((err, i) => (
              <li key={i} className="error-item">
                {err}
              </li>
            ))}
          </ul>
        </>
      )}

      {result.invoice_numbering_gaps.length > 0 && (
        <>
          <h4>Invoice Numbering Gaps</h4>
          <ul className="warning-list" role="list" aria-label="Numbering gaps">
            {result.invoice_numbering_gaps.map((gap, i) => (
              <li key={i} className="warning-item">
                {gap}
              </li>
            ))}
          </ul>
        </>
      )}
    </div>
  )
}

/* ── Main MigrationTool Component ── */

export function MigrationTool() {
  const [orgId, setOrgId] = useState('')
  const [mode, setMode] = useState<MigrationMode>('full')
  const [sourceFormat, setSourceFormat] = useState('json')
  const [sourceData, setSourceData] = useState<Record<string, unknown[]> | null>(null)
  const [description, setDescription] = useState('')
  const [currentJob, setCurrentJob] = useState<MigrationJob | null>(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null)

  // Poll for job status while in progress
  useEffect(() => {
    if (
      currentJob &&
      ['in_progress', 'validating', 'integrity_check'].includes(currentJob.status)
    ) {
      pollRef.current = setInterval(async () => {
        try {
          const res = await apiClient.get(
            `/api/v2/admin/migrations/status?job_id=${currentJob.id}`,
          )
          setCurrentJob(res.data)
          if (['completed', 'failed', 'rolled_back'].includes(res.data.status)) {
            if (pollRef.current) clearInterval(pollRef.current)
          }
        } catch {
          // Silently retry on next interval
        }
      }, 2000)

      return () => {
        if (pollRef.current) clearInterval(pollRef.current)
      }
    }
  }, [currentJob?.id, currentJob?.status])

  const handleCreateAndExecute = useCallback(async () => {
    if (!orgId || !sourceData) {
      setError('Please provide an organisation ID and upload source data')
      return
    }

    setLoading(true)
    setError(null)

    try {
      // Create the job
      const createRes = await apiClient.post('/api/v2/admin/migrations', {
        org_id: orgId,
        mode,
        source_format: sourceFormat,
        source_data: sourceData,
        description: description || undefined,
      })
      setCurrentJob(createRes.data)

      // Execute the job
      const execRes = await apiClient.post('/api/v2/admin/migrations/execute', {
        job_id: createRes.data.id,
      })
      setCurrentJob(execRes.data)
    } catch (err: unknown) {
      const msg =
        err instanceof Error
          ? err.message
          : typeof err === 'object' && err !== null && 'response' in err
            ? String((err as { response?: { data?: { detail?: string } } }).response?.data?.detail)
            : 'Migration failed'
      setError(msg)
    } finally {
      setLoading(false)
    }
  }, [orgId, mode, sourceFormat, sourceData, description])

  const handleRollback = useCallback(async () => {
    if (!currentJob) return

    setLoading(true)
    setError(null)

    try {
      await apiClient.post('/api/v2/admin/migrations/rollback', {
        job_id: currentJob.id,
        reason: 'Manual rollback from admin console',
      })
      // Refresh status
      const res = await apiClient.get(
        `/api/v2/admin/migrations/status?job_id=${currentJob.id}`,
      )
      setCurrentJob(res.data)
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : 'Rollback failed'
      setError(msg)
    } finally {
      setLoading(false)
    }
  }, [currentJob])

  return (
    <div className="migration-tool" role="main" aria-label="Database Migration Tool">
      <h2>Database Migration Tool</h2>
      <p className="description">
        Import data from external sources into an organisation. Supports full migration
        (all data at once) and live migration (dual-write with sync verification).
      </p>

      {error && (
        <div className="error-banner" role="alert">
          {error}
        </div>
      )}

      {/* Configuration */}
      <div className="config-section" role="region" aria-label="Migration configuration">
        <h3>Configuration</h3>
        <div className="form-group">
          <label htmlFor="org-id">Organisation ID:</label>
          <input
            id="org-id"
            type="text"
            value={orgId}
            onChange={(e) => setOrgId(e.target.value)}
            placeholder="Enter organisation UUID"
            aria-label="Organisation ID"
          />
        </div>
        <div className="form-group">
          <label htmlFor="migration-mode">Mode:</label>
          <select
            id="migration-mode"
            value={mode}
            onChange={(e) => setMode(e.target.value as MigrationMode)}
            aria-label="Migration mode"
          >
            <option value="full">Full Migration</option>
            <option value="live">Live Migration</option>
          </select>
        </div>
        <div className="form-group">
          <label htmlFor="migration-desc">Description:</label>
          <input
            id="migration-desc"
            type="text"
            value={description}
            onChange={(e) => setDescription(e.target.value)}
            placeholder="Optional description"
            aria-label="Migration description"
          />
        </div>
      </div>

      {/* Source Upload */}
      <SourceUpload
        onDataLoaded={setSourceData}
        sourceFormat={sourceFormat}
        onFormatChange={setSourceFormat}
      />

      {/* Field Mapping */}
      {sourceData && <FieldMapping sourceData={sourceData} />}

      {/* Actions */}
      <div className="actions" role="region" aria-label="Migration actions">
        <button
          onClick={handleCreateAndExecute}
          disabled={loading || !orgId || !sourceData}
          aria-label="Start migration"
        >
          {loading ? 'Processing...' : 'Start Migration'}
        </button>
        {currentJob && !['rolled_back', 'pending'].includes(currentJob.status) && (
          <button
            onClick={handleRollback}
            disabled={loading || currentJob.status === 'rolled_back'}
            className="btn-danger"
            aria-label="Rollback migration"
          >
            Rollback
          </button>
        )}
      </div>

      {/* Progress */}
      <ProgressTracker job={currentJob} />

      {/* Integrity Report */}
      {currentJob?.integrity_check && (
        <IntegrityReport result={currentJob.integrity_check} />
      )}
    </div>
  )
}

export default MigrationTool
