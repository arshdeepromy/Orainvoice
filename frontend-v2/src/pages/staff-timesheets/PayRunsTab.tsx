import { useEffect, useState } from 'react'
import apiClient from '@/api/client'

interface PayCycle {
  id: string
  name: string
  frequency: string
  anchor_date: string
  pay_date_offset_days: number
  is_default: boolean
}

interface PayCyclesResponse {
  items: PayCycle[]
  total: number
}

export default function PayRunsTab() {
  const [cycles, setCycles] = useState<PayCycle[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [generating, setGenerating] = useState(false)

  useEffect(() => {
    const controller = new AbortController()
    const fetchCycles = async () => {
      try {
        setLoading(true)
        const res = await apiClient.get<PayCyclesResponse>('/api/v2/pay-cycles/', {
          signal: controller.signal,
        })
        setCycles(res.data?.items ?? [])
        setError(null)
      } catch (err: unknown) {
        if (!controller.signal.aborted) {
          setError('Failed to load pay cycles')
        }
      } finally {
        if (!controller.signal.aborted) setLoading(false)
      }
    }
    fetchCycles()
    return () => controller.abort()
  }, [])

  const handleGeneratePayRun = async () => {
    setGenerating(true)
    try {
      // Placeholder — will need a real pay_period_id
      await apiClient.post('/api/v2/pay-run/generate/', null, {
        params: { pay_period_id: '00000000-0000-0000-0000-000000000000' },
      })
    } catch {
      // Expected to fail with no real period
    } finally {
      setGenerating(false)
    }
  }

  if (loading) {
    return (
      <div className="animate-pulse space-y-3">
        <div className="h-10 w-48 rounded-lg bg-muted/10" />
        {[1, 2].map((i) => (
          <div key={i} className="h-20 rounded-lg bg-muted/10" />
        ))}
      </div>
    )
  }

  if (error) {
    return (
      <div className="flex flex-col items-center justify-center py-12">
        <div className="rounded-full bg-danger/10 p-3">
          <svg className="h-6 w-6 text-danger" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={2}>
            <path strokeLinecap="round" strokeLinejoin="round" d="M12 9v2m0 4h.01m-6.938 4h13.856c1.54 0 2.502-1.667 1.732-2.5L13.732 4c-.77-.833-1.964-.833-2.732 0L4.082 16.5c-.77.833.192 2.5 1.732 2.5z" />
          </svg>
        </div>
        <p className="mt-3 text-sm font-medium text-text">{error}</p>
        <button onClick={() => window.location.reload()} className="mt-2 text-sm text-accent hover:underline">Retry</button>
      </div>
    )
  }

  return (
    <div className="space-y-6">
      {/* Pay Cycles */}
      <div>
        <div className="mb-3 flex items-center justify-between">
          <h3 className="text-sm font-semibold text-text">Pay Cycles</h3>
          <button className="inline-flex h-8 items-center gap-1.5 rounded-lg border border-border bg-card px-3 text-xs font-medium text-text hover:bg-canvas transition-colors">
            <svg className="h-3.5 w-3.5" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={2}>
              <path strokeLinecap="round" strokeLinejoin="round" d="M12 4v16m8-8H4" />
            </svg>
            New Cycle
          </button>
        </div>

        {cycles.length === 0 ? (
          <div className="rounded-lg border border-dashed border-border p-6 text-center">
            <div className="mx-auto mb-3 rounded-full bg-muted/10 p-3 w-fit">
              <svg className="h-5 w-5 text-muted" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={1.5}>
                <path strokeLinecap="round" strokeLinejoin="round" d="M19.5 12c0-1.232-.046-2.453-.138-3.662a4.006 4.006 0 00-3.7-3.7 48.678 48.678 0 00-7.324 0 4.006 4.006 0 00-3.7 3.7c-.017.22-.032.441-.046.662M19.5 12l3-3m-3 3l-3-3m-12 3c0 1.232.046 2.453.138 3.662a4.006 4.006 0 003.7 3.7 48.656 48.656 0 007.324 0 4.006 4.006 0 003.7-3.7c.017-.22.032-.441.046-.662M4.5 12l3 3m-3-3l-3 3" />
              </svg>
            </div>
            <p className="text-sm font-medium text-text">No pay cycles configured</p>
            <p className="mt-1 text-xs text-muted">
              Create a pay cycle to define how often your staff get paid (weekly, fortnightly, or monthly).
              Pay periods will be auto-generated based on the cycle.
            </p>
          </div>
        ) : (
          <div className="space-y-2">
            {cycles.map((cycle) => (
              <div key={cycle.id} className="flex items-center justify-between rounded-lg border border-border p-4 hover:bg-muted/5 transition-colors">
                <div className="flex items-center gap-3">
                  <div className="flex h-9 w-9 items-center justify-center rounded-full bg-accent/10">
                    <svg className="h-4 w-4 text-accent" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={2}>
                      <path strokeLinecap="round" strokeLinejoin="round" d="M19.5 12c0-1.232-.046-2.453-.138-3.662a4.006 4.006 0 00-3.7-3.7 48.678 48.678 0 00-7.324 0 4.006 4.006 0 00-3.7 3.7c-.017.22-.032.441-.046.662M19.5 12l3-3m-3 3l-3-3m-12 3c0 1.232.046 2.453.138 3.662a4.006 4.006 0 003.7 3.7 48.656 48.656 0 007.324 0 4.006 4.006 0 003.7-3.7c.017-.22.032-.441.046-.662M4.5 12l3 3m-3-3l-3 3" />
                    </svg>
                  </div>
                  <div>
                    <div className="flex items-center gap-2">
                      <p className="text-sm font-medium text-text">{cycle.name}</p>
                      {cycle.is_default && (
                        <span className="rounded bg-accent/10 px-1.5 py-0.5 text-[10px] font-medium text-accent">Default</span>
                      )}
                    </div>
                    <p className="text-xs text-muted capitalize">
                      {cycle.frequency} • Anchor: {cycle.anchor_date} • Pay offset: {cycle.pay_date_offset_days} days
                    </p>
                  </div>
                </div>
                <div className="flex items-center gap-2">
                  <button className="inline-flex h-7 items-center rounded border border-border px-2 text-xs text-text hover:bg-canvas">
                    Generate Periods
                  </button>
                  <button className="text-xs text-accent hover:underline">Edit</button>
                </div>
              </div>
            ))}
          </div>
        )}
      </div>

      {/* Pay Run Actions */}
      <div>
        <h3 className="mb-3 text-sm font-semibold text-text">Pay Run</h3>
        <div className="rounded-lg border border-border p-5">
          <div className="flex items-start gap-4">
            <div className="rounded-full bg-accent/10 p-2.5">
              <svg className="h-5 w-5 text-accent" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={1.5}>
                <path strokeLinecap="round" strokeLinejoin="round" d="M2.25 18.75a60.07 60.07 0 0115.797 2.101c.727.198 1.453-.342 1.453-1.096V18.75M3.75 4.5v.75A.75.75 0 013 6h-.75m0 0v-.375c0-.621.504-1.125 1.125-1.125H20.25M2.25 6v9m18-10.5v.75c0 .414.336.75.75.75h.75m-1.5-1.5h.375c.621 0 1.125.504 1.125 1.125v9.75c0 .621-.504 1.125-1.125 1.125h-.375m1.5-1.5H21a.75.75 0 00-.75.75v.75m0 0H3.75m0 0h-.375a1.125 1.125 0 01-1.125-1.125V15m1.5 1.5v-.75A.75.75 0 003 15h-.75M15 10.5a3 3 0 11-6 0 3 3 0 016 0zm3 0h.008v.008H18V10.5zm-12 0h.008v.008H6V10.5z" />
              </svg>
            </div>
            <div className="flex-1">
              <p className="text-sm font-medium text-text">Generate Payslip Drafts</p>
              <p className="mt-0.5 text-xs text-muted">
                Generate draft payslips for all locked timesheets in the current period.
                Hour bands (ordinary, overtime, public holiday) will flow into the payslip line items.
              </p>
              <button
                onClick={handleGeneratePayRun}
                disabled={generating}
                className="mt-3 inline-flex h-9 items-center gap-2 rounded-lg bg-accent px-4 text-sm font-medium text-white hover:bg-accent/90 disabled:opacity-50 transition-colors"
              >
                {generating ? (
                  <>
                    <svg className="h-4 w-4 animate-spin" viewBox="0 0 24 24" fill="none">
                      <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth={4} />
                      <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z" />
                    </svg>
                    Generating...
                  </>
                ) : (
                  'Generate Pay Run'
                )}
              </button>
            </div>
          </div>
        </div>
      </div>

      {/* Adjustments */}
      <div>
        <div className="mb-3 flex items-center justify-between">
          <h3 className="text-sm font-semibold text-text">Corrections & Adjustments</h3>
          <button className="inline-flex h-8 items-center gap-1.5 rounded-lg border border-border bg-card px-3 text-xs font-medium text-text hover:bg-canvas transition-colors">
            <svg className="h-3.5 w-3.5" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={2}>
              <path strokeLinecap="round" strokeLinejoin="round" d="M12 4v16m8-8H4" />
            </svg>
            New Adjustment
          </button>
        </div>
        <div className="rounded-lg border border-dashed border-border p-6 text-center">
          <p className="text-sm text-muted">No adjustments for this period</p>
          <p className="mt-0.5 text-xs text-muted">
            Post-lock corrections appear here and carry into the next pay run
          </p>
        </div>
      </div>
    </div>
  )
}
