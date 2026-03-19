import { useState } from 'react'
import { Button } from '@/components/ui/Button'
import { Badge } from '@/components/ui/Badge'
import { Spinner } from '@/components/ui/Spinner'
import { AlertBanner } from '@/components/ui/AlertBanner'
import apiClient from '@/api/client'

/* ── Types ── */

export interface TestResult {
  test_name: string
  category: 'api_functions' | 'webhook_handlers'
  status: 'passed' | 'failed' | 'skipped'
  error_message?: string | null
  skip_reason?: string | null
}

interface TestSummary {
  total: number
  passed: number
  failed: number
  skipped: number
}

interface TestAllResponse {
  results: TestResult[]
  summary: TestSummary
}

/* ── Helpers ── */

const CATEGORY_LABELS: Record<string, string> = {
  api_functions: 'API Functions',
  webhook_handlers: 'Webhook Handlers',
}

function statusBadgeVariant(status: TestResult['status']): 'success' | 'error' | 'warning' {
  switch (status) {
    case 'passed':
      return 'success'
    case 'failed':
      return 'error'
    case 'skipped':
      return 'warning'
  }
}

function statusLabel(status: TestResult['status']): string {
  return status.charAt(0).toUpperCase() + status.slice(1)
}

/* ── Result Group ── */

function ResultGroup({ category, results }: { category: string; results: TestResult[] }) {
  return (
    <div className="rounded-lg border border-gray-200">
      <div className="px-4 py-2.5 bg-gray-50 border-b border-gray-200">
        <h4 className="text-sm font-semibold text-gray-900">
          {CATEGORY_LABELS[category] ?? category}
        </h4>
      </div>
      <ul className="divide-y divide-gray-100" role="list">
        {results.map((r) => (
          <li key={r.test_name} className="px-4 py-3">
            <div className="flex items-center justify-between gap-3">
              <span className="text-sm text-gray-900">{r.test_name}</span>
              <Badge variant={statusBadgeVariant(r.status)}>
                {statusLabel(r.status)}
              </Badge>
            </div>
            {r.status === 'failed' && r.error_message && (
              <p className="mt-1.5 text-xs text-red-700 bg-red-50 rounded px-2 py-1">
                {r.error_message}
              </p>
            )}
            {r.status === 'skipped' && r.skip_reason && (
              <p className="mt-1.5 text-xs text-amber-700 bg-amber-50 rounded px-2 py-1">
                {r.skip_reason}
              </p>
            )}
          </li>
        ))}
      </ul>
    </div>
  )
}

/* ── Summary ── */

function SummaryLine({ summary }: { summary: TestSummary }) {
  const allPassed = summary.failed === 0
  return (
    <div
      className={`flex items-center gap-2 rounded-md px-4 py-2.5 text-sm font-medium ${
        allPassed
          ? 'bg-green-50 text-green-800 border border-green-200'
          : 'bg-red-50 text-red-800 border border-red-200'
      }`}
      role="status"
    >
      <span aria-hidden="true">{allPassed ? '✓' : '✕'}</span>
      {summary.passed} of {summary.total} tests passed
      {summary.skipped > 0 && (
        <span className="text-amber-700 ml-1">({summary.skipped} skipped)</span>
      )}
    </div>
  )
}

/* ── Main Component ── */

export function StripeTestSuite() {
  const [running, setRunning] = useState(false)
  const [results, setResults] = useState<TestResult[] | null>(null)
  const [summary, setSummary] = useState<TestSummary | null>(null)
  const [error, setError] = useState<string | null>(null)

  const runTests = async () => {
    setRunning(true)
    setError(null)
    setResults(null)
    setSummary(null)
    try {
      const res = await apiClient.post<TestAllResponse>('/admin/integrations/stripe/test-all')
      setResults(res.data.results)
      setSummary(res.data.summary)
    } catch (err: any) {
      const msg =
        err.response?.data?.detail ??
        err.response?.data?.message ??
        'Failed to run tests. Please check your Stripe configuration and try again.'
      setError(msg)
    } finally {
      setRunning(false)
    }
  }

  // Group results by category
  const apiResults = results?.filter((r) => r.category === 'api_functions') ?? []
  const webhookResults = results?.filter((r) => r.category === 'webhook_handlers') ?? []

  return (
    <div className="rounded-lg border border-gray-200 p-5 space-y-4">
      <div className="flex items-center justify-between">
        <div>
          <h3 className="text-md font-semibold text-gray-900">Stripe Test Suite</h3>
          <p className="text-xs text-gray-500 mt-0.5">
            Run automated tests for all Stripe API functions and webhook handlers.
          </p>
        </div>
        <Button onClick={runTests} loading={running} variant="secondary" size="sm">
          Run All Tests
        </Button>
      </div>

      {running && (
        <div className="flex items-center justify-center py-8">
          <Spinner label="Running Stripe tests" />
        </div>
      )}

      {error && (
        <AlertBanner variant="error" title="Test run failed">
          {error}
        </AlertBanner>
      )}

      {results && !running && (
        <div className="space-y-4">
          {apiResults.length > 0 && (
            <ResultGroup category="api_functions" results={apiResults} />
          )}
          {webhookResults.length > 0 && (
            <ResultGroup category="webhook_handlers" results={webhookResults} />
          )}
          {summary && <SummaryLine summary={summary} />}
        </div>
      )}
    </div>
  )
}
