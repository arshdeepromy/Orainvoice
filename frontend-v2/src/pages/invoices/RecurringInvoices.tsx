import { useState, useEffect, useCallback } from 'react'
import apiClient from '@/api/client'
import { Button, Input, Select, Badge, Spinner, Modal } from '@/components/ui'
import type { BadgeVariant } from '@/components/ui'

/* ------------------------------------------------------------------ */
/*  Types                                                              */
/* ------------------------------------------------------------------ */

type Frequency = 'weekly' | 'fortnightly' | 'monthly' | 'quarterly' | 'annually'
type LineItemType = 'service' | 'part' | 'labour'

interface RecurringLineItem {
  item_type: LineItemType
  description: string
  quantity: number
  unit_price: number
  hours?: number
  hourly_rate?: number
  is_gst_exempt: boolean
  warranty_note?: string
  discount_type?: string
  discount_value?: number
}

interface RecurringSchedule {
  id: string
  org_id: string
  customer_id: string
  frequency: Frequency
  line_items: RecurringLineItem[]
  auto_issue: boolean
  is_active: boolean
  next_due_date: string | null
  last_generated_at: string | null
  notes: string | null
  created_by: string
  created_at: string
  updated_at: string
}

interface RecurringScheduleListResponse {
  schedules: RecurringSchedule[]
  total: number
}

interface CustomerOption {
  id: string
  first_name: string
  last_name: string
  email: string
  phone: string
}

/* ------------------------------------------------------------------ */
/*  Helpers                                                            */
/* ------------------------------------------------------------------ */

function formatDate(dateStr: string | null): string {
  if (!dateStr) return '—'
  return new Intl.DateTimeFormat('en-NZ', { day: '2-digit', month: '2-digit', year: 'numeric' }).format(new Date(dateStr))
}

function formatNZD(amount: number): string {
  return new Intl.NumberFormat('en-NZ', { style: 'currency', currency: 'NZD' }).format(amount)
}

const FREQUENCY_LABELS: Record<Frequency, string> = {
  weekly: 'Weekly',
  fortnightly: 'Fortnightly',
  monthly: 'Monthly',
  quarterly: 'Quarterly',
  annually: 'Annually',
}

const FREQUENCY_OPTIONS = [
  { value: 'weekly', label: 'Weekly' },
  { value: 'fortnightly', label: 'Fortnightly' },
  { value: 'monthly', label: 'Monthly' },
  { value: 'quarterly', label: 'Quarterly' },
  { value: 'annually', label: 'Annually' },
]

const LINE_ITEM_TYPE_OPTIONS = [
  { value: 'service', label: 'Service' },
  { value: 'part', label: 'Part' },
  { value: 'labour', label: 'Labour' },
]

function calcLineTotal(item: RecurringLineItem): number {
  if (item.item_type === 'labour' && item.hours != null && item.hourly_rate != null) {
    return item.hours * item.hourly_rate
  }
  return item.quantity * item.unit_price
}

function emptyLineItem(): RecurringLineItem {
  return {
    item_type: 'service',
    description: '',
    quantity: 1,
    unit_price: 0,
    is_gst_exempt: false,
  }
}

function getStatusConfig(schedule: RecurringSchedule): { label: string; variant: BadgeVariant } {
  if (schedule.is_active) return { label: 'Active', variant: 'success' }
  return { label: 'Paused / Cancelled', variant: 'neutral' }
}

/* ------------------------------------------------------------------ */
/*  Schedule Form (Create / Edit)                                      */
/* ------------------------------------------------------------------ */

interface ScheduleFormProps {
  initial?: RecurringSchedule | null
  onSave: () => void
  onCancel: () => void
}

function ScheduleForm({ initial, onSave, onCancel }: ScheduleFormProps) {
  const isEdit = !!initial

  /* Customer search */
  const [customerQuery, setCustomerQuery] = useState('')
  const [customerResults, setCustomerResults] = useState<CustomerOption[]>([])
  const [customerLoading, setCustomerLoading] = useState(false)
  const [selectedCustomer, setSelectedCustomer] = useState<CustomerOption | null>(null)
  const [showCustomerDropdown, setShowCustomerDropdown] = useState(false)

  /* Form fields */
  const [customerId, setCustomerId] = useState(initial?.customer_id ?? '')
  const [frequency, setFrequency] = useState<Frequency>(initial?.frequency ?? 'monthly')
  const [nextDueDate, setNextDueDate] = useState(initial?.next_due_date ?? '')
  const [autoIssue, setAutoIssue] = useState(initial?.auto_issue ?? false)
  const [notes, setNotes] = useState(initial?.notes ?? '')
  const [lineItems, setLineItems] = useState<RecurringLineItem[]>(
    initial?.line_items?.length ? initial.line_items : [emptyLineItem()],
  )

  const [saving, setSaving] = useState(false)
  const [error, setError] = useState('')

  /* Customer search debounce */
  useEffect(() => {
    if (customerQuery.trim().length < 2) {
      setCustomerResults([])
      return
    }
    const controller = new AbortController()
    const timer = setTimeout(async () => {
      setCustomerLoading(true)
      try {
        const res = await apiClient.get<{ items?: CustomerOption[]; customers?: CustomerOption[] }>('/customers', {
          params: { search: customerQuery.trim(), page_size: 8 },
          signal: controller.signal,
        })
        setCustomerResults(res.data?.items ?? res.data?.customers ?? [])
        setShowCustomerDropdown(true)
      } catch {
        if (!controller.signal.aborted) setCustomerResults([])
      } finally {
        if (!controller.signal.aborted) setCustomerLoading(false)
      }
    }, 300)
    return () => {
      clearTimeout(timer)
      controller.abort()
    }
  }, [customerQuery])

  /* Line item helpers */
  const updateLineItem = (idx: number, patch: Partial<RecurringLineItem>) => {
    setLineItems((prev) => prev.map((li, i) => (i === idx ? { ...li, ...patch } : li)))
  }

  const removeLineItem = (idx: number) => {
    setLineItems((prev) => (prev.length <= 1 ? prev : prev.filter((_, i) => i !== idx)))
  }

  const addLineItem = () => setLineItems((prev) => [...prev, emptyLineItem()])

  /* Submit */
  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault()
    setError('')

    const cid = customerId || selectedCustomer?.id
    if (!cid) { setError('Please select a customer.'); return }
    if (!nextDueDate) { setError('Please set the next due date.'); return }
    if (lineItems.some((li) => !li.description.trim())) {
      setError('All line items must have a description.')
      return
    }

    setSaving(true)
    try {
      if (isEdit && initial) {
        await apiClient.put(`/invoices/recurring/${initial.id}`, {
          frequency,
          line_items: lineItems,
          next_due_date: nextDueDate,
          auto_issue: autoIssue,
          notes: notes || null,
        })
      } else {
        await apiClient.post('/invoices/recurring', {
          customer_id: cid,
          frequency,
          line_items: lineItems,
          next_due_date: nextDueDate,
          auto_issue: autoIssue,
          notes: notes || null,
        })
      }
      onSave()
    } catch (err: unknown) {
      const detail = (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail
      setError(detail || 'Failed to save recurring schedule.')
    } finally {
      setSaving(false)
    }
  }

  const subtotal = lineItems.reduce((sum, li) => sum + calcLineTotal(li), 0)

  return (
    <form onSubmit={handleSubmit} className="space-y-6">
      {error && (
        <div className="rounded-ctl border border-danger bg-danger-soft px-4 py-3 text-sm text-danger" role="alert">
          {error}
        </div>
      )}

      {/* Customer selection */}
      {!isEdit && (
        <div className="relative">
          <Input
            label="Customer"
            placeholder="Search by name, email, or phone…"
            value={selectedCustomer ? `${selectedCustomer.first_name} ${selectedCustomer.last_name}` : customerQuery}
            onChange={(e) => {
              setCustomerQuery(e.target.value)
              setSelectedCustomer(null)
              setCustomerId('')
            }}
            onFocus={() => customerResults.length > 0 && setShowCustomerDropdown(true)}
            aria-label="Search customers"
          />
          {customerLoading && (
            <div className="absolute right-3 top-9">
              <Spinner label="" />
            </div>
          )}
          {showCustomerDropdown && customerResults.length > 0 && !selectedCustomer && (
            <ul
              className="absolute z-20 mt-1 max-h-48 w-full overflow-auto rounded-card border border-border bg-card shadow-pop"
              role="listbox"
              aria-label="Customer search results"
            >
              {customerResults && customerResults.length > 0 && customerResults.map((c) => (
                <li
                  key={c.id}
                  role="option"
                  aria-selected={false}
                  className="cursor-pointer px-4 py-2 text-sm text-text hover:bg-accent-soft"
                  onClick={() => {
                    setSelectedCustomer(c)
                    setCustomerId(c.id)
                    setShowCustomerDropdown(false)
                    setCustomerQuery('')
                  }}
                >
                  <span className="font-medium">{c.first_name} {c.last_name}</span>
                  {c.email && <span className="ml-2 text-muted">{c.email}</span>}
                  {c.phone && <span className="ml-2 text-muted-2">{c.phone}</span>}
                </li>
              ))}
            </ul>
          )}
        </div>
      )}

      {/* Frequency & next due date */}
      <div className="grid grid-cols-1 gap-4 sm:grid-cols-3">
        <Select
          label="Frequency"
          options={FREQUENCY_OPTIONS}
          value={frequency}
          onChange={(e) => setFrequency(e.target.value as Frequency)}
        />
        <Input
          label="Next due date"
          type="date"
          value={nextDueDate}
          onChange={(e) => setNextDueDate(e.target.value)}
          required
        />
        <div className="flex items-end pb-1">
          <label className="flex items-center gap-2 text-sm text-text cursor-pointer">
            <input
              type="checkbox"
              checked={autoIssue}
              onChange={(e) => setAutoIssue(e.target.checked)}
              className="h-4 w-4 rounded border-border text-accent focus:ring-accent"
            />
            Auto-issue (otherwise creates as Draft)
          </label>
        </div>
      </div>

      {/* Line items */}
      <fieldset>
        <legend className="text-sm font-medium text-text mb-2">Line Items</legend>
        <div className="space-y-3">
          {lineItems.map((li, idx) => (
            <div key={idx} className="grid grid-cols-1 gap-3 rounded-card border border-border bg-canvas p-3 sm:grid-cols-12 sm:items-end">
              <div className="sm:col-span-2">
                <Select
                  label="Type"
                  options={LINE_ITEM_TYPE_OPTIONS}
                  value={li.item_type}
                  onChange={(e) => updateLineItem(idx, { item_type: e.target.value as LineItemType })}
                />
              </div>
              <div className="sm:col-span-4">
                <Input
                  label="Description"
                  value={li.description}
                  onChange={(e) => updateLineItem(idx, { description: e.target.value })}
                  required
                />
              </div>
              {li.item_type === 'labour' ? (
                <>
                  <div className="sm:col-span-2">
                    <Input
                      label="Hours"
                      type="number"
                      min="0"
                      step="0.25"
                      value={li.hours ?? ''}
                      onChange={(e) => updateLineItem(idx, { hours: parseFloat(e.target.value) || 0 })}
                    />
                  </div>
                  <div className="sm:col-span-2">
                    <Input
                      label="Rate ($/hr)"
                      type="number"
                      min="0"
                      step="0.01"
                      value={li.hourly_rate ?? ''}
                      onChange={(e) => updateLineItem(idx, { hourly_rate: parseFloat(e.target.value) || 0 })}
                    />
                  </div>
                </>
              ) : (
                <>
                  <div className="sm:col-span-2">
                    <Input
                      label="Qty"
                      type="number"
                      min="0"
                      step="1"
                      value={li.quantity}
                      onChange={(e) => updateLineItem(idx, { quantity: parseFloat(e.target.value) || 0 })}
                    />
                  </div>
                  <div className="sm:col-span-2">
                    <Input
                      label="Unit price"
                      type="number"
                      min="0"
                      step="0.01"
                      value={li.unit_price}
                      onChange={(e) => updateLineItem(idx, { unit_price: parseFloat(e.target.value) || 0 })}
                    />
                  </div>
                </>
              )}
              <div className="sm:col-span-1 flex items-end justify-between gap-2">
                <span className="mono text-sm font-medium text-text">
                  {formatNZD(calcLineTotal(li))}
                </span>
                {lineItems.length > 1 && (
                  <button
                    type="button"
                    onClick={() => removeLineItem(idx)}
                    className="text-danger hover:brightness-95 text-sm focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-danger rounded"
                    aria-label={`Remove line item ${idx + 1}`}
                  >
                    ✕
                  </button>
                )}
              </div>
            </div>
          ))}
        </div>
        <div className="mt-3 flex items-center justify-between">
          <Button type="button" variant="ghost" size="sm" onClick={addLineItem}>
            + Add Line Item
          </Button>
          <span className="mono text-sm font-semibold text-text">
            Subtotal: {formatNZD(subtotal)}
          </span>
        </div>
      </fieldset>

      {/* Notes */}
      <div>
        <label htmlFor="schedule-notes" className="block text-sm font-medium text-text mb-1">
          Notes (optional)
        </label>
        <textarea
          id="schedule-notes"
          rows={3}
          className="w-full rounded-ctl border border-border bg-card px-3 py-2 text-sm text-text shadow-sm focus:border-accent focus:outline-none focus:shadow-[0_0_0_3px_var(--accent-soft)]"
          value={notes}
          onChange={(e) => setNotes(e.target.value)}
          placeholder="Internal notes for this recurring schedule…"
        />
      </div>

      {/* Actions */}
      <div className="flex items-center justify-end gap-3 border-t border-border pt-4">
        <Button type="button" variant="ghost" onClick={onCancel}>
          Cancel
        </Button>
        <Button type="submit" loading={saving}>
          {isEdit ? 'Save Changes' : 'Create Schedule'}
        </Button>
      </div>
    </form>
  )
}

/* ------------------------------------------------------------------ */
/*  Main Component                                                     */
/* ------------------------------------------------------------------ */

export default function RecurringInvoices() {
  const [schedules, setSchedules] = useState<RecurringSchedule[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const [activeOnly, setActiveOnly] = useState(false)

  /* Modal state */
  const [formOpen, setFormOpen] = useState(false)
  const [editingSchedule, setEditingSchedule] = useState<RecurringSchedule | null>(null)

  /* Confirm modal for pause / cancel */
  const [confirmAction, setConfirmAction] = useState<{ type: 'pause' | 'cancel'; schedule: RecurringSchedule } | null>(null)
  const [actionLoading, setActionLoading] = useState(false)
  const [actionMessage, setActionMessage] = useState('')

  /* Fetch schedules */
  const fetchSchedules = useCallback(async () => {
    setLoading(true)
    setError('')
    try {
      const res = await apiClient.get<RecurringScheduleListResponse>('/invoices/recurring', {
        params: activeOnly ? { active_only: true } : {},
      })
      setSchedules(res.data?.schedules ?? [])
    } catch {
      setError('Failed to load recurring schedules.')
    } finally {
      setLoading(false)
    }
  }, [activeOnly])

  useEffect(() => {
    fetchSchedules()
  }, [fetchSchedules])

  /* Open create form */
  const openCreate = () => {
    setEditingSchedule(null)
    setFormOpen(true)
  }

  /* Open edit form */
  const openEdit = (schedule: RecurringSchedule) => {
    setEditingSchedule(schedule)
    setFormOpen(true)
  }

  /* Close form */
  const closeForm = () => {
    setFormOpen(false)
    setEditingSchedule(null)
  }

  /* After save */
  const handleSaved = () => {
    closeForm()
    fetchSchedules()
    setActionMessage(editingSchedule ? 'Schedule updated.' : 'Schedule created.')
  }

  /* Pause / Cancel */
  const handleConfirmAction = async () => {
    if (!confirmAction) return
    setActionLoading(true)
    try {
      const endpoint = confirmAction.type === 'pause' ? 'pause' : 'cancel'
      await apiClient.post(`/invoices/recurring/${confirmAction.schedule.id}/${endpoint}`)
      setActionMessage(
        confirmAction.type === 'pause'
          ? 'Schedule paused.'
          : 'Schedule cancelled.',
      )
      setConfirmAction(null)
      fetchSchedules()
    } catch (err: unknown) {
      const detail = (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail
      setActionMessage(detail || `Failed to ${confirmAction.type} schedule.`)
    } finally {
      setActionLoading(false)
    }
  }

  return (
    <div className="px-4 py-6 sm:px-6 lg:px-8">
      {/* Header */}
      <div className="flex flex-col gap-4 sm:flex-row sm:items-center sm:justify-between mb-6">
        <div>
          <h1 className="text-2xl font-semibold text-text">Recurring Invoices</h1>
          <p className="mt-1 text-sm text-muted">
            Manage automated recurring invoice schedules for regular customers.
          </p>
        </div>
        <Button onClick={openCreate}>+ New Schedule</Button>
      </div>

      {/* Filter */}
      <div className="mb-4 flex items-center gap-3">
        <label className="flex items-center gap-2 text-sm text-text cursor-pointer">
          <input
            type="checkbox"
            checked={activeOnly}
            onChange={(e) => setActiveOnly(e.target.checked)}
            className="h-4 w-4 rounded border-border text-accent focus:ring-accent"
          />
          Show active only
        </label>
        <span className="text-sm text-muted-2">
          {schedules.length} schedule{schedules.length !== 1 ? 's' : ''}
        </span>
      </div>

      {/* Action message */}
      {actionMessage && (
        <div
          className="mb-4 rounded-ctl border border-border bg-canvas px-4 py-2 text-sm text-muted"
          role="status"
        >
          {actionMessage}
          <button
            onClick={() => setActionMessage('')}
            className="ml-3 text-muted-2 hover:text-text"
            aria-label="Dismiss message"
          >
            ✕
          </button>
        </div>
      )}

      {/* Error */}
      {error && (
        <div className="mb-4 rounded-ctl border border-danger bg-danger-soft px-4 py-3 text-sm text-danger" role="alert">
          {error}
        </div>
      )}

      {/* Loading */}
      {loading && schedules.length === 0 && (
        <div className="py-16">
          <Spinner label="Loading recurring schedules" />
        </div>
      )}

      {/* Schedule table */}
      {!loading && schedules.length === 0 && (
        <div className="py-16 text-center text-sm text-muted">
          No recurring schedules yet. Create one to automate repeat billing.
        </div>
      )}

      {schedules.length > 0 && (
        <div className="overflow-x-auto rounded-card border border-border bg-card shadow-card">
          <table className="min-w-full" role="grid">
            <caption className="sr-only">Recurring invoice schedules</caption>
            <thead>
              <tr>
                <th scope="col" className="mono border-b border-border px-4 py-3 text-left text-[10.5px] font-medium uppercase tracking-[0.08em] text-muted-2">
                  Customer
                </th>
                <th scope="col" className="mono border-b border-border px-4 py-3 text-left text-[10.5px] font-medium uppercase tracking-[0.08em] text-muted-2">
                  Frequency
                </th>
                <th scope="col" className="mono border-b border-border px-4 py-3 text-right text-[10.5px] font-medium uppercase tracking-[0.08em] text-muted-2">
                  Amount
                </th>
                <th scope="col" className="mono border-b border-border px-4 py-3 text-left text-[10.5px] font-medium uppercase tracking-[0.08em] text-muted-2">
                  Next Due
                </th>
                <th scope="col" className="mono border-b border-border px-4 py-3 text-left text-[10.5px] font-medium uppercase tracking-[0.08em] text-muted-2">
                  Last Generated
                </th>
                <th scope="col" className="mono border-b border-border px-4 py-3 text-left text-[10.5px] font-medium uppercase tracking-[0.08em] text-muted-2">
                  Status
                </th>
                <th scope="col" className="mono border-b border-border px-4 py-3 text-left text-[10.5px] font-medium uppercase tracking-[0.08em] text-muted-2">
                  Auto-Issue
                </th>
                <th scope="col" className="mono border-b border-border px-4 py-3 text-right text-[10.5px] font-medium uppercase tracking-[0.08em] text-muted-2">
                  Actions
                </th>
              </tr>
            </thead>
            <tbody>
              {schedules.map((s) => {
                const cfg = getStatusConfig(s)
                const total = s.line_items.reduce((sum, li) => sum + calcLineTotal(li), 0)
                return (
                  <tr key={s.id} className="border-b border-border last:border-b-0 hover:bg-canvas">
                    <td className="mono whitespace-nowrap px-4 py-3 text-sm text-text">
                      {s.customer_id.slice(0, 8)}…
                    </td>
                    <td className="whitespace-nowrap px-4 py-3 text-sm text-muted">
                      {FREQUENCY_LABELS[s.frequency] ?? s.frequency}
                    </td>
                    <td className="mono whitespace-nowrap px-4 py-3 text-sm text-text text-right">
                      {formatNZD(total)}
                    </td>
                    <td className="mono whitespace-nowrap px-4 py-3 text-sm text-muted">
                      {formatDate(s.next_due_date)}
                    </td>
                    <td className="mono whitespace-nowrap px-4 py-3 text-sm text-muted">
                      {formatDate(s.last_generated_at)}
                    </td>
                    <td className="whitespace-nowrap px-4 py-3 text-sm">
                      <Badge variant={cfg.variant}>{cfg.label}</Badge>
                    </td>
                    <td className="whitespace-nowrap px-4 py-3 text-sm text-muted">
                      {s.auto_issue ? 'Yes' : 'No'}
                    </td>
                    <td className="whitespace-nowrap px-4 py-3 text-sm text-right">
                      <div className="flex items-center justify-end gap-2">
                        <Button
                          size="sm"
                          variant="ghost"
                          onClick={() => openEdit(s)}
                          disabled={!s.is_active}
                        >
                          Edit
                        </Button>
                        {s.is_active && (
                          <Button
                            size="sm"
                            variant="ghost"
                            onClick={() => setConfirmAction({ type: 'pause', schedule: s })}
                          >
                            Pause
                          </Button>
                        )}
                        {s.is_active && (
                          <Button
                            size="sm"
                            variant="ghost"
                            onClick={() => setConfirmAction({ type: 'cancel', schedule: s })}
                          >
                            Cancel
                          </Button>
                        )}
                      </div>
                    </td>
                  </tr>
                )
              })}
            </tbody>
          </table>
        </div>
      )}

      {/* Create / Edit Modal */}
      <Modal
        open={formOpen}
        onClose={closeForm}
        title={editingSchedule ? 'Edit Recurring Schedule' : 'New Recurring Schedule'}
        className="max-w-3xl"
      >
        <ScheduleForm
          initial={editingSchedule}
          onSave={handleSaved}
          onCancel={closeForm}
        />
      </Modal>

      {/* Pause / Cancel Confirmation Modal */}
      <Modal
        open={!!confirmAction}
        onClose={() => setConfirmAction(null)}
        title={confirmAction?.type === 'pause' ? 'Pause Schedule' : 'Cancel Schedule'}
      >
        <div className="space-y-4">
          <p className="text-sm text-text">
            {confirmAction?.type === 'pause'
              ? 'Pausing this schedule will stop new invoices from being generated until it is resumed. You can resume it later.'
              : 'Cancelling this schedule is permanent. No further invoices will be generated from it.'}
          </p>
          <div className="flex items-center justify-end gap-3">
            <Button variant="ghost" onClick={() => setConfirmAction(null)}>
              Go Back
            </Button>
            <Button
              variant="primary"
              loading={actionLoading}
              onClick={handleConfirmAction}
            >
              {confirmAction?.type === 'pause' ? 'Pause Schedule' : 'Cancel Schedule'}
            </Button>
          </div>
        </div>
      </Modal>
    </div>
  )
}
