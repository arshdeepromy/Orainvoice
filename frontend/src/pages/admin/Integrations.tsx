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
import CalendarSync from './CalendarSync'
import { XeroCredentialsSettings } from './XeroCredentialsSettings'
import { StripeSetupGuide, type StripeSetupProgress } from '@/components/admin/StripeSetupGuide'
import { StripeTestSuite } from '@/components/admin/StripeTestSuite'

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
  /** Group name for sectioned rendering (Stripe uses 'api-keys' and 'connect') */
  group?: string
}

const INTEGRATION_FIELDS: Record<IntegrationName, FieldDef[]> = {
  carjam: [
    { key: 'api_key', label: 'API key', type: 'password', placeholder: '••••••••', backendKey: 'api_key_last4' },
    { key: 'endpoint_url', label: 'Endpoint URL', type: 'text', placeholder: 'https://www.carjam.co.nz' },
    { key: 'per_lookup_cost_nzd', label: 'Basic per-lookup cost (NZD)', type: 'number', placeholder: '0.50', helperText: 'Cost charged per basic CarJam API lookup' },
    { key: 'abcd_per_lookup_cost_nzd', label: 'ABCD per-lookup cost (NZD)', type: 'number', placeholder: '0.05', helperText: 'Cost charged per ABCD (lower-cost) lookup' },
    { key: 'global_rate_limit_per_minute', label: 'Global rate limit (calls/min)', type: 'number', placeholder: '60' },
  ],
  stripe: [
    { key: 'publishable_key', label: 'Publishable key', type: 'password', placeholder: 'pk_test_... or pk_live_...', backendKey: 'publishable_key_last4', helperText: 'Used by the frontend for Stripe.js / Elements', group: 'api-keys' },
    { key: 'secret_key', label: 'Secret key', type: 'password', placeholder: 'sk_test_... or sk_live_...', backendKey: 'secret_key_last4', helperText: 'Used by the backend for API calls (charges, subscriptions)', group: 'api-keys' },
    { key: 'connect_client_id', label: 'Connect client ID', type: 'password', placeholder: 'ca_...', backendKey: 'connect_client_id_last4', helperText: 'Found in Stripe Dashboard → Settings → Connect → OAuth settings', group: 'connect' },
    { key: 'platform_account_id', label: 'Platform account ID', type: 'password', placeholder: 'acct_...', backendKey: 'platform_account_id_last4', group: 'connect' },
    { key: 'webhook_endpoint', label: 'Webhook endpoint URL', type: 'text', placeholder: 'https://...', group: 'connect' },
    { key: 'signing_secret', label: 'Webhook signing secret', type: 'password', placeholder: '••••••••', backendKey: 'signing_secret_last4', group: 'connect' },
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
  
  // Separate state for API keys section (Stripe only)
  const [savingKeys, setSavingKeys] = useState(false)
  const [testingKeys, setTestingKeys] = useState(false)
  const [keysTestResult, setKeysTestResult] = useState<{ success: boolean; message: string } | null>(null)
  
  // Vehicle lookup test state (Carjam only)
  const [lookupRego, setLookupRego] = useState('')
  const [lookupTesting, setLookupTesting] = useState(false)
  const [lookupResult, setLookupResult] = useState<{
    success: boolean
    message: string
    data?: any
    source?: string
  } | null>(null)
  
  // ABCD lookup test state (Carjam only)
  const [abcdRego, setAbcdRego] = useState('')
  const [abcdUseMvr, setAbcdUseMvr] = useState(true)
  const [abcdTesting, setAbcdTesting] = useState(false)
  const [abcdResult, setAbcdResult] = useState<{
    success: boolean
    message: string
    data?: any
    source?: string
    mvr_used?: boolean
    retry_suggested?: boolean
  } | null>(null)

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
      const payload: Record<string, string | number> = {}
      for (const f of fields) {
        // Skip fields hidden by visibleWhen condition
        if (f.visibleWhen) {
          const depValue = values[f.visibleWhen.key] ?? ''
          if (!f.visibleWhen.oneOf.split('|').includes(depValue)) continue
        }
        const val = values[f.key]
        if (f.type === 'password' && val === MASKED_VALUE) continue // unchanged
        
        // Convert number fields to actual numbers
        if (f.type === 'number' && val) {
          payload[f.key] = parseFloat(val)
        } else {
          payload[f.key] = val
        }
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

  // Save only API keys group (Stripe)
  const handleSaveKeys = async () => {
    setSavingKeys(true)
    try {
      const payload: Record<string, string> = {}
      for (const f of fields) {
        if (f.group !== 'api-keys') continue
        const val = values[f.key]
        if (f.type === 'password' && val === MASKED_VALUE) continue
        payload[f.key] = val
      }
      await apiClient.put(`/admin/integrations/${name}`, payload)
      onToast('success', 'Stripe API keys saved')
      fetchConfig()
    } catch {
      onToast('error', 'Failed to save Stripe API keys')
    } finally {
      setSavingKeys(false)
    }
  }

  // Test API keys (Stripe)
  const handleTestKeys = async () => {
    setTestingKeys(true)
    setKeysTestResult(null)
    try {
      const res = await apiClient.post<{ success: boolean; message: string }>(
        `/admin/integrations/stripe/test-keys`,
      )
      setKeysTestResult(res.data)
      if (res.data.success) {
        onToast('success', 'Stripe API keys verified')
      } else {
        onToast('error', 'Stripe API key test failed')
      }
    } catch {
      setKeysTestResult({ success: false, message: 'API key test failed — check your secret key' })
      onToast('error', 'Stripe API key test failed')
    } finally {
      setTestingKeys(false)
    }
  }
  
  const handleVehicleLookup = async () => {
    if (!lookupRego.trim()) {
      onToast('error', 'Please enter a registration number')
      return
    }
    
    setLookupTesting(true)
    setLookupResult(null)
    try {
      const res = await apiClient.post<{
        success: boolean
        message: string
        data?: any
        source?: string
      }>(`/admin/integrations/carjam/lookup-test`, { rego: lookupRego.trim() })
      
      setLookupResult(res.data)
      if (res.data.success) {
        onToast('success', `Vehicle found: ${res.data.message}`)
      } else {
        onToast('error', res.data.message)
      }
    } catch (err: any) {
      const errorMsg = err.response?.data?.message || 'Vehicle lookup failed'
      setLookupResult({ success: false, message: errorMsg })
      onToast('error', errorMsg)
    } finally {
      setLookupTesting(false)
    }
  }
  
  const handleAbcdLookup = async () => {
    if (!abcdRego.trim()) {
      onToast('error', 'Please enter a registration number')
      return
    }
    
    setAbcdTesting(true)
    setAbcdResult(null)
    try {
      const res = await apiClient.post<{
        success: boolean
        message: string
        data?: any
        source?: string
        mvr_used?: boolean
        attempts?: number
        retry_suggested?: boolean
      }>(`/admin/integrations/carjam/lookup-test-abcd`, { 
        rego: abcdRego.trim(),
        use_mvr: abcdUseMvr
      })
      
      setAbcdResult(res.data)
      if (res.data.success) {
        const attemptsMsg = res.data.attempts && res.data.attempts > 1 
          ? ` (${res.data.attempts} attempts)` 
          : ''
        onToast('success', `ABCD lookup successful${attemptsMsg}: ${res.data.message}`)
      } else if (res.data.retry_suggested) {
        onToast('success', 'Carjam is fetching data. Please try again in a few seconds.')
      } else {
        onToast('error', res.data.message)
      }
    } catch (err: any) {
      const errorMsg = err.response?.data?.message || 'ABCD lookup failed'
      setAbcdResult({ success: false, message: errorMsg })
      onToast('error', errorMsg)
    } finally {
      setAbcdTesting(false)
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

  const hasGroups = fields.some((f) => f.group)

  const renderField = (f: FieldDef) => {
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
  }

  return (
    <div className="max-w-lg space-y-5">
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

      {/* Grouped layout for Stripe */}
      {hasGroups ? (
        <>
          {/* Stripe Setup Guide — above API Keys */}
          {name === 'stripe' && (
            <StripeSetupGuide
              progress={{
                apiKeysSaved:
                  values['publishable_key'] === MASKED_VALUE &&
                  values['secret_key'] === MASKED_VALUE,
                apiKeysTested: keysTestResult?.success === true,
                webhookEndpointSet:
                  !!values['webhook_endpoint'] &&
                  values['webhook_endpoint'] !== MASKED_VALUE &&
                  values['webhook_endpoint'].trim().length > 0,
                signingSecretSaved: values['signing_secret'] === MASKED_VALUE,
                connectionTested: isVerified,
              } satisfies StripeSetupProgress}
            />
          )}

          {/* API Keys section */}
          <div className="rounded-lg border border-gray-200 p-5 space-y-4">
            <h3 className="text-md font-semibold text-gray-900">API Keys</h3>
            <p className="text-xs text-gray-500">Your Stripe publishable and secret keys for processing payments.</p>
            {fields.filter((f) => f.group === 'api-keys').map(renderField)}

            {keysTestResult && (
              <AlertBanner
                variant={keysTestResult.success ? 'success' : 'error'}
                title={keysTestResult.success ? 'API keys verified' : 'API key test failed'}
              >
                {keysTestResult.message}
              </AlertBanner>
            )}

            <div className="flex gap-3 pt-1">
              <Button type="button" onClick={handleSaveKeys} loading={savingKeys}>
                Save API keys
              </Button>
              <Button type="button" variant="secondary" onClick={handleTestKeys} loading={testingKeys}>
                Test API keys
              </Button>
            </div>
          </div>

          {/* Connect / Webhook section */}
          <form onSubmit={handleSave} className="rounded-lg border border-gray-200 p-5 space-y-4">
            <h3 className="text-md font-semibold text-gray-900">Platform &amp; Webhooks</h3>
            <p className="text-xs text-gray-500">Stripe Connect platform account and webhook configuration.</p>
            {fields.filter((f) => f.group === 'connect').map(renderField)}

            {/* Connect Setup Guide */}
            {name === 'stripe' && (
              <div className="mt-4 rounded-lg bg-blue-50 border border-blue-200 p-4 space-y-3">
                <h4 className="text-sm font-medium text-blue-900">Stripe Connect Setup Guide</h4>
                <div className="text-sm text-blue-800 space-y-2">
                  <p>To enable online payments for your organisations:</p>
                  <ol className="list-decimal list-inside space-y-1 ml-2">
                    <li>Go to <a href="https://dashboard.stripe.com/settings/connect" target="_blank" rel="noopener noreferrer" className="underline font-medium">Stripe Dashboard → Settings → Connect</a></li>
                    <li>Enable Connect and choose <strong>Platform</strong> business model</li>
                    <li>Under <strong>OAuth settings</strong>, copy the <strong>client_id</strong> (starts with <code className="bg-blue-100 px-1 rounded">ca_</code>) and paste it above</li>
                    <li>Add this <strong>Redirect URI</strong> to your Stripe Connect OAuth settings:</li>
                  </ol>
                  <div className="bg-white rounded border border-blue-300 px-3 py-2 font-mono text-xs break-all select-all">
                    {window.location.origin}/api/v1/org/stripe-connect/callback
                  </div>
                  <p className="text-xs text-blue-600">Click the URI above to select it, then paste it into Stripe's redirect URI field.</p>
                </div>
              </div>
            )}

            {testResult && (
              <AlertBanner
                variant={testResult.success ? 'success' : 'error'}
                title={testResult.success ? 'Connection successful' : 'Connection failed'}
              >
                {testResult.message}
              </AlertBanner>
            )}

            <div className="flex gap-3 pt-1">
              <Button type="submit" loading={saving}>
                Save configuration
              </Button>
              <Button type="button" variant="secondary" onClick={handleTest} loading={testing}>
                Test connection
              </Button>
            </div>
          </form>

          {/* Stripe Test Suite — below existing config sections */}
          {name === 'stripe' && <StripeTestSuite />}
        </>
      ) : (
        /* Non-grouped layout (Carjam, etc.) */
        <form onSubmit={handleSave} className="space-y-5">
          {fields.map(renderField)}

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
      {name === 'carjam' && (
        <div className="mt-8 pt-6 border-t border-gray-200">
          <h3 className="text-md font-semibold text-gray-900 mb-4">Test Vehicle Lookup</h3>
          <p className="text-sm text-gray-600 mb-4">
            Enter a registration number to test the Carjam API and caching. 
            First lookup will fetch from Carjam API and cache the result. 
            Subsequent lookups will use the cached data.
          </p>
          
          <div className="flex gap-3 items-end">
            <div className="flex-1">
              <Input
                label="Registration Number"
                value={lookupRego}
                onChange={(e) => setLookupRego(e.target.value.toUpperCase())}
                placeholder="ABC123"
                onKeyDown={(e) => {
                  if (e.key === 'Enter') {
                    e.preventDefault()
                    handleVehicleLookup()
                  }
                }}
              />
            </div>
            <Button
              type="button"
              onClick={handleVehicleLookup}
              loading={lookupTesting}
              disabled={!lookupRego.trim()}
            >
              Lookup Vehicle
            </Button>
          </div>
          
          {lookupResult && (
            <div className="mt-4">
              <AlertBanner
                variant={lookupResult.success ? 'success' : 'error'}
                title={lookupResult.success ? 'Vehicle Found' : 'Lookup Failed'}
              >
                <div className="space-y-2">
                  <p>{lookupResult.message}</p>
                  {lookupResult.success && lookupResult.data && (
                    <div className="mt-3 p-3 bg-white rounded border border-gray-200">
                      <div className="grid grid-cols-2 gap-2 text-sm">
                        <div><span className="font-medium">Registration:</span> {lookupResult.data.rego}</div>
                        <div><span className="font-medium">Source:</span> <span className={lookupResult.source === 'cache' ? 'text-green-600' : 'text-blue-600'}>{lookupResult.source === 'cache' ? 'Cached' : 'Carjam API'}</span></div>
                        {lookupResult.data.make && <div><span className="font-medium">Make:</span> {lookupResult.data.make}</div>}
                        {lookupResult.data.model && <div><span className="font-medium">Model:</span> {lookupResult.data.model}</div>}
                        {lookupResult.data.year && <div><span className="font-medium">Year:</span> {lookupResult.data.year}</div>}
                        {lookupResult.data.colour && <div><span className="font-medium">Colour:</span> {lookupResult.data.colour}</div>}
                        {lookupResult.data.body_type && <div><span className="font-medium">Body Type:</span> {lookupResult.data.body_type}</div>}
                        {lookupResult.data.fuel_type && <div><span className="font-medium">Fuel:</span> {lookupResult.data.fuel_type}</div>}
                      </div>
                    </div>
                  )}
                </div>
              </AlertBanner>
            </div>
          )}
        </div>
      )}
      
      {/* ABCD Lookup Test (Carjam only) */}
      {name === 'carjam' && (
        <div className="mt-8 pt-6 border-t border-gray-200">
          <h3 className="text-md font-semibold text-gray-900 mb-4">Test ABCD Lookup (Lower Cost)</h3>
          <p className="text-sm text-gray-600 mb-4">
            ABCD (Absolute Basic Car Details) is a lower-cost API option that provides basic vehicle information.
            This does NOT cache results or increment usage counters - it's for testing only.
          </p>
          
          <div className="mb-4">
            <label className="flex items-center gap-2 text-sm">
              <input
                type="checkbox"
                checked={abcdUseMvr}
                onChange={(e) => setAbcdUseMvr(e.target.checked)}
                className="rounded border-gray-300"
              />
              <span>Use Motor Vehicle Register (MVR) - adds 17c NZD per lookup</span>
            </label>
            <p className="text-xs text-gray-500 mt-1 ml-6">
              If unchecked, only uses CarJam's internal data. If checked, fetches from MVR if data is missing.
            </p>
          </div>
          
          <div className="flex gap-3 items-end">
            <div className="flex-1">
              <Input
                label="Registration Number"
                value={abcdRego}
                onChange={(e) => setAbcdRego(e.target.value.toUpperCase())}
                placeholder="ABC123"
                onKeyDown={(e) => {
                  if (e.key === 'Enter') {
                    e.preventDefault()
                    handleAbcdLookup()
                  }
                }}
              />
            </div>
            <Button
              type="button"
              onClick={handleAbcdLookup}
              loading={abcdTesting}
              disabled={!abcdRego.trim()}
            >
              ABCD Lookup
            </Button>
          </div>
          
          {abcdResult && (
            <div className="mt-4">
              <AlertBanner
                variant={abcdResult.success ? 'success' : abcdResult.retry_suggested ? 'info' : 'error'}
                title={abcdResult.success ? 'ABCD Lookup Successful' : abcdResult.retry_suggested ? 'Data Being Fetched' : 'ABCD Lookup Failed'}
              >
                <div className="space-y-2">
                  <p>{abcdResult.message}</p>
                  {abcdResult.retry_suggested && (
                    <p className="text-sm mt-2">
                      ℹ️ The ABCD API is asynchronously fetching data from Carjam. 
                      This is normal for first-time lookups. Please wait a few seconds and try again.
                    </p>
                  )}
                  {abcdResult.success && abcdResult.data && (
                    <div className="mt-3 p-3 bg-white rounded border border-gray-200">
                      <div className="mb-2 text-xs text-gray-500">
                        Source: <span className="font-medium text-blue-600">Carjam ABCD API</span>
                        {abcdResult.mvr_used !== undefined && (
                          <span className="ml-2">
                            | MVR: <span className={abcdResult.mvr_used ? 'text-orange-600' : 'text-green-600'}>
                              {abcdResult.mvr_used ? 'Enabled (+17c)' : 'Disabled'}
                            </span>
                          </span>
                        )}
                      </div>
                      <div className="grid grid-cols-2 gap-2 text-sm">
                        <div><span className="font-medium">Registration:</span> {abcdResult.data.rego}</div>
                        {abcdResult.data.vin && <div><span className="font-medium">VIN:</span> {abcdResult.data.vin}</div>}
                        {abcdResult.data.make && <div><span className="font-medium">Make:</span> {abcdResult.data.make}</div>}
                        {abcdResult.data.model && <div><span className="font-medium">Model:</span> {abcdResult.data.model}</div>}
                        {abcdResult.data.submodel && <div><span className="font-medium">Submodel:</span> {abcdResult.data.submodel}</div>}
                        {abcdResult.data.year && <div><span className="font-medium">Year:</span> {abcdResult.data.year}</div>}
                        {abcdResult.data.colour && <div><span className="font-medium">Colour:</span> {abcdResult.data.colour}</div>}
                        {abcdResult.data.body_type && <div><span className="font-medium">Body Type:</span> {abcdResult.data.body_type}</div>}
                        {abcdResult.data.reported_stolen && <div><span className="font-medium">Stolen:</span> {abcdResult.data.reported_stolen === 'Y' ? '⚠️ Yes' : '✓ No'}</div>}
                      </div>
                    </div>
                  )}
                </div>
              </AlertBanner>
            </div>
          )}
        </div>
      )}
    </form>
      )}
    </div>
  )
}



/* ── Main Page ── */

export function Integrations() {
  const { toasts, addToast, dismissToast } = useToast()
  const [restoring, setRestoring] = useState(false)
  const [backing, setBacking] = useState(false)

  const handleBackup = async () => {
    setBacking(true)
    try {
      const res = await apiClient.get('/admin/integrations/backup')
      const blob = new Blob([JSON.stringify(res.data, null, 2)], { type: 'application/json' })
      const url = URL.createObjectURL(blob)
      const a = document.createElement('a')
      a.href = url
      a.download = `integration-settings-backup-${new Date().toISOString().slice(0, 10)}.json`
      document.body.appendChild(a)
      a.click()
      document.body.removeChild(a)
      URL.revokeObjectURL(url)
      addToast('success', 'Backup downloaded')
    } catch {
      addToast('error', 'Failed to export backup')
    } finally {
      setBacking(false)
    }
  }

  const handleRestore = () => {
    const input = document.createElement('input')
    input.type = 'file'
    input.accept = '.json'
    input.onchange = async (e) => {
      const file = (e.target as HTMLInputElement).files?.[0]
      if (!file) return
      setRestoring(true)
      try {
        const text = await file.text()
        const data = JSON.parse(text)
        const res = await apiClient.post('/admin/integrations/restore', data)
        const restored = res.data.restored || {}
        const parts: string[] = []
        if (restored.integrations?.length) parts.push(`${restored.integrations.length} integrations`)
        if (restored.sms_providers?.length) parts.push(`${restored.sms_providers.length} SMS providers`)
        if (restored.email_providers?.length) parts.push(`${restored.email_providers.length} email providers`)
        addToast('success', `Restored: ${parts.join(', ') || 'nothing to restore'}`)
      } catch {
        addToast('error', 'Failed to restore settings. Check the file format.')
      } finally {
        setRestoring(false)
      }
    }
    input.click()
  }

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
    {
      id: 'calendar-sync',
      label: 'Calendar Sync',
      content: <CalendarSync />,
    },
    {
      id: 'xero-credentials',
      label: 'Xero Credentials',
      content: <XeroCredentialsSettings />,
    },
  ]

  return (
    <div>
      <div className="flex items-center justify-between mb-6">
        <h1 className="text-2xl font-semibold text-gray-900">Integrations</h1>
        <div className="flex gap-2">
          <Button variant="secondary" size="sm" onClick={handleBackup} loading={backing}>
            Backup Settings
          </Button>
          <Button variant="secondary" size="sm" onClick={handleRestore} loading={restoring}>
            Restore Settings
          </Button>
        </div>
      </div>
      <ToastContainer toasts={toasts} onDismiss={dismissToast} />
      <Tabs tabs={tabs} defaultTab="carjam" urlPersist />
    </div>
  )
}
