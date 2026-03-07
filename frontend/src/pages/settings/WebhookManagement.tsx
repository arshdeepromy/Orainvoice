/**
 * Outbound webhook management page (V2).
 *
 * Provides CRUD for outbound webhooks, a test button, and delivery log.
 *
 * Validates: Requirement 47 — Webhook Management and Security
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

const ALL_EVENT_TYPES: { value: WebhookEventType; label: string }[] = [
  { value: 'invoice.created', label: 'Invoice created' },
  { value: 'invoice.paid', label: 'Invoice paid' },
  { value: 'customer.created', label: 'Customer created' },
  { value: 'job.status_changed', label: 'Job status changed' },
  { value: 'booking.created', label: 'Booking created' },
  { value: 'payment.received', label: 'Payment received' },
  { value: 'stock.low', label: 'Stock low' },
]

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
        <label key={value} className="flex items-center gap-2 py-1">
          <input
            type="checkbox"
            checked={selected.includes(value)}
            onChange={() => toggle(value)}
            aria-label={label}
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
        await apiClient.put(`/outbound-webhooks/${webhook!.id}`, body)
      } else {
        await apiClient.post('/outbound-webhooks', body)
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
          <label htmlFor="webhook-url">Webhook URL</label>
          <Input
            id="webhook-url"
            value={url}
            onChange={(e) => setUrl(e.target.value)}
            placeholder="https://example.com/webhook"
            aria-label="Webhook URL"
          />
          {urlError && <p className="text-red-500 text-sm">{urlError}</p>}
        </div>
        <div>
          <EventTypeSelector selected={eventTypes} onChange={setEventTypes} />
          {eventError && <p className="text-red-500 text-sm">{eventError}</p>}
        </div>
        <label className="flex items-center gap-2">
          <input
            type="checkbox"
            checked={isActive}
            onChange={(e) => setIsActive(e.target.checked)}
            aria-label="Active"
          />
          Active
        </label>
        <div className="flex gap-2 justify-end">
          <Button variant="secondary" onClick={onClose}>Cancel</Button>
          <Button onClick={handleSubmit} disabled={saving}>
            {isEdit ? 'Save changes' : 'Create webhook'}
          </Button>
        </div>
      </div>
    </Modal>
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

  const columns: Column<OutboundWebhook>[] = [
    { key: 'target_url', header: 'URL', render: (w) => w.target_url },
    {
      key: 'event_types',
      header: 'Events',
      render: (w) =>
        w.event_types.map((et) => (
          <Badge key={et} variant="default" className="mr-1 mb-1">{et}</Badge>
        )),
    },
    {
      key: 'is_active',
      header: 'Status',
      render: (w) => (
        <Badge variant={w.is_active ? 'success' : 'secondary'}>
          {w.is_active ? 'Active' : 'Inactive'}
        </Badge>
      ),
    },
    {
      key: 'consecutive_failures',
      header: 'Failures',
      render: (w) => w.consecutive_failures,
    },
    {
      key: 'actions',
      header: '',
      render: (w) => (
        <div className="flex gap-2">
          <Button size="sm" variant="secondary" onClick={() => onTest(w)} disabled={testingId === w.id}>
            {testingId === w.id ? 'Testing…' : 'Test'}
          </Button>
          <Button size="sm" variant="secondary" onClick={() => onEdit(w)}>Edit</Button>
          <Button size="sm" variant="destructive" onClick={() => onDelete(w)}>Delete</Button>
        </div>
      ),
    },
  ]

  return <DataTable columns={columns} data={webhooks} keyField="id" />
}

/* ── Delivery Log ── */

function DeliveryLog({
  webhookId,
  deliveries,
}: {
  webhookId: string | null
  deliveries: DeliveryLogEntry[]
}) {
  if (deliveries.length === 0) {
    return <p>No delivery history yet.</p>
  }

  const columns: Column<DeliveryLogEntry>[] = [
    { key: 'event_type', header: 'Event', render: (d) => d.event_type },
    {
      key: 'status',
      header: 'Status',
      render: (d) => (
        <Badge variant={d.status === 'success' ? 'success' : 'destructive'}>
          {d.status}
        </Badge>
      ),
    },
    {
      key: 'response_status',
      header: 'HTTP Status',
      render: (d) => d.response_status ?? '—',
    },
    {
      key: 'response_time_ms',
      header: 'Response Time',
      render: (d) => (d.response_time_ms != null ? `${d.response_time_ms}ms` : '—'),
    },
    { key: 'retry_count', header: 'Retries', render: (d) => d.retry_count },
    { key: 'created_at', header: 'Time', render: (d) => formatDate(d.created_at) },
  ]

  return <DataTable columns={columns} data={deliveries} keyField="id" />
}

/* ── Main Component ── */

export function WebhookManagement() {
  const [webhooks, setWebhooks] = useState<OutboundWebhook[]>([])
  const [deliveries, setDeliveries] = useState<DeliveryLogEntry[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [modalWebhook, setModalWebhook] = useState<OutboundWebhook | null | undefined>(undefined)
  const [selectedWebhookId, setSelectedWebhookId] = useState<string | null>(null)
  const [testingId, setTestingId] = useState<string | null>(null)
  const { addToast, toasts } = useToast()

  const fetchWebhooks = useCallback(async () => {
    try {
      const res = await apiClient.get('/outbound-webhooks')
      setWebhooks(res.data)
    } catch {
      setError("Couldn't load your webhook settings. Please try again.")
    }
  }, [])

  const fetchDeliveries = useCallback(async (webhookId: string) => {
    try {
      const res = await apiClient.get(`/outbound-webhooks/${webhookId}/deliveries`)
      setDeliveries(res.data)
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
    await apiClient.delete(`/outbound-webhooks/${w.id}`)
    addToast({ type: 'success', message: 'Webhook deleted' })
    fetchWebhooks()
  }

  const handleTest = async (w: OutboundWebhook) => {
    setTestingId(w.id)
    try {
      const res = await apiClient.post(`/outbound-webhooks/${w.id}/test`)
      if (res.data.success) {
        addToast({ type: 'success', message: 'Test delivery successful' })
      } else {
        addToast({ type: 'error', message: `Test failed: ${res.data.error || 'Unknown error'}` })
      }
    } catch {
      addToast({ type: 'error', message: 'Test request failed' })
    } finally {
      setTestingId(null)
    }
  }

  if (loading) {
    return <Spinner label="Loading webhook management" aria-label="Loading webhook management" />
  }

  if (error) {
    return <AlertBanner variant="error">{error}</AlertBanner>
  }

  const hasFailures = webhooks.some((w) => w.consecutive_failures > 0)

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <h1>Webhook management</h1>
        <Button onClick={() => setModalWebhook(null)}>Create webhook</Button>
      </div>

      {hasFailures && (
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
                  >
                    <option value="">Select a webhook</option>
                    {webhooks.map((w) => (
                      <option key={w.id} value={w.id}>{w.target_url}</option>
                    ))}
                  </select>
                )}
                <DeliveryLog webhookId={selectedWebhookId} deliveries={deliveries} />
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

      <ToastContainer toasts={toasts} />
    </div>
  )
}
