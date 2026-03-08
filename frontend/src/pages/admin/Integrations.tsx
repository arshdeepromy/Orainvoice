import { useState, useEffect, useCallback } from 'react'
import { Button } from '@/components/ui/Button'
import { Badge } from '@/components/ui/Badge'
import { Spinner } from '@/components/ui/Spinner'
import { AlertBanner } from '@/components/ui/AlertBanner'
import { Input } from '@/components/ui/Input'
import { Tabs } from '@/components/ui/Tabs'
import { ToastContainer, useToast } from '@/components/ui/Toast'
import apiClient from '@/api/client'
import { SmsProviders } from './SmsProviders'
import { EmailProviders } from './EmailProviders'

/* ── Types ── */

export interface IntegrationConfig {
  name: string
  is_verified: boolean
  updated_at: string | null
  fields: Record<string, string>
}

export type IntegrationName = 'carjam' | 'stripe'

/* ── Field definitions per integration ── */

interface FieldDef {
  key: string
  label: string
  type: 'text' | 'password' | 'number' | 'select'
  placeholder?: string
  helperText?: string
  backendKey?: string
  options?: { value: string; label: string }[]
  /** Show this field only when the given sibling key matches one of the pipe-separated values */
  visibleWhen?: { key: string; oneOf: string }
}

const INTEGRATION_FIELDS: Record<IntegrationName, FieldDef[]> = {
  carjam: [
    { key: 'api_key', label: 'API key', type: 'password', placeholder: '••••••••', backendKey: 'api_key_last4' },
    { key: 'endpoint_url', label: 'Endpoint URL', type: 'text', placeholder: 'https://api.carjam.co.nz/v2' },
    { key: 'per_lookup_cost_nzd', label: 'Per-lookup cost (NZD)', type: 'number', placeholder: '0.50' },
    { key: 'global_rate_limit_per_minute', label: 'Global rate limit (calls/min)', type: 'number', placeholder: '60' },
  ],
  stripe: [
    { key: 'platform_account_id', label: 'Platform account ID', type: 'password', placeholder: 'acct_...', backendKey: 'platform_account_id_last4' },
    { key: 'webhook_endpoint', label: 'Webhook endpoint URL', type: 'text', placeholder: 'https://...' },
    { key: 'signing_secret', label: 'Webhook signing secret', type: 'password', placeholder: '••••••••', backendKey: 'signing_secret_last4' },
  ],
}

const INTEGRATION_LABELS: Record<IntegrationName, string> = {
  carjam: 'Carjam',
  stripe: 'Stripe',
}

const MASKED_VALUE = '••••••••'

/* ── Integration Config Panel ── */

function IntegrationPanel({
  name,
  onToast,
}: {
  name: IntegrationName
  onToast: (variant: 'success' | 'error', message: string) => void
}) {
  const fields = INTEGRATION_FIELDS[name]
  const [values, setValues] = useState<Record<string, string>>({})
  const [isVerified, setIsVerified] = useState(false)
  const [updatedAt, setUpdatedAt] = useState<string | null>(null)
  const [loading, setLoading] = useState(true)
  const [saving, setSaving] = useState(false)
  const [testing, setTesting] = useState(false)
  const [testResult, setTestResult] = useState<{ success: boolean; message: string } | null>(null)
  const [error, setError] = useState(false)

  const fetchConfig = useCallback(async () => {
    setLoading(true)
    setError(false)
    try {
      const res = await apiClient.get<IntegrationConfig>(`/admin/integrations/${name}`)
      const config = res.data
      // Credential fields come back masked from the API — display masked placeholder
      const fieldValues: Record<string, string> = {}
      for (const f of fields) {
        if (f.type === 'password') {
          // Backend returns masked fields with a different key (e.g. api_key_last4)
          const bk = f.backendKey ?? f.key
          fieldValues[f.key] = config.fields[bk] ? MASKED_VALUE : ''
        } else if (f.type === 'select' && f.options) {
          // Use backend value or default to first option
          fieldValues[f.key] = config.fields[f.key] != null
            ? String(config.fields[f.key])
            : f.options[0]?.value ?? ''
        } else {
          fieldValues[f.key] = config.fields[f.key] != null ? String(config.fields[f.key]) : ''
        }
      }
      setValues(fieldValues)
      setIsVerified(config.is_verified)
      setUpdatedAt(config.updated_at)
    } catch {
      setError(true)
    } finally {
      setLoading(false)
    }
  }, [name, fields])

  useEffect(() => {
    fetchConfig()
  }, [fetchConfig])

  const handleChange = (key: string, value: string) => {
    setValues((prev) => ({ ...prev, [key]: value }))
    setTestResult(null)
  }

  const handleClearCredential = (key: string) => {
    setValues((prev) => ({ ...prev, [key]: '' }))
    setTestResult(null)
  }

  const handleSave = async (e: React.FormEvent) => {
    e.preventDefault()
    setSaving(true)
    try {
      // Only send fields that have been changed (non-masked values) and are currently visible
      const payload: Record<string, string> = {}
      for (const f of fields) {
        // Skip fields hidden by visibleWhen condition
        if (f.visibleWhen) {
          const depValue = values[f.visibleWhen.key] ?? ''
          if (!f.visibleWhen.oneOf.split('|').includes(depValue)) continue
        }
        const val = values[f.key]
        if (f.type === 'password' && val === MASKED_VALUE) continue // unchanged
        payload[f.key] = val
      }
      await apiClient.put(`/admin/integrations/${name}`, payload)
      onToast('success', `${INTEGRATION_LABELS[name]} configuration saved`)
      fetchConfig()
    } catch {
      onToast('error', `Failed to save ${INTEGRATION_LABELS[name]} configuration`)
    } finally {
      setSaving(false)
    }
  }

  const handleTest = async () => {
    setTesting(true)
    setTestResult(null)
    try {
      const res = await apiClient.post<{ success: boolean; message: string }>(
        `/admin/integrations/${name}/test`,
      )
      setTestResult(res.data)
      if (res.data.success) {
        onToast('success', `${INTEGRATION_LABELS[name]} connection test passed`)
      } else {
        onToast('error', `${INTEGRATION_LABELS[name]} connection test failed`)
      }
    } catch {
      setTestResult({ success: false, message: 'Connection test failed — check credentials' })
      onToast('error', `${INTEGRATION_LABELS[name]} connection test failed`)
    } finally {
      setTesting(false)
    }
  }

  if (loading) {
    return (
      <div className="flex items-center justify-center py-12">
        <Spinner label={`Loading ${INTEGRATION_LABELS[name]} configuration`} />
      </div>
    )
  }

  if (error) {
    return (
      <AlertBanner variant="error" title="Failed to load configuration">
        Could not load {INTEGRATION_LABELS[name]} configuration. Please try again.
      </AlertBanner>
    )
  }

  return (
    <form onSubmit={handleSave} className="max-w-lg space-y-5">
      <div className="flex items-center gap-3 mb-2">
        <h2 className="text-lg font-semibold text-gray-900">{INTEGRATION_LABELS[name]}</h2>
        <Badge variant={isVerified ? 'success' : 'neutral'}>
          {isVerified ? 'Verified' : 'Not verified'}
        </Badge>
      </div>

      {updatedAt && (
        <p className="text-sm text-gray-500">
          Last updated: {new Date(updatedAt).toLocaleDateString('en-NZ', { day: 'numeric', month: 'short', year: 'numeric', hour: '2-digit', minute: '2-digit' })}
        </p>
      )}

      {fields.map((f) => {
        // Conditional visibility: skip fields whose visibleWhen condition is not met
        if (f.visibleWhen) {
          const depValue = values[f.visibleWhen.key] ?? ''
          if (!f.visibleWhen.oneOf.split('|').includes(depValue)) return null
        }

        return (
        <div key={f.key}>
          {f.type === 'select' && f.options ? (
            <div className="flex flex-col gap-1">
              <label className="text-sm font-medium text-gray-700">{f.label}</label>
              <select
                className="rounded-md border border-gray-300 bg-white px-3 py-2 text-gray-900"
                value={values[f.key] ?? ''}
                onChange={(e) => handleChange(f.key, e.target.value)}
              >
                {f.options.map((opt) => (
                  <option key={opt.value} value={opt.value}>{opt.label}</option>
                ))}
              </select>
            </div>
          ) : f.type === 'password' && values[f.key] === MASKED_VALUE ? (
            <div className="flex flex-col gap-1">
              <label className="text-sm font-medium text-gray-700">{f.label}</label>
              <div className="flex items-center gap-2">
                <span className="rounded-md border border-gray-300 bg-gray-50 px-3 py-2 text-gray-500 flex-1">
                  {MASKED_VALUE}
                </span>
                <Button
                  type="button"
                  variant="secondary"
                  size="sm"
                  onClick={() => handleClearCredential(f.key)}
                >
                  Change
                </Button>
              </div>
              <p className="text-sm text-gray-500">Credential is set. Click Change to update.</p>
            </div>
          ) : (
            <Input
              label={f.label}
              type={f.type === 'password' ? 'password' : f.type === 'number' ? 'number' : 'text'}
              value={values[f.key] ?? ''}
              onChange={(e) => handleChange(f.key, e.target.value)}
              placeholder={f.placeholder}
              helperText={f.helperText}
              step={f.type === 'number' ? '0.01' : undefined}
            />
          )}
        </div>
        )
      })}

      {testResult && (
        <AlertBanner
          variant={testResult.success ? 'success' : 'error'}
          title={testResult.success ? 'Connection successful' : 'Connection failed'}
        >
          {testResult.message}
        </AlertBanner>
      )}

      <div className="flex gap-3 pt-2">
        <Button type="submit" loading={saving}>
          Save configuration
        </Button>
        <Button type="button" variant="secondary" onClick={handleTest} loading={testing}>
          Test connection
        </Button>
      </div>
    </form>
  )
}

/* ── Main Page ── */

export function Integrations() {
  const { toasts, addToast, dismissToast } = useToast()

  const tabs = [
    {
      id: 'carjam',
      label: 'Carjam',
      content: <IntegrationPanel name="carjam" onToast={addToast} />,
    },
    {
      id: 'stripe',
      label: 'Stripe',
      content: <IntegrationPanel name="stripe" onToast={addToast} />,
    },
    {
      id: 'sms-providers',
      label: 'SMS Providers',
      content: <SmsProviders />,
    },
    {
      id: 'email-providers',
      label: 'Email Providers',
      content: <EmailProviders />,
    },
  ]

  return (
    <div>
      <h1 className="text-2xl font-semibold text-gray-900 mb-6">Integrations</h1>
      <ToastContainer toasts={toasts} onDismiss={dismissToast} />
      <Tabs tabs={tabs} defaultTab="carjam" />
    </div>
  )
}
