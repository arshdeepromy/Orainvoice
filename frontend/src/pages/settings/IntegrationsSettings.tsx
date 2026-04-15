/**
 * IntegrationsSettings — Unified integration cards for Xero, MYOB, Akahu, IRD.
 *
 * Sprint 7: Req 31.1-31.6, 34.1-34.4
 */
import { useState, useEffect } from 'react'
import { Navigate } from 'react-router-dom'
import { Button } from '@/components/ui/Button'
import { Badge } from '@/components/ui/Badge'
import { Spinner } from '@/components/ui/Spinner'
import { Modal } from '@/components/ui/Modal'
import { ToastContainer, useToast } from '@/components/ui/Toast'
import { useModules } from '@/contexts/ModuleContext'
import apiClient from '@/api/client'

interface IntegrationProvider {
  provider: string
  label: string
  description: string
  connected: boolean
  account_name: string | null
  connected_at: string | null
  last_sync_at: string | null
}

interface TestResult {
  success: boolean
  provider: string
  account_name?: string
  error?: string
  tested_at: string
}

const PROVIDERS: { provider: string; label: string; description: string }[] = [
  { provider: 'xero', label: 'Xero', description: 'Sync invoices, payments, and credit notes with Xero.' },
  { provider: 'myob', label: 'MYOB', description: 'Sync invoices and payments with MYOB AccountRight.' },
  { provider: 'akahu', label: 'Akahu', description: 'Connect NZ bank accounts for automatic transaction import.' },
  { provider: 'ird', label: 'IRD Gateway', description: 'File GST and income tax returns directly to IRD.' },
]

function formatDate(iso: string | null): string {
  if (!iso) return 'Never'
  try {
    return new Date(iso).toLocaleString()
  } catch {
    return iso
  }
}

function IntegrationCard({
  provider: _provider,
  label,
  description,
  connected,
  accountName,
  connectedAt,
  lastSyncAt,
  onConnect,
  onDisconnect,
  onTest,
  testing,
  testResult,
  connecting,
}: {
  provider: string
  label: string
  description: string
  connected: boolean
  accountName: string | null
  connectedAt: string | null
  lastSyncAt: string | null
  onConnect: () => void
  onDisconnect: () => void
  onTest: () => void
  testing: boolean
  testResult: TestResult | null
  connecting: boolean
}) {
  const [showDisconnectModal, setShowDisconnectModal] = useState(false)

  return (
    <div className="rounded-lg border border-gray-200 p-5">
      <div className="flex items-center justify-between mb-3">
        <h3 className="text-lg font-semibold text-gray-900">{label}</h3>
        <Badge variant={connected ? 'success' : 'neutral'}>
          {connected ? 'Connected' : 'Not connected'}
        </Badge>
      </div>

      {connected ? (
        <>
          {accountName && (
            <p className="text-sm text-gray-600 mb-1">
              Account: <span className="font-medium text-gray-900">{accountName}</span>
            </p>
          )}
          <p className="text-sm text-gray-600 mb-1">
            Connected: {formatDate(connectedAt)}
          </p>
          <p className="text-sm text-gray-600 mb-3">
            Last sync: {formatDate(lastSyncAt)}
          </p>

          {/* Test result */}
          {testResult && (
            <div className={`text-sm mb-3 p-2 rounded ${
              testResult.success
                ? 'bg-green-50 text-green-700'
                : 'bg-red-50 text-red-700'
            }`}>
              {testResult.success
                ? `Connection OK - tested ${formatDate(testResult.tested_at)}`
                : `Connection failed: ${testResult.error ?? 'Unknown error'}`
              }
            </div>
          )}

          <div className="flex gap-2">
            <Button
              size="sm"
              variant="secondary"
              onClick={onTest}
              loading={testing}
            >
              Test Connection
            </Button>
            <Button
              size="sm"
              variant="danger"
              onClick={() => setShowDisconnectModal(true)}
            >
              Disconnect
            </Button>
          </div>

          {showDisconnectModal && (
            <Modal
              open={showDisconnectModal}
              title={`Disconnect ${label}?`}
              onClose={() => setShowDisconnectModal(false)}
            >
              <p className="text-sm text-gray-600 mb-4">
                This will delete all stored tokens and disconnect {label}. You will need to reconnect to resume syncing.
              </p>
              <div className="flex gap-2 justify-end">
                <Button variant="secondary" onClick={() => setShowDisconnectModal(false)}>
                  Cancel
                </Button>
                <Button
                  variant="danger"
                  onClick={() => {
                    setShowDisconnectModal(false)
                    onDisconnect()
                  }}
                >
                  Disconnect
                </Button>
              </div>
            </Modal>
          )}
        </>
      ) : (
        <>
          <p className="text-sm text-gray-600 mb-3">{description}</p>
          <Button onClick={onConnect} loading={connecting}>
            Connect {label}
          </Button>
        </>
      )}
    </div>
  )
}

export default function IntegrationsSettings() {
  const { isEnabled } = useModules()
  const { toasts, addToast, dismissToast } = useToast()
  const [loading, setLoading] = useState(true)
  const [providers, setProviders] = useState<IntegrationProvider[]>([])
  const [testing, setTesting] = useState<string | null>(null)
  const [testResults, setTestResults] = useState<Record<string, TestResult>>({})
  const [connecting, setConnecting] = useState<string | null>(null)

  if (!isEnabled('accounting')) return <Navigate to="/dashboard" replace />

  useEffect(() => {
    const controller = new AbortController()
    const fetchData = async () => {
      try {
        const res = await apiClient.get('/org/accounting/connections', { signal: controller.signal })
        const connections = res.data?.items ?? []

        // Map connections to provider list
        const providerData = PROVIDERS.map((p) => {
          const conn = connections.find((c: { provider: string }) => c.provider === p.provider)
          return {
            provider: p.provider,
            label: p.label,
            description: p.description,
            connected: conn?.connected ?? false,
            account_name: conn?.account_name ?? null,
            connected_at: conn?.connected_at ?? null,
            last_sync_at: conn?.last_sync_at ?? null,
          }
        })
        setProviders(providerData)
      } catch {
        if (!controller.signal.aborted) {
          // If connections endpoint fails, show all as disconnected
          setProviders(PROVIDERS.map((p) => ({
            ...p,
            connected: false,
            account_name: null,
            connected_at: null,
            last_sync_at: null,
          })))
        }
      } finally {
        setLoading(false)
      }
    }
    fetchData()
    return () => controller.abort()
  }, []) // eslint-disable-line react-hooks/exhaustive-deps

  const handleConnect = async (provider: string) => {
    setConnecting(provider)
    try {
      const res = await apiClient.post(`/org/accounting/connect/${provider}`)
      const redirectUrl = res.data?.redirect_url
      if (redirectUrl) {
        window.location.href = redirectUrl
      } else {
        addToast('success', `${provider} connected`)
      }
    } catch {
      addToast('error', `Failed to connect ${provider}`)
    } finally {
      setConnecting(null)
    }
  }

  const handleDisconnect = async (provider: string) => {
    try {
      await apiClient.post(`/org/accounting/disconnect/${provider}`)
      setProviders((prev) =>
        prev.map((p) =>
          p.provider === provider
            ? { ...p, connected: false, account_name: null, connected_at: null, last_sync_at: null }
            : p
        )
      )
      addToast('success', `${provider} disconnected`)
    } catch {
      addToast('error', `Failed to disconnect ${provider}`)
    }
  }

  const handleTest = async (provider: string) => {
    setTesting(provider)
    try {
      const res = await apiClient.get<TestResult>(`/integrations/${provider}/test`)
      const result: TestResult = {
        success: res.data?.success ?? false,
        provider: res.data?.provider ?? provider,
        account_name: res.data?.account_name,
        error: res.data?.error,
        tested_at: res.data?.tested_at ?? new Date().toISOString(),
      }
      setTestResults((prev) => ({ ...prev, [provider]: result }))
      if (result.success) {
        addToast('success', `${provider} connection test passed`)
      } else {
        addToast('error', result.error ?? `${provider} connection test failed`)
      }
    } catch {
      addToast('error', `Failed to test ${provider} connection`)
    } finally {
      setTesting(null)
    }
  }

  if (loading) return <Spinner />

  return (
    <div className="space-y-6 max-w-3xl">
      <ToastContainer toasts={toasts} onDismiss={dismissToast} />
      <h2 className="text-lg font-semibold text-gray-900">Integrations</h2>
      <p className="text-sm text-gray-600">
        Manage your connected accounting, banking, and tax filing integrations.
      </p>

      <div className="grid gap-4 md:grid-cols-2">
        {providers.map((p) => (
          <IntegrationCard
            key={p.provider}
            provider={p.provider}
            label={p.label}
            description={p.description}
            connected={p.connected}
            accountName={p.account_name}
            connectedAt={p.connected_at}
            lastSyncAt={p.last_sync_at}
            onConnect={() => handleConnect(p.provider)}
            onDisconnect={() => handleDisconnect(p.provider)}
            onTest={() => handleTest(p.provider)}
            testing={testing === p.provider}
            testResult={testResults[p.provider] ?? null}
            connecting={connecting === p.provider}
          />
        ))}
      </div>
    </div>
  )
}
