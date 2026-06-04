import { useState, useEffect } from 'react'
import Button from '@/components/ui/Button'
import { Input } from '@/components/ui/Input'
import { Spinner } from '@/components/ui/Spinner'
import { AlertBanner } from '@/components/ui/AlertBanner'
import { ToastContainer, useToast } from '@/components/ui/Toast'
import apiClient from '@/api/client'

/* ── Types ── */

interface XeroCredentials {
  client_id_masked: string | null
  client_secret_masked: string | null
  webhook_key_masked: string | null
}

interface FieldState {
  value: string
  isMasked: boolean
}

const MASKED_PLACEHOLDER = '••••••••'

/* ── Setup Guide ── */

function CopyButton({ text }: { text: string }) {
  const [copied, setCopied] = useState(false)
  const handleCopy = () => {
    navigator.clipboard.writeText(text).then(() => {
      setCopied(true)
      setTimeout(() => setCopied(false), 2000)
    })
  }
  return (
    <button
      type="button"
      onClick={handleCopy}
      className="ml-2 inline-flex items-center gap-1 rounded border border-border bg-card px-2 py-0.5 text-xs text-muted hover:bg-canvas"
      title="Copy to clipboard"
    >
      {copied ? '✓ Copied' : 'Copy'}
    </button>
  )
}

function XeroSetupGuide({
  hasClientId,
  hasClientSecret,
  hasWebhookKey,
}: {
  hasClientId: boolean
  hasClientSecret: boolean
  hasWebhookKey: boolean
}) {
  const [dismissed, setDismissed] = useState(() => {
    try { return localStorage.getItem('xero-setup-guide-dismissed') === 'true' } catch { return false }
  })

  if (dismissed && hasClientId && hasClientSecret) return null

  const origin = typeof window !== 'undefined' ? window.location.origin : 'https://yourdomain.com'
  const redirectUri = `${origin}/api/v1/org/accounting/callback/xero`
  const webhookUri = `${origin}/api/webhooks/xero`

  const steps = [
    {
      number: 1,
      title: 'Create a Xero app',
      done: false,
      content: (
        <div className="space-y-2 text-sm text-muted">
          <p>Go to the Xero Developer Portal and create a new app:</p>
          <a
            href="https://developer.xero.com/app/manage"
            target="_blank"
            rel="noopener noreferrer"
            className="inline-flex items-center gap-1 text-accent hover:text-accent-press underline"
          >
            Open Xero Developer Portal
            <svg className="h-3.5 w-3.5" fill="none" viewBox="0 0 24 24" stroke="currentColor" aria-hidden="true">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M10 6H6a2 2 0 00-2 2v10a2 2 0 002 2h10a2 2 0 002-2v-4M14 4h6m0 0v6m0-6L10 14" />
            </svg>
          </a>
          <p>Use these settings when creating the app:</p>
          <ul className="list-disc list-inside space-y-1 ml-2">
            <li>App name: <span className="font-medium">OraInvoice</span> (or your brand name)</li>
            <li>Integration type: <span className="font-medium">Web app</span></li>
            <li>AI model usage: <span className="font-medium">No</span></li>
            <li>Security requirements: <span className="font-medium">Yes</span></li>
          </ul>
        </div>
      ),
    },
    {
      number: 2,
      title: 'Set the Company URL',
      done: false,
      content: (
        <div className="space-y-2 text-sm text-muted">
          <p>In the Xero app form, enter your application URL:</p>
          <div className="flex items-center rounded-ctl border border-border bg-canvas px-3 py-2 mono text-xs">
            <span className="flex-1 select-all">{origin}</span>
            <CopyButton text={origin} />
          </div>
          <p className="text-xs text-warn">Make sure it starts with <code>https://</code> (not <code>htttps://</code> or <code>http://</code>)</p>
        </div>
      ),
    },
    {
      number: 3,
      title: 'Set the OAuth 2.0 Redirect URI',
      done: false,
      content: (
        <div className="space-y-2 text-sm text-muted">
          <p>In the same form, paste this exact redirect URI:</p>
          <div className="flex items-center rounded-ctl border border-border bg-canvas px-3 py-2 mono text-xs">
            <span className="flex-1 select-all break-all">{redirectUri}</span>
            <CopyButton text={redirectUri} />
          </div>
          <p className="text-xs text-muted">This is where Xero sends users back after they authorize the connection.</p>
        </div>
      ),
    },
    {
      number: 4,
      title: 'Copy the Client ID and Client Secret',
      done: hasClientId && hasClientSecret,
      content: (
        <div className="space-y-2 text-sm text-muted">
          <p>After creating the app, Xero will show you a Client ID and generate a Client Secret.</p>
          <p>Copy both values and paste them into the fields below, then click <span className="font-medium">Save credentials</span>.</p>
          {hasClientId && hasClientSecret && (
            <p className="text-ok font-medium">✓ Client ID and Secret are saved</p>
          )}
        </div>
      ),
    },
    {
      number: 5,
      title: 'Set up webhooks (optional)',
      done: hasWebhookKey,
      content: (
        <div className="space-y-2 text-sm text-muted">
          <p>To receive real-time updates from Xero (when invoices or contacts change externally), set up a webhook:</p>
          <ol className="list-decimal list-inside space-y-1 ml-2">
            <li>In your Xero app settings, go to <span className="font-medium">Webhooks</span></li>
            <li>Add a new webhook with this delivery URL:</li>
          </ol>
          <div className="flex items-center rounded-ctl border border-border bg-canvas px-3 py-2 mono text-xs">
            <span className="flex-1 select-all break-all">{webhookUri}</span>
            <CopyButton text={webhookUri} />
          </div>
          <ol className="list-decimal list-inside space-y-1 ml-2" start={3}>
            <li>Xero will generate a Webhook Key — copy it and paste it into the Webhook Key field below</li>
          </ol>
          {hasWebhookKey && (
            <p className="text-ok font-medium">✓ Webhook Key is saved</p>
          )}
        </div>
      ),
    },
  ]

  return (
    <div className="rounded-card border border-border bg-card p-5 space-y-4 shadow-card">
      <div className="flex items-center justify-between">
        <h3 className="text-md font-semibold text-text">Setup Guide</h3>
        {hasClientId && hasClientSecret && (
          <button
            type="button"
            onClick={() => {
              setDismissed(true)
              try { localStorage.setItem('xero-setup-guide-dismissed', 'true') } catch {}
            }}
            className="text-xs text-muted-2 hover:text-muted"
          >
            Dismiss
          </button>
        )}
      </div>

      <div className="space-y-4">
        {steps.map((step) => (
          <div key={step.number} className="flex gap-3">
            <div className={`flex-shrink-0 flex items-center justify-center w-6 h-6 rounded-full text-xs font-medium ${
              step.done
                ? 'bg-ok-soft text-ok'
                : 'bg-canvas text-muted'
            }`}>
              {step.done ? '✓' : step.number}
            </div>
            <div className="flex-1 min-w-0">
              <p className={`text-sm font-medium ${step.done ? 'text-ok' : 'text-text'}`}>
                {step.title}
              </p>
              <div className="mt-1">{step.content}</div>
            </div>
          </div>
        ))}
      </div>
    </div>
  )
}

/* ── Component ── */

export function XeroCredentialsSettings() {
  const [loading, setLoading] = useState(true)
  const [saving, setSaving] = useState(false)
  const [testing, setTesting] = useState(false)
  const [testResult, setTestResult] = useState<{ success: boolean; message: string } | null>(null)
  const [error, setError] = useState(false)
  const { toasts, addToast, dismissToast } = useToast()

  const [clientId, setClientId] = useState<FieldState>({ value: '', isMasked: false })
  const [clientSecret, setClientSecret] = useState<FieldState>({ value: '', isMasked: false })
  const [webhookKey, setWebhookKey] = useState<FieldState>({ value: '', isMasked: false })

  useEffect(() => {
    const controller = new AbortController()
    const fetchCredentials = async () => {
      setLoading(true)
      setError(false)
      try {
        const res = await apiClient.get<XeroCredentials>(
          '/admin/platform-settings/xero',
          { signal: controller.signal },
        )
        const data = res.data
        setClientId({
          value: data?.client_id_masked ?? '',
          isMasked: !!data?.client_id_masked,
        })
        setClientSecret({
          value: data?.client_secret_masked ?? '',
          isMasked: !!data?.client_secret_masked,
        })
        setWebhookKey({
          value: data?.webhook_key_masked ?? '',
          isMasked: !!data?.webhook_key_masked,
        })
      } catch (err) {
        if (!controller.signal.aborted) setError(true)
      } finally {
        setLoading(false)
      }
    }
    fetchCredentials()
    return () => controller.abort()
  }, [])

  const handleSave = async (e: React.FormEvent) => {
    e.preventDefault()
    setSaving(true)
    try {
      const payload: Record<string, string> = {}
      if (!clientId.isMasked && clientId.value) payload.client_id = clientId.value
      if (!clientSecret.isMasked && clientSecret.value) payload.client_secret = clientSecret.value
      if (!webhookKey.isMasked && webhookKey.value) payload.webhook_key = webhookKey.value

      if (Object.keys(payload).length === 0) {
        addToast('error', 'No changes to save')
        setSaving(false)
        return
      }

      await apiClient.post('/admin/platform-settings/xero', payload)
      addToast('success', 'Xero credentials saved')

      // Refresh masked values
      const res = await apiClient.get<XeroCredentials>('/admin/platform-settings/xero')
      const data = res.data
      setClientId({ value: data?.client_id_masked ?? '', isMasked: !!data?.client_id_masked })
      setClientSecret({ value: data?.client_secret_masked ?? '', isMasked: !!data?.client_secret_masked })
      setWebhookKey({ value: data?.webhook_key_masked ?? '', isMasked: !!data?.webhook_key_masked })
    } catch {
      addToast('error', 'Failed to save Xero credentials')
    } finally {
      setSaving(false)
    }
  }

  const handleClear = (
    setter: React.Dispatch<React.SetStateAction<FieldState>>,
  ) => {
    setter({ value: '', isMasked: false })
  }

  if (loading) {
    return (
      <div className="flex items-center justify-center py-12">
        <Spinner label="Loading Xero credentials" />
      </div>
    )
  }

  if (error) {
    return (
      <AlertBanner variant="error" title="Failed to load">
        Could not load Xero credentials. Please try again.
      </AlertBanner>
    )
  }

  const renderField = (
    label: string,
    state: FieldState,
    setter: React.Dispatch<React.SetStateAction<FieldState>>,
  ) => {
    if (state.isMasked) {
      return (
        <div className="flex flex-col gap-1">
          <label className="text-sm font-medium text-text">{label}</label>
          <div className="flex items-center gap-2">
            <span className="rounded-ctl border border-border bg-canvas px-3 py-2 text-muted flex-1 mono">
              {state.value || MASKED_PLACEHOLDER}
            </span>
            <Button type="button" variant="ghost" size="sm" onClick={() => handleClear(setter)}>
              Change
            </Button>
          </div>
          <p className="text-sm text-muted">Credential is set. Click Change to update.</p>
        </div>
      )
    }

    return (
      <Input
        label={label}
        type="password"
        value={state.value}
        onChange={(e) => setter({ value: e.target.value, isMasked: false })}
        placeholder={MASKED_PLACEHOLDER}
      />
    )
  }

  return (
    <div className="max-w-lg space-y-5">
      <ToastContainer toasts={toasts} onDismiss={dismissToast} />

      <div className="rounded-card border-l-4 border-accent bg-accent-soft p-4 mb-4">
        <h2 className="text-lg font-semibold text-accent">Xero API Credentials</h2>
        <p className="text-sm text-accent mt-1">
          Platform-wide Xero OAuth credentials used for all organisation connections.
          These are stored encrypted and override environment variable defaults.
        </p>
      </div>

      {/* Setup Guide */}
      <XeroSetupGuide
        hasClientId={clientId.isMasked}
        hasClientSecret={clientSecret.isMasked}
        hasWebhookKey={webhookKey.isMasked}
      />

      <form onSubmit={handleSave} className="space-y-5">
        {renderField('Client ID', clientId, setClientId)}
        {renderField('Client Secret', clientSecret, setClientSecret)}
        {renderField('Webhook Key', webhookKey, setWebhookKey)}

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
            Save credentials
          </Button>
          <Button
            type="button"
            variant="ghost"
            loading={testing}
            onClick={async () => {
              setTesting(true)
              setTestResult(null)
              try {
                const res = await apiClient.post<{ success: boolean; message: string }>(
                  '/admin/platform-settings/xero/test',
                )
                setTestResult(res.data ?? { success: false, message: 'No response' })
                if (res.data?.success) {
                  addToast('success', 'Xero credentials verified')
                } else {
                  addToast('error', res.data?.message ?? 'Test failed')
                }
              } catch {
                setTestResult({ success: false, message: 'Connection test failed — check credentials' })
                addToast('error', 'Xero connection test failed')
              } finally {
                setTesting(false)
              }
            }}
          >
            Test connection
          </Button>
        </div>
      </form>
    </div>
  )
}
