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
    pending: { label: 'Pending', className: 'bg-warn-soft text-warn' },
    validating: { label: 'Validating', className: 'bg-accent-soft text-accent' },
    in_progress: { label: 'In Progress', className: 'bg-accent-soft text-accent' },
    integrity_check: { label: 'Checking', className: 'bg-purple-soft text-purple' },
    completed: { label: 'Completed', className: 'bg-ok-soft text-ok' },
    failed: { label: 'Failed', className: 'bg-danger-soft text-danger' },
    rolled_back: { label: 'Rolled Back', className: 'bg-warn-soft text-warn' },
  }
  return map[status] || { label: status, className: 'bg-canvas text-muted' }
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
    <div className="rounded-card border border-border bg-card p-5 shadow-card space-y-4" role="region" aria-label="Source data upload">
      <h3 className="text-lg font-semibold text-text">Upload Source Data</h3>
      <div className="flex items-center gap-3">
        <label htmlFor="source-format" className="text-[12.5px] font-medium text-text">Format:</label>
        <select
          id="source-format"
          value={sourceFormat}
          onChange={(e) => onFormatChange(e.target.value)}
          aria-label="Source format"
          className="h-[42px] rounded-ctl border border-border bg-card px-[13px] text-[13.5px] text-text focus:border-accent focus:outline-none focus:shadow-[0_0_0_3px_var(--accent-soft)]"
        >
          <option value="json">JSON</option>
          <option value="csv">CSV</option>
        </select>
      </div>
      <div className="flex items-center gap-3">
        <input
          ref={fileInputRef}
          type="file"
          accept={sourceFormat === 'json' ? '.json' : '.csv'}
          onChange={handleFileChange}
          aria-label="Upload source file"
          className="text-sm text-muted file:mr-3 file:rounded-ctl file:border file:border-border file:bg-card file:px-3 file:py-1.5 file:text-sm file:text-text hover:file:bg-canvas"
        />
        {fileName && <span className="mono text-sm text-muted">{fileName}</span>}
      </div>
      {parseError && (
        <div className="rounded-ctl border border-danger/30 bg-danger-soft px-4 py-3 text-sm text-danger" role="alert">
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
    <div className="space-y-3" role="region" aria-label="Field mapping">
      <h3 className="text-lg font-semibold text-text">Data Mapping</h3>
      <div className="overflow-hidden rounded-card border border-border bg-card shadow-card">
        <table className="min-w-full" aria-label="Source data summary">
          <thead>
            <tr>
              <th className="mono border-b border-border px-4 py-3 text-left text-[10.5px] font-medium uppercase tracking-[0.08em] text-muted-2">Entity Type</th>
              <th className="mono border-b border-border px-4 py-3 text-left text-[10.5px] font-medium uppercase tracking-[0.08em] text-muted-2">Record Count</th>
              <th className="mono border-b border-border px-4 py-3 text-left text-[10.5px] font-medium uppercase tracking-[0.08em] text-muted-2">Status</th>
            </tr>
          </thead>
          <tbody>
            {entityTypes.map((type) => (
              <tr key={type} className="border-b border-border last:border-b-0 hover:bg-canvas">
                <td className="px-4 py-2 text-sm text-text">{type}</td>
                <td className="mono px-4 py-2 text-sm text-text">{Array.isArray(sourceData[type]) ? sourceData[type].length : 0}</td>
                <td className="px-4 py-2 text-sm text-muted">Ready</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
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
    <div className="rounded-card border border-border bg-card p-5 shadow-card space-y-3" role="region" aria-label="Migration progress">
      <h3 className="text-lg font-semibold text-text">Migration Progress</h3>
      <div className="flex items-center justify-between">
        <span className={`inline-flex items-center rounded-full px-2.5 py-0.5 text-xs font-medium ${badge.className}`}>{badge.label}</span>
        <span className="mono text-sm text-muted">
          {job.records_processed} / {job.records_total} records
        </span>
      </div>
      <div
        className="h-2.5 w-full overflow-hidden rounded-full bg-border"
        role="progressbar"
        aria-valuenow={job.progress_pct}
        aria-valuemin={0}
        aria-valuemax={100}
        aria-label="Migration progress"
      >
        <div className="h-full bg-accent transition-all" style={{ width: `${job.progress_pct}%` }} />
      </div>
      <span className="mono text-sm text-muted">{(job.progress_pct ?? 0).toFixed(1)}%</span>
      {job.error_message && (
        <div className="rounded-ctl border border-danger/30 bg-danger-soft px-4 py-3 text-sm text-danger" role="alert">
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
    <div className="rounded-card border border-border bg-card p-5 shadow-card space-y-4" role="region" aria-label="Integrity check report">
      <h3 className="text-lg font-semibold text-text">Integrity Check Report</h3>
      <div className={`rounded-ctl px-4 py-3 text-sm font-medium ${result.passed ? 'bg-ok-soft text-ok' : 'bg-danger-soft text-danger'}`}>
        {result.passed ? '✓ All checks passed' : '✗ Integrity check failed'}
      </div>

      <h4 className="text-sm font-semibold text-text">Record Counts</h4>
      <div className="overflow-hidden rounded-card border border-border">
        <table className="min-w-full" aria-label="Record count comparison">
          <thead>
            <tr>
              <th className="mono border-b border-border px-4 py-3 text-left text-[10.5px] font-medium uppercase tracking-[0.08em] text-muted-2">Entity</th>
              <th className="mono border-b border-border px-4 py-3 text-left text-[10.5px] font-medium uppercase tracking-[0.08em] text-muted-2">Source</th>
              <th className="mono border-b border-border px-4 py-3 text-left text-[10.5px] font-medium uppercase tracking-[0.08em] text-muted-2">Migrated</th>
              <th className="mono border-b border-border px-4 py-3 text-left text-[10.5px] font-medium uppercase tracking-[0.08em] text-muted-2">Match</th>
            </tr>
          </thead>
          <tbody>
            {Object.entries(result.record_counts).map(([entity, counts]) => (
              <tr key={entity} className="border-b border-border last:border-b-0 hover:bg-canvas">
                <td className="px-4 py-2 text-sm text-text">{entity}</td>
                <td className="mono px-4 py-2 text-sm text-text">{counts.source}</td>
                <td className="mono px-4 py-2 text-sm text-text">{counts.migrated}</td>
                <td className="px-4 py-2 text-sm">{counts.source === counts.migrated ? '✓' : '✗'}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      <h4 className="text-sm font-semibold text-text">Financial Totals</h4>
      <div className="overflow-hidden rounded-card border border-border">
        <table className="min-w-full" aria-label="Financial totals comparison">
          <thead>
            <tr>
              <th className="mono border-b border-border px-4 py-3 text-left text-[10.5px] font-medium uppercase tracking-[0.08em] text-muted-2">Metric</th>
              <th className="mono border-b border-border px-4 py-3 text-left text-[10.5px] font-medium uppercase tracking-[0.08em] text-muted-2">Value</th>
            </tr>
          </thead>
          <tbody>
            {Object.entries(result.financial_totals).map(([key, value]) => (
              <tr key={key} className="border-b border-border last:border-b-0 hover:bg-canvas">
                <td className="px-4 py-2 text-sm text-text">{key.replace(/_/g, ' ')}</td>
                <td className="mono px-4 py-2 text-sm text-text">${(value ?? 0).toFixed(2)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      {result.reference_errors.length > 0 && (
        <>
          <h4 className="text-sm font-semibold text-text">Reference Errors</h4>
          <ul className="space-y-1" role="list" aria-label="Reference errors">
            {result.reference_errors.map((err, i) => (
              <li key={i} className="rounded-ctl bg-danger-soft px-3 py-2 text-sm text-danger">
                {err}
              </li>
            ))}
          </ul>
        </>
      )}

      {result.invoice_numbering_gaps.length > 0 && (
        <>
          <h4 className="text-sm font-semibold text-text">Invoice Numbering Gaps</h4>
          <ul className="space-y-1" role="list" aria-label="Numbering gaps">
            {result.invoice_numbering_gaps.map((gap, i) => (
              <li key={i} className="rounded-ctl bg-warn-soft px-3 py-2 text-sm text-warn">
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
    <div className="space-y-6" role="main" aria-label="Database Migration Tool">
      <h2 className="text-2xl font-semibold text-text">Database Migration Tool</h2>
      <p className="text-sm text-muted">
        Import data from external sources into an organisation. Supports full migration
        (all data at once) and live migration (dual-write with sync verification).
      </p>

      {error && (
        <div className="rounded-ctl border border-danger/30 bg-danger-soft px-4 py-3 text-sm text-danger" role="alert">
          {error}
        </div>
      )}

      {/* Configuration */}
      <div className="rounded-card border border-border bg-card p-5 shadow-card space-y-4" role="region" aria-label="Migration configuration">
        <h3 className="text-lg font-semibold text-text">Configuration</h3>
        <div className="flex flex-col gap-[7px]">
          <label htmlFor="org-id" className="text-[12.5px] font-medium text-text">Organisation ID:</label>
          <input
            id="org-id"
            type="text"
            value={orgId}
            onChange={(e) => setOrgId(e.target.value)}
            placeholder="Enter organisation UUID"
            aria-label="Organisation ID"
            className="h-[42px] w-full rounded-ctl border border-border bg-card px-[13px] text-[13.5px] text-text placeholder:text-muted-2 focus:border-accent focus:outline-none focus:shadow-[0_0_0_3px_var(--accent-soft)]"
          />
        </div>
        <div className="flex flex-col gap-[7px]">
          <label htmlFor="migration-mode" className="text-[12.5px] font-medium text-text">Mode:</label>
          <select
            id="migration-mode"
            value={mode}
            onChange={(e) => setMode(e.target.value as MigrationMode)}
            aria-label="Migration mode"
            className="h-[42px] w-full rounded-ctl border border-border bg-card px-[13px] text-[13.5px] text-text focus:border-accent focus:outline-none focus:shadow-[0_0_0_3px_var(--accent-soft)]"
          >
            <option value="full">Full Migration</option>
            <option value="live">Live Migration</option>
          </select>
        </div>
        <div className="flex flex-col gap-[7px]">
          <label htmlFor="migration-desc" className="text-[12.5px] font-medium text-text">Description:</label>
          <input
            id="migration-desc"
            type="text"
            value={description}
            onChange={(e) => setDescription(e.target.value)}
            placeholder="Optional description"
            aria-label="Migration description"
            className="h-[42px] w-full rounded-ctl border border-border bg-card px-[13px] text-[13.5px] text-text placeholder:text-muted-2 focus:border-accent focus:outline-none focus:shadow-[0_0_0_3px_var(--accent-soft)]"
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
      <div className="flex gap-3" role="region" aria-label="Migration actions">
        <button
          onClick={handleCreateAndExecute}
          disabled={loading || !orgId || !sourceData}
          aria-label="Start migration"
          className="inline-flex h-10 items-center justify-center rounded-ctl bg-accent px-4 text-[13.5px] font-semibold text-white shadow-[0_1px_2px_rgba(16,24,40,0.18),inset_0_1px_0_rgba(255,255,255,0.14)] hover:bg-accent-press disabled:pointer-events-none disabled:opacity-60"
        >
          {loading ? 'Processing...' : 'Start Migration'}
        </button>
        {currentJob && !['rolled_back', 'pending'].includes(currentJob.status) && (
          <button
            onClick={handleRollback}
            disabled={loading || currentJob.status === 'rolled_back'}
            className="inline-flex h-10 items-center justify-center rounded-ctl bg-danger px-4 text-[13.5px] font-semibold text-white hover:brightness-95 disabled:pointer-events-none disabled:opacity-60"
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
