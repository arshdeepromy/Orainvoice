import { useEffect, useState } from 'react'
import apiClient from '@/api/client'
import type { TimesheetSettingsResponse } from './types'

export default function TimesheetSettings() {
  const [data, setData] = useState<TimesheetSettingsResponse | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    const controller = new AbortController()
    const fetchSettings = async () => {
      try {
        setLoading(true)
        const res = await apiClient.get<TimesheetSettingsResponse>(
          '/api/v2/timesheet-settings',
          { signal: controller.signal },
        )
        setData(res.data)
        setError(null)
      } catch (err: unknown) {
        if (!controller.signal.aborted) setError('Failed to load settings')
      } finally {
        if (!controller.signal.aborted) setLoading(false)
      }
    }
    fetchSettings()
    return () => controller.abort()
  }, [])

  if (loading) {
    return (
      <div className="animate-pulse space-y-4">
        {[1, 2, 3].map((i) => (
          <div key={i} className="h-16 rounded bg-muted/20" />
        ))}
      </div>
    )
  }

  if (error) {
    return (
      <div className="rounded-lg border border-danger/20 bg-danger/5 p-4">
        <p className="text-sm text-danger">{error}</p>
      </div>
    )
  }

  const settings = data?.org_default

  return (
    <div className="space-y-6">
      <h1 className="text-2xl font-bold text-text">Timesheet Settings</h1>

      <div className="space-y-4 rounded-lg border border-border p-6">
        <h2 className="font-semibold text-text">Organisation Defaults</h2>
        {settings ? (
          <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
            <div>
              <label className="text-xs text-muted">Clock Rounding</label>
              <p className="font-medium">
                {settings.clock_rounding_minutes} min ({settings.clock_rounding_direction})
              </p>
            </div>
            <div>
              <label className="text-xs text-muted">Match Policy</label>
              <p className="font-medium">
                {settings.match_policy?.replace(/_/g, ' ') ?? 'pay actual'}
              </p>
            </div>
            <div>
              <label className="text-xs text-muted">Grace Window</label>
              <p className="font-medium">
                Early: {settings.early_grace_minutes ?? 0}min / Late:{' '}
                {settings.late_grace_minutes ?? 0}min
              </p>
            </div>
            <div>
              <label className="text-xs text-muted">Auto-Approve Threshold</label>
              <p className="font-medium">
                {(settings.auto_approve_threshold_minutes ?? 0) === 0
                  ? 'Disabled'
                  : `${settings.auto_approve_threshold_minutes} min`}
              </p>
            </div>
          </div>
        ) : (
          <p className="text-sm text-muted">No settings configured. Defaults will be used.</p>
        )}
      </div>

      {(data?.branch_overrides ?? []).length > 0 && (
        <div className="space-y-4 rounded-lg border border-border p-6">
          <h2 className="font-semibold text-text">Branch Overrides</h2>
          {(data?.branch_overrides ?? []).map((override) => (
            <div key={override.id} className="border-b border-border pb-3 last:border-0">
              <p className="font-medium">{override.branch_name ?? 'Branch'}</p>
              <p className="text-xs text-muted">
                Rounding: {override.clock_rounding_minutes}min • Policy: {override.match_policy}
              </p>
            </div>
          ))}
        </div>
      )}

      {!data?.branch_overrides?.length && !settings && (
        <p className="text-sm text-muted">No branch overrides configured.</p>
      )}
    </div>
  )
}
