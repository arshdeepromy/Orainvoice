import { useState, useEffect, useCallback } from 'react'
import apiClient from '../../api/client'
import { Button, Input, Select, Spinner, Modal } from '../../components/ui'

/* ------------------------------------------------------------------ */
/*  Types                                                              */
/* ------------------------------------------------------------------ */

interface ManualReminder {
  id: string
  name: string
  description: string
}

interface ReminderRule {
  id: string
  org_id: string
  name: string
  reminder_type: string
  target: string
  days_offset: number
  timing: string
  reference_date: string
  send_email: boolean
  send_sms: boolean
  is_enabled: boolean
  sort_order: number
  /** true when the rule hasn't been persisted yet */
  _isNew?: boolean
}

interface RemindersResponse {
  manual_reminders: ManualReminder[]
  automated_reminders: ReminderRule[]
  total: number
}

/* ------------------------------------------------------------------ */
/*  Constants                                                          */
/* ------------------------------------------------------------------ */

const REMINDER_TYPE_OPTIONS = [
  { value: 'payment_due', label: 'Payment Due' },
  { value: 'payment_expected', label: 'Payment Expected' },
  { value: 'invoice_issued', label: 'Invoice Issued' },
  { value: 'quote_expiry', label: 'Quote Expiry' },
  { value: 'service_due', label: 'Service Due' },
  { value: 'custom', label: 'Custom' },
]

const TARGET_OPTIONS = [
  { value: 'customer', label: 'Remind customer' },
  { value: 'me', label: 'Remind me' },
  { value: 'both', label: 'Remind both' },
]

const TIMING_OPTIONS = [
  { value: 'before', label: 'Before' },
  { value: 'after', label: 'After' },
]

const REFERENCE_DATE_OPTIONS = [
  { value: 'due_date', label: 'Due date' },
  { value: 'expected_payment_date', label: 'Expected payment date' },
  { value: 'invoice_date', label: 'Invoice date' },
  { value: 'quote_expiry_date', label: 'Quote expiry date' },
  { value: 'service_due_date', label: 'Service due date' },
]

const CHANNEL_OPTIONS = [
  { value: 'email', label: 'Email only' },
  { value: 'sms', label: 'SMS only' },
  { value: 'both', label: 'Email + SMS' },
]

/** Map reminder_type to its natural reference_date */
const TYPE_TO_REFERENCE: Record<string, string> = {
  payment_due: 'due_date',
  payment_expected: 'expected_payment_date',
  invoice_issued: 'invoice_date',
  quote_expiry: 'quote_expiry_date',
  service_due: 'service_due_date',
  custom: 'due_date',
}

/* ------------------------------------------------------------------ */
/*  Helpers                                                            */
/* ------------------------------------------------------------------ */

function channelFromBooleans(send_email: boolean, send_sms: boolean): string {
  if (send_email && send_sms) return 'both'
  if (send_sms) return 'sms'
  return 'email'
}

function booleansFromChannel(channel: string): { send_email: boolean; send_sms: boolean } {
  switch (channel) {
    case 'both': return { send_email: true, send_sms: true }
    case 'sms': return { send_email: false, send_sms: true }
    default: return { send_email: true, send_sms: false }
  }
}

function formatSchedule(rule: ReminderRule): string {
  const targetLabel = TARGET_OPTIONS.find(o => o.value === rule.target)?.label || rule.target
  const timingLabel = rule.timing === 'before' ? 'Before' : 'After'
  const refLabel = REFERENCE_DATE_OPTIONS.find(o => o.value === rule.reference_date)?.label?.toLowerCase() || rule.reference_date
  return `${targetLabel} ${rule.days_offset} day(s) ${timingLabel} ${refLabel}`
}

/* ------------------------------------------------------------------ */
/*  Default form state                                                 */
/* ------------------------------------------------------------------ */

function defaultFormState(): ReminderRule {
  return {
    id: '',
    org_id: '',
    name: '',
    reminder_type: 'payment_due',
    target: 'customer',
    days_offset: 0,
    timing: 'after',
    reference_date: 'due_date',
    send_email: true,
    send_sms: false,
    is_enabled: true,
    sort_order: 0,
    _isNew: true,
  }
}

/* ------------------------------------------------------------------ */
/*  Component                                                          */
/* ------------------------------------------------------------------ */

export default function Reminders() {
  const [manualReminders, setManualReminders] = useState<ManualReminder[]>([])
  const [rules, setRules] = useState<ReminderRule[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const [saving, setSaving] = useState(false)

  // Modal state
  const [modalOpen, setModalOpen] = useState(false)
  const [editingRule, setEditingRule] = useState<ReminderRule>(defaultFormState())
  const [isEditing, setIsEditing] = useState(false)

  // Actions menu
  const [actionsOpenId, setActionsOpenId] = useState<string | null>(null)

  const fetchReminders = useCallback(async () => {
    setLoading(true)
    setError('')
    try {
      const res = await apiClient.get<RemindersResponse>('/notifications/reminders')
      setManualReminders(res.data?.manual_reminders ?? [])
      setRules(res.data?.automated_reminders ?? [])
    } catch {
      setError('Failed to load reminders.')
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => { fetchReminders() }, [fetchReminders])

  // Close actions menu on outside click
  useEffect(() => {
    if (!actionsOpenId) return
    const handler = () => setActionsOpenId(null)
    document.addEventListener('click', handler)
    return () => document.removeEventListener('click', handler)
  }, [actionsOpenId])

  /* ---- Modal handlers ---- */

  const openNewReminder = () => {
    setEditingRule(defaultFormState())
    setIsEditing(false)
    setModalOpen(true)
  }

  const openEditReminder = (rule: ReminderRule) => {
    setEditingRule({ ...rule })
    setIsEditing(true)
    setModalOpen(true)
    setActionsOpenId(null)
  }

  const handleFormChange = (updates: Partial<ReminderRule>) => {
    setEditingRule(prev => {
      const next = { ...prev, ...updates }
      // Auto-set reference_date when reminder_type changes
      if (updates.reminder_type && !updates.reference_date) {
        next.reference_date = TYPE_TO_REFERENCE[updates.reminder_type] || 'due_date'
      }
      return next
    })
  }

  const handleSaveRule = async () => {
    if (!editingRule.name.trim()) {
      setError('Reminder name is required.')
      return
    }
    setSaving(true)
    setError('')
    try {
      const payload = {
        name: editingRule.name,
        reminder_type: editingRule.reminder_type,
        target: editingRule.target,
        days_offset: editingRule.days_offset,
        timing: editingRule.timing,
        reference_date: editingRule.reference_date,
        send_email: editingRule.send_email,
        send_sms: editingRule.send_sms,
        is_enabled: editingRule.is_enabled,
      }
      if (isEditing) {
        await apiClient.put(`/notifications/reminders/${editingRule.id}`, payload)
      } else {
        await apiClient.post('/notifications/reminders', payload)
      }
      setModalOpen(false)
      await fetchReminders()
    } catch {
      setError('Failed to save reminder rule.')
    } finally {
      setSaving(false)
    }
  }

  /* ---- Toggle ---- */

  const handleToggle = async (rule: ReminderRule) => {
    setSaving(true)
    setError('')
    // Optimistic update
    setRules(prev => prev.map(r => r.id === rule.id ? { ...r, is_enabled: !r.is_enabled } : r))
    try {
      await apiClient.put(`/notifications/reminders/${rule.id}/toggle?enabled=${!rule.is_enabled}`)
    } catch {
      // Revert
      setRules(prev => prev.map(r => r.id === rule.id ? { ...r, is_enabled: rule.is_enabled } : r))
      setError('Failed to toggle reminder.')
    } finally {
      setSaving(false)
    }
  }

  /* ---- Delete ---- */

  const handleDelete = async (ruleId: string) => {
    setSaving(true)
    setError('')
    setActionsOpenId(null)
    try {
      await apiClient.delete(`/notifications/reminders/${ruleId}`)
      setRules(prev => prev.filter(r => r.id !== ruleId))
    } catch {
      setError('Failed to delete reminder.')
    } finally {
      setSaving(false)
    }
  }

  /* ---- Group automated reminders by reference_date ---- */

  const groupedByRef: Record<string, ReminderRule[]> = {}
  for (const rule of rules) {
    const key = rule.reference_date
    if (!groupedByRef[key]) groupedByRef[key] = []
    groupedByRef[key].push(rule)
  }

  const refDateLabel = (ref: string) =>
    REFERENCE_DATE_OPTIONS.find(o => o.value === ref)?.label || ref.replace(/_/g, ' ')

  if (loading) {
    return <div className="py-16"><Spinner label="Loading reminders" /></div>
  }

  return (
    <div>
      <p className="text-sm text-gray-500 mb-6">
        Configure manual and automated reminders for invoices, payments, quotes, and services.
      </p>

      {error && (
        <div className="mb-4 rounded-md border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700" role="alert">
          {error}
        </div>
      )}

      {/* Manual Reminders */}
      <section className="mb-8">
        <h3 className="text-lg font-medium text-gray-900 mb-3">Manual Reminders</h3>
        <div className="rounded-lg border border-gray-200 bg-white overflow-hidden">
          <table className="min-w-full divide-y divide-gray-200">
            <thead className="bg-gray-50">
              <tr>
                <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">Name</th>
                <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">Description</th>
                <th className="px-4 py-3 text-right text-xs font-medium text-gray-500 uppercase tracking-wider">Actions</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-gray-100">
              {manualReminders.map(mr => (
                <tr key={mr.id}>
                  <td className="px-4 py-3 text-sm text-blue-600 font-medium">{mr.name}</td>
                  <td className="px-4 py-3 text-sm text-gray-600">{mr.description}</td>
                  <td className="px-4 py-3 text-right">
                    <span className="text-gray-400 text-sm" title="Edit template in Templates tab">
                      <svg className="w-4 h-4 inline" fill="none" stroke="currentColor" viewBox="0 0 24 24" aria-hidden="true">
                        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M15.232 5.232l3.536 3.536m-2.036-5.036a2.5 2.5 0 113.536 3.536L6.5 21.036H3v-3.572L16.732 3.732z" />
                      </svg>
                    </span>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </section>

      {/* Automated Reminders */}
      <section>
        <h3 className="text-lg font-medium text-gray-900 mb-3">Automated Reminders</h3>
        <div className="rounded-lg border border-gray-200 bg-white overflow-hidden">
          <table className="min-w-full divide-y divide-gray-200">
            <thead className="bg-gray-50">
              <tr>
                <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">Name</th>
                <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">Schedule</th>
                <th className="px-4 py-3 text-center text-xs font-medium text-gray-500 uppercase tracking-wider">Status</th>
                <th className="px-4 py-3 text-right text-xs font-medium text-gray-500 uppercase tracking-wider">Actions</th>
              </tr>
            </thead>
            {Object.entries(groupedByRef).map(([refDate, groupRules]) => (
              <tbody key={`group-${refDate}`} className="divide-y divide-gray-100">
                <tr className="bg-gray-50">
                  <td colSpan={4} className="px-4 py-2 text-xs font-semibold text-gray-700 uppercase">
                    Reminders Based on {refDateLabel(refDate)}
                  </td>
                </tr>
                {groupRules.map(rule => (
                  <tr key={rule.id}>
                    <td className="px-4 py-3 text-sm text-blue-600 font-medium">
                      {rule.name}
                    </td>
                    <td className="px-4 py-3 text-sm text-gray-600">
                      {formatSchedule(rule)}
                    </td>
                    <td className="px-4 py-3 text-center">
                      <button
                        role="switch"
                        aria-checked={rule.is_enabled}
                        aria-label={`Toggle ${rule.name}`}
                        onClick={() => handleToggle(rule)}
                        disabled={saving}
                        className={`relative inline-flex h-6 w-11 shrink-0 cursor-pointer rounded-full border-2 border-transparent transition-colors
                          focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-blue-500 focus-visible:ring-offset-2
                          ${rule.is_enabled ? 'bg-blue-600' : 'bg-gray-200'}
                          ${saving ? 'opacity-50' : ''}`}
                      >
                        <span
                          aria-hidden="true"
                          className={`pointer-events-none inline-block h-5 w-5 rounded-full bg-white shadow ring-0 transition-transform
                            ${rule.is_enabled ? 'translate-x-5' : 'translate-x-0'}`}
                        />
                      </button>
                    </td>
                    <td className="px-4 py-3 text-right">
                      <div className="relative inline-block">
                        <button
                          onClick={(e) => { e.stopPropagation(); setActionsOpenId(actionsOpenId === rule.id ? null : rule.id) }}
                          className="text-gray-400 hover:text-gray-600 p-1"
                          aria-label={`Actions for ${rule.name}`}
                        >
                          <svg className="w-5 h-5" fill="currentColor" viewBox="0 0 20 20" aria-hidden="true">
                            <path d="M10 6a2 2 0 110-4 2 2 0 010 4zM10 12a2 2 0 110-4 2 2 0 010 4zM10 18a2 2 0 110-4 2 2 0 010 4z" />
                          </svg>
                        </button>
                        {actionsOpenId === rule.id && (
                          <div className="absolute right-0 z-10 mt-1 w-36 rounded-md border border-gray-200 bg-white shadow-lg">
                            <button
                              onClick={() => openEditReminder(rule)}
                              className="block w-full px-4 py-2 text-left text-sm text-gray-700 hover:bg-gray-50"
                            >
                              Edit
                            </button>
                            <button
                              onClick={() => handleDelete(rule.id)}
                              className="block w-full px-4 py-2 text-left text-sm text-red-600 hover:bg-red-50"
                            >
                              Delete
                            </button>
                          </div>
                        )}
                      </div>
                    </td>
                  </tr>
                ))}
              </tbody>
            ))}
            {rules.length === 0 && (
              <tbody>
                <tr>
                  <td colSpan={4} className="px-4 py-6 text-center text-sm text-gray-400 italic">
                    No automated reminders configured yet.
                  </td>
                </tr>
              </tbody>
            )}
          </table>
        </div>

        <button
          onClick={openNewReminder}
          className="mt-4 inline-flex items-center gap-1 text-sm font-medium text-blue-600 hover:text-blue-700"
        >
          <svg className="w-4 h-4" fill="currentColor" viewBox="0 0 20 20" aria-hidden="true">
            <path fillRule="evenodd" d="M10 3a1 1 0 011 1v5h5a1 1 0 110 2h-5v5a1 1 0 11-2 0v-5H4a1 1 0 110-2h5V4a1 1 0 011-1z" clipRule="evenodd" />
          </svg>
          New Reminder
        </button>
      </section>

      {/* Create / Edit Modal */}
      <Modal
        open={modalOpen}
        onClose={() => setModalOpen(false)}
        title={isEditing ? 'Edit Reminder' : 'New Reminder'}
      >
        <div className="space-y-4">
          <Input
            label="Reminder Name"
            value={editingRule.name}
            onChange={(e) => handleFormChange({ name: e.target.value })}
            placeholder="e.g. Reminder - 1"
          />

          <Select
            label="Reminder Type"
            value={editingRule.reminder_type}
            onChange={(e) => handleFormChange({ reminder_type: e.target.value })}
            options={REMINDER_TYPE_OPTIONS}
            disabled={isEditing}
          />

          <Select
            label="Who to Remind"
            value={editingRule.target}
            onChange={(e) => handleFormChange({ target: e.target.value })}
            options={TARGET_OPTIONS}
          />

          <div className="grid grid-cols-2 gap-3">
            <Input
              label="Days"
              type="number"
              min={0}
              max={365}
              value={String(editingRule.days_offset)}
              onChange={(e) => handleFormChange({ days_offset: Math.max(0, parseInt(e.target.value) || 0) })}
            />
            <Select
              label="Timing"
              value={editingRule.timing}
              onChange={(e) => handleFormChange({ timing: e.target.value })}
              options={TIMING_OPTIONS}
            />
          </div>

          <Select
            label="Reference Date"
            value={editingRule.reference_date}
            onChange={(e) => handleFormChange({ reference_date: e.target.value })}
            options={REFERENCE_DATE_OPTIONS}
          />

          <Select
            label="Send Via"
            value={channelFromBooleans(editingRule.send_email, editingRule.send_sms)}
            onChange={(e) => {
              const bools = booleansFromChannel(e.target.value)
              handleFormChange({ send_email: bools.send_email, send_sms: bools.send_sms })
            }}
            options={CHANNEL_OPTIONS}
          />

          <div className="flex items-center gap-3">
            <button
              role="switch"
              aria-checked={editingRule.is_enabled}
              aria-label="Enable this reminder"
              onClick={() => handleFormChange({ is_enabled: !editingRule.is_enabled })}
              className={`relative inline-flex h-6 w-11 shrink-0 cursor-pointer rounded-full border-2 border-transparent transition-colors
                focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-blue-500 focus-visible:ring-offset-2
                ${editingRule.is_enabled ? 'bg-blue-600' : 'bg-gray-200'}`}
            >
              <span
                aria-hidden="true"
                className={`pointer-events-none inline-block h-5 w-5 rounded-full bg-white shadow ring-0 transition-transform
                  ${editingRule.is_enabled ? 'translate-x-5' : 'translate-x-0'}`}
              />
            </button>
            <span className="text-sm text-gray-700">
              {editingRule.is_enabled ? 'Enabled' : 'Disabled'}
            </span>
          </div>

          <div className="flex justify-end gap-3 pt-2">
            <Button variant="secondary" onClick={() => setModalOpen(false)}>Cancel</Button>
            <Button onClick={handleSaveRule} loading={saving}>
              {isEditing ? 'Save Changes' : 'Create Reminder'}
            </Button>
          </div>
        </div>
      </Modal>
    </div>
  )
}
