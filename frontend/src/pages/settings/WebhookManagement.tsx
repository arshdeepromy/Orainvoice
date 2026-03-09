/**
 * Outbound webhook management page (V2).
 *
 * Provides CRUD for outbound webhooks, test button with response modal,
 * delivery log per webhook, visual health status indicators, and
 * auto-disable warning with re-enable button.
 *
 * Validates: Requirements 6.1, 6.2, 6.3, 6.4, 6.5, 6.6, 6.7, 6.8
 */

import { useState, useEffect, useCallback } from 'react'
import { Button } from '@/components/ui/Button'
import { Badge } from '@/components/ui/Badge'
import { Spinner } from '@/components/ui/Spinner'
import { AlertBanner } from '@/components/ui/AlertBanner'
import { DataTable, type Column } from '@/components/ui/DataTable'
import { Modal } from '@/components/ui/Modal'
import { Input } from '@/components/ui/Input'
import { Tabs } from '@/components/ui/Tabs'
import { ToastContainer, useToast } from '@/components/ui/Toast'
import apiClient from '@/api/client'
import { useTerm } from '@/contexts/TerminologyContext'
import { useFlag } from '@/contexts/FeatureFlagContext'
import { useModules } from '@/contexts/ModuleContext'
import { isValidWebhookUrl, getWebhookHealthStatus } from '@/utils/webhookUtils'
import type { WebhookHealthStatus } from '@/utils/webhookUtils'

/* ── Types ── */

export type WebhookEventType =
  | 'invoice.created'
  | 'invoice.paid'
  | 'customer.created'
  | 'job.status_changed'
  | 'booking.created'
  | 'payment.received'
  | 'stock.low'

export interface OutboundWebhook {
  id: string
  org_id: string
  target_url: string
  event_types: WebhookEventType[]
  is_active: boolean
  consecutive_failures: number
  last_delivery_at: string | null
  created_at: string
  updated_at: string
}

export interface DeliveryLogEntry {
  id: string
  webhook_id: string
  event_type: string
  payload: Record<string, unknown> | null
  response_status: number | null
  response_time_ms: number | null
  retry_count: number
  status: string
  error_details: string | null
  created_at: string
}

interface TestResult {
  success: boolean
  status_code?: number
  response_time_ms?: number
  body?: string
  error?: string
}

const ALL_EVENT_TYPES: { value: WebhookEventType; label: string }[] = [
  { value: 'invoice.created', label: 'Invoice created' },
  { value: 'invoice.paid', label: 'Invoice paid' },
  { value: 'customer.created', label: 'Customer created' },
  { value: 'job.status_changed', label: 'Job status changed' },
  { value: 'booking.created', label: 'Booking created' },
  { value: 'payment.received', label: 'Payment received' },
  { value: 'stock.low', label: 'Stock low' },
]

/* ── Health Status Helpers ── */

const HEALTH_COLORS: Record<WebhookHealthStatus, string> = {
  healthy: '#22c55e',
  degraded: '#f59e0b',
  failing: '#ef4444',
  disabled: '#9ca3af',
}

const HEALTH_LABELS: Record<WebhookHealthStatus, string> = {
  healthy: 'Healthy',
  degraded: 'Degraded',
  failing: 'Failing',
  disabled: 'Disabled',
}

/* ── Helpers ── */

function formatDate(iso: string | null): string {
  if (!iso) return '—'
  return new Date(iso).toLocaleDateString('en-NZ', {
    day: 'numeric',
    month: 'short',
    year: 'numeric',
    hour: '2-digit',
    minute: '2-digit',
  })
}

/* ── Health Status Indicator ── */

function HealthIndicator({ webhook }: { webhook: OutboundWebhook }) {
  const status = getWebhookHealthStatus(webhook.consecutive_failures, webhook.is_active)
  const color = HEALTH_COLORS[status]
  const label = HEALTH_LABELS[status]

  return (
    <span
      data-testid={`health-${webhook.id}`}
      className="inline-flex items-center gap-1.5"
      title={`${label} — ${webhook.consecutive_failures} consecutive failures`}
    >
      <span
        style={{
          display: 'inline-block',
          width: 10,
          height: 10,
          borderRadius: '50%',
          backgroundColor: color,
        }}
        aria-hidden="true"
      />
      <span>{label}</span>
    </span>
  )
}

/* ── Event Type Selector ── */

function EventTypeSelector({
  selected,
  onChange,
}: {
  selected: WebhookEventType[]
  onChange: (types: WebhookEventType[]) => void
}) {
  const toggle = (value: WebhookEventType) => {
    if (selected.includes(value)) {
      onChange(selected.filter((t) => t !== value))
    } else {
      onChange([...selected, value])
    }
  }

  return (
    <fieldset>
      <legend className="sr-only">Event types</legend>
      {ALL_EVENT_TYPES.map(({ value, label }) => (
        <label key={value} className="flex items-center gap-2 py-1" style={{ minHeight: 44 }}>
          <input
            type="checkbox"
            checked={selected.includes(value)}
            onChange={() => toggle(value)}
            aria-label={label}
            style={{ minWidth: 20, minHeight: 20 }}
          />
          {label}
        </label>
      ))}
    </fieldset>
  )
}

/* ── Webhook Form Modal ── */

function WebhookFormModal({
  webhook,
  onClose,
  onSaved,
}: {
  webhook: OutboundWebhook | null
  onClose: () => void
  onSaved: () => void
}) {
  const isEdit = webhook !== null
  const [url, setUrl] = useState(webhook?.target_url ?? '')
  const [eventTypes, setEventTypes] = useState<WebhookEventType[]>(
    webhook?.event_types ?? [],
  )
  const [isActive, setIsActive] = useState(webhook?.is_active ?? true)
  const [urlError, setUrlError] = useState('')
  const [eventError, setEventError] = useState('')
  const [saving, setSaving] = useState(false)

  const handleSubmit = async () => {
    setUrlError('')
    setEventError('')
    let hasError = false

    if (!url.trim()) {
      setUrlError('URL is required')
      hasError = true
    } else if (!isValidWebhookUrl(url.trim())) {
      setUrlError('URL must start with https://')
      hasError = true
    }
    if (eventTypes.length === 0) {
      setEventError('Select at least one event type')
      hasError = true
    }
    if (hasError) return

    setSaving(true)
    try {
      const body = { target_url: url, event_types: eventTypes, is_active: isActive }
      if (isEdit) {
        await apiClient.put(`/api/v2/outbound-webhooks/${webhook!.id}`, body)
      } else {
        await apiClient.post('/api/v2/outbound-webhooks', body)
      }
      onSaved()
      onClose()
    } finally {
      setSaving(false)
    }
  }

  return (
    <Modal open={true} onClose={onClose} title={isEdit ? 'Edit webhook' : 'Create webhook'}>
      <div className="space-y-4">
        <div>
          <Input
            id="webhook-url"
            label="Webhook URL"
            value={url}
            onChange={(e) => setUrl(e.target.value)}
            placeholder="https://example.com/webhook"
            aria-label="Webhook URL"
          />
          {urlError && <p className="text-red-500 text-sm" role="alert">{urlError}</p>}
        </div>
        <div>
          <EventTypeSelector selected={eventTypes} onChange={setEventTypes} />
          {eventError && <p className="text-red-500 text-sm" role="alert">{eventError}</p>}
        </div>
        <label className="flex items-center gap-2" style={{ minHeight: 44 }}>
          <input
            type="checkbox"
            checked={isActive}
            onChange={(e) => setIsActive(e.target.checked)}
            aria-label="Active"
            style={{ minWidth: 20, minHeight: 20 }}
          />
          Active
        </label>
        <div className="flex gap-2 justify-end">
          <Button variant="secondary" onClick={onClose} style={{ minHeight: 44, minWidth: 44 }}>Cancel</Button>
          <Button onClick={handleSubmit} disabled={saving} style={{ minHeight: 44, minWidth: 44 }}>
            {isEdit ? 'Save changes' : 'Create webhook'}
          </Button>
        </div>
      </div>
    </Modal>
  )
}

/* ── Test Result Modal ── */

function TestResultModal({
  result,
  onClose,
}: {
  result: TestResult
  onClose: () => void
}) {
  return (
    <Modal open={true} onClose={onClose} title="Webhook test result">
      <div className="space-y-3" data-testid="test-result-modal">
        <div className="flex items-center gap-2">
          <span className="font-medium">Status:</span>
          <Badge variant={result.success ? 'success' : 'error'}>
            {result.success ? 'Success' : 'Failed'}
          </Badge>
        </div>
        {result.status_code != null && (
          <div>
            <span className="font-medium">HTTP Status:</span> {result.status_code}
          </div>
        )}
        {result.response_time_ms != null && (
          <div>
            <span className="font-medium">Response Time:</span> {result.response_time_ms}ms
          </div>
        )}
        {result.body && (
          <div>
            <span className="font-medium">Response Body:</span>
            <pre className="mt-1 p-2 bg-gray-100 rounded text-sm overflow-auto max-h-48">
              {result.body}
            </pre>
          </div>
        )}
        {result.error && (
          <div>
            <span className="font-medium">Error:</span>
            <p className="text-red-600 text-sm mt-1">{result.error}</p>
          </div>
        )}
        <div className="flex justify-end">
          <Button onClick={onClose} style={{ minHeight: 44, minWidth: 44 }}>Close</Button>
        </div>
      </div>
    </Modal>
  )
}

/* ── Auto-Disable Warning ── */

function AutoDisableWarning({
  webhook,
  onReEnable,
  reEnabling,
}: {
  webhook: OutboundWebhook
  onReEnable: (w: OutboundWebhook) => void
  reEnabling: boolean
}) {
  return (
    <AlertBanner variant="error" data-testid={`auto-disable-warning-${webhook.id}`}>
      <div className="flex items-center justify-between gap-4 flex-wrap">
        <div>
          <strong>Webhook auto-disabled:</strong> {webhook.target_url} has been disabled after{' '}
          {webhook.consecutive_failures} consecutive delivery failures.
        </div>
        <Button
          size="sm"
          variant="secondary"
          onClick={() => onReEnable(webhook)}
          disabled={reEnabling}
          style={{ minHeight: 44, minWidth: 44 }}
          aria-label={`Re-enable ${webhook.target_url}`}
        >
          {reEnabling ? 'Re-enabling…' : 'Re-enable'}
        </Button>
      </div>
    </AlertBanner>
  )
}

/* ── Webhook List ── */

function WebhookList({
  webhooks,
  onEdit,
  onDelete,
  onTest,
  testingId,
}: {
  webhooks: OutboundWebhook[]
  onEdit: (w: OutboundWebhook) => void
  onDelete: (w: OutboundWebhook) => void
  onTest: (w: OutboundWebhook) => void
  testingId: string | null
}) {
  if (webhooks.length === 0) {
    return <p>No webhooks configured. Create one to get started.</p>
  }

  const columns: Column<Record<string, unknown>>[] = [
    { key: 'target_url', header: 'URL', render: (r) => String(r.target_url) },
    {
      key: 'event_types',
      header: 'Events',
      render: (r) =>
        (r.event_types as string[]).map((et) => (
          <Badge key={et} variant="neutral" className="mr-1 mb-1">{et}</Badge>
        )),
    },
    {
      key: 'is_active',
      header: 'Status',
      render: (r) => (
        <Badge variant={r.is_active ? 'success' : 'neutral'}>
          {r.is_active ? 'Active' : 'Inactive'}
        </Badge>
      ),
    },
    {
      key: 'health',
      header: 'Health',
      render: (r) => {
        const w = r as unknown as OutboundWebhook
        return <HealthIndicator webhook={w} />
      },
    },
    {
      key: 'consecutive_failures',
      header: 'Failures',
      render: (r) => String(r.consecutive_failures),
    },
    {
      key: 'actions',
      header: '',
      render: (r) => {
        const w = r as unknown as OutboundWebhook
        return (
          <div className="flex gap-2">
            <Button
              size="sm"
              variant="secondary"
              onClick={() => onTest(w)}
              disabled={testingId === w.id}
              style={{ minHeight: 44, minWidth: 44 }}
            >
              {testingId === w.id ? 'Testing…' : 'Test'}
            </Button>
            <Button size="sm" variant="secondary" onClick={() => onEdit(w)} style={{ minHeight: 44, minWidth: 44 }}>
              Edit
            </Button>
            <Button size="sm" variant="danger" onClick={() => onDelete(w)} style={{ minHeight: 44, minWidth: 44 }}>
              Delete
            </Button>
          </div>
        )
      },
    },
  ]

  return (
    <DataTable
      columns={columns}
      data={webhooks as unknown as Record<string, unknown>[]}
      keyField="id"
    />
  )
}

/* ── Delivery Log ── */

function DeliveryLog({
  deliveries,
}: {
  deliveries: DeliveryLogEntry[]
}) {
  if (deliveries.length === 0) {
    return <p>No delivery history yet.</p>
  }

  const columns: Column<Record<string, unknown>>[] = [
    { key: 'event_type', header: 'Event', render: (d) => String(d.event_type) },
    {
      key: 'status',
      header: 'Status',
      render: (d) => (
        <Badge variant={d.status === 'success' ? 'success' : 'error'}>
          {String(d.status)}
        </Badge>
      ),
    },
    {
      key: 'response_status',
      header: 'HTTP Status',
      render: (d) => (d.response_status != null ? String(d.response_status) : '—'),
    },
    {
      key: 'response_time_ms',
      header: 'Response Time',
      render: (d) => (d.response_time_ms != null ? `${d.response_time_ms}ms` : '—'),
    },
    { key: 'retry_count', header: 'Retries', render: (d) => String(d.retry_count) },
    { key: 'created_at', header: 'Time', render: (d) => formatDate(String(d.created_at)) },
  ]

  return (
    <DataTable
      columns={columns}
      data={deliveries as unknown as Record<string, unknown>[]}
      keyField="id"
    />
  )
}

/* ── Main Component ── */

export function WebhookManagement() {
  const webhookLabel = useTerm('webhook', 'Webhook')
  // Integrate FeatureFlagContext and ModuleContext per Req 6.8
  void useFlag('webhooks')
  void useModules()

  const [webhooks, setWebhooks] = useState<OutboundWebhook[]>([])
  const [deliveries, setDeliveries] = useState<DeliveryLogEntry[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [modalWebhook, setModalWebhook] = useState<OutboundWebhook | null | undefined>(undefined)
  const [selectedWebhookId, setSelectedWebhookId] = useState<string | null>(null)
  const [testingId, setTestingId] = useState<string | null>(null)
  const [testResult, setTestResult] = useState<TestResult | null>(null)
  const [reEnablingId, setReEnablingId] = useState<string | null>(null)
  const { addToast, toasts, dismissToast } = useToast()

  const fetchWebhooks = useCallback(async () => {
    try {
      const res = await apiClient.get('/api/v2/outbound-webhooks')
      console.log('Webhooks response:', res.data)
      // Handle both array and wrapped response formats
      const webhookData = Array.isArray(res.data) ? res.data : (res.data?.webhooks || [])
      setWebhooks(webhookData)
      setError(null)
    } catch (err) {
      console.error('Webhooks fetch error:', err)
      setError("Couldn't load your webhook settings. Please try again.")
      setWebhooks([])
    }
  }, [])

  const fetchDeliveries = useCallback(async (webhookId: string) => {
    try {
      const res = await apiClient.get(`/api/v2/outbound-webhooks/${webhookId}/deliveries`)
      // Handle both array and wrapped response formats
      const deliveryData = Array.isArray(res.data) ? res.data : (res.data?.deliveries || [])
      setDeliveries(deliveryData)
    } catch {
      setDeliveries([])
    }
  }, [])

  useEffect(() => {
    setLoading(true)
    fetchWebhooks().finally(() => setLoading(false))
  }, [fetchWebhooks])

  useEffect(() => {
    if (selectedWebhookId) {
      fetchDeliveries(selectedWebhookId)
    }
  }, [selectedWebhookId, fetchDeliveries])

  const handleDelete = async (w: OutboundWebhook) => {
    await apiClient.delete(`/api/v2/outbound-webhooks/${w.id}`)
    addToast('success', `${webhookLabel} deleted`)
    fetchWebhooks()
  }

  const handleTest = async (w: OutboundWebhook) => {
    setTestingId(w.id)
    try {
      const res = await apiClient.post(`/api/v2/outbound-webhooks/${w.id}/test`)
      const data = res.data
      setTestResult({
        success: !!data.success,
        status_code: data.status_code,
        response_time_ms: data.response_time_ms,
        body: data.body ? JSON.stringify(data.body, null, 2) : undefined,
        error: data.error,
      })
      if (data.success) {
        addToast('success', 'Test delivery successful')
      } else {
        addToast('error', `Test failed: ${data.error || 'Unknown error'}`)
      }
    } catch {
      setTestResult({
        success: false,
        error: 'Test request failed — could not reach the server.',
      })
      addToast('error', 'Test request failed')
    } finally {
      setTestingId(null)
    }
  }

  const handleReEnable = async (w: OutboundWebhook) => {
    setReEnablingId(w.id)
    try {
      await apiClient.put(`/api/v2/outbound-webhooks/${w.id}`, {
        target_url: w.target_url,
        event_types: w.event_types,
        is_active: true,
      })
      addToast('success', `${webhookLabel} re-enabled`)
      fetchWebhooks()
    } catch {
      addToast('error', `Failed to re-enable ${webhookLabel.toLowerCase()}`)
    } finally {
      setReEnablingId(null)
    }
  }

  if (loading) {
    return <Spinner label="Loading webhook management" aria-label="Loading webhook management" />
  }

  if (error) {
    return <AlertBanner variant="error">{error}</AlertBanner>
  }

  const hasFailures = webhooks.some((w) => w.consecutive_failures > 0)
  const autoDisabledWebhooks = webhooks.filter(
    (w) => !w.is_active && w.consecutive_failures >= 5,
  )

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <h1>{webhookLabel} management</h1>
        <Button onClick={() => setModalWebhook(null)} style={{ minHeight: 44, minWidth: 44 }}>
          Create webhook
        </Button>
      </div>

      {autoDisabledWebhooks.map((w) => (
        <AutoDisableWarning
          key={w.id}
          webhook={w}
          onReEnable={handleReEnable}
          reEnabling={reEnablingId === w.id}
        />
      ))}

      {hasFailures && autoDisabledWebhooks.length === 0 && (
        <AlertBanner variant="warning">
          Some webhooks have delivery failures. Check the delivery log for details.
        </AlertBanner>
      )}

      <Tabs
        tabs={[
          {
            id: 'webhooks',
            label: 'Webhooks',
            content: (
              <WebhookList
                webhooks={webhooks}
                onEdit={(w) => setModalWebhook(w)}
                onDelete={handleDelete}
                onTest={handleTest}
                testingId={testingId}
              />
            ),
          },
          {
            id: 'delivery-log',
            label: 'Delivery log',
            content: (
              <div className="space-y-4">
                {webhooks.length > 0 && (
                  <select
                    aria-label="Select webhook"
                    value={selectedWebhookId ?? ''}
                    onChange={(e) => setSelectedWebhookId(e.target.value || null)}
                    style={{ minHeight: 44 }}
                  >
                    <option value="">Select a webhook</option>
                    {webhooks.map((w) => (
                      <option key={w.id} value={w.id}>{w.target_url}</option>
                    ))}
                  </select>
                )}
                <DeliveryLog deliveries={deliveries} />
              </div>
            ),
          },
        ]}
      />

      {modalWebhook !== undefined && (
        <WebhookFormModal
          webhook={modalWebhook}
          onClose={() => setModalWebhook(undefined)}
          onSaved={fetchWebhooks}
        />
      )}

      {testResult && (
        <TestResultModal
          result={testResult}
          onClose={() => setTestResult(null)}
        />
      )}

      <ToastContainer toasts={toasts} onDismiss={dismissToast} />
    </div>
  )
}
