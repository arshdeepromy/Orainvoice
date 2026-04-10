import { useState, useEffect, useCallback } from 'react'
import { Button } from '@/components/ui/Button'
import { Spinner } from '@/components/ui/Spinner'
import { AlertBanner } from '@/components/ui/AlertBanner'
import { Input } from '@/components/ui/Input'
import { ToastContainer, useToast } from '@/components/ui/Toast'
import apiClient from '@/api/client'

interface EmailProvider {
  id: string
  provider_key: string
  display_name: string
  description: string | null
  smtp_host: string | null
  smtp_port: number | null
  smtp_encryption: 'none' | 'tls' | 'ssl' | null
  priority: number
  is_active: boolean
  credentials_set: boolean
  config: Record<string, unknown>
  setup_guide: string | null
  created_at: string
  updated_at: string
}

const CREDENTIAL_FIELDS: Record<string, { key: string; label: string; placeholder: string; type?: string; isSelect?: boolean; options?: string[] }[]> = {
  brevo: [
    { key: 'api_key', label: 'SMTP Key / API Key', placeholder: 'xkeysib-...', type: 'password' },
    { key: 'from_email', label: 'From Email', placeholder: 'noreply@yourdomain.com' },
    { key: 'from_name', label: 'From Name', placeholder: 'My App' },
  ],
  sendgrid: [
    { key: 'api_key', label: 'API Key', placeholder: 'SG.xxxxxxxx...', type: 'password' },
    { key: 'from_email', label: 'From Email', placeholder: 'noreply@yourdomain.com' },
    { key: 'from_name', label: 'From Name', placeholder: 'My App' },
  ],
  mailgun: [
    { key: 'username', label: 'SMTP Username', placeholder: 'postmaster@mg.yourdomain.com' },
    { key: 'password', label: 'SMTP Password', placeholder: 'Your Mailgun SMTP password', type: 'password' },
    { key: 'from_email', label: 'From Email', placeholder: 'noreply@yourdomain.com' },
    { key: 'from_name', label: 'From Name', placeholder: 'My App' },
  ],
  ses: [
    { key: 'username', label: 'SMTP Username', placeholder: 'AKIA...' },
    { key: 'password', label: 'SMTP Password', placeholder: 'AWS SMTP password', type: 'password' },
    { key: 'smtp_host', label: 'SMTP Host', placeholder: 'email-smtp.us-east-1.amazonaws.com' },
    { key: 'from_email', label: 'From Email', placeholder: 'noreply@yourdomain.com' },
    { key: 'from_name', label: 'From Name', placeholder: 'My App' },
  ],
  gmail: [
    { key: 'username', label: 'Gmail Address', placeholder: 'you@gmail.com' },
    { key: 'password', label: 'App Password', placeholder: '16-character app password', type: 'password' },
    { key: 'from_name', label: 'From Name', placeholder: 'My App' },
  ],
  outlook: [
    { key: 'username', label: 'Email Address', placeholder: 'you@yourdomain.com' },
    { key: 'password', label: 'Password / App Password', placeholder: 'Your password', type: 'password' },
    { key: 'from_name', label: 'From Name', placeholder: 'My App' },
  ],
  custom_smtp: [
    { key: 'smtp_host', label: 'SMTP Host', placeholder: 'mail.yourdomain.com' },
    { key: 'smtp_port', label: 'SMTP Port', placeholder: '587' },
    { key: 'smtp_encryption', label: 'Encryption', placeholder: 'tls', isSelect: true, options: ['none', 'tls', 'ssl'] },
    { key: 'username', label: 'Username', placeholder: 'smtp-user' },
    { key: 'password', label: 'Password', placeholder: 'Your SMTP password', type: 'password' },
    { key: 'from_email', label: 'From Email', placeholder: 'noreply@yourdomain.com' },
    { key: 'from_name', label: 'From Name', placeholder: 'My App' },
    { key: 'reply_to', label: 'Reply-To (optional)', placeholder: 'support@yourdomain.com' },
  ],
}

function SetupGuide({ guide }: { guide: string }) {
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

function ProviderCard({
  provider,
  onActivate,
  onDeactivate,
  onSaveCredentials,
  onTest,
  onUpdatePriority,
  saving,
  testing,
}: {
  provider: EmailProvider
  onActivate: (key: string) => void
  onDeactivate: (key: string) => void
  onSaveCredentials: (key: string, data: Record<string, string>) => void
  onTest: (key: string, toEmail: string) => void
  onUpdatePriority: (key: string, priority: number) => void
  saving: boolean
  testing: boolean
}) {
  const [expanded, setExpanded] = useState(false)
  const [fields, setFields] = useState<Record<string, string>>({})
  const [testEmail, setTestEmail] = useState('')
  const credFields = CREDENTIAL_FIELDS[provider.provider_key] ?? CREDENTIAL_FIELDS.custom_smtp

  return (
    <div className={`rounded-lg border transition-colors ${
      provider.is_active ? 'border-green-300 bg-green-50/40' : 'border-gray-200 bg-white'
    }`}>
      <div className="flex items-center gap-4 px-5 py-4">
        {/* Icon */}
        <div className={`flex h-10 w-10 shrink-0 items-center justify-center rounded-full ${
          provider.is_active ? 'bg-green-100 text-green-600' : 'bg-gray-100 text-gray-400'
        }`}>
          <svg className="h-5 w-5" fill="none" viewBox="0 0 24 24" stroke="currentColor" aria-hidden="true">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5} d="M21.75 6.75v10.5a2.25 2.25 0 01-2.25 2.25h-15a2.25 2.25 0 01-2.25-2.25V6.75m19.5 0A2.25 2.25 0 0019.5 4.5h-15a2.25 2.25 0 00-2.25 2.25m19.5 0v.243a2.25 2.25 0 01-1.07 1.916l-7.5 4.615a2.25 2.25 0 01-2.36 0L3.32 8.91a2.25 2.25 0 01-1.07-1.916V6.75" />
          </svg>
        </div>

        {/* Name + description */}
        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-2">
            <span className="font-medium text-gray-900">{provider.display_name}</span>
            {provider.is_active && (
              <span className="inline-flex items-center gap-1 rounded-full bg-green-100 px-2 py-0.5 text-xs font-medium text-green-700">
                <svg className="h-3 w-3" fill="currentColor" viewBox="0 0 24 24" aria-hidden="true">
                  <path d="M11.48 3.499a.562.562 0 011.04 0l2.125 5.111a.563.563 0 00.475.345l5.518.442c.499.04.701.663.321.988l-4.204 3.602a.563.563 0 00-.182.557l1.285 5.385a.562.562 0 01-.84.61l-4.725-2.885a.563.563 0 00-.586 0L6.982 20.54a.562.562 0 01-.84-.61l1.285-5.386a.562.562 0 00-.182-.557l-4.204-3.602a.563.563 0 01.321-.988l5.518-.442a.563.563 0 00.475-.345L11.48 3.5z" />
                </svg>
                Active
              </span>
            )}
          </div>
          <p className="text-sm text-gray-500">{provider.smtp_host ?? provider.description}</p>
        </div>

        {/* Actions */}
        <div className="flex items-center gap-2">
          {!provider.is_active && (
            <Button
              onClick={() => onActivate(provider.provider_key)}
              variant="secondary"
              loading={saving}
              className="text-sm"
            >
              Set as Active
            </Button>
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

      {/* Expanded config section */}
      {expanded && (
        <div className="border-t border-gray-200 px-5 py-4 space-y-4">
          {/* Setup guide */}
          {provider.setup_guide && <SetupGuide guide={provider.setup_guide} />}

          {/* Status info */}
          <div className="flex flex-wrap gap-4 text-xs text-gray-500">
            <span>Credentials: {provider.credentials_set ? '✓ Set' : '✗ Not set'}</span>
            {provider.smtp_host && <span>Host: {provider.smtp_host}:{provider.smtp_port}</span>}
            {provider.smtp_encryption && <span>Encryption: {provider.smtp_encryption.toUpperCase()}</span>}
            {!!provider.config?.from_email && <span>From: {String(provider.config.from_email)}</span>}
            {provider.is_active && <span>Priority: {provider.priority || 1}</span>}
          </div>

          {/* Credential form */}
          <div>
            <h4 className="text-sm font-medium text-gray-700 mb-3">Configuration</h4>
            <div className="grid gap-3 sm:grid-cols-2">
              {credFields.map((f) => (
                f.isSelect ? (
                  <div key={f.key} className="flex flex-col gap-1">
                    <label className="text-sm font-medium text-gray-700">{f.label}</label>
                    <select
                      value={fields[f.key] ?? provider.smtp_encryption ?? 'tls'}
                      onChange={(e) => setFields((prev) => ({ ...prev, [f.key]: e.target.value }))}
                      className="h-[42px] w-full appearance-none rounded-md border border-gray-300 bg-white px-3 py-2 text-gray-900 shadow-sm transition-colors bg-[url('data:image/svg+xml;charset=utf-8,%3Csvg%20xmlns%3D%22http%3A%2F%2Fwww.w3.org%2F2000%2Fsvg%22%20fill%3D%22none%22%20viewBox%3D%220%200%2024%2024%22%20stroke%3D%22%236b7280%22%3E%3Cpath%20stroke-linecap%3D%22round%22%20stroke-linejoin%3D%22round%22%20stroke-width%3D%222%22%20d%3D%22M19%209l-7%207-7-7%22%2F%3E%3C%2Fsvg%3E')] bg-[length:20px_20px] bg-[right_8px_center] bg-no-repeat pr-10 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-blue-500 focus-visible:ring-offset-2 focus-visible:border-blue-500"
                    >
                      {f.options?.map((opt) => (
                        <option key={opt} value={opt}>{opt === 'none' ? 'None' : opt.toUpperCase()}</option>
                      ))}
                    </select>
                  </div>
                ) : (
                  <Input
                    key={f.key}
                    label={f.label}
                    type={f.type ?? 'text'}
                    placeholder={f.placeholder}
                    value={fields[f.key] ?? ''}
                    onChange={(e) => setFields((prev) => ({ ...prev, [f.key]: e.target.value }))}
                  />
                )
              ))}
            </div>
            
            {/* Priority setting for active providers */}
            {provider.is_active && (
              <div className="mt-4 p-3 bg-gray-50 rounded-lg">
                <label className="block text-sm font-medium text-gray-700 mb-2">
                  Priority (lower = higher priority, used when multiple providers are active)
                </label>
                <div className="flex items-center gap-3">
                  <input
                    type="number"
                    min="1"
                    max="10"
                    value={provider.priority || 1}
                    onChange={(e) => onUpdatePriority(provider.provider_key, parseInt(e.target.value, 10) || 1)}
                    className="h-[42px] w-20 rounded-md border border-gray-300 bg-white px-3 py-2 text-gray-900 shadow-sm transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-blue-500 focus-visible:ring-offset-2 focus-visible:border-blue-500"
                  />
                  <span className="text-xs text-gray-500">1 = Primary, 2 = Fallback, etc.</span>
                </div>
              </div>
            )}
            
            {/* Test email section */}
            {provider.credentials_set && (
              <div className="mt-4 p-3 bg-blue-50 rounded-lg border border-blue-200">
                <label className="block text-sm font-medium text-gray-700 mb-2">
                  Send Test Email
                </label>
                <div className="flex items-end gap-3">
                  <div className="flex-1">
                    <Input
                      label=""
                      type="email"
                      placeholder="Enter email address to send test"
                      value={testEmail}
                      onChange={(e) => setTestEmail(e.target.value)}
                    />
                  </div>
                  <Button
                    onClick={() => onTest(provider.provider_key, testEmail)}
                    loading={testing}
                    variant="secondary"
                    disabled={!testEmail.trim()}
                  >
                    Send Test
                  </Button>
                </div>
              </div>
            )}
            
            <div className="mt-4 flex flex-wrap gap-2">
              <Button
                onClick={() => onSaveCredentials(provider.provider_key, fields)}
                loading={saving}
                variant="primary"
              >
                Save configuration
              </Button>
              {provider.is_active && (
                <Button
                  onClick={() => onDeactivate(provider.provider_key)}
                  variant="secondary"
                  loading={saving}
                  className="text-red-600 hover:text-red-700"
                >
                  Deactivate
                </Button>
              )}
            </div>
          </div>
        </div>
      )}
    </div>
  )
}

export function EmailProviders() {
  const [providers, setProviders] = useState<EmailProvider[]>([])
  const [activeProvider, setActiveProvider] = useState<string | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [saving, setSaving] = useState(false)
  const [testing, setTesting] = useState(false)
  const { toasts, addToast, dismissToast } = useToast()

  const fetchProviders = useCallback(async () => {
    setLoading(true)
    setError(null)
    try {
      const res = await apiClient.get('/api/v2/admin/email-providers')
      setProviders(res.data.providers)
      setActiveProvider(res.data.active_provider)
    } catch {
      setError('Failed to load email providers')
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => { fetchProviders() }, [fetchProviders])

  async function handleActivate(key: string) {
    setSaving(true)
    try {
      await apiClient.post(`/api/v2/admin/email-providers/${key}/activate`)
      addToast('success', 'Email provider activated')
      await fetchProviders()
    } catch {
      addToast('error', 'Failed to activate provider')
    } finally {
      setSaving(false)
    }
  }

  async function handleDeactivate(key: string) {
    setSaving(true)
    try {
      await apiClient.post(`/api/v2/admin/email-providers/${key}/deactivate`)
      addToast('success', 'Provider deactivated')
      await fetchProviders()
    } catch {
      addToast('error', 'Failed to deactivate provider')
    } finally {
      setSaving(false)
    }
  }

  async function handleSaveCredentials(key: string, data: Record<string, string>) {
    const nonEmpty = Object.fromEntries(Object.entries(data).filter(([, v]) => v.trim()))
    if (Object.keys(nonEmpty).length === 0) {
      addToast('error', 'Please fill in at least one field')
      return
    }
    setSaving(true)
    try {
      const { smtp_host, smtp_port, smtp_encryption, from_email, from_name, reply_to, ...credentials } = nonEmpty
      await apiClient.put(`/api/v2/admin/email-providers/${key}/credentials`, {
        credentials,
        smtp_host: smtp_host || undefined,
        smtp_port: smtp_port ? parseInt(smtp_port, 10) : undefined,
        smtp_encryption: smtp_encryption || undefined,
        from_email: from_email || undefined,
        from_name: from_name || undefined,
        reply_to: reply_to || undefined,
      })
      addToast('success', 'Configuration saved')
      await fetchProviders()
    } catch {
      addToast('error', 'Failed to save configuration')
    } finally {
      setSaving(false)
    }
  }

  async function handleTest(key: string, toEmail: string) {
    if (!toEmail.trim()) {
      addToast('error', 'Please enter an email address')
      return
    }
    setTesting(true)
    try {
      const res = await apiClient.post(`/api/v2/admin/email-providers/${key}/test`, { to_email: toEmail })
      if (res.data?.success) {
        addToast('success', `Test email sent to ${toEmail}! Check your inbox.`)
      } else {
        addToast('error', res.data?.error || 'Test email failed')
      }
    } catch (err: unknown) {
      const message = (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail || 'Failed to send test email'
      addToast('error', message)
    } finally {
      setTesting(false)
    }
  }

  async function handleUpdatePriority(key: string, priority: number) {
    try {
      await apiClient.put(`/api/v2/admin/email-providers/${key}/priority`, { priority })
      addToast('success', 'Priority updated')
      await fetchProviders()
    } catch {
      addToast('error', 'Failed to update priority')
    }
  }

  if (loading) {
    return (
      <div className="flex justify-center py-12">
        <Spinner size="lg" label="Loading email providers" />
      </div>
    )
  }

  const activeP = providers.find((p) => p.provider_key === activeProvider)

  return (
    <div className="space-y-6">
      <ToastContainer toasts={toasts} onDismiss={dismissToast} />

      {/* Active provider banner */}
      {activeP && (
        <div className="flex items-center gap-3 rounded-lg border border-green-200 bg-green-50 px-5 py-3">
          <svg className="h-6 w-6 text-green-600 shrink-0" fill="none" viewBox="0 0 24 24" stroke="currentColor" aria-hidden="true">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 12.75L11.25 15 15 9.75M21 12a9 9 0 11-18 0 9 9 0 0118 0z" />
          </svg>
          <span className="text-sm text-gray-700">
            <span className="font-semibold">Active Provider:</span>{' '}
            <span className="font-medium text-green-700">{activeP.display_name}</span>
          </span>
        </div>
      )}

      {error && <AlertBanner variant="error">{error}</AlertBanner>}

      {/* Provider cards — active first (sorted by priority), then rest sorted by name */}
      <div className="space-y-3">
        {[...providers]
          .sort((a, b) => {
            if (a.is_active && !b.is_active) return -1
            if (!a.is_active && b.is_active) return 1
            if (a.is_active && b.is_active) return (a.priority || 1) - (b.priority || 1)
            return a.display_name.localeCompare(b.display_name)
          })
          .map((p) => (
            <ProviderCard
              key={p.id}
              provider={p}
              onActivate={handleActivate}
              onDeactivate={handleDeactivate}
              onSaveCredentials={handleSaveCredentials}
              onTest={handleTest}
              onUpdatePriority={handleUpdatePriority}
              saving={saving}
              testing={testing}
            />
          ))}
      </div>
    </div>
  )
}

export default EmailProviders
