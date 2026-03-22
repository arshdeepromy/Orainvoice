import { useState, useEffect, useCallback, useRef } from 'react'
import apiClient from '@/api/client'

/* ── Types ── */

export type MigrationJobStatus =
  | 'pending'
  | 'validating'
  | 'schema_migrating'
  | 'copying_data'
  | 'draining_queue'
  | 'integrity_check'
  | 'ready_for_cutover'
  | 'cutting_over'
  | 'completed'
  | 'failed'
  | 'cancelled'
  | 'rolled_back'

export interface TableProgress {
  table_name: string
  source_count: number
  migrated_count: number
  status: 'pending' | 'in_progress' | 'completed' | 'failed'
}

export interface RowCountComparison {
  source: number
  target: number
  match: boolean
}

export interface FinancialComparison {
  source_total: number
  target_total: number
  match: boolean
}

export interface SequenceComparison {
  source_value: number
  target_value: number
  valid: boolean
}

export interface IntegrityCheckResult {
  passed: boolean
  row_counts: Record<string, RowCountComparison>
  fk_errors: string[]
  financial_totals: Record<string, FinancialComparison>
  sequence_checks: Record<string, SequenceComparison>
}

export interface MigrationStatusResponse {
  job_id: string
  status: MigrationJobStatus
  current_table: string | null
  tables: TableProgress[]
  rows_processed: number
  rows_total: number
  progress_pct: number
  estimated_seconds_remaining: number | null
  dual_write_queue_depth: number
  integrity_check: IntegrityCheckResult | null
  error_message: string | null
  started_at: string
  updated_at: string
}

export interface MigrationJobSummary {
  job_id: string
  status: string
  started_at: string
  completed_at: string | null
  rows_total: number
  source_host: string
  target_host: string
}

export interface MigrationJobDetail extends MigrationJobSummary {
  integrity_check: IntegrityCheckResult | null
  error_message: string | null
  tables: TableProgress[]
}

interface ValidationResult {
  valid: boolean
  server_version?: string | null
  available_disk_space_mb?: number | null
  has_existing_tables?: boolean
  error?: string | null
}

/* ── Helpers ── */

const ACTIVE_STATUSES: MigrationJobStatus[] = [
  'pending', 'validating', 'schema_migrating', 'copying_data',
  'draining_queue', 'integrity_check', 'ready_for_cutover', 'cutting_over',
]

const CANCELLABLE_STATUSES: MigrationJobStatus[] = [
  'validating', 'schema_migrating', 'copying_data', 'draining_queue',
]

const IN_PROGRESS_STATUSES: MigrationJobStatus[] = [
  'validating', 'schema_migrating', 'copying_data', 'draining_queue', 'integrity_check',
]

function tableStatusBadge(status: string): { label: string; className: string } {
  const map: Record<string, { label: string; className: string }> = {
    pending: { label: 'Pending', className: 'bg-gray-100 text-gray-700' },
    in_progress: { label: 'In Progress', className: 'bg-blue-100 text-blue-700' },
    completed: { label: 'Completed', className: 'bg-green-100 text-green-700' },
    failed: { label: 'Failed', className: 'bg-red-100 text-red-700' },
  }
  return map[status] || { label: status, className: 'bg-gray-100 text-gray-700' }
}

function jobStatusBadge(status: string): { label: string; className: string } {
  const map: Record<string, { label: string; className: string }> = {
    pending: { label: 'Pending', className: 'bg-gray-100 text-gray-700' },
    validating: { label: 'Validating', className: 'bg-blue-100 text-blue-700' },
    schema_migrating: { label: 'Schema Migrating', className: 'bg-blue-100 text-blue-700' },
    copying_data: { label: 'Copying Data', className: 'bg-blue-100 text-blue-700' },
    draining_queue: { label: 'Draining Queue', className: 'bg-blue-100 text-blue-700' },
    integrity_check: { label: 'Integrity Check', className: 'bg-yellow-100 text-yellow-700' },
    ready_for_cutover: { label: 'Ready for Cutover', className: 'bg-green-100 text-green-700' },
    cutting_over: { label: 'Cutting Over', className: 'bg-purple-100 text-purple-700' },
    completed: { label: 'Completed', className: 'bg-green-100 text-green-700' },
    failed: { label: 'Failed', className: 'bg-red-100 text-red-700' },
    cancelled: { label: 'Cancelled', className: 'bg-gray-100 text-gray-700' },
    rolled_back: { label: 'Rolled Back', className: 'bg-orange-100 text-orange-700' },
  }
  return map[status] || { label: status, className: 'bg-gray-100 text-gray-700' }
}

export function formatEta(seconds: number | null): string {
  if (seconds === null || seconds <= 0) return '—'
  if (seconds < 60) return `${Math.round(seconds)}s`
  if (seconds < 3600) return `${Math.floor(seconds / 60)}m ${Math.round(seconds % 60)}s`
  const h = Math.floor(seconds / 3600)
  const m = Math.floor((seconds % 3600) / 60)
  return `${h}h ${m}m`
}

export function formatDateTime(iso: string | null): string {
  if (!iso) return '—'
  return new Date(iso).toLocaleString()
}

export function getRollbackTimeRemaining(cutoverAt: string | null): number {
  if (!cutoverAt) return 0
  const deadline = new Date(cutoverAt).getTime() + 24 * 60 * 60 * 1000
  return Math.max(0, deadline - Date.now())
}

export function formatCountdown(ms: number): string {
  if (ms <= 0) return 'Expired'
  const hours = Math.floor(ms / (1000 * 60 * 60))
  const minutes = Math.floor((ms % (1000 * 60 * 60)) / (1000 * 60))
  return `${hours}h ${minutes}m remaining`
}

/* ── 11.1 ConnectionForm ── */

interface ConnectionFormProps {
  onMigrationStarted: (jobId: string) => void
  disabled?: boolean
}

export function ConnectionForm({ onMigrationStarted, disabled }: ConnectionFormProps) {
  const [connectionString, setConnectionString] = useState('')
  const [sslMode, setSslMode] = useState<'require' | 'prefer' | 'disable'>('prefer')
  const [batchSize, setBatchSize] = useState(1000)
  const [validating, setValidating] = useState(false)
  const [starting, setStarting] = useState(false)
  const [validation, setValidation] = useState<ValidationResult | null>(null)
  const [confirmOverwrite, setConfirmOverwrite] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const handleValidate = useCallback(async () => {
    setValidating(true)
    setError(null)
    setValidation(null)
    try {
      const res = await apiClient.post<ValidationResult>('/admin/migration/validate', {
        connection_string: connectionString,
        ssl_mode: sslMode,
      })
      setValidation(res.data)
    } catch (err: unknown) {
      const detail =
        err && typeof err === 'object' && 'response' in err
          ? (err as { response?: { data?: { detail?: string } } }).response?.data?.detail
          : null
      setError(detail || 'Validation failed')
    } finally {
      setValidating(false)
    }
  }, [connectionString, sslMode])

  const handleStart = useCallback(async () => {
    setStarting(true)
    setError(null)
    try {
      const res = await apiClient.post<{ job_id: string }>('/admin/migration/start', {
        connection_string: connectionString,
        ssl_mode: sslMode,
        batch_size: batchSize,
        confirm_overwrite: confirmOverwrite,
      })
      onMigrationStarted(res.data.job_id)
    } catch (err: unknown) {
      const detail =
        err && typeof err === 'object' && 'response' in err
          ? (err as { response?: { data?: { detail?: string } } }).response?.data?.detail
          : null
      setError(detail || 'Failed to start migration')
    } finally {
      setStarting(false)
    }
  }, [connectionString, sslMode, batchSize, confirmOverwrite, onMigrationStarted])

  return (
    <div className="rounded-lg border border-gray-200 bg-white p-6" role="region" aria-label="Connection configuration">
      <h3 className="text-lg font-semibold text-gray-900 mb-4">Target Database Connection</h3>

      <div className="space-y-4">
        <div>
          <label htmlFor="conn-string" className="block text-sm font-medium text-gray-700 mb-1">
            Connection String
          </label>
          <input
            id="conn-string"
            type="text"
            value={connectionString}
            onChange={(e) => setConnectionString(e.target.value)}
            placeholder="postgresql+asyncpg://user:pass@host:5432/dbname"
            disabled={disabled}
            className="w-full rounded-md border border-gray-300 px-3 py-2 text-sm focus:border-indigo-500 focus:ring-1 focus:ring-indigo-500 disabled:bg-gray-50 disabled:text-gray-500"
            aria-label="Connection string"
          />
        </div>

        <div className="flex gap-4">
          <div className="flex-1">
            <label htmlFor="ssl-mode" className="block text-sm font-medium text-gray-700 mb-1">
              SSL Mode
            </label>
            <select
              id="ssl-mode"
              value={sslMode}
              onChange={(e) => setSslMode(e.target.value as 'require' | 'prefer' | 'disable')}
              disabled={disabled}
              className="w-full rounded-md border border-gray-300 px-3 py-2 text-sm focus:border-indigo-500 focus:ring-1 focus:ring-indigo-500 min-h-[44px] disabled:bg-gray-50"
              aria-label="SSL mode"
            >
              <option value="require">Require</option>
              <option value="prefer">Prefer</option>
              <option value="disable">Disable</option>
            </select>
          </div>
          <div className="flex-1">
            <label htmlFor="batch-size" className="block text-sm font-medium text-gray-700 mb-1">
              Batch Size
            </label>
            <input
              id="batch-size"
              type="number"
              min={100}
              max={10000}
              value={batchSize}
              onChange={(e) => setBatchSize(Number(e.target.value))}
              disabled={disabled}
              className="w-full rounded-md border border-gray-300 px-3 py-2 text-sm focus:border-indigo-500 focus:ring-1 focus:ring-indigo-500 disabled:bg-gray-50"
              aria-label="Batch size"
            />
          </div>
        </div>

        <button
          onClick={handleValidate}
          disabled={disabled || validating || !connectionString.trim()}
          className="min-h-[44px] rounded-md bg-indigo-600 px-4 py-2 text-sm font-medium text-white hover:bg-indigo-700 disabled:bg-gray-300 disabled:cursor-not-allowed"
          aria-label="Validate connection"
        >
          {validating ? 'Validating…' : 'Validate Connection'}
        </button>

        {error && (
          <div className="rounded-md bg-red-50 p-3 text-sm text-red-700" role="alert">
            {error}
          </div>
        )}

        {validation && !validation.valid && validation.error && (
          <div className="rounded-md bg-red-50 p-3 text-sm text-red-700" role="alert">
            {validation.error}
          </div>
        )}

        {validation && validation.valid && (
          <div className="rounded-md bg-green-50 p-4 space-y-3">
            <p className="text-sm text-green-700 font-medium">Connection validated successfully</p>
            <div className="text-sm text-green-600 space-y-1">
              {validation.server_version && <p>Server version: {validation.server_version}</p>}
              {validation.available_disk_space_mb != null && (
                <p>Available disk space: {validation.available_disk_space_mb} MB</p>
              )}
            </div>

            {validation.has_existing_tables && (
              <div className="rounded-md bg-yellow-50 border border-yellow-200 p-3">
                <label className="flex items-center gap-2 text-sm text-yellow-800 cursor-pointer min-h-[44px]">
                  <input
                    type="checkbox"
                    checked={confirmOverwrite}
                    onChange={(e) => setConfirmOverwrite(e.target.checked)}
                    className="h-4 w-4 rounded border-gray-300 text-indigo-600"
                    aria-label="Confirm overwrite existing tables"
                  />
                  Target database contains existing tables. Check to confirm overwrite.
                </label>
              </div>
            )}

            <button
              onClick={handleStart}
              disabled={starting || (validation.has_existing_tables && !confirmOverwrite)}
              className="min-h-[44px] rounded-md bg-green-600 px-4 py-2 text-sm font-medium text-white hover:bg-green-700 disabled:bg-gray-300 disabled:cursor-not-allowed"
              aria-label="Start migration"
            >
              {starting ? 'Starting…' : 'Start Migration'}
            </button>
          </div>
        )}
      </div>
    </div>
  )
}

/* ── 11.2 MigrationProgress ── */

interface MigrationProgressProps {
  jobId: string
  onStatusUpdate: (status: MigrationStatusResponse) => void
  onCancel: () => void
}

export function MigrationProgress({ jobId, onStatusUpdate, onCancel }: MigrationProgressProps) {
  const [status, setStatus] = useState<MigrationStatusResponse | null>(null)
  const [cancelling, setCancelling] = useState(false)
  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null)

  useEffect(() => {
    let active = true

    const poll = async () => {
      try {
        const res = await apiClient.get<MigrationStatusResponse>(`/admin/migration/status/${jobId}`)
        if (!active) return
        setStatus(res.data)
        onStatusUpdate(res.data)
        if (!IN_PROGRESS_STATUSES.includes(res.data.status) && res.data.status !== 'cutting_over') {
          if (pollRef.current) clearInterval(pollRef.current)
        }
      } catch {
        // Silently retry on next interval
      }
    }

    poll()
    pollRef.current = setInterval(poll, 2000)

    return () => {
      active = false
      if (pollRef.current) clearInterval(pollRef.current)
    }
  }, [jobId, onStatusUpdate])

  const handleCancel = useCallback(async () => {
    setCancelling(true)
    try {
      await apiClient.post(`/admin/migration/cancel/${jobId}`)
      onCancel()
    } catch {
      // Error handled by parent
    } finally {
      setCancelling(false)
    }
  }, [jobId, onCancel])

  if (!status) {
    return (
      <div className="rounded-lg border border-gray-200 bg-white p-6" role="region" aria-label="Migration progress">
        <p className="text-sm text-gray-500">Loading migration status…</p>
      </div>
    )
  }

  const badge = jobStatusBadge(status.status)
  const pct = Math.min(100, Math.max(0, status.progress_pct))

  return (
    <div className="rounded-lg border border-gray-200 bg-white p-6 space-y-4" role="region" aria-label="Migration progress">
      <div className="flex items-center justify-between">
        <h3 className="text-lg font-semibold text-gray-900">Migration Progress</h3>
        <span className={`inline-flex items-center rounded-full px-2.5 py-0.5 text-xs font-medium ${badge.className}`}>
          {badge.label}
        </span>
      </div>

      {/* Overall progress bar */}
      <div>
        <div className="flex justify-between text-sm text-gray-600 mb-1">
          <span>{status.rows_processed.toLocaleString()} / {status.rows_total.toLocaleString()} rows</span>
          <span>{pct.toFixed(1)}%</span>
        </div>
        <div
          className="h-3 w-full rounded-full bg-gray-200 overflow-hidden"
          role="progressbar"
          aria-valuenow={pct}
          aria-valuemin={0}
          aria-valuemax={100}
          aria-label="Overall migration progress"
        >
          <div
            className="h-full rounded-full bg-indigo-600 transition-all duration-300"
            style={{ width: `${pct}%` }}
          />
        </div>
      </div>

      {/* ETA and queue depth */}
      <div className="flex gap-6 text-sm text-gray-600">
        <span>ETA: {formatEta(status.estimated_seconds_remaining)}</span>
        <span>Dual-write queue: {status.dual_write_queue_depth}</span>
        {status.current_table && <span>Current table: {status.current_table}</span>}
      </div>

      {/* Table breakdown */}
      {status.tables.length > 0 && (
        <div className="overflow-x-auto">
          <table className="min-w-full text-sm" aria-label="Table migration breakdown">
            <thead>
              <tr className="border-b border-gray-200">
                <th className="text-left py-2 pr-4 font-medium text-gray-700">Table</th>
                <th className="text-right py-2 px-4 font-medium text-gray-700">Source</th>
                <th className="text-right py-2 px-4 font-medium text-gray-700">Migrated</th>
                <th className="text-left py-2 pl-4 font-medium text-gray-700">Status</th>
              </tr>
            </thead>
            <tbody>
              {status.tables.map((t) => {
                const tBadge = tableStatusBadge(t.status)
                return (
                  <tr key={t.table_name} className="border-b border-gray-100">
                    <td className="py-2 pr-4 text-gray-900">{t.table_name}</td>
                    <td className="py-2 px-4 text-right text-gray-600">{t.source_count.toLocaleString()}</td>
                    <td className="py-2 px-4 text-right text-gray-600">{t.migrated_count.toLocaleString()}</td>
                    <td className="py-2 pl-4">
                      <span className={`inline-flex items-center rounded-full px-2 py-0.5 text-xs font-medium ${tBadge.className}`}>
                        {tBadge.label}
                      </span>
                    </td>
                  </tr>
                )
              })}
            </tbody>
          </table>
        </div>
      )}

      {/* Error message */}
      {status.error_message && (
        <div className="rounded-md bg-red-50 p-3 text-sm text-red-700" role="alert">
          {status.error_message}
        </div>
      )}

      {/* Cancel button */}
      {CANCELLABLE_STATUSES.includes(status.status) && (
        <button
          onClick={handleCancel}
          disabled={cancelling}
          className="min-h-[44px] rounded-md bg-red-600 px-4 py-2 text-sm font-medium text-white hover:bg-red-700 disabled:bg-gray-300 disabled:cursor-not-allowed"
          aria-label="Cancel migration"
        >
          {cancelling ? 'Cancelling…' : 'Cancel Migration'}
        </button>
      )}
    </div>
  )
}

/* ── 11.3 IntegrityReport ── */

interface IntegrityReportProps {
  result: IntegrityCheckResult
}

export function LiveIntegrityReport({ result }: IntegrityReportProps) {
  const rowCountEntries = Object.entries(result.row_counts)
  const financialEntries = Object.entries(result.financial_totals)
  const sequenceEntries = Object.entries(result.sequence_checks)

  return (
    <div className="rounded-lg border border-gray-200 bg-white p-6 space-y-6" role="region" aria-label="Integrity check report">
      <div className="flex items-center gap-3">
        <h3 className="text-lg font-semibold text-gray-900">Integrity Check Results</h3>
        <span
          className={`inline-flex items-center rounded-full px-2.5 py-0.5 text-xs font-medium ${
            result.passed ? 'bg-green-100 text-green-700' : 'bg-red-100 text-red-700'
          }`}
        >
          {result.passed ? 'Passed' : 'Failed'}
        </span>
      </div>

      {/* Row counts */}
      {rowCountEntries.length > 0 && (
        <div>
          <h4 className="text-sm font-medium text-gray-700 mb-2">Row Count Comparison</h4>
          <div className="overflow-x-auto">
            <table className="min-w-full text-sm" aria-label="Row count comparison">
              <thead>
                <tr className="border-b border-gray-200">
                  <th className="text-left py-2 pr-4 font-medium text-gray-700">Table</th>
                  <th className="text-right py-2 px-4 font-medium text-gray-700">Source</th>
                  <th className="text-right py-2 px-4 font-medium text-gray-700">Target</th>
                  <th className="text-center py-2 pl-4 font-medium text-gray-700">Match</th>
                </tr>
              </thead>
              <tbody>
                {rowCountEntries.map(([table, cmp]) => (
                  <tr key={table} className="border-b border-gray-100">
                    <td className="py-2 pr-4 text-gray-900">{table}</td>
                    <td className="py-2 px-4 text-right text-gray-600">{cmp.source.toLocaleString()}</td>
                    <td className="py-2 px-4 text-right text-gray-600">{cmp.target.toLocaleString()}</td>
                    <td className="py-2 pl-4 text-center">
                      <span className={cmp.match ? 'text-green-600' : 'text-red-600'}>
                        {cmp.match ? '✓' : '✗'}
                      </span>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}

      {/* Financial totals */}
      {financialEntries.length > 0 && (
        <div>
          <h4 className="text-sm font-medium text-gray-700 mb-2">Financial Total Comparison</h4>
          <div className="overflow-x-auto">
            <table className="min-w-full text-sm" aria-label="Financial total comparison">
              <thead>
                <tr className="border-b border-gray-200">
                  <th className="text-left py-2 pr-4 font-medium text-gray-700">Metric</th>
                  <th className="text-right py-2 px-4 font-medium text-gray-700">Source</th>
                  <th className="text-right py-2 px-4 font-medium text-gray-700">Target</th>
                  <th className="text-center py-2 pl-4 font-medium text-gray-700">Match</th>
                </tr>
              </thead>
              <tbody>
                {financialEntries.map(([metric, cmp]) => (
                  <tr key={metric} className="border-b border-gray-100">
                    <td className="py-2 pr-4 text-gray-900">{metric.replace(/_/g, ' ')}</td>
                    <td className="py-2 px-4 text-right text-gray-600">${cmp.source_total.toFixed(2)}</td>
                    <td className="py-2 px-4 text-right text-gray-600">${cmp.target_total.toFixed(2)}</td>
                    <td className="py-2 pl-4 text-center">
                      <span className={cmp.match ? 'text-green-600' : 'text-red-600'}>
                        {cmp.match ? '✓' : '✗'}
                      </span>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}

      {/* FK errors */}
      {result.fk_errors.length > 0 && (
        <div>
          <h4 className="text-sm font-medium text-gray-700 mb-2">
            Foreign Key Errors
            <span className="ml-2 inline-flex items-center rounded-full bg-red-100 px-2 py-0.5 text-xs font-medium text-red-700">
              {result.fk_errors.length}
            </span>
          </h4>
          <ul className="space-y-1 text-sm text-red-700" role="list" aria-label="Foreign key errors">
            {result.fk_errors.map((err, i) => (
              <li key={i} className="rounded bg-red-50 px-3 py-1">{err}</li>
            ))}
          </ul>
        </div>
      )}

      {/* Sequence checks */}
      {sequenceEntries.length > 0 && (
        <div>
          <h4 className="text-sm font-medium text-gray-700 mb-2">Sequence Checks</h4>
          <div className="overflow-x-auto">
            <table className="min-w-full text-sm" aria-label="Sequence checks">
              <thead>
                <tr className="border-b border-gray-200">
                  <th className="text-left py-2 pr-4 font-medium text-gray-700">Sequence</th>
                  <th className="text-right py-2 px-4 font-medium text-gray-700">Source</th>
                  <th className="text-right py-2 px-4 font-medium text-gray-700">Target</th>
                  <th className="text-center py-2 pl-4 font-medium text-gray-700">Valid</th>
                </tr>
              </thead>
              <tbody>
                {sequenceEntries.map(([seq, cmp]) => (
                  <tr key={seq} className="border-b border-gray-100">
                    <td className="py-2 pr-4 text-gray-900">{seq}</td>
                    <td className="py-2 px-4 text-right text-gray-600">{cmp.source_value.toLocaleString()}</td>
                    <td className="py-2 px-4 text-right text-gray-600">{cmp.target_value.toLocaleString()}</td>
                    <td className="py-2 pl-4 text-center">
                      <span className={cmp.valid ? 'text-green-600' : 'text-red-600'}>
                        {cmp.valid ? '✓' : '✗'}
                      </span>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}
    </div>
  )
}

/* ── 11.4 CutoverPanel ── */

interface CutoverPanelProps {
  jobId: string
  integrityPassed: boolean
  onCutoverComplete: () => void
  onError: (msg: string) => void
}

export function CutoverPanel({ jobId, integrityPassed, onCutoverComplete, onError }: CutoverPanelProps) {
  const [showModal, setShowModal] = useState(false)
  const [confirmText, setConfirmText] = useState('')
  const [submitting, setSubmitting] = useState(false)
  const [result, setResult] = useState<'success' | 'failed' | null>(null)
  const [failMessage, setFailMessage] = useState<string | null>(null)

  const handleCutover = useCallback(async () => {
    setSubmitting(true)
    setResult(null)
    setFailMessage(null)
    try {
      await apiClient.post(`/admin/migration/cutover/${jobId}`, {
        confirmation_text: confirmText,
      })
      setResult('success')
      setShowModal(false)
      setConfirmText('')
      onCutoverComplete()
    } catch (err: unknown) {
      const detail =
        err && typeof err === 'object' && 'response' in err
          ? (err as { response?: { data?: { detail?: string } } }).response?.data?.detail
          : null
      const msg = detail || 'Cutover failed'
      setResult('failed')
      setFailMessage(msg)
      setShowModal(false)
      setConfirmText('')
      onError(msg)
    } finally {
      setSubmitting(false)
    }
  }, [jobId, confirmText, onCutoverComplete, onError])

  return (
    <div className="rounded-lg border border-gray-200 bg-white p-6 space-y-4" role="region" aria-label="Cutover panel">
      <h3 className="text-lg font-semibold text-gray-900">Database Cutover</h3>

      {result === 'success' && (
        <div className="rounded-md bg-green-50 p-3 text-sm text-green-700" role="alert">
          Cutover completed successfully. The application is now using the new database.
        </div>
      )}

      {result === 'failed' && failMessage && (
        <div className="rounded-md bg-red-50 p-3 text-sm text-red-700" role="alert">
          Cutover failed: {failMessage}. The system has automatically rolled back to the previous database.
        </div>
      )}

      {result === null && (
        <>
          <p className="text-sm text-gray-600">
            {integrityPassed
              ? 'All integrity checks passed. You can proceed with the cutover.'
              : 'Cutover is disabled because the integrity check has not passed.'}
          </p>
          <button
            onClick={() => setShowModal(true)}
            disabled={!integrityPassed}
            className="min-h-[44px] rounded-md bg-purple-600 px-4 py-2 text-sm font-medium text-white hover:bg-purple-700 disabled:bg-gray-300 disabled:cursor-not-allowed"
            aria-label="Cut over to new database"
          >
            Cut Over to New Database
          </button>
        </>
      )}

      {/* Confirmation modal */}
      {showModal && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50" role="dialog" aria-modal="true" aria-label="Confirm cutover">
          <div className="w-full max-w-md rounded-lg bg-white p-6 shadow-xl space-y-4">
            <h4 className="text-lg font-semibold text-gray-900">Confirm Cutover</h4>
            <p className="text-sm text-gray-600">
              This will switch the application to the new database. Type <strong>CONFIRM CUTOVER</strong> to proceed.
            </p>
            <input
              type="text"
              value={confirmText}
              onChange={(e) => setConfirmText(e.target.value)}
              placeholder="Type CONFIRM CUTOVER"
              className="w-full rounded-md border border-gray-300 px-3 py-2 text-sm focus:border-indigo-500 focus:ring-1 focus:ring-indigo-500"
              aria-label="Cutover confirmation text"
            />
            <div className="flex gap-3 justify-end">
              <button
                onClick={() => { setShowModal(false); setConfirmText('') }}
                className="min-h-[44px] rounded-md border border-gray-300 px-4 py-2 text-sm font-medium text-gray-700 hover:bg-gray-50"
                aria-label="Cancel cutover"
              >
                Cancel
              </button>
              <button
                onClick={handleCutover}
                disabled={confirmText !== 'CONFIRM CUTOVER' || submitting}
                className="min-h-[44px] rounded-md bg-purple-600 px-4 py-2 text-sm font-medium text-white hover:bg-purple-700 disabled:bg-gray-300 disabled:cursor-not-allowed"
                aria-label="Confirm cutover"
              >
                {submitting ? 'Processing…' : 'Confirm Cutover'}
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}

/* ── 11.5 RollbackPanel ── */

interface RollbackPanelProps {
  jobId: string
  cutoverAt: string | null
  onRollbackComplete: () => void
  onError: (msg: string) => void
}

export function RollbackPanel({ jobId, cutoverAt, onRollbackComplete, onError }: RollbackPanelProps) {
  const [reason, setReason] = useState('')
  const [submitting, setSubmitting] = useState(false)
  const [timeRemaining, setTimeRemaining] = useState(() => getRollbackTimeRemaining(cutoverAt))

  useEffect(() => {
    if (!cutoverAt) return
    const interval = setInterval(() => {
      setTimeRemaining(getRollbackTimeRemaining(cutoverAt))
    }, 60_000) // update every minute
    return () => clearInterval(interval)
  }, [cutoverAt])

  const expired = timeRemaining <= 0

  const handleRollback = useCallback(async () => {
    setSubmitting(true)
    try {
      await apiClient.post(`/admin/migration/rollback/${jobId}`, { reason })
      onRollbackComplete()
    } catch (err: unknown) {
      const detail =
        err && typeof err === 'object' && 'response' in err
          ? (err as { response?: { data?: { detail?: string } } }).response?.data?.detail
          : null
      onError(detail || 'Rollback failed')
    } finally {
      setSubmitting(false)
    }
  }, [jobId, reason, onRollbackComplete, onError])

  return (
    <div className="rounded-lg border border-gray-200 bg-white p-6 space-y-4" role="region" aria-label="Rollback panel">
      <h3 className="text-lg font-semibold text-gray-900">Rollback</h3>

      <div className="text-sm text-gray-600">
        {expired ? (
          <div className="rounded-md bg-yellow-50 border border-yellow-200 p-3 text-yellow-800">
            Rollback window has expired. More than 24 hours have passed since cutover.
            Rollback is no longer available due to potential data divergence.
          </div>
        ) : (
          <p>Rollback window: {formatCountdown(timeRemaining)}</p>
        )}
      </div>

      {!expired && (
        <>
          <div>
            <label htmlFor="rollback-reason" className="block text-sm font-medium text-gray-700 mb-1">
              Reason for rollback
            </label>
            <input
              id="rollback-reason"
              type="text"
              value={reason}
              onChange={(e) => setReason(e.target.value)}
              placeholder="Enter reason for rollback"
              className="w-full rounded-md border border-gray-300 px-3 py-2 text-sm focus:border-indigo-500 focus:ring-1 focus:ring-indigo-500"
              aria-label="Rollback reason"
            />
          </div>
          <button
            onClick={handleRollback}
            disabled={submitting || !reason.trim()}
            className="min-h-[44px] rounded-md bg-orange-600 px-4 py-2 text-sm font-medium text-white hover:bg-orange-700 disabled:bg-gray-300 disabled:cursor-not-allowed"
            aria-label="Roll back to previous database"
          >
            {submitting ? 'Rolling back…' : 'Roll Back to Previous Database'}
          </button>
        </>
      )}
    </div>
  )
}

/* ── 11.6 MigrationHistory ── */

interface MigrationHistoryProps {
  onSelectJob?: (jobId: string) => void
}

export function MigrationHistory({ onSelectJob }: MigrationHistoryProps) {
  const [jobs, setJobs] = useState<MigrationJobSummary[]>([])
  const [loading, setLoading] = useState(true)
  const [expandedJobId, setExpandedJobId] = useState<string | null>(null)
  const [detail, setDetail] = useState<MigrationJobDetail | null>(null)
  const [detailLoading, setDetailLoading] = useState(false)

  useEffect(() => {
    let active = true
    const fetchHistory = async () => {
      try {
        const res = await apiClient.get<MigrationJobSummary[]>('/admin/migration/history')
        if (active) setJobs(res.data)
      } catch {
        // Silently fail
      } finally {
        if (active) setLoading(false)
      }
    }
    fetchHistory()
    return () => { active = false }
  }, [])

  const handleRowClick = useCallback(async (jobId: string) => {
    if (expandedJobId === jobId) {
      setExpandedJobId(null)
      setDetail(null)
      return
    }
    setExpandedJobId(jobId)
    setDetailLoading(true)
    setDetail(null)
    try {
      const res = await apiClient.get<MigrationJobDetail>(`/admin/migration/history/${jobId}`)
      setDetail(res.data)
    } catch {
      // Silently fail
    } finally {
      setDetailLoading(false)
    }
    onSelectJob?.(jobId)
  }, [expandedJobId, onSelectJob])

  if (loading) {
    return (
      <div className="rounded-lg border border-gray-200 bg-white p-6" role="region" aria-label="Migration history">
        <p className="text-sm text-gray-500">Loading migration history…</p>
      </div>
    )
  }

  return (
    <div className="rounded-lg border border-gray-200 bg-white p-6 space-y-4" role="region" aria-label="Migration history">
      <h3 className="text-lg font-semibold text-gray-900">Migration History</h3>

      {jobs.length === 0 ? (
        <p className="text-sm text-gray-500">No past migrations found.</p>
      ) : (
        <div className="overflow-x-auto">
          <table className="min-w-full text-sm" aria-label="Past migration jobs">
            <thead>
              <tr className="border-b border-gray-200">
                <th className="text-left py-2 pr-4 font-medium text-gray-700">Status</th>
                <th className="text-left py-2 px-4 font-medium text-gray-700">Started</th>
                <th className="text-left py-2 px-4 font-medium text-gray-700">Completed</th>
                <th className="text-right py-2 px-4 font-medium text-gray-700">Records</th>
                <th className="text-left py-2 px-4 font-medium text-gray-700">Source</th>
                <th className="text-left py-2 pl-4 font-medium text-gray-700">Target</th>
              </tr>
            </thead>
            <tbody>
              {jobs.map((job) => {
                const badge = jobStatusBadge(job.status)
                const isExpanded = expandedJobId === job.job_id
                return (
                  <>
                    <tr
                      key={job.job_id}
                      onClick={() => handleRowClick(job.job_id)}
                      className="border-b border-gray-100 cursor-pointer hover:bg-gray-50 min-h-[44px]"
                      role="button"
                      tabIndex={0}
                      aria-expanded={isExpanded}
                      aria-label={`Migration job ${job.job_id}`}
                      onKeyDown={(e) => { if (e.key === 'Enter' || e.key === ' ') handleRowClick(job.job_id) }}
                    >
                      <td className="py-3 pr-4">
                        <span className={`inline-flex items-center rounded-full px-2 py-0.5 text-xs font-medium ${badge.className}`}>
                          {badge.label}
                        </span>
                      </td>
                      <td className="py-3 px-4 text-gray-600">{formatDateTime(job.started_at)}</td>
                      <td className="py-3 px-4 text-gray-600">{formatDateTime(job.completed_at)}</td>
                      <td className="py-3 px-4 text-right text-gray-600">{job.rows_total.toLocaleString()}</td>
                      <td className="py-3 px-4 text-gray-600">{job.source_host}</td>
                      <td className="py-3 pl-4 text-gray-600">{job.target_host}</td>
                    </tr>
                    {isExpanded && (
                      <tr key={`${job.job_id}-detail`}>
                        <td colSpan={6} className="p-4 bg-gray-50">
                          {detailLoading ? (
                            <p className="text-sm text-gray-500">Loading details…</p>
                          ) : detail ? (
                            <div className="space-y-4">
                              {detail.error_message && (
                                <div className="rounded-md bg-red-50 p-3 text-sm text-red-700">
                                  Error: {detail.error_message}
                                </div>
                              )}
                              {detail.tables.length > 0 && (
                                <div>
                                  <h4 className="text-sm font-medium text-gray-700 mb-2">Tables</h4>
                                  <div className="grid grid-cols-2 gap-2 text-xs">
                                    {detail.tables.map((t) => (
                                      <div key={t.table_name} className="flex justify-between bg-white rounded px-2 py-1 border border-gray-200">
                                        <span>{t.table_name}</span>
                                        <span className="text-gray-500">{t.migrated_count}/{t.source_count}</span>
                                      </div>
                                    ))}
                                  </div>
                                </div>
                              )}
                              {detail.integrity_check && (
                                <LiveIntegrityReport result={detail.integrity_check} />
                              )}
                            </div>
                          ) : (
                            <p className="text-sm text-gray-500">No details available.</p>
                          )}
                        </td>
                      </tr>
                    )}
                  </>
                )
              })}
            </tbody>
          </table>
        </div>
      )}
    </div>
  )
}

/* ── 11.7 LiveMigrationTool (main page) ── */

export function LiveMigrationTool() {
  const [jobId, setJobId] = useState<string | null>(null)
  const [jobStatus, setJobStatus] = useState<MigrationStatusResponse | null>(null)
  const [error, setError] = useState<string | null>(null)

  const handleMigrationStarted = useCallback((newJobId: string) => {
    setJobId(newJobId)
    setError(null)
  }, [])

  const handleStatusUpdate = useCallback((status: MigrationStatusResponse) => {
    setJobStatus(status)
  }, [])

  const handleCancel = useCallback(() => {
    setJobId(null)
    setJobStatus(null)
  }, [])

  const handleCutoverComplete = useCallback(() => {
    // Refresh status to get cutover_at timestamp
    if (jobId) {
      apiClient.get<MigrationStatusResponse>(`/admin/migration/status/${jobId}`)
        .then((res) => setJobStatus(res.data))
        .catch(() => {})
    }
  }, [jobId])

  const handleRollbackComplete = useCallback(() => {
    setJobId(null)
    setJobStatus(null)
  }, [])

  const handleError = useCallback((msg: string) => {
    setError(msg)
  }, [])

  const currentStatus = jobStatus?.status
  const showConnectionForm = !jobId || currentStatus === 'failed' || currentStatus === 'cancelled' || currentStatus === 'rolled_back'
  const showProgress = jobId && currentStatus && ACTIVE_STATUSES.includes(currentStatus) && currentStatus !== 'ready_for_cutover'
  const showIntegrity = jobStatus?.integrity_check != null
  const showCutover = currentStatus === 'ready_for_cutover'
  const showRollback = currentStatus === 'completed'

  return (
    <div className="space-y-6 max-w-5xl" role="main" aria-label="Live Database Migration Tool">
      <div>
        <h2 className="text-2xl font-bold text-gray-900">Live Database Migration</h2>
        <p className="mt-1 text-sm text-gray-600">
          Migrate the platform database to a new PostgreSQL server with zero downtime.
        </p>
      </div>

      {/* Error banner */}
      {error && (
        <div className="rounded-md bg-red-50 border border-red-200 p-4 flex items-start gap-3" role="alert">
          <span className="text-red-600 text-sm flex-1">{error}</span>
          <button
            onClick={() => setError(null)}
            className="min-h-[44px] min-w-[44px] flex items-center justify-center text-red-400 hover:text-red-600"
            aria-label="Dismiss error"
          >
            ✕
          </button>
        </div>
      )}

      {/* Connection form */}
      {showConnectionForm && (
        <ConnectionForm
          onMigrationStarted={handleMigrationStarted}
          disabled={!!jobId && ACTIVE_STATUSES.includes(currentStatus!)}
        />
      )}

      {/* Progress */}
      {showProgress && jobId && (
        <MigrationProgress
          jobId={jobId}
          onStatusUpdate={handleStatusUpdate}
          onCancel={handleCancel}
        />
      )}

      {/* Integrity report */}
      {showIntegrity && jobStatus?.integrity_check && (
        <LiveIntegrityReport result={jobStatus.integrity_check} />
      )}

      {/* Cutover panel */}
      {showCutover && jobId && (
        <CutoverPanel
          jobId={jobId}
          integrityPassed={jobStatus?.integrity_check?.passed ?? false}
          onCutoverComplete={handleCutoverComplete}
          onError={handleError}
        />
      )}

      {/* Rollback panel */}
      {showRollback && jobId && (
        <RollbackPanel
          jobId={jobId}
          cutoverAt={jobStatus?.updated_at ?? null}
          onRollbackComplete={handleRollbackComplete}
          onError={handleError}
        />
      )}

      {/* Migration history */}
      <MigrationHistory />
    </div>
  )
}

export default LiveMigrationTool
