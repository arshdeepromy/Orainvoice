import { useState, useEffect, useCallback } from 'react'
import React from 'react'
import { Button } from '@/components/ui/Button'
import { Spinner } from '@/components/ui/Spinner'
import { AlertBanner } from '@/components/ui/AlertBanner'
import { Input } from '@/components/ui/Input'
import { ToastContainer, useToast } from '@/components/ui/Toast'
import apiClient from '@/api/client'

interface SmsProvider {
  id: string
  provider_key: string
  display_name: string
  description: string | null
  icon: string | null
  is_active: boolean
  is_default: boolean
  priority: number
  credentials_set: boolean
  config: Record<string, unknown>
  setup_guide: string | null
  created_at: string
  updated_at: string
}

interface FallbackChainItem {
  provider_key: string
  display_name: string
  priority: number
}

interface ConnexusBalance {
  balance: number
  currency: string
}

const PROVIDER_ICONS: Record<string, React.JSX.Element> = {
  phone: (
    <svg className="h-6 w-6" fill="none" viewBox="0 0 24 24" stroke="currentColor" aria-hidden="true">
      <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5} d="M2.25 6.75c0 8.284 6.716 15 15 15h2.25a2.25 2.25 0 002.25-2.25v-1.372c0-.516-.351-.966-.852-1.091l-4.423-1.106c-.44-.11-.902.055-1.173.417l-.97 1.293c-.282.376-.769.542-1.21.38a12.035 12.035 0 01-7.143-7.143c-.162-.441.004-.928.38-1.21l1.293-.97c.363-.271.527-.734.417-1.173L6.963 3.102a1.125 1.125 0 00-1.091-.852H4.5A2.25 2.25 0 002.25 4.5v2.25z" />
    </svg>
  ),
  firebase: (
    <svg className="h-6 w-6" viewBox="0 0 24 24" fill="none" stroke="currentColor" aria-hidden="true">
      <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5} d="M15.362 5.214A8.252 8.252 0 0112 21 8.25 8.25 0 016.038 7.048 8.287 8.287 0 009 9.6a8.983 8.983 0 013.361-6.867 8.21 8.21 0 003 2.48z" />
      <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5} d="M12 18a3.75 3.75 0 00.495-7.467 5.99 5.99 0 00-1.925 3.546 5.974 5.974 0 01-2.133-1A3.75 3.75 0 0012 18z" />
    </svg>
  ),
  cloud: (
    <svg className="h-6 w-6" fill="none" viewBox="0 0 24 24" stroke="currentColor" aria-hidden="true">
      <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5} d="M2.25 15a4.5 4.5 0 004.5 4.5H18a3.75 3.75 0 001.332-7.257 3 3 0 00-3.758-3.848 5.25 5.25 0 00-10.233 2.33A4.502 4.502 0 002.25 15z" />
    </svg>
  ),
}

const CREDENTIAL_FIELDS: Record<string, { label: string; placeholder: string; type?: string }[]> = {
  firebase_phone_auth: [
    { label: 'Project ID', placeholder: 'my-firebase-project' },
    { label: 'API Key', placeholder: 'AIzaSy...', type: 'password' },
    { label: 'App ID', placeholder: '1:123456789:web:abcdef' },
  ],
  connexus: [
    { label: 'Client ID', placeholder: 'cid_your_client_id' },
    { label: 'Client Secret', placeholder: 'csk_your_client_secret', type: 'password' },
    { label: 'Sender ID', placeholder: 'Leave blank for shared shortcode (optional)' },
  ],
}

const BALANCE_LOW_THRESHOLD = 10

function formatDate(iso: string) {
  return new Date(iso).toLocaleString('en-NZ', {
    day: '2-digit', month: '2-digit', year: 'numeric',
    hour: 'numeric', minute: '2-digit', hour12: true,
  })
}

function SmsSetupGuide({ guide }: { guide: string }) {
  const [open, setOpen] = useState(false)
  const steps = guide.split('\n').filter(Boolean)

  return (
    <div className="rounded-lg border border-blue-200 bg-blue-50/50">
      <button
        onClick={() => setOpen(!open)}
        className="flex w-full items-center gap-2 px-4 py-3 text-left text-sm font-medium text-blue-700 hover:bg-blue-50 transition-colors rounded-lg"
        aria-expanded={open}
      >
        <svg className="h-5 w-5 shrink-0 text-blue-500" fill="none" viewBox="0 0 24 24" stroke="currentColor" aria-hidden="true">
          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5} d="M9.879 7.519c1.171-1.025 3.071-1.025 4.242 0 1.172 1.025 1.172 2.687 0 3.712-.203.179-.43.326-.67.442-.745.361-1.45.999-1.45 1.827v.75M21 12a9 9 0 11-18 0 9 9 0 0118 0zm-9 5.25h.008v.008H12v-.008z" />
        </svg>
        <span>How to configure this provider</span>
        <svg className={`ml-auto h-4 w-4 transition-transform ${open ? 'rotate-180' : ''}`} fill="none" viewBox="0 0 24 24" stroke="currentColor" aria-hidden="true">
          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M19 9l-7 7-7-7" />
        </svg>
      </button>
      {open && (
        <div className="border-t border-blue-200 px-4 py-3">
          <ol className="space-y-2 text-sm text-gray-700">
            {steps.map((step, i) => {
              const text = step.replace(/^\d+\.\s*/, '')
              return (
                <li key={i} className="flex gap-2">
                  <span className="flex h-5 w-5 shrink-0 items-center justify-center rounded-full bg-blue-100 text-xs font-semibold text-blue-700">
                    {i + 1}
                  </span>
                  <span>{text}</span>
                </li>
              )
            })}
          </ol>
        </div>
      )}
    </div>
  )
}

function ConnexusSection({ provider, addToast }: { provider: SmsProvider; addToast: (type: 'success' | 'error', msg: string) => void }) {
  const [balance, setBalance] = useState<ConnexusBalance | null>(null)
  const [balanceError, setBalanceError] = useState<string | null>(null)
  const [loadingBalance, setLoadingBalance] = useState(false)
  const [configuringWebhooks, setConfiguringWebhooks] = useState(false)
  const [copied, setCopied] = useState<string | null>(null)

  const incomingWebhookUrl = `${window.location.origin}/api/webhooks/connexus/incoming`
  const statusWebhookUrl = `${window.location.origin}/api/webhooks/connexus/status`

  const fetchBalance = useCallback(async () => {
    setLoadingBalance(true)
    setBalanceError(null)
    try {
      const res = await apiClient.get('/api/v2/admin/integrations/connexus/balance')
      if (res.data?.detail) {
        setBalanceError(res.data.detail)
      } else {
        setBalance({ balance: res.data.balance, currency: res.data.currency })
      }
    } catch (err: unknown) {
      const msg = (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail
      setBalanceError(msg || 'Failed to fetch balance')
    } finally {
      setLoadingBalance(false)
    }
  }, [])

  useEffect(() => {
    if (provider.credentials_set) {
      fetchBalance()
    }
  }, [provider.credentials_set, fetchBalance])

  async function handleConfigureWebhooks() {
    setConfiguringWebhooks(true)
    try {
      const res = await apiClient.post('/api/v2/admin/integrations/connexus/configure-webhooks', {
        mo_webhook_url: incomingWebhookUrl,
        dlr_webhook_url: statusWebhookUrl,
      })
      if (res.data?.detail) {
        addToast('error', res.data.detail)
      } else {
        addToast('success', 'Webhook URLs configured successfully')
      }
    } catch (err: unknown) {
      const msg = (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail
      addToast('error', msg || 'Failed to configure webhooks')
    } finally {
      setConfiguringWebhooks(false)
    }
  }

  function copyToClipboard(text: string, label: string) {
    navigator.clipboard.writeText(text).then(() => {
      setCopied(label)
      setTimeout(() => setCopied(null), 2000)
    })
  }

  return (
    <div className="space-y-4">
      {/* Balance display */}
      <div className="border-t border-gray-200 pt-4">
        <h4 className="text-sm font-medium text-gray-700 mb-3">Account Balance</h4>
        {!provider.credentials_set && (
          <AlertBanner variant="warning">
            Save credentials first to check the Connexus account balance.
          </AlertBanner>
        )}
        {provider.credentials_set && loadingBalance && (
          <div className="flex items-center gap-2 text-sm text-gray-500">
            <Spinner size="sm" /> Checking balance…
          </div>
        )}
        {provider.credentials_set && balanceError && (
          <AlertBanner variant="error">{balanceError}</AlertBanner>
        )}
        {provider.credentials_set && balance && (
          <div className="space-y-2">
            <div className="flex items-center gap-2">
              <span className="text-2xl font-semibold text-gray-900">
                ${balance.balance.toFixed(2)}
              </span>
              <span className="text-sm text-gray-500">{balance.currency}</span>
              <button
                onClick={fetchBalance}
                className="ml-2 rounded p-1 text-gray-400 hover:text-gray-600 hover:bg-gray-100 transition-colors"
                title="Refresh balance"
                aria-label="Refresh balance"
              >
                <svg className="h-4 w-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" aria-hidden="true">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M4 4v5h.582m15.356 2A8.001 8.001 0 004.582 9m0 0H9m11 11v-5h-.581m0 0a8.003 8.003 0 01-15.357-2m15.357 2H15" />
                </svg>
              </button>
            </div>
            {balance.balance < BALANCE_LOW_THRESHOLD && (
              <AlertBanner variant="warning">
                Balance is below ${BALANCE_LOW_THRESHOLD.toFixed(2)}. Consider topping up your Connexus account to avoid SMS delivery interruptions.
              </AlertBanner>
            )}
          </div>
        )}
      </div>

      {/* Webhook URLs */}
      <div className="border-t border-gray-200 pt-4">
        <h4 className="text-sm font-medium text-gray-700 mb-3">Webhook URLs</h4>
        <p className="text-xs text-gray-500 mb-3">
          Configure these URLs in your Connexus dashboard, or use the button below to set them automatically.
        </p>
        <div className="space-y-2">
          <div className="flex items-center gap-2">
            <label className="text-xs font-medium text-gray-600 w-28 shrink-0">Incoming SMS:</label>
            <code className="flex-1 rounded bg-gray-100 px-3 py-1.5 text-xs text-gray-700 font-mono truncate">
              {incomingWebhookUrl}
            </code>
            <button
              onClick={() => copyToClipboard(incomingWebhookUrl, 'incoming')}
              className="shrink-0 rounded px-2 py-1 text-xs text-indigo-600 hover:bg-indigo-50 transition-colors"
              aria-label="Copy incoming webhook URL"
            >
              {copied === 'incoming' ? 'Copied!' : 'Copy'}
            </button>
          </div>
          <div className="flex items-center gap-2">
            <label className="text-xs font-medium text-gray-600 w-28 shrink-0">Delivery Status:</label>
            <code className="flex-1 rounded bg-gray-100 px-3 py-1.5 text-xs text-gray-700 font-mono truncate">
              {statusWebhookUrl}
            </code>
            <button
              onClick={() => copyToClipboard(statusWebhookUrl, 'status')}
              className="shrink-0 rounded px-2 py-1 text-xs text-indigo-600 hover:bg-indigo-50 transition-colors"
              aria-label="Copy delivery status webhook URL"
            >
              {copied === 'status' ? 'Copied!' : 'Copy'}
            </button>
          </div>
        </div>
        <div className="mt-3">
          <Button
            onClick={handleConfigureWebhooks}
            loading={configuringWebhooks}
            variant="secondary"
            className="w-full sm:w-auto"
            disabled={!provider.credentials_set}
          >
            Configure Webhooks
          </Button>
        </div>
      </div>
    </div>
  )
}

function SmsCostConfig({ provider, addToast, onConfigSaved }: { provider: SmsProvider; addToast: (type: 'success' | 'error', msg: string) => void; onConfigSaved: () => void }) {
  const [cost, setCost] = useState(String(provider.config?.per_sms_cost_nzd ?? ''))
  const [saving, setSaving] = useState(false)

  const handleSave = async () => {
    setSaving(true)
    try {
      const updated = { ...provider.config, per_sms_cost_nzd: cost ? parseFloat(cost) : 0 }
      await apiClient.patch(`/api/v2/admin/sms-providers/${provider.provider_key}`, { config: updated })
      addToast('success', 'Per-SMS cost saved')
      onConfigSaved()
    } catch {
      addToast('error', 'Failed to save per-SMS cost')
    } finally {
      setSaving(false)
    }
  }

  return (
    <div className="border-t border-gray-200 pt-4">
      <h4 className="text-sm font-medium text-gray-700 mb-3">Pricing</h4>
      <div className="flex items-end gap-3">
        <div className="max-w-xs">
          <Input
            label="Per-SMS cost (NZD)"
            type="number"
            placeholder="0.08"
            value={cost}
            onChange={(e) => setCost(e.target.value)}
          />
        </div>
        <Button onClick={handleSave} loading={saving} variant="primary" className="mb-0.5">
          Save
        </Button>
      </div>
      <p className="mt-1 text-xs text-gray-400">
        Cost per outbound SMS. Used for usage cost calculations on the dashboard.
      </p>
    </div>
  )
}

function formatDuration(seconds: number): string {
  if (seconds <= 0) return ''
  const h = Math.floor(seconds / 3600)
  const m = Math.floor((seconds % 3600) / 60)
  const s = seconds % 60
  const parts: string[] = []
  if (h > 0) parts.push(`${h} hour${h !== 1 ? 's' : ''}`)
  if (m > 0) parts.push(`${m} minute${m !== 1 ? 's' : ''}`)
  if (s > 0 && h === 0) parts.push(`${s} second${s !== 1 ? 's' : ''}`)
  return parts.join(' ')
}

function TokenRefreshConfig({ provider, addToast, onConfigSaved }: { provider: SmsProvider; addToast: (type: 'success' | 'error', msg: string) => void; onConfigSaved: () => void }) {
  const currentVal = Number(provider.config?.token_refresh_interval_seconds ?? 0)
  const [interval, setInterval] = useState(currentVal > 0 ? String(currentVal) : '')
  const [saving, setSaving] = useState(false)

  const parsed = parseInt(interval, 10)
  const isValid = !interval || (Number.isFinite(parsed) && parsed >= 1)
  const durationLabel = Number.isFinite(parsed) && parsed > 0 ? formatDuration(parsed) : ''

  const handleSave = async () => {
    setSaving(true)
    try {
      const val = interval ? parseInt(interval, 10) : 0
      const updated = { ...provider.config, token_refresh_interval_seconds: val }
      await apiClient.patch(`/api/v2/admin/sms-providers/${provider.provider_key}`, { config: updated })
      addToast('success', val > 0 ? `Token refresh interval set to ${formatDuration(val)}` : 'Token refresh interval reset to default')
      onConfigSaved()
    } catch {
      addToast('error', 'Failed to save token refresh settings')
    } finally {
      setSaving(false)
    }
  }

  return (
    <div className="border-t border-gray-200 pt-4">
      <h4 className="text-sm font-medium text-gray-700 mb-3">Token Refresh Settings</h4>
      <div className="flex items-end gap-3">
        <div className="max-w-xs">
          <Input
            label="Refresh interval (seconds)"
            type="number"
            placeholder="3300"
            value={interval}
            onChange={(e) => setInterval(e.target.value)}
          />
        </div>
        <Button onClick={handleSave} loading={saving} variant="primary" className="mb-0.5" disabled={!isValid}>
          Save
        </Button>
        {durationLabel && (
          <span className="mb-1.5 text-sm text-gray-600">
            = {durationLabel}
          </span>
        )}
      </div>
      {interval && !isValid && (
        <p className="mt-1 text-xs text-red-500">
          Must be a positive number.
        </p>
      )}
      <p className="mt-1 text-xs text-gray-400">
        How long to reuse a cached token before refreshing. Connexus tokens expire after 3600 seconds (1 hour).
        {!interval && ' Default: 3300 seconds (55 minutes).'}
      </p>
    </div>
  )
}

function ProviderCard({
  provider,
  onToggleActive,
  onSetDefault,
  onSaveCredentials,
  onTestProvider,
  saving,
  addToast,
  onConfigSaved,
}: {
  provider: SmsProvider
  onToggleActive: (key: string, active: boolean) => void
  onSetDefault: (key: string) => void
  onSaveCredentials: (key: string, creds: Record<string, string>) => void
  onTestProvider: (key: string, toNumber: string, message: string) => Promise<void>
  saving: boolean
  addToast: (type: 'success' | 'error', msg: string) => void
  onConfigSaved: () => void
}) {
  const [expanded, setExpanded] = useState(false)
  const [creds, setCreds] = useState<Record<string, string>>({})
  const [maskedCreds, setMaskedCreds] = useState<Record<string, string>>({})
  const [credsLoaded, setCredsLoaded] = useState(false)
  const [testNumber, setTestNumber] = useState('')
  const [testMessage, setTestMessage] = useState('Hello from OraInvoice! This is a test SMS.')
  const [testing, setTesting] = useState(false)
  const [settingMfaDefault, setSettingMfaDefault] = useState(false)
  const [sendingTestCode, setSendingTestCode] = useState(false)
  const [testCodeNumber, setTestCodeNumber] = useState('')
  const fields = CREDENTIAL_FIELDS[provider.provider_key] ?? []
  const isMfaDefault = !!(provider.config as Record<string, unknown>)?.mfa_default

  const iconEl = PROVIDER_ICONS[provider.icon ?? ''] ?? PROVIDER_ICONS.phone

  // Load saved credentials when expanding — show as placeholders, not editable values
  useEffect(() => {
    if (!expanded || credsLoaded || !provider.credentials_set) return
    let cancelled = false
    async function loadCreds() {
      try {
        const res = await apiClient.get(`/api/v2/admin/sms-providers/${provider.provider_key}/credentials`)
        if (!cancelled && res.data?.credentials) {
          // Store masked values separately for display — don't put them in the editable creds
          setMaskedCreds(res.data.credentials)
          setCredsLoaded(true)
        }
      } catch {
        // Non-blocking
      }
    }
    loadCreds()
    return () => { cancelled = true }
  }, [expanded, credsLoaded, provider.credentials_set, provider.provider_key])

  return (
    <div
      className={`rounded-lg border transition-colors ${
        provider.is_active
          ? 'border-green-200 bg-green-50/30'
          : 'border-gray-200 bg-white'
      }`}
    >
      <div className="flex items-center gap-4 px-5 py-4">
        <div className={`flex h-10 w-10 shrink-0 items-center justify-center rounded-full ${
          provider.is_active ? 'bg-green-100 text-green-600' : 'bg-gray-100 text-gray-400'
        }`}>
          {iconEl}
        </div>

        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-2">
            <span className="font-medium text-gray-900">{provider.display_name}</span>
            {provider.is_active && (
              <span className="inline-flex items-center rounded-full bg-green-100 px-2 py-0.5 text-xs font-medium text-green-700">
                Active
              </span>
            )}
          </div>
          <p className="text-sm text-gray-500 truncate">{provider.description}</p>
        </div>

        <div className="flex items-center gap-2">
          {provider.is_active && (
            <>
              <button
                onClick={() => onToggleActive(provider.provider_key, false)}
                className="min-h-[36px] min-w-[36px] flex items-center justify-center rounded-md text-gray-400 hover:text-red-500 hover:bg-red-50 transition-colors"
                title="Deactivate"
                aria-label={`Deactivate ${provider.display_name}`}
              >
                <svg className="h-5 w-5" fill="none" viewBox="0 0 24 24" stroke="currentColor" aria-hidden="true">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M5.636 5.636a9 9 0 1012.728 0M12 3v9" />
                </svg>
              </button>
              <button
                onClick={() => onSetDefault(provider.provider_key)}
                className={`min-h-[36px] min-w-[36px] flex items-center justify-center rounded-md transition-colors ${
                  provider.is_default
                    ? 'text-yellow-500'
                    : 'text-gray-300 hover:text-yellow-500 hover:bg-yellow-50'
                }`}
                title={provider.is_default ? 'Default provider' : 'Set as default'}
                aria-label={provider.is_default ? 'Default provider' : `Set ${provider.display_name} as default`}
              >
                <svg className="h-5 w-5" viewBox="0 0 24 24" fill={provider.is_default ? 'currentColor' : 'none'} stroke="currentColor" aria-hidden="true">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5} d="M11.48 3.499a.562.562 0 011.04 0l2.125 5.111a.563.563 0 00.475.345l5.518.442c.499.04.701.663.321.988l-4.204 3.602a.563.563 0 00-.182.557l1.285 5.385a.562.562 0 01-.84.61l-4.725-2.885a.563.563 0 00-.586 0L6.982 20.54a.562.562 0 01-.84-.61l1.285-5.386a.562.562 0 00-.182-.557l-4.204-3.602a.563.563 0 01.321-.988l5.518-.442a.563.563 0 00.475-.345L11.48 3.5z" />
                </svg>
              </button>
            </>
          )}
          <button
            onClick={() => setExpanded(!expanded)}
            className="min-h-[36px] min-w-[36px] flex items-center justify-center rounded-md text-gray-400 hover:text-gray-600 hover:bg-gray-100 transition-colors"
            aria-expanded={expanded}
            aria-label={expanded ? 'Collapse' : 'Expand'}
          >
            <svg className={`h-5 w-5 transition-transform ${expanded ? 'rotate-180' : ''}`} fill="none" viewBox="0 0 24 24" stroke="currentColor" aria-hidden="true">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M19 9l-7 7-7-7" />
            </svg>
          </button>
        </div>
      </div>

      {/* Metadata line */}
      {provider.is_active && (
        <div className="flex items-center gap-4 px-5 pb-3 text-xs text-gray-500">
          <span>Credentials: {provider.credentials_set ? '✓ Set' : '✗ Not set'}</span>
          <span>Priority: {provider.priority}</span>
          <span>Updated: {formatDate(provider.updated_at)}</span>
        </div>
      )}

      {/* Expanded section */}
      {expanded && (
        <div className="border-t border-gray-200 px-5 py-4 space-y-4">
          {/* Setup guide */}
          {provider.setup_guide && <SmsSetupGuide guide={provider.setup_guide} />}

          {!provider.is_active && (
            <Button
              onClick={() => onToggleActive(provider.provider_key, true)}
              variant="primary"
              className="w-full sm:w-auto"
            >
              Activate provider
            </Button>
          )}

          {provider.is_active && (
            <>
              <div>
                <h4 className="text-sm font-medium text-gray-700 mb-3">Credentials</h4>
                <div className="grid gap-3 sm:grid-cols-2">
                  {fields.map((f) => {
                    const key = f.label.toLowerCase().replace(/\s+/g, '_')
                    const masked = maskedCreds[key]
                    return (
                      <Input
                        key={key}
                        label={f.label}
                        type={f.type ?? 'text'}
                        placeholder={masked || f.placeholder}
                        value={creds[key] ?? ''}
                        onChange={(e) => setCreds((prev) => ({ ...prev, [key]: e.target.value }))}
                      />
                    )
                  })}
                </div>
                {provider.credentials_set && (
                  <p className="mt-1 text-xs text-gray-500">
                    Only fill in fields you want to change. Blank fields keep their current value.
                  </p>
                )}
                <div className="mt-3">
                  <Button
                    onClick={() => onSaveCredentials(provider.provider_key, creds)}
                    loading={saving}
                    variant="primary"
                    className="w-full sm:w-auto"
                  >
                    Save credentials
                  </Button>
                </div>
              </div>

              {/* Connexus-specific sections */}
              {provider.provider_key === 'connexus' && (
                <ConnexusSection provider={provider} addToast={addToast} />
              )}

              {/* Per-SMS cost config */}
              <SmsCostConfig provider={provider} addToast={addToast} onConfigSaved={onConfigSaved} />

              {/* Token refresh config — Connexus only */}
              {provider.provider_key === 'connexus' && (
                <TokenRefreshConfig provider={provider} addToast={addToast} onConfigSaved={onConfigSaved} />
              )}

              {/* Test SMS */}
              {provider.credentials_set && (
                <div className="border-t border-gray-200 pt-4">
                  <h4 className="text-sm font-medium text-gray-700 mb-3">Test Connection</h4>
                  {provider.provider_key === 'firebase_phone_auth' && (
                    <p className="text-xs text-amber-600 mb-3">
                      Firebase Phone Auth validates credentials only. To send actual SMS messages, configure Connexus.
                    </p>
                  )}
                  <div className="space-y-3">
                    <div className="flex items-end gap-3">
                      <div className="flex-1 max-w-xs">
                        <Input
                          label="Phone number (E.164)"
                          placeholder="+6421234567"
                          value={testNumber}
                          onChange={(e) => setTestNumber(e.target.value)}
                        />
                      </div>
                    </div>
                    {provider.provider_key !== 'firebase_phone_auth' && (
                      <div>
                        <label className="block text-sm font-medium text-gray-700 mb-1">Message</label>
                        <textarea
                          className="w-full rounded-md border border-gray-300 px-3 py-2 text-sm shadow-sm focus:border-indigo-500 focus:ring-1 focus:ring-indigo-500"
                          rows={3}
                          placeholder="Enter test message..."
                          value={testMessage}
                          onChange={(e) => setTestMessage(e.target.value)}
                        />
                      </div>
                    )}
                    <Button
                      onClick={async () => {
                        setTesting(true)
                        try { await onTestProvider(provider.provider_key, testNumber, testMessage) }
                        finally { setTesting(false) }
                      }}
                      loading={testing}
                      variant="secondary"
                      className="w-full sm:w-auto"
                    >
                      {provider.provider_key === 'firebase_phone_auth' ? 'Verify Credentials' : 'Send Test SMS'}
                    </Button>
                  </div>
                </div>
              )}

              {/* Firebase-specific: Set as MFA default + Send test verification code */}
              {provider.provider_key === 'firebase_phone_auth' && provider.is_active && provider.credentials_set && (
                <>
                  <div className="border-t border-gray-200 pt-4">
                    <h4 className="text-sm font-medium text-gray-700 mb-2">MFA / Phone Verification Default</h4>
                    <p className="text-xs text-gray-500 mb-3">
                      Set Firebase as the default provider for delivering MFA and phone verification codes. All verification SMS will be routed through Firebase.
                    </p>
                    {isMfaDefault ? (
                      <div className="flex items-center gap-2">
                        <span className="inline-flex items-center rounded-full bg-green-100 px-3 py-1 text-sm font-medium text-green-700">
                          ✓ Default MFA provider
                        </span>
                      </div>
                    ) : (
                      <Button
                        onClick={async () => {
                          setSettingMfaDefault(true)
                          try {
                            const res = await apiClient.post(`/api/v2/admin/sms-providers/${provider.provider_key}/set-mfa-default`)
                            if (res.data.success) {
                              addToast('success', res.data.message)
                              onConfigSaved()
                            } else {
                              addToast('error', res.data.message || 'Failed to set MFA default')
                            }
                          } catch {
                            addToast('error', 'Failed to set as MFA default provider')
                          } finally {
                            setSettingMfaDefault(false)
                          }
                        }}
                        loading={settingMfaDefault}
                        variant="primary"
                        className="w-full sm:w-auto"
                      >
                        Set as default MFA provider
                      </Button>
                    )}
                  </div>

                  <div className="border-t border-gray-200 pt-4">
                    <h4 className="text-sm font-medium text-gray-700 mb-2">Send Test Verification Code</h4>
                    <p className="text-xs text-gray-500 mb-3">
                      Send a real SMS verification code via Firebase to test end-to-end delivery. Uses invisible reCAPTCHA automatically.
                    </p>
                    <div className="space-y-3">
                      <div className="flex-1 max-w-xs">
                        <Input
                          label="Phone number (E.164)"
                          placeholder="+6421234567"
                          value={testCodeNumber}
                          onChange={(e) => setTestCodeNumber(e.target.value)}
                        />
                      </div>
                      {/* Invisible reCAPTCHA container — Firebase attaches here */}
                      <div id="firebase-recaptcha-container" />
                      <Button
                        onClick={async () => {
                          if (!testCodeNumber.trim()) {
                            addToast('error', 'Please enter a phone number')
                            return
                          }

                          setSendingTestCode(true)
                          try {
                            // 1. Fetch real Firebase config from backend
                            const cfgRes = await apiClient.get(
                              `/api/v2/admin/sms-providers/firebase_phone_auth/firebase-config`
                            )
                            const cfg = cfgRes.data
                            if (!cfg?.apiKey || !cfg?.projectId) {
                              addToast('error', 'Firebase config incomplete — save credentials first')
                              return
                            }

                            // 2. Dynamically import Firebase SDK (tree-shaken, only loaded when needed)
                            const { initializeApp, getApps, deleteApp } = await import('firebase/app')
                            const { getAuth, signInWithPhoneNumber, RecaptchaVerifier } = await import('firebase/auth')

                            // 3. Initialise (or reuse) a Firebase app instance
                            const firebaseConfig = {
                              apiKey: cfg.apiKey,
                              authDomain: cfg.authDomain,
                              projectId: cfg.projectId,
                              appId: cfg.appId,
                            }
                            const existingApps = getApps()
                            const testApp = existingApps.find(a => a.name === '__sms_test__')
                            if (testApp) await deleteApp(testApp)
                            const app = initializeApp(firebaseConfig, '__sms_test__')
                            const auth = getAuth(app)

                            // 4. Create invisible reCAPTCHA verifier
                            const container = document.getElementById('firebase-recaptcha-container')
                            if (container) container.innerHTML = ''
                            const recaptchaVerifier = new RecaptchaVerifier(auth, 'firebase-recaptcha-container', {
                              size: 'invisible',
                            })

                            // 5. Send the verification code — this triggers a real SMS
                            const confirmationResult = await signInWithPhoneNumber(auth, testCodeNumber.trim(), recaptchaVerifier)
                            addToast(
                              'success',
                              `Verification code sent to ${testCodeNumber.trim()}. Confirmation ID: ${confirmationResult.verificationId.slice(0, 12)}…`
                            )
                          } catch (err: unknown) {
                            const firebaseErr = err as { code?: string; message?: string }
                            const code = firebaseErr.code || ''
                            let msg = firebaseErr.message || 'Failed to send verification code'
                            if (code === 'auth/invalid-phone-number') {
                              msg = 'Invalid phone number format. Use E.164 format like +6421234567'
                            } else if (code === 'auth/too-many-requests') {
                              msg = 'Too many requests. Wait a few minutes before trying again.'
                            } else if (code === 'auth/captcha-check-failed') {
                              msg = 'reCAPTCHA verification failed. Refresh the page and try again.'
                            } else if (code === 'auth/quota-exceeded') {
                              msg = 'SMS quota exceeded. Check your Firebase project billing.'
                            }
                            addToast('error', msg)
                          } finally {
                            setSendingTestCode(false)
                          }
                        }}
                        loading={sendingTestCode}
                        variant="secondary"
                        className="w-full sm:w-auto"
                      >
                        Send verification code
                      </Button>
                    </div>
                  </div>
                </>
              )}
            </>
          )}
        </div>
      )}
    </div>
  )
}

export function SmsProviders() {
  const [providers, setProviders] = useState<SmsProvider[]>([])
  const [chain, setChain] = useState<FallbackChainItem[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [saving, setSaving] = useState(false)
  const { toasts, addToast, dismissToast } = useToast()

  const fetchProviders = useCallback(async () => {
    setLoading(true)
    setError(null)
    try {
      const res = await apiClient.get('/api/v2/admin/sms-providers')
      setProviders(res.data.providers)
      setChain(res.data.fallback_chain)
    } catch {
      setError('Failed to load SMS providers')
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => { fetchProviders() }, [fetchProviders])

  async function handleToggleActive(key: string, active: boolean) {
    setSaving(true)
    try {
      await apiClient.patch(`/api/v2/admin/sms-providers/${key}`, { is_active: active })
      addToast('success', `Provider ${active ? 'activated' : 'deactivated'}`)
      await fetchProviders()
    } catch {
      addToast('error', 'Failed to update provider')
    } finally {
      setSaving(false)
    }
  }

  async function handleSetDefault(key: string) {
    setSaving(true)
    try {
      await apiClient.patch(`/api/v2/admin/sms-providers/${key}`, { is_default: true })
      addToast('success', 'Default provider updated')
      await fetchProviders()
    } catch {
      addToast('error', 'Failed to set default')
    } finally {
      setSaving(false)
    }
  }

  async function handleSaveCredentials(key: string, creds: Record<string, string>) {
    const nonEmpty = Object.fromEntries(Object.entries(creds).filter(([, v]) => v.trim()))
    if (Object.keys(nonEmpty).length === 0) {
      addToast('error', 'Please fill in at least one credential field')
      return
    }
    setSaving(true)
    try {
      await apiClient.put(`/api/v2/admin/sms-providers/${key}/credentials`, { credentials: nonEmpty })
      addToast('success', 'Credentials saved')
      await fetchProviders()
    } catch {
      addToast('error', 'Failed to save credentials')
    } finally {
      setSaving(false)
    }
  }

  async function handleTestProvider(key: string, toNumber: string, message: string) {
    if (!toNumber.trim()) {
      addToast('error', 'Please enter a phone number')
      return
    }
    try {
      const res = await apiClient.post(`/api/v2/admin/sms-providers/${key}/test`, {
        to_number: toNumber.trim(),
        message: message.trim() || 'Hello from OraInvoice! This is a test SMS.',
      })
      if (res.data.success) {
        addToast('success', res.data.message)
      } else {
        addToast('error', res.data.message || 'Test failed')
      }
    } catch {
      addToast('error', 'Failed to send test message')
    }
  }

  if (loading) {
    return (
      <div className="flex justify-center py-12">
        <Spinner size="lg" label="Loading SMS providers" />
      </div>
    )
  }

  return (
    <div className="space-y-6">
      <ToastContainer toasts={toasts} onDismiss={dismissToast} />

      {/* Header */}
      <div className="rounded-lg border border-gray-200 bg-white px-5 py-4">
        <div className="flex items-center gap-3">
          <div className="flex h-10 w-10 items-center justify-center rounded-full bg-indigo-100 text-indigo-600">
            <svg className="h-5 w-5" fill="none" viewBox="0 0 24 24" stroke="currentColor" aria-hidden="true">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5} d="M8.625 9.75a.375.375 0 11-.75 0 .375.375 0 01.75 0zm0 0H8.25m4.125 0a.375.375 0 11-.75 0 .375.375 0 01.75 0zm0 0H12m4.125 0a.375.375 0 11-.75 0 .375.375 0 01.75 0zm0 0h-.375m-13.5 3.01c0 1.6 1.123 2.994 2.707 3.227 1.087.16 2.185.283 3.293.369V21l4.184-4.183a1.14 1.14 0 01.778-.332 48.294 48.294 0 005.83-.498c1.585-.233 2.708-1.626 2.708-3.228V6.741c0-1.602-1.123-2.995-2.707-3.228A48.394 48.394 0 0012 3c-2.392 0-4.744.175-7.043.513C3.373 3.746 2.25 5.14 2.25 6.741v6.018z" />
            </svg>
          </div>
          <div>
            <h2 className="text-lg font-semibold text-gray-900">SMS Verification Providers</h2>
            <p className="text-sm text-gray-500">
              Configure SMS providers for phone number verification. Set one as default and enable fallback providers for reliability.
            </p>
          </div>
        </div>
      </div>

      {error && <AlertBanner variant="error">{error}</AlertBanner>}

      {/* Fallback chain */}
      {chain.length > 0 && (
        <div className="rounded-lg border border-gray-200 bg-white px-5 py-4">
          <h3 className="text-sm font-semibold text-gray-900">Fallback Chain Order</h3>
          <p className="mt-1 text-sm text-gray-500">
            When sending SMS, providers are tried in this order. The default provider is tried first, then remaining active providers by priority.
          </p>
          <div className="mt-3 flex flex-wrap gap-2">
            {chain.map((item) => (
              <span
                key={item.provider_key}
                className="inline-flex items-center gap-1.5 rounded-md border border-gray-200 bg-gray-50 px-3 py-1.5 text-sm font-medium text-gray-700"
              >
                {item.display_name}
                <span className="text-xs text-gray-400">P{item.priority}</span>
              </span>
            ))}
          </div>
        </div>
      )}

      {/* Provider cards */}
      <div className="space-y-4">
        {providers.map((p) => (
          <ProviderCard
            key={p.id}
            provider={p}
            onToggleActive={handleToggleActive}
            onSetDefault={handleSetDefault}
            onSaveCredentials={handleSaveCredentials}
            onTestProvider={handleTestProvider}
            saving={saving}
            addToast={addToast}
            onConfigSaved={fetchProviders}
          />
        ))}
      </div>
    </div>
  )
}

export default SmsProviders