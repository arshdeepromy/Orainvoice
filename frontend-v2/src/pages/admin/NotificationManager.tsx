import { useState, useEffect, useCallback } from 'react'
import apiClient from '@/api/client'

/* ── Types ── */

type NotificationType = 'maintenance' | 'alert' | 'feature' | 'info'
type Severity = 'info' | 'warning' | 'critical'
type TargetType = 'all' | 'country' | 'trade_family' | 'plan_tier' | 'specific_orgs'

export interface PlatformNotification {
  id: string
  notification_type: NotificationType
  title: string
  message: string
  severity: Severity
  target_type: TargetType
  target_value: string | null
  scheduled_at: string | null
  published_at: string | null
  expires_at: string | null
  maintenance_start: string | null
  maintenance_end: string | null
  is_active: boolean
  created_by: string | null
  created_at: string
  updated_at: string
}

interface FormData {
  notification_type: NotificationType
  title: string
  message: string
  severity: Severity
  target_type: TargetType
  target_value: string
  scheduled_at: string
  expires_at: string
  maintenance_start: string
  maintenance_end: string
}

const EMPTY_FORM: FormData = {
  notification_type: 'info',
  title: '',
  message: '',
  severity: 'info',
  target_type: 'all',
  target_value: '',
  scheduled_at: '',
  expires_at: '',
  maintenance_start: '',
  maintenance_end: '',
}

const SEVERITY_BADGE: Record<Severity, string> = {
  info: 'bg-accent-soft text-accent',
  warning: 'bg-warn-soft text-warn',
  critical: 'bg-danger-soft text-danger',
}

const TYPE_BADGE: Record<NotificationType, string> = {
  maintenance: 'bg-warn-soft text-warn',
  alert: 'bg-danger-soft text-danger',
  feature: 'bg-ok-soft text-ok',
  info: 'bg-accent-soft text-accent',
}

/* ── Component ── */

export default function NotificationManager() {
  const [notifications, setNotifications] = useState<PlatformNotification[]>([])
  const [loading, setLoading] = useState(true)
  const [showForm, setShowForm] = useState(false)
  const [editingId, setEditingId] = useState<string | null>(null)
  const [form, setForm] = useState<FormData>(EMPTY_FORM)
  const [error, setError] = useState<string | null>(null)
  const [includeInactive, setIncludeInactive] = useState(false)

  const fetchNotifications = useCallback(async () => {
    try {
      setLoading(true)
      const res = await apiClient.get('/api/v2/admin/notifications', {
        params: { include_inactive: includeInactive },
      })
      setNotifications(res.data?.notifications ?? [])
    } catch {
      setError('Failed to load notifications')
    } finally {
      setLoading(false)
    }
  }, [includeInactive])

  useEffect(() => { fetchNotifications() }, [fetchNotifications])

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault()
    setError(null)

    const payload: Record<string, unknown> = {
      notification_type: form.notification_type,
      title: form.title,
      message: form.message,
      severity: form.severity,
      target_type: form.target_type,
    }
    if (form.target_value) payload.target_value = form.target_value
    if (form.scheduled_at) payload.scheduled_at = form.scheduled_at
    if (form.expires_at) payload.expires_at = form.expires_at
    if (form.maintenance_start) payload.maintenance_start = form.maintenance_start
    if (form.maintenance_end) payload.maintenance_end = form.maintenance_end

    try {
      if (editingId) {
        await apiClient.put(`/api/v2/admin/notifications/${editingId}`, payload)
      } else {
        await apiClient.post('/api/v2/admin/notifications', payload)
      }
      setShowForm(false)
      setEditingId(null)
      setForm(EMPTY_FORM)
      fetchNotifications()
    } catch (err: any) {
      setError(err?.response?.data?.detail || 'Failed to save notification')
    }
  }

  const handleEdit = (notif: PlatformNotification) => {
    setForm({
      notification_type: notif.notification_type,
      title: notif.title,
      message: notif.message,
      severity: notif.severity,
      target_type: notif.target_type,
      target_value: notif.target_value || '',
      scheduled_at: notif.scheduled_at || '',
      expires_at: notif.expires_at || '',
      maintenance_start: notif.maintenance_start || '',
      maintenance_end: notif.maintenance_end || '',
    })
    setEditingId(notif.id)
    setShowForm(true)
  }

  const handleDelete = async (id: string) => {
    if (!window.confirm('Deactivate this notification?')) return
    try {
      await apiClient.delete(`/api/v2/admin/notifications/${id}`)
      fetchNotifications()
    } catch {
      setError('Failed to deactivate notification')
    }
  }

  const handlePublish = async (id: string) => {
    try {
      await apiClient.post(`/api/v2/admin/notifications/${id}/publish`)
      fetchNotifications()
    } catch {
      setError('Failed to publish notification')
    }
  }

  return (
    <div className="p-6 max-w-6xl mx-auto" data-testid="notification-manager">
      <div className="flex items-center justify-between mb-6">
        <h1 className="text-2xl font-bold text-text">Platform Notifications</h1>
        <button
          onClick={() => { setShowForm(true); setEditingId(null); setForm(EMPTY_FORM) }}
          className="px-4 py-2 bg-accent text-white rounded-ctl hover:bg-accent-press"
          data-testid="create-notification-btn"
        >
          Create Notification
        </button>
      </div>

      {error && (
        <div className="mb-4 p-3 bg-danger-soft border border-danger/30 text-danger rounded-ctl" role="alert">
          {error}
        </div>
      )}

      {/* Filter */}
      <div className="mb-4">
        <label className="flex items-center gap-2 text-sm text-text">
          <input
            type="checkbox"
            checked={includeInactive}
            onChange={e => setIncludeInactive(e.target.checked)}
          />
          Show inactive notifications
        </label>
      </div>

      {/* Create/Edit Form */}
      {showForm && (
        <form onSubmit={handleSubmit} className="mb-6 p-4 border border-border rounded-card bg-canvas" data-testid="notification-form">
          <h2 className="text-lg font-semibold mb-4 text-text">
            {editingId ? 'Edit Notification' : 'Create Notification'}
          </h2>
          <div className="grid grid-cols-2 gap-4">
            <div>
              <label className="block text-sm font-medium mb-1 text-text">Type</label>
              <select
                value={form.notification_type}
                onChange={e => setForm(f => ({ ...f, notification_type: e.target.value as NotificationType }))}
                className="w-full border border-border bg-card rounded-ctl px-3 py-2 text-text focus:border-accent focus:outline-none focus:shadow-[0_0_0_3px_var(--accent-soft)]"
                data-testid="type-select"
              >
                <option value="info">Info</option>
                <option value="alert">Alert</option>
                <option value="feature">Feature</option>
                <option value="maintenance">Maintenance</option>
              </select>
            </div>
            <div>
              <label className="block text-sm font-medium mb-1 text-text">Severity</label>
              <select
                value={form.severity}
                onChange={e => setForm(f => ({ ...f, severity: e.target.value as Severity }))}
                className="w-full border border-border bg-card rounded-ctl px-3 py-2 text-text focus:border-accent focus:outline-none focus:shadow-[0_0_0_3px_var(--accent-soft)]"
                data-testid="severity-select"
              >
                <option value="info">Info</option>
                <option value="warning">Warning</option>
                <option value="critical">Critical</option>
              </select>
            </div>
            <div className="col-span-2">
              <label className="block text-sm font-medium mb-1 text-text">Title</label>
              <input
                type="text"
                value={form.title}
                onChange={e => setForm(f => ({ ...f, title: e.target.value }))}
                className="w-full border border-border bg-card rounded-ctl px-3 py-2 text-text focus:border-accent focus:outline-none focus:shadow-[0_0_0_3px_var(--accent-soft)]"
                required
                data-testid="title-input"
              />
            </div>
            <div className="col-span-2">
              <label className="block text-sm font-medium mb-1 text-text">Message</label>
              <textarea
                value={form.message}
                onChange={e => setForm(f => ({ ...f, message: e.target.value }))}
                className="w-full border border-border bg-card rounded-ctl px-3 py-2 text-text focus:border-accent focus:outline-none focus:shadow-[0_0_0_3px_var(--accent-soft)]"
                rows={3}
                required
                data-testid="message-input"
              />
            </div>
            <div>
              <label className="block text-sm font-medium mb-1 text-text">Target Type</label>
              <select
                value={form.target_type}
                onChange={e => setForm(f => ({ ...f, target_type: e.target.value as TargetType }))}
                className="w-full border border-border bg-card rounded-ctl px-3 py-2 text-text focus:border-accent focus:outline-none focus:shadow-[0_0_0_3px_var(--accent-soft)]"
                data-testid="target-type-select"
              >
                <option value="all">All Organisations</option>
                <option value="country">By Country</option>
                <option value="trade_family">By Trade Family</option>
                <option value="plan_tier">By Plan Tier</option>
                <option value="specific_orgs">Specific Organisations</option>
              </select>
            </div>
            {form.target_type !== 'all' && (
              <div>
                <label className="block text-sm font-medium mb-1 text-text">Target Value</label>
                <input
                  type="text"
                  value={form.target_value}
                  onChange={e => setForm(f => ({ ...f, target_value: e.target.value }))}
                  className="w-full border border-border bg-card rounded-ctl px-3 py-2 text-text focus:border-accent focus:outline-none focus:shadow-[0_0_0_3px_var(--accent-soft)]"
                  placeholder='e.g. "NZ" or ["NZ","AU"]'
                  data-testid="target-value-input"
                />
              </div>
            )}
            <div>
              <label className="block text-sm font-medium mb-1 text-text">Scheduled At</label>
              <input
                type="datetime-local"
                value={form.scheduled_at}
                onChange={e => setForm(f => ({ ...f, scheduled_at: e.target.value }))}
                className="w-full border border-border bg-card rounded-ctl px-3 py-2 text-text focus:border-accent focus:outline-none focus:shadow-[0_0_0_3px_var(--accent-soft)]"
                data-testid="scheduled-at-input"
              />
            </div>
            <div>
              <label className="block text-sm font-medium mb-1 text-text">Expires At</label>
              <input
                type="datetime-local"
                value={form.expires_at}
                onChange={e => setForm(f => ({ ...f, expires_at: e.target.value }))}
                className="w-full border border-border bg-card rounded-ctl px-3 py-2 text-text focus:border-accent focus:outline-none focus:shadow-[0_0_0_3px_var(--accent-soft)]"
                data-testid="expires-at-input"
              />
            </div>
            {form.notification_type === 'maintenance' && (
              <>
                <div>
                  <label className="block text-sm font-medium mb-1 text-text">Maintenance Start</label>
                  <input
                    type="datetime-local"
                    value={form.maintenance_start}
                    onChange={e => setForm(f => ({ ...f, maintenance_start: e.target.value }))}
                    className="w-full border border-border bg-card rounded-ctl px-3 py-2 text-text focus:border-accent focus:outline-none focus:shadow-[0_0_0_3px_var(--accent-soft)]"
                    data-testid="maintenance-start-input"
                  />
                </div>
                <div>
                  <label className="block text-sm font-medium mb-1 text-text">Maintenance End</label>
                  <input
                    type="datetime-local"
                    value={form.maintenance_end}
                    onChange={e => setForm(f => ({ ...f, maintenance_end: e.target.value }))}
                    className="w-full border border-border bg-card rounded-ctl px-3 py-2 text-text focus:border-accent focus:outline-none focus:shadow-[0_0_0_3px_var(--accent-soft)]"
                    data-testid="maintenance-end-input"
                  />
                </div>
              </>
            )}
          </div>
          <div className="flex gap-2 mt-4">
            <button
              type="submit"
              className="px-4 py-2 bg-accent text-white rounded-ctl hover:bg-accent-press"
              data-testid="submit-btn"
            >
              {editingId ? 'Update' : 'Create'}
            </button>
            <button
              type="button"
              onClick={() => { setShowForm(false); setEditingId(null); setForm(EMPTY_FORM) }}
              className="px-4 py-2 bg-canvas border border-border rounded-ctl hover:bg-border/40 text-text"
              data-testid="cancel-btn"
            >
              Cancel
            </button>
          </div>
        </form>
      )}

      {/* Notification list */}
      {loading ? (
        <p className="text-muted">Loading notifications...</p>
      ) : notifications.length === 0 ? (
        <p className="text-muted" data-testid="empty-state">No notifications found.</p>
      ) : (
        <div className="space-y-3" data-testid="notification-list">
          {notifications.map(notif => (
            <div
              key={notif.id}
              className={`p-4 border border-border rounded-card ${notif.is_active ? 'bg-card' : 'bg-canvas opacity-60'}`}
              data-testid={`notification-item-${notif.id}`}
            >
              <div className="flex items-start justify-between">
                <div className="flex-1">
                  <div className="flex items-center gap-2 mb-1">
                    <span className={`px-2 py-0.5 rounded text-xs font-medium ${TYPE_BADGE[notif.notification_type]}`}>
                      {notif.notification_type}
                    </span>
                    <span className={`px-2 py-0.5 rounded text-xs font-medium ${SEVERITY_BADGE[notif.severity]}`}>
                      {notif.severity}
                    </span>
                    {!notif.is_active && (
                      <span className="px-2 py-0.5 rounded text-xs font-medium bg-canvas text-muted">
                        inactive
                      </span>
                    )}
                    {notif.published_at ? (
                      <span className="text-xs text-ok">Published</span>
                    ) : (
                      <span className="text-xs text-warn">Scheduled</span>
                    )}
                  </div>
                  <h3 className="font-semibold text-text">{notif.title}</h3>
                  <p className="text-sm text-muted mt-1">{notif.message}</p>
                  <div className="text-xs text-muted-2 mt-2">
                    Target: {notif.target_type}
                    {notif.target_value && ` → ${notif.target_value}`}
                  </div>
                </div>
                <div className="flex gap-2 ml-4">
                  {!notif.published_at && notif.is_active && (
                    <button
                      onClick={() => handlePublish(notif.id)}
                      className="px-3 py-1 text-sm bg-ok-soft text-ok rounded hover:brightness-95"
                      data-testid={`publish-btn-${notif.id}`}
                    >
                      Publish
                    </button>
                  )}
                  <button
                    onClick={() => handleEdit(notif)}
                    className="px-3 py-1 text-sm bg-canvas border border-border rounded hover:bg-border/40 text-text"
                    data-testid={`edit-btn-${notif.id}`}
                  >
                    Edit
                  </button>
                  {notif.is_active && (
                    <button
                      onClick={() => handleDelete(notif.id)}
                      className="px-3 py-1 text-sm bg-danger-soft text-danger rounded hover:brightness-95"
                      data-testid={`deactivate-btn-${notif.id}`}
                    >
                      Deactivate
                    </button>
                  )}
                </div>
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  )
}
