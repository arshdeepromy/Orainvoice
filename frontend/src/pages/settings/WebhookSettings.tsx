import { useState, useEffect } from 'react'
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
  | 'invoice.overdue'
  | 'payment.received'
  | 'customer.created'
  | 'vehicle.added'

export interface Webhook {
  id: string
  url: string
  event_types: WebhookEventType[]
  is_active: boolean
  secret: string | null
  created_at: string
  [key: string]: unknown
}

export interface WebhookDelivery {
  id: string
  webhook_id: string
  event_type: WebhookEventType
  status: 'success' | 'failed'
  response_code: number | null
  attempt: number
  delivered_at: string
  [key: string]: unknown
}

const ALL_EVENT_TYPES: { value: WebhookEventType; label: string }[] = [
  { value: 'invoice.created', label: 'Invoice created' },
  { value: 'invoice.paid', label: 'Invoice paid' },
  { value: 'invoice.overdue', label: 'Invoice overdue' },
  { value: 'payment.received', label: 'Payment received' },
  { value: 'customer.created', label: 'Customer created' },
  { value: 'vehicle.added', label: 'Vehicle added' },
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

/* ── Event Type Multi-Select ── */

function EventTypeSelector({
  selected,
  onChange,
}: {
  selected: WebhookEventType[]
  onChange: (types: WebhookEventType[]) => void
}) {
  const toggle = (eventType: WebhookEventType) => {
    if (selected.includes(eventType)) {
      onChange(selected.filter((t) => t !== eventType))
    } else {
      onChange([...selected, eventType])
    }
  }

  return (
    <fieldset>
      <legend className="text-sm font-medium text-gray-700 mb-2">Event types</legend>
      <div className="space-y-2">
        {ALL_EVENT_TYPES.map((evt) => (
          <label key={evt.value} className="flex items-center gap-2 text-sm text-gray-700 cursor-pointer">
            <input
              type="checkbox"
              checked={selected.includes(evt.value)}
              onChange={() => toggle(evt.value)}
              className="rounded border-gray-300 text-blue-600 focus:ring-blue-500"
            />
            {evt.label}
          </label>
        ))}
      </div>
    </fieldset>
  )
}

/* ── Webhook Form Modal ── */

function WebhookFormModal({
  open,
  onClose,
  onSave,
  saving,
  webhook,
}: {
  open: boolean
  onClose: () => void
  onSave: (data: { url: string; event_types: WebhookEventType[]; is_active: boolean }) => void
  saving: boolean
  webhook: Webhook | null
}) {
  const [url, setUrl] = useState('')
  const [eventTypes, setEventTypes] = useState<WebhookEventType[]>([])
  const [isActive, setIsActive] = useState(true)
  const [urlError, setUrlError] = useState('')

  useEffect(() => {
    if (open) {
      setUrl(webhook?.url ?? '')
      setEventTypes(webhook?.event_types ?? [])
      setIsActive(webhook?.is_active ?? true)
      setUrlError('')
    }
  }, [open, webhook])

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault()
    if (!url.trim()) {
      setUrlError('URL is required')
      return
    }
    try {
      new URL(url)
    } catch {
      setUrlError('Please enter a valid URL')
      return
    }
    if (eventTypes.length === 0) {
      setUrlError('Select at least one event type')
      return
    }
    setUrlError('')
    onSave({ url: url.trim(), event_types: eventTypes, is_active: isActive })
  }

  return (
    <Modal open={open} onClose={onClose} title={webhook ? 'Edit webhook' : 'Create webhook'}>
      <form onSubmit={handleSubmit} className="space-y-4">
        <Input
          label="Webhook URL"
          type="url"
          placeholder="https://example.com/webhook"
          value={url}
          onChange={(e) => setUrl(e.target.value)}
          error={urlError}
        />

        <EventTypeSelector selected={eventTypes} onChange={setEventTypes} />

        <label className="flex items-center gap-2 text-sm text-gray-700 cursor-pointer">
          <input
            type="checkbox"
            checked={isActive}
            onChange={(e) => setIsActive(e.target.checked)}
            className="rounded border-gray-300 text-blue-600 focus:ring-blue-500"
          />
          Active
        </label>

        <div className="flex justify-end gap-3 pt-2">
          <Button type="button" variant="secondary" onClick={onClose}>
            Cancel
          </Button>
          <Button type="submit" loading={saving}>
            {webhook ? 'Save changes' : 'Create webhook'}
          </Button>
        </div>
      </form>
    </Modal>
  )
}

/* ── Webhook List ── */

function WebhookList({
  webhooks,
  onEdit,
  onDelete,
  deleting,
}: {
  webhooks: Webhook[]
  onEdit: (webhook: Webhook) => void
  onDelete: (webhook: Webhook) => void
  deleting: string | null
}) {
  const columns: Column<Webhook>[] = [
    {
      key: 'url',
      header: 'URL',
      render: (row) => (
        <span className="font-mono text-xs break-all">{row.url}</span>
      ),
    },
    {
      key: 'event_types',
      header: 'Events',
      render: (row) => (
        <div className="flex flex-wrap gap-1">
          {row.event_types.map((evt) => (
            <Badge key={evt} variant="info">{evt}</Badge>
          ))}
        </div>
      ),
    },
    {
      key: 'is_active',
      header: 'Status',
      render: (row) => (
        <Badge variant={row.is_active ? 'success' : 'neutral'}>
          {row.is_active ? 'Active' : 'Inactive'}
        </Badge>
      ),
    },
    {
      key: 'created_at',
      header: 'Created',
      sortable: true,
      render: (row) => formatDate(row.created_at),
    },
    {
      key: 'id',
      header: 'Actions',
      render: (row) => (
        <div className="flex gap-2">
          <Button size="sm" variant="secondary" onClick={() => onEdit(row)}>
            Edit
          </Button>
          <Button
            size="sm"
            variant="danger"
            onClick={() => onDelete(row)}
            loading={deleting === row.id}
          >
            Delete
          </Button>
        </div>
      ),
    },
  ]

  return (
    <div>
      {webhooks.length === 0 ? (
        <p className="text-sm text-gray-500 py-4">
          No webhooks configured. Create one to start receiving event notifications.
        </p>
      ) : (
        <DataTable columns={columns} data={webhooks} keyField="id" caption="Configured webhooks" />
      )}
    </div>
  )
}

/* ── Delivery Log ── */

function DeliveryLog({ deliveries }: { deliveries: WebhookDelivery[] }) {
  const columns: Column<WebhookDelivery>[] = [
    {
      key: 'delivered_at',
      header: 'Time',
      sortable: true,
      render: (row) => formatDate(row.delivered_at),
    },
    {
      key: 'event_type',
      header: 'Event',
      render: (row) => <Badge variant="info">{row.event_type}</Badge>,
    },
    {
      key: 'status',
      header: 'Status',
      render: (row) => (
        <Badge variant={row.status === 'success' ? 'success' : 'error'}>
          {row.status}
        </Badge>
      ),
    },
    {
      key: 'response_code',
      header: 'Response code',
      render: (row) => (row.response_code != null ? String(row.response_code) : '—'),
    },
    {
      key: 'attempt',
      header: 'Attempt',
      render: (row) => String(row.attempt),
    },
  ]

  return (
    <div>
      {deliveries.length === 0 ? (
        <p className="text-sm text-gray-500 py-4">No delivery history yet.</p>
      ) : (
        <DataTable columns={columns} data={deliveries} keyField="id" caption="Webhook delivery log" />
      )}
    </div>
  )
}

/* ── Main Page ── */

export function WebhookSettings() {
  const [webhooks, setWebhooks] = useState<Webhook[]>([])
  const [deliveries, setDeliveries] = useState<WebhookDelivery[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(false)
  const [modalOpen, setModalOpen] = useState(false)
  const [editingWebhook, setEditingWebhook] = useState<Webhook | null>(null)
  const [saving, setSaving] = useState(false)
  const [deleting, setDeleting] = useState<string | null>(null)
  const { toasts, addToast, dismissToast } = useToast()

  const fetchData = async () => {
    setLoading(true)
    setError(false)
    try {
      const [whRes, dlRes] = await Promise.all([
        apiClient.get<Webhook[]>('/webhooks'),
        apiClient.get<WebhookDelivery[]>('/webhooks/deliveries'),
      ])
      setWebhooks(whRes.data)
      setDeliveries(dlRes.data)
    } catch {
      setError(true)
      addToast('error', 'Failed to load webhook settings')
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => { fetchData() }, [])

  const openCreate = () => {
    setEditingWebhook(null)
    setModalOpen(true)
  }

  const openEdit = (webhook: Webhook) => {
    setEditingWebhook(webhook)
    setModalOpen(true)
  }

  const handleSave = async (data: { url: string; event_types: WebhookEventType[]; is_active: boolean }) => {
    setSaving(true)
    try {
      if (editingWebhook) {
        await apiClient.put(`/webhooks/${editingWebhook.id}`, data)
        addToast('success', 'Webhook updated')
      } else {
        await apiClient.post('/webhooks', data)
        addToast('success', 'Webhook created')
      }
      setModalOpen(false)
      fetchData()
    } catch {
      addToast('error', editingWebhook ? 'Failed to update webhook' : 'Failed to create webhook')
    } finally {
      setSaving(false)
    }
  }

  const handleDelete = async (webhook: Webhook) => {
    setDeleting(webhook.id)
    try {
      await apiClient.delete(`/webhooks/${webhook.id}`)
      addToast('success', 'Webhook deleted')
      fetchData()
    } catch {
      addToast('error', 'Failed to delete webhook')
    } finally {
      setDeleting(null)
    }
  }

  if (loading) {
    return (
      <div className="flex items-center justify-center py-20">
        <Spinner label="Loading webhook settings" />
      </div>
    )
  }

  if (error && webhooks.length === 0) {
    return (
      <AlertBanner variant="error" title="Something went wrong">
        We couldn't load your webhook settings. Please refresh the page or try again later.
      </AlertBanner>
    )
  }

  const hasFailedDeliveries = deliveries.some((d) => d.status === 'failed')

  const tabs = [
    {
      id: 'webhooks',
      label: 'Webhooks',
      content: (
        <div className="space-y-4">
          <div className="flex justify-end">
            <Button onClick={openCreate}>Create webhook</Button>
          </div>
          <WebhookList
            webhooks={webhooks}
            onEdit={openEdit}
            onDelete={handleDelete}
            deleting={deleting}
          />
        </div>
      ),
    },
    {
      id: 'deliveries',
      label: 'Delivery log',
      content: <DeliveryLog deliveries={deliveries} />,
    },
  ]

  return (
    <div>
      <h1 className="text-2xl font-semibold text-gray-900 mb-6">Webhook settings</h1>
      <ToastContainer toasts={toasts} onDismiss={dismissToast} />

      <div className="max-w-4xl space-y-4">
        {hasFailedDeliveries && (
          <AlertBanner variant="warning" title="Delivery failures detected">
            Some webhook deliveries have failed. Check the delivery log for details.
          </AlertBanner>
        )}

        <Tabs tabs={tabs} defaultTab="webhooks" />
      </div>

      <WebhookFormModal
        open={modalOpen}
        onClose={() => setModalOpen(false)}
        onSave={handleSave}
        saving={saving}
        webhook={editingWebhook}
      />
    </div>
  )
}
