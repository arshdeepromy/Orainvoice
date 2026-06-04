/**
 * CustomerProfile — Task 23 port of frontend/src/pages/customers/CustomerProfile.tsx.
 *
 * ALL logic is copied VERBATIM from the original: profile fetch + reminder
 * config fetch (AbortController-free in the original; preserved as-is with
 * `?? 0`/`?? []`-safe consumption), the Issue Invoice / Issue Quote vehicle
 * picker flow (navigates to /invoices/new?customer_id=…&vehicle_rego(s)=… and
 * /quotes/new…), notify (email/SMS) modal, customer merge (search → preview →
 * execute), Privacy-Act export (blob download) + deletion (anonymise), the full
 * Configure-Reminders modal, role/module/trade-family gating (vehicles +
 * service-due gated by the `vehicles` module; WOF/COF automotive-only; SMS
 * channel gated by the `sms` module), and the claims summary tab
 * (useCustomerClaims).
 *
 * Presentation follows OraInvoice_Handoff/app/CustomerDetail.html: crumbs, a
 * customer hero (avatar + name + status), a KPI row, and a two-column detail
 * grid (tabs + contact / payment-behaviour sidebar cards) — all in the
 * design-system token language. Elements the prototype omits (the action
 * toolbar, notify / merge / export / delete / reminder modals, portal-access
 * card, claims tab) are designed on the fly with the same tokens (FR-2b).
 * `.mono` is applied to money / regos / phones / dates per FR-2. The v2 Button
 * has no `secondary` variant, so `secondary` maps to `ghost`.
 */

import { useState, useEffect, useCallback } from 'react'
import { useParams, useNavigate } from 'react-router-dom'
import apiClient from '@/api/client'
import { Button, Badge, Spinner, Modal, Tabs, Input, Select } from '@/components/ui'
import { useTenant } from '@/contexts/TenantContext'
import { useModules } from '@/contexts/ModuleContext'
import { useCustomerClaims } from '@/hooks/useCustomerClaims'
import { CustomerEditModal } from '@/components/customers/CustomerEditModal'
import { VehiclePickerModal } from '@/components/customers/VehiclePickerModal'

/* ------------------------------------------------------------------ */
/*  Types                                                              */
/* ------------------------------------------------------------------ */

type ProfileBadgeVariant = 'success' | 'warning' | 'error' | 'info' | 'neutral'

interface LinkedVehicle {
  id: string
  rego: string | null
  make: string | null
  model: string | null
  year: number | null
  colour: string | null
  source: string
  origin?: string
  linked_at: string
}

interface InvoiceHistoryItem {
  id: string
  invoice_number: string | null
  vehicle_rego: string | null
  status: string
  issue_date: string | null
  total: string
  balance_due: string
}

interface CustomerProfile {
  id: string
  first_name: string
  last_name: string
  email: string | null
  phone: string | null
  address: string | null
  notes: string | null
  is_anonymised: boolean
  enable_portal: boolean
  portal_token: string | null
  portal_token_expires_at: string | null
  last_portal_access_at: string | null
  created_at: string
  updated_at: string
  vehicles: LinkedVehicle[]
  invoices: InvoiceHistoryItem[]
  total_spend: string
  outstanding_balance: string
}

/* Merge types */
interface MergePreviewVehicle {
  id: string
  rego: string | null
  make: string | null
  model: string | null
  year: number | null
  source: string
}

interface MergePreviewInvoice {
  id: string
  invoice_number: string | null
  status: string
  total: string
}

interface MergePreviewContactChanges {
  email: string | null
  phone: string | null
  address: string | null
  notes: string | null
}

interface CustomerBasic {
  id: string
  first_name: string
  last_name: string
  email: string | null
  phone: string | null
}

interface MergePreview {
  target_customer: CustomerBasic
  source_customer: CustomerBasic
  vehicles_to_transfer: MergePreviewVehicle[]
  invoices_to_transfer: MergePreviewInvoice[]
  contact_changes: MergePreviewContactChanges
  fleet_account_transfer: boolean
}

/* Search result for merge source picker */
interface CustomerSearchResult {
  id: string
  first_name: string
  last_name: string
  email: string | null
  phone: string | null
}

/* Reminder config types */
interface ReminderEntry {
  enabled: boolean
  days_before: number
  channel: 'email' | 'sms' | 'both'
}

interface VehicleExpiryData {
  global_vehicle_id: string
  rego: string | null
  make: string | null
  model: string | null
  year: number | null
  service_due_date: string | null
  wof_expiry: string | null
  cof_expiry: string | null
  inspection_type: string | null
}

interface CustomerReminderConfig {
  service_due: ReminderEntry
  wof_expiry: ReminderEntry
  cof_expiry: ReminderEntry
  vehicles: VehicleExpiryData[]
}

/* ------------------------------------------------------------------ */
/*  Helpers                                                            */
/* ------------------------------------------------------------------ */

function formatNZD(amount: string | number): string {
  const num = typeof amount === 'string' ? parseFloat(amount) : amount
  return new Intl.NumberFormat('en-NZ', { style: 'currency', currency: 'NZD' }).format(num)
}

function formatDate(dateStr: string | null | undefined): string {
  if (!dateStr) return '—'
  return new Intl.DateTimeFormat('en-NZ', { day: '2-digit', month: '2-digit', year: 'numeric' }).format(new Date(dateStr))
}

const INVOICE_STATUS_CONFIG: Record<string, { label: string; variant: ProfileBadgeVariant }> = {
  draft: { label: 'Draft', variant: 'neutral' },
  issued: { label: 'Issued', variant: 'info' },
  partially_paid: { label: 'Partially Paid', variant: 'warning' },
  paid: { label: 'Paid', variant: 'success' },
  overdue: { label: 'Overdue', variant: 'error' },
  voided: { label: 'Voided', variant: 'neutral' },
}

/* Map the original Badge variant names (success/warning/error/info/neutral) to
   the v2 Badge variant union (ok/warn/danger/info/neutral) so the ported badges
   render against the design-system tones. */
const BADGE_VARIANT_MAP: Record<ProfileBadgeVariant, 'ok' | 'warn' | 'danger' | 'info' | 'neutral'> = {
  success: 'ok',
  warning: 'warn',
  error: 'danger',
  info: 'info',
  neutral: 'neutral',
}

/* ------------------------------------------------------------------ */
/*  Portal Access Card                                                 */
/* ------------------------------------------------------------------ */

function PortalAccessCard({ customer }: { customer: CustomerProfile; onRefresh: () => void }) {
  const [copyFeedback, setCopyFeedback] = useState(false)
  const [sendStatus, setSendStatus] = useState<'idle' | 'sending' | 'sent' | 'error'>('idle')
  const [sendError, setSendError] = useState('')

  const isEnabled = !!customer.enable_portal && !!customer.portal_token
  const portalUrl = isEnabled ? `${window.location.origin}/portal/${customer.portal_token}` : null

  const handleCopy = async () => {
    if (!portalUrl) return
    try {
      await navigator.clipboard.writeText(portalUrl)
      setCopyFeedback(true)
      setTimeout(() => setCopyFeedback(false), 2000)
    } catch {
      // fallback
    }
  }

  const handleSendLink = async () => {
    setSendStatus('sending')
    setSendError('')
    try {
      await apiClient.post(`/api/v2/customers/${customer.id}/send-portal-link`)
      setSendStatus('sent')
      setTimeout(() => setSendStatus('idle'), 3000)
    } catch (err: any) {
      const detail = err?.response?.data?.detail ?? 'Failed to send portal link'
      setSendError(detail)
      setSendStatus('error')
      setTimeout(() => setSendStatus('idle'), 4000)
    }
  }

  return (
    <section className="mb-6 rounded-card border border-border bg-card p-4 shadow-card">
      <h2 className="mono mb-3 text-[11px] font-medium uppercase tracking-[0.1em] text-muted-2">Portal Access</h2>

      {!isEnabled ? (
        <p className="text-[13px] text-muted">
          Portal access is disabled for this customer. Enable it in the Edit Customer form to generate a portal link.
        </p>
      ) : (
        <div className="space-y-3">
          {/* Portal URL with copy/send buttons */}
          <div className="flex items-center gap-2 rounded-ctl border border-border bg-canvas px-3 py-2">
            <span className="h-2 w-2 flex-shrink-0 rounded-full bg-ok" />
            <span className="mono min-w-0 flex-1 truncate text-[13px] text-text" title={portalUrl ?? ''}>
              {portalUrl}
            </span>
            <button
              type="button"
              onClick={handleCopy}
              className="inline-flex min-h-[36px] flex-shrink-0 items-center gap-1 rounded-chip bg-accent-soft px-2 py-1 text-[11px] font-medium text-accent transition-colors hover:brightness-95"
            >
              {copyFeedback ? '✓ Copied' : 'Copy Link'}
            </button>
            <button
              type="button"
              onClick={handleSendLink}
              disabled={sendStatus === 'sending' || sendStatus === 'sent'}
              className="inline-flex min-h-[36px] flex-shrink-0 items-center gap-1 rounded-chip bg-ok-soft px-2 py-1 text-[11px] font-medium text-ok transition-colors hover:brightness-95 disabled:cursor-not-allowed disabled:opacity-50"
            >
              {sendStatus === 'sending' ? 'Sending…' : sendStatus === 'sent' ? '✓ Sent' : 'Send Link'}
            </button>
          </div>

          {sendStatus === 'error' && sendError && (
            <p className="text-[11px] text-danger">{sendError}</p>
          )}

          {/* Metadata */}
          <div className="flex flex-wrap gap-x-6 gap-y-1 text-[11px] text-muted">
            {customer.portal_token_expires_at && (
              <span>Expires: {formatDate(customer.portal_token_expires_at)}</span>
            )}
            {customer.last_portal_access_at && (
              <span>Last accessed: {new Date(customer.last_portal_access_at).toLocaleString()}</span>
            )}
          </div>
        </div>
      )}
    </section>
  )
}

/* ------------------------------------------------------------------ */
/*  Component                                                          */
/* ------------------------------------------------------------------ */

export default function CustomerProfilePage() {
  const { id } = useParams<{ id: string }>()
  const navigate = useNavigate()
  const { tradeFamily } = useTenant()
  const { isEnabled: isModuleEnabled } = useModules()
  const smsEnabled = isModuleEnabled('sms')
  const vehiclesEnabled = isModuleEnabled('vehicles')
  const isAutomotive = (tradeFamily ?? 'automotive-transport') === 'automotive-transport'

  const [customer, setCustomer] = useState<CustomerProfile | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')

  /* Privacy Act compliance */
  const [deleteOpen, setDeleteOpen] = useState(false)
  const [deleting, setDeleting] = useState(false)
  const [deleteError, setDeleteError] = useState('')
  const [exportOpen, setExportOpen] = useState(false)
  const [exporting, setExporting] = useState(false)
  const [exportError, setExportError] = useState('')

  /* Notify modal */
  const [notifyOpen, setNotifyOpen] = useState(false)
  const [notifyChannel, setNotifyChannel] = useState<'email' | 'sms'>('email')
  const [notifySubject, setNotifySubject] = useState('')
  const [notifyMessage, setNotifyMessage] = useState('')
  const [notifying, setNotifying] = useState(false)
  const [notifyResult, setNotifyResult] = useState('')
  const [notifyError, setNotifyError] = useState('')

  /* Edit modal */
  const [editOpen, setEditOpen] = useState(false)

  /* Vehicle picker modal — opens before navigating to /invoices/new or
     /quotes/new when the customer has more than one linked vehicle so the
     user can choose which one(s) to attach. ``pickerAction`` records
     whether the user pressed "Issue Invoice" or "Issue Quote" so the
     confirm handler routes to the right page. */
  const [pickerOpen, setPickerOpen] = useState(false)
  const [pickerAction, setPickerAction] = useState<'invoice' | 'quote'>('invoice')

  /* Merge modal */
  const [mergeOpen, setMergeOpen] = useState(false)
  const [mergeSearch, setMergeSearch] = useState('')
  const [mergeResults, setMergeResults] = useState<CustomerSearchResult[]>([])
  const [mergeSourceId, setMergeSourceId] = useState<string | null>(null)
  const [mergePreview, setMergePreview] = useState<MergePreview | null>(null)
  const [mergeLoading, setMergeLoading] = useState(false)
  const [merging, setMerging] = useState(false)
  const [mergeError, setMergeError] = useState('')

  /* Reminder config modal */
  const defaultReminderConfig: CustomerReminderConfig = {
    service_due: { enabled: false, days_before: 30, channel: 'email' },
    wof_expiry: { enabled: false, days_before: 30, channel: 'email' },
    cof_expiry: { enabled: false, days_before: 30, channel: 'email' },
    vehicles: [],
  }
  const [reminderOpen, setReminderOpen] = useState(false)
  const [reminderConfig, setReminderConfig] = useState<CustomerReminderConfig>(defaultReminderConfig)
  const [reminderLoading, setReminderLoading] = useState(false)
  const [reminderSaving, setReminderSaving] = useState(false)
  const [reminderError, setReminderError] = useState('')
  const [remindersConfigured, setRemindersConfigured] = useState(false)
  const [vehicleDateEdits, setVehicleDateEdits] = useState<Record<string, { service_due_date?: string; wof_expiry?: string; cof_expiry?: string }>>({})

  /* ---- Fetch profile ---- */
  const { data: claimsData, loading: claimsLoading } = useCustomerClaims(id)

  const fetchProfile = useCallback(async () => {
    if (!id) return
    setLoading(true)
    setError('')
    try {
      const res = await apiClient.get<CustomerProfile>(`/customers/${id}`)
      setCustomer(res.data)
    } catch {
      setError('Failed to load customer profile.')
    } finally {
      setLoading(false)
    }
  }, [id])

  useEffect(() => { fetchProfile() }, [fetchProfile])

  /* ---- Fetch reminder config ---- */
  const fetchReminderConfig = useCallback(async () => {
    if (!id) return
    try {
      const res = await apiClient.get<CustomerReminderConfig>(`/customers/${id}/reminders`)
      setReminderConfig(res.data)
      const hasAny = res.data?.service_due?.enabled || res.data?.wof_expiry?.enabled || res.data?.cof_expiry?.enabled
      setRemindersConfigured(!!hasAny)
    } catch {
      /* ignore — defaults will be used */
    }
  }, [id])

  useEffect(() => { fetchReminderConfig() }, [fetchReminderConfig])

  /* ---- Open reminder modal ---- */
  const handleOpenReminders = async () => {
    setReminderOpen(true)
    setReminderError('')
    setReminderLoading(true)
    setVehicleDateEdits({})
    try {
      const res = await apiClient.get<CustomerReminderConfig>(`/customers/${id}/reminders`)
      setReminderConfig(res.data)
    } catch {
      setReminderError('Failed to load reminder settings.')
    } finally {
      setReminderLoading(false)
    }
  }

  /* ---- Save reminder config ---- */
  const handleSaveReminders = async () => {
    setReminderSaving(true)
    setReminderError('')
    try {
      // Save vehicle date edits first if any
      const dateUpdates = Object.entries(vehicleDateEdits)
        .filter(([, v]) => v.service_due_date !== undefined || v.wof_expiry !== undefined || v.cof_expiry !== undefined)
        .map(([gvId, dates]) => ({ global_vehicle_id: gvId, ...dates }))

      if (dateUpdates.length > 0) {
        await apiClient.put(`/customers/${id}/vehicle-dates`, { vehicles: dateUpdates })
      }

      // Save reminder config
      const { vehicles: _v, ...configOnly } = reminderConfig
      await apiClient.put(`/customers/${id}/reminders`, configOnly)
      const hasAny = reminderConfig.service_due.enabled || reminderConfig.wof_expiry.enabled || reminderConfig.cof_expiry.enabled
      setRemindersConfigured(hasAny)
      setReminderOpen(false)
      setVehicleDateEdits({})
      // Refresh to get updated vehicle dates
      fetchReminderConfig()
    } catch {
      setReminderError('Failed to save reminder settings.')
    } finally {
      setReminderSaving(false)
    }
  }

  const updateReminder = (type: 'service_due' | 'wof_expiry' | 'cof_expiry', updates: Partial<ReminderEntry>) => {
    setReminderConfig(prev => ({
      ...prev,
      [type]: { ...prev[type], ...updates },
    }))
  }

  const updateVehicleDate = (globalVehicleId: string, field: 'service_due_date' | 'wof_expiry' | 'cof_expiry', value: string) => {
    setVehicleDateEdits(prev => ({
      ...prev,
      [globalVehicleId]: { ...prev[globalVehicleId], [field]: value },
    }))
    // Also update the local display state
    setReminderConfig(prev => ({
      ...prev,
      vehicles: prev.vehicles.map(v =>
        v.global_vehicle_id === globalVehicleId ? { ...v, [field]: value || null } : v
      ),
    }))
  }

  const getVehicleDate = (v: VehicleExpiryData, field: 'service_due_date' | 'wof_expiry' | 'cof_expiry'): string => {
    const edit = vehicleDateEdits[v.global_vehicle_id]
    if (edit && edit[field] !== undefined) return edit[field] || ''
    return v[field] || ''
  }

  const hasCofVehicles = (reminderConfig?.vehicles ?? []).some(v => v.inspection_type === 'cof')

  /* ---- Send notification ---- */
  const handleNotify = async () => {
    if (!customer) return
    if (!notifyMessage.trim()) {
      setNotifyError('Message is required.')
      return
    }
    if (notifyChannel === 'email' && !notifySubject.trim()) {
      setNotifyError('Subject is required for email.')
      return
    }
    setNotifying(true)
    setNotifyError('')
    try {
      const body: Record<string, string> = {
        channel: notifyChannel,
        message: notifyMessage.trim(),
      }
      if (notifyChannel === 'email') body.subject = notifySubject.trim()
      await apiClient.post(`/customers/${customer.id}/notify`, body)
      setNotifyResult(`${notifyChannel === 'email' ? 'Email' : 'SMS'} sent successfully.`)
      setNotifyOpen(false)
      setNotifySubject('')
      setNotifyMessage('')
    } catch (err: any) {
      const detail = err?.response?.data?.detail || 'Failed to send notification.'
      setNotifyError(detail)
    } finally {
      setNotifying(false)
    }
  }

  /* ---- Merge: search for source customer ---- */
  const handleMergeSearch = async (query: string) => {
    setMergeSearch(query)
    if (query.trim().length < 2) {
      setMergeResults([])
      return
    }
    try {
      const res = await apiClient.get<{ customers?: CustomerSearchResult[] }>('/customers', {
        params: { search: query.trim(), page_size: 10 },
      })
      const customers = res.data.customers || []
      setMergeResults(customers.filter((c) => c.id !== id))
    } catch {
      /* ignore search errors */
    }
  }

  /* ---- Merge: preview ---- */
  const handleMergePreview = async (sourceId: string) => {
    if (!id) return
    setMergeSourceId(sourceId)
    setMergeLoading(true)
    setMergeError('')
    try {
      const res = await apiClient.post<{ preview: MergePreview }>(`/customers/${id}/merge`, {
        source_customer_id: sourceId,
        preview_only: true,
      })
      setMergePreview(res.data?.preview ?? null)
    } catch {
      setMergeError('Failed to generate merge preview.')
    } finally {
      setMergeLoading(false)
    }
  }

  /* ---- Merge: execute ---- */
  const handleMergeExecute = async () => {
    if (!id || !mergeSourceId) return
    setMerging(true)
    setMergeError('')
    try {
      await apiClient.post(`/customers/${id}/merge`, {
        source_customer_id: mergeSourceId,
        preview_only: false,
      })
      setMergeOpen(false)
      setMergePreview(null)
      setMergeSourceId(null)
      setMergeSearch('')
      fetchProfile()
    } catch {
      setMergeError('Failed to merge customers.')
    } finally {
      setMerging(false)
    }
  }

  const resetMerge = () => {
    setMergeOpen(false)
    setMergePreview(null)
    setMergeSourceId(null)
    setMergeSearch('')
    setMergeResults([])
    setMergeError('')
  }

  /* ---- Privacy Act: Process deletion (anonymise) ---- */
  const handleProcessDeletion = async () => {
    if (!customer) return
    setDeleting(true)
    setDeleteError('')
    try {
      await apiClient.delete(`/customers/${customer.id}`)
      setDeleteOpen(false)
      navigate('/customers')
    } catch {
      setDeleteError('Failed to process deletion request.')
    } finally {
      setDeleting(false)
    }
  }

  /* ---- Privacy Act: Export customer data ---- */
  const handleExportData = async () => {
    if (!customer) return
    setExporting(true)
    setExportError('')
    try {
      const res = await apiClient.get(`/customers/${customer.id}/export`, {
        responseType: 'blob',
      })
      const blob = new Blob([res.data], { type: 'application/json' })
      const url = URL.createObjectURL(blob)
      const link = document.createElement('a')
      link.href = url
      link.download = `customer-${customer.id}-export.json`
      document.body.appendChild(link)
      link.click()
      document.body.removeChild(link)
      URL.revokeObjectURL(url)
      setExportOpen(false)
    } catch {
      setExportError('Failed to export customer data.')
    } finally {
      setExporting(false)
    }
  }

  /* ---- Loading / Error ---- */
  if (loading) {
    return <div className="py-16"><Spinner label="Loading customer" /></div>
  }

  if (error || !customer) {
    return (
      <div className="page page-wide">
        <div className="rounded-ctl border border-danger/30 bg-danger-soft px-4 py-3 text-[13px] text-danger" role="alert">
          {error || 'Customer not found.'}
        </div>
        <Button variant="ghost" className="mt-4" onClick={() => { window.location.href = '/customers' }}>
          ← Back to Customers
        </Button>
      </div>
    )
  }

  const fullName = `${customer.first_name} ${customer.last_name}`
  const outstandingNum = parseFloat(customer.outstanding_balance)

  /* ---- Tab content ---- */
  const vehiclesTab = (
    <div>
      {customer.vehicles.length === 0 ? (
        <p className="text-[13px] text-muted">No vehicles linked to this customer.</p>
      ) : (
        <div className="overflow-x-auto rounded-card border border-border bg-card shadow-card">
          <table className="w-full border-collapse">
            <caption className="sr-only">Linked vehicles</caption>
            <thead>
              <tr>
                <th scope="col" className="mono border-b border-border px-5 py-[11px] text-left text-[10.5px] font-medium uppercase tracking-[0.08em] text-muted-2">Rego</th>
                <th scope="col" className="mono border-b border-border px-5 py-[11px] text-left text-[10.5px] font-medium uppercase tracking-[0.08em] text-muted-2">Vehicle</th>
                <th scope="col" className="mono border-b border-border px-5 py-[11px] text-left text-[10.5px] font-medium uppercase tracking-[0.08em] text-muted-2">Colour</th>
                <th scope="col" className="mono border-b border-border px-5 py-[11px] text-left text-[10.5px] font-medium uppercase tracking-[0.08em] text-muted-2">Source</th>
                <th scope="col" className="mono border-b border-border px-5 py-[11px] text-left text-[10.5px] font-medium uppercase tracking-[0.08em] text-muted-2">Linked</th>
              </tr>
            </thead>
            <tbody>
              {customer.vehicles.map((v) => (
                <tr key={v.id} className="border-b border-border transition-colors last:border-b-0 hover:bg-canvas">
                  <td className="mono whitespace-nowrap px-5 py-3 text-[13.5px] font-medium text-accent">{v.rego || '—'}</td>
                  <td className="whitespace-nowrap px-5 py-3 text-[13.5px] text-text">
                    {[v.year, v.make, v.model].filter(Boolean).join(' ') || '—'}
                  </td>
                  <td className="whitespace-nowrap px-5 py-3 text-[13.5px] text-text">{v.colour || '—'}</td>
                  <td className="whitespace-nowrap px-5 py-3 text-[13.5px]">
                    {(() => {
                      // Prefer the explicit origin field; fall back to the
                      // legacy storage-location heuristic for older clients.
                      const origin = v.origin ?? (v.source === 'global' ? 'carjam' : 'manual')
                      const isCarjam = origin === 'carjam'
                      return (
                        <Badge variant={isCarjam ? 'info' : 'neutral'}>
                          {isCarjam ? 'Carjam' : 'Manual'}
                        </Badge>
                      )
                    })()}
                  </td>
                  <td className="mono whitespace-nowrap px-5 py-3 text-[13.5px] text-text">{formatDate(v.linked_at)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  )

  const invoicesTab = (
    <div>
      {customer.invoices.length === 0 ? (
        <p className="text-[13px] text-muted">No invoices for this customer.</p>
      ) : (
        <div className="overflow-x-auto rounded-card border border-border bg-card shadow-card">
          <table className="w-full border-collapse">
            <caption className="sr-only">Invoice history</caption>
            <thead>
              <tr>
                <th scope="col" className="mono border-b border-border px-5 py-[11px] text-left text-[10.5px] font-medium uppercase tracking-[0.08em] text-muted-2">Invoice #</th>
                <th scope="col" className="mono border-b border-border px-5 py-[11px] text-left text-[10.5px] font-medium uppercase tracking-[0.08em] text-muted-2">Rego</th>
                <th scope="col" className="mono border-b border-border px-5 py-[11px] text-left text-[10.5px] font-medium uppercase tracking-[0.08em] text-muted-2">Status</th>
                <th scope="col" className="mono border-b border-border px-5 py-[11px] text-left text-[10.5px] font-medium uppercase tracking-[0.08em] text-muted-2">Date</th>
                <th scope="col" className="mono border-b border-border px-5 py-[11px] text-right text-[10.5px] font-medium uppercase tracking-[0.08em] text-muted-2">Total</th>
                <th scope="col" className="mono border-b border-border px-5 py-[11px] text-right text-[10.5px] font-medium uppercase tracking-[0.08em] text-muted-2">Balance</th>
              </tr>
            </thead>
            <tbody>
              {customer.invoices.map((inv) => {
                const cfg = INVOICE_STATUS_CONFIG[inv.status] ?? { label: inv.status, variant: 'neutral' as ProfileBadgeVariant }
                return (
                  <tr
                    key={inv.id}
                    className="cursor-pointer border-b border-border transition-colors last:border-b-0 hover:bg-canvas"
                    onClick={() => { window.location.href = `/invoices/${inv.id}` }}
                  >
                    <td className="whitespace-nowrap px-5 py-3 text-[13.5px] font-medium text-accent">
                      {inv.invoice_number || <span className="italic text-muted-2">Draft</span>}
                    </td>
                    <td className="mono whitespace-nowrap px-5 py-3 text-[13.5px] text-text">{inv.vehicle_rego || '—'}</td>
                    <td className="whitespace-nowrap px-5 py-3 text-[13.5px]"><Badge variant={BADGE_VARIANT_MAP[cfg.variant]}>{cfg.label}</Badge></td>
                    <td className="mono whitespace-nowrap px-5 py-3 text-[13.5px] text-text">{formatDate(inv.issue_date)}</td>
                    <td className="mono whitespace-nowrap px-5 py-3 text-right text-[13.5px] text-text">{formatNZD(inv.total)}</td>
                    <td className="mono whitespace-nowrap px-5 py-3 text-right text-[13.5px]">
                      <span className={parseFloat(inv.balance_due) > 0 ? 'font-medium text-danger' : 'text-text'}>
                        {formatNZD(inv.balance_due)}
                      </span>
                    </td>
                  </tr>
                )
              })}
            </tbody>
          </table>
        </div>
      )}
    </div>
  )

  const avatarInitials = `${customer.first_name?.[0] ?? ''}${customer.last_name?.[0] ?? ''}`.toUpperCase() || '—'

  return (
    <div className="page page-wide">
      {/* Breadcrumbs */}
      <div className="crumbs">
        <a href="/customers" className="hover:text-text">Customers</a>
        <span className="sep">/</span>
        <span className="text-text">{fullName}</span>
      </div>

      {/* Header */}
      <div className="page-head">
        <div className="flex items-center gap-4">
          <button
            onClick={() => { window.location.href = '/customers' }}
            className="rounded p-1 text-muted-2 hover:text-text focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent"
            aria-label="Back to customers"
          >
            ←
          </button>
          <div className="grid h-14 w-14 flex-shrink-0 place-items-center rounded-[15px] bg-accent text-[22px] font-bold text-white">
            {avatarInitials}
          </div>
          <div>
            <div className="flex items-center gap-2.5">
              <h1>{fullName}</h1>
              {customer.is_anonymised && <Badge variant="neutral">Anonymised</Badge>}
            </div>
          </div>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          <Button size="sm" variant="ghost" onClick={() => setEditOpen(true)}>
            Edit
          </Button>
          <Button
            size="sm"
            variant="ghost"
            onClick={() => {
              const linked = (customer.vehicles ?? []).filter((v) => v.rego)
              if (linked.length > 1) {
                setPickerAction('invoice')
                setPickerOpen(true)
                return
              }
              const params = new URLSearchParams({ customer_id: customer.id })
              if (linked[0]?.rego) params.set('vehicle_rego', linked[0].rego)
              navigate(`/invoices/new?${params.toString()}`)
            }}
          >
            Issue Invoice
          </Button>
          <Button
            size="sm"
            variant="ghost"
            onClick={() => {
              const linked = (customer.vehicles ?? []).filter((v) => v.rego)
              if (linked.length > 1) {
                setPickerAction('quote')
                setPickerOpen(true)
                return
              }
              const params = new URLSearchParams({ customer_id: customer.id })
              if (linked[0]?.rego) params.set('vehicle_rego', linked[0].rego)
              navigate(`/quotes/new?${params.toString()}`)
            }}
          >
            Issue Quote
          </Button>
          {remindersConfigured ? (
            <Button
              size="sm"
              variant="ghost"
              className="border-ok bg-ok text-white hover:bg-ok hover:brightness-95 focus-visible:ring-ok"
              onClick={handleOpenReminders}
            >
              ✓ Reminders Configured
            </Button>
          ) : (
            <Button size="sm" variant="ghost" onClick={handleOpenReminders}>
              Configure Reminders
            </Button>
          )}
          <Button size="sm" variant="ghost" onClick={() => setNotifyOpen(true)}>
            {smsEnabled ? 'Send Email / SMS' : 'Send Email'}
          </Button>
          <Button size="sm" variant="ghost" onClick={() => setMergeOpen(true)}>
            Merge Customer
          </Button>
          {!customer.is_anonymised && (
            <>
              <Button size="sm" variant="ghost" onClick={() => setExportOpen(true)}>
                Export Customer Data
              </Button>
              <Button size="sm" variant="danger" onClick={() => setDeleteOpen(true)}>
                Process Deletion Request
              </Button>
            </>
          )}
        </div>
      </div>

      {/* Notification result */}
      {notifyResult && (
        <div className="mb-4 rounded-ctl border border-ok/30 bg-ok-soft px-4 py-2 text-[13px] text-ok" role="status">
          {notifyResult}
        </div>
      )}

      {/* Summary KPI cards */}
      <div className="kpis">
        <div className="kpi">
          <div className="top"><span className="label">Total Spend</span></div>
          <div className="val">{formatNZD(customer.total_spend)}</div>
        </div>
        <div className="kpi">
          <div className="top"><span className="label">Outstanding</span></div>
          <div className={`val ${outstandingNum > 0 ? 'text-danger' : 'text-ok'}`}>
            {formatNZD(customer.outstanding_balance)}
          </div>
        </div>
        {vehiclesEnabled && (
        <div className="kpi">
          <div className="top"><span className="label">Vehicles</span></div>
          <div className="val">{customer.vehicles.length}</div>
        </div>
        )}
        <div className="kpi">
          <div className="top"><span className="label">Invoices</span></div>
          <div className="val">{customer.invoices.length}</div>
        </div>
      </div>

      {/* Two-column detail grid */}
      <div className="detail-grid">
        <div className="flex flex-col gap-[22px]">
          {/* Tabs: Vehicles, Invoices & Claims */}
          <Tabs
            tabs={[
              ...(vehiclesEnabled ? [{ id: 'vehicles', label: `Vehicles (${customer.vehicles.length})`, content: vehiclesTab }] : []),
              { id: 'invoices', label: `Invoices (${customer.invoices.length})`, content: invoicesTab },
              {
                id: 'claims',
                label: `Claims (${claimsData?.total_claims ?? 0})`,
                content: (
                  <div className="space-y-4">
                    {/* Summary stats */}
                    <div className="grid grid-cols-1 gap-4 sm:grid-cols-3">
                      <div className="rounded-card border border-border p-4">
                        <p className="mono text-[11px] font-medium uppercase tracking-wider text-muted-2">Total Claims</p>
                        <p className="mono mt-1 text-xl font-semibold text-text">{(claimsData?.total_claims ?? 0).toLocaleString()}</p>
                      </div>
                      <div className="rounded-card border border-border p-4">
                        <p className="mono text-[11px] font-medium uppercase tracking-wider text-muted-2">Open Claims</p>
                        <p className="mono mt-1 text-xl font-semibold text-warn">{(claimsData?.open_claims ?? 0).toLocaleString()}</p>
                      </div>
                      <div className="rounded-card border border-border p-4">
                        <p className="mono text-[11px] font-medium uppercase tracking-wider text-muted-2">Total Cost to Business</p>
                        <p className="mono mt-1 text-xl font-semibold text-danger">{formatNZD(claimsData?.total_cost_to_business ?? 0)}</p>
                      </div>
                    </div>

                    {/* New Claim button */}
                    <div className="flex justify-end">
                      <Button size="sm" onClick={() => navigate(`/claims/new?customer_id=${id}`)}>
                        New Claim
                      </Button>
                    </div>

                    {/* Claims list */}
                    {claimsLoading ? (
                      <Spinner size="sm" />
                    ) : (claimsData?.claims ?? []).length === 0 ? (
                      <p className="text-[13px] text-muted">No claims for this customer.</p>
                    ) : (
                      <div className="overflow-x-auto rounded-card border border-border bg-card shadow-card">
                        <table className="w-full border-collapse">
                          <caption className="sr-only">Customer claims</caption>
                          <thead>
                            <tr>
                              <th scope="col" className="mono border-b border-border px-5 py-[11px] text-left text-[10.5px] font-medium uppercase tracking-[0.08em] text-muted-2">Type</th>
                              <th scope="col" className="mono border-b border-border px-5 py-[11px] text-left text-[10.5px] font-medium uppercase tracking-[0.08em] text-muted-2">Status</th>
                              <th scope="col" className="mono border-b border-border px-5 py-[11px] text-left text-[10.5px] font-medium uppercase tracking-[0.08em] text-muted-2">Description</th>
                              <th scope="col" className="mono border-b border-border px-5 py-[11px] text-left text-[10.5px] font-medium uppercase tracking-[0.08em] text-muted-2">Created</th>
                              <th scope="col" className="mono border-b border-border px-5 py-[11px] text-right text-[10.5px] font-medium uppercase tracking-[0.08em] text-muted-2">Cost</th>
                            </tr>
                          </thead>
                          <tbody>
                            {(claimsData?.claims ?? []).map((claim) => {
                              const statusCfg: Record<string, { label: string; variant: ProfileBadgeVariant }> = {
                                open: { label: 'Open', variant: 'info' },
                                investigating: { label: 'Investigating', variant: 'warning' },
                                approved: { label: 'Approved', variant: 'success' },
                                rejected: { label: 'Rejected', variant: 'error' },
                                resolved: { label: 'Resolved', variant: 'neutral' },
                              }
                              const cfg = statusCfg[claim.status] ?? { label: claim.status, variant: 'neutral' as ProfileBadgeVariant }
                              return (
                                <tr
                                  key={claim.id}
                                  className="cursor-pointer border-b border-border transition-colors last:border-b-0 hover:bg-canvas"
                                  onClick={() => navigate(`/claims/${claim.id}`)}
                                >
                                  <td className="whitespace-nowrap px-5 py-3 text-[13.5px] capitalize text-text">{(claim.claim_type ?? '').replace(/_/g, ' ')}</td>
                                  <td className="whitespace-nowrap px-5 py-3 text-[13.5px]"><Badge variant={BADGE_VARIANT_MAP[cfg.variant]}>{cfg.label}</Badge></td>
                                  <td className="max-w-xs truncate px-5 py-3 text-[13.5px] text-muted">{claim.description}</td>
                                  <td className="mono whitespace-nowrap px-5 py-3 text-[13.5px] text-text">{formatDate(claim.created_at)}</td>
                                  <td className="mono whitespace-nowrap px-5 py-3 text-right text-[13.5px] text-text">{formatNZD(claim.cost_to_business ?? 0)}</td>
                                </tr>
                              )
                            })}
                          </tbody>
                        </table>
                      </div>
                    )}
                  </div>
                ),
              },
            ]}
            defaultTab={vehiclesEnabled ? 'vehicles' : 'invoices'}
          />
        </div>

        <div className="flex flex-col gap-[22px]">
          {/* Contact details */}
          <section className="rounded-card border border-border bg-card p-4 shadow-card">
            <div className="section-label">Contact</div>
            <dl>
              <div className="meta-row"><dt className="k">Email</dt><dd className="v">{customer.email || '—'}</dd></div>
              <div className="meta-row"><dt className="k">Phone</dt><dd className="v mono">{customer.phone || '—'}</dd></div>
              <div className="meta-row"><dt className="k">Address</dt><dd className="v">{customer.address || '—'}</dd></div>
              {customer.notes && (
                <div className="meta-row"><dt className="k">Notes</dt><dd className="v whitespace-pre-wrap">{customer.notes}</dd></div>
              )}
            </dl>
          </section>

          {/* Portal Access */}
          <PortalAccessCard customer={customer} onRefresh={fetchProfile} />
        </div>
      </div>

      {/* ---- Notify Modal ---- */}
      <Modal open={notifyOpen} onClose={() => { setNotifyOpen(false); setNotifyError('') }} title={smsEnabled ? 'Send Email / SMS' : 'Send Email'}>
        <div className="space-y-3">
          {smsEnabled ? (
          <Select
            label="Channel"
            options={[
              { value: 'email', label: 'Email' },
              { value: 'sms', label: 'SMS' },
            ]}
            value={notifyChannel}
            onChange={(e) => setNotifyChannel(e.target.value as 'email' | 'sms')}
          />
          ) : null}
          {notifyChannel === 'email' && (
            <Input label="Subject" value={notifySubject} onChange={(e) => setNotifySubject(e.target.value)} />
          )}
          <div>
            <label className="mb-1 block text-[12.5px] font-medium text-text">Message</label>
            <textarea
              value={notifyMessage}
              onChange={(e) => setNotifyMessage(e.target.value)}
              rows={4}
              className="w-full rounded-ctl border border-border bg-card px-3 py-2 text-[13.5px] text-text placeholder:text-muted-2 focus:border-accent focus:outline-none focus:shadow-[0_0_0_3px_var(--accent-soft)]"
              placeholder={notifyChannel === 'email' ? 'Email body…' : 'SMS message…'}
            />
          </div>
        </div>
        {notifyError && <p className="mt-2 text-[13px] text-danger" role="alert">{notifyError}</p>}
        <div className="mt-4 flex justify-end gap-2">
          <Button variant="ghost" size="sm" onClick={() => { setNotifyOpen(false); setNotifyError('') }}>Cancel</Button>
          <Button size="sm" onClick={handleNotify} loading={notifying}>Send</Button>
        </div>
      </Modal>

      {/* ---- Merge Modal ---- */}
      <Modal open={mergeOpen} onClose={resetMerge} title="Merge Customer" className="max-w-2xl">
        {!mergePreview ? (
          /* Step 1: Search for source customer */
          <div>
            <p className="mb-3 text-[13.5px] text-muted">
              Search for the duplicate customer to merge into <span className="font-medium text-text">{fullName}</span>.
              The selected customer's data will be combined into this profile.
            </p>
            <Input
              label="Search customer"
              placeholder="Name, email, or phone…"
              value={mergeSearch}
              onChange={(e) => handleMergeSearch(e.target.value)}
            />
            {mergeResults.length > 0 && (
              <ul className="mt-2 max-h-48 divide-y divide-border overflow-auto rounded-ctl border border-border">
                {mergeResults.map((c) => (
                  <li key={c.id}>
                    <button
                      onClick={() => handleMergePreview(c.id)}
                      className="w-full px-3 py-2 text-left text-[13px] hover:bg-canvas focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent"
                    >
                      <span className="font-medium text-text">{c.first_name} {c.last_name}</span>
                      {c.email && <span className="ml-2 text-muted">{c.email}</span>}
                      {c.phone && <span className="mono ml-2 text-muted">{c.phone}</span>}
                    </button>
                  </li>
                ))}
              </ul>
            )}
            {mergeLoading && <div className="mt-3"><Spinner label="Loading preview" /></div>}
            {mergeError && <p className="mt-2 text-[13px] text-danger" role="alert">{mergeError}</p>}
          </div>
        ) : (
          /* Step 2: Confirmation preview */
          <div>
            <p className="mb-4 text-[13.5px] text-muted">
              Review what will be combined when merging{' '}
              <span className="font-medium text-text">{mergePreview.source_customer.first_name} {mergePreview.source_customer.last_name}</span>
              {' '}into{' '}
              <span className="font-medium text-text">{mergePreview.target_customer.first_name} {mergePreview.target_customer.last_name}</span>.
            </p>

            {/* Vehicles to transfer */}
            {mergePreview.vehicles_to_transfer.length > 0 && (
              <div className="mb-3">
                <h3 className="mb-1 text-[13px] font-medium text-text">
                  Vehicles to transfer ({mergePreview.vehicles_to_transfer.length})
                </h3>
                <ul className="space-y-1 text-[13px] text-muted">
                  {mergePreview.vehicles_to_transfer.map((v) => (
                    <li key={v.id} className="flex items-center gap-2">
                      <span className="mono">{v.rego || 'No rego'}</span>
                      <span>{[v.make, v.model].filter(Boolean).join(' ')}</span>
                    </li>
                  ))}
                </ul>
              </div>
            )}

            {/* Invoices to transfer */}
            {mergePreview.invoices_to_transfer.length > 0 && (
              <div className="mb-3">
                <h3 className="mb-1 text-[13px] font-medium text-text">
                  Invoices to transfer ({mergePreview.invoices_to_transfer.length})
                </h3>
                <ul className="space-y-1 text-[13px] text-muted">
                  {mergePreview.invoices_to_transfer.map((inv) => (
                    <li key={inv.id} className="flex items-center gap-2">
                      <span className="font-medium text-text">{inv.invoice_number || 'Draft'}</span>
                      <Badge variant={BADGE_VARIANT_MAP[(INVOICE_STATUS_CONFIG[inv.status]?.variant ?? 'neutral') as ProfileBadgeVariant]}>
                        {INVOICE_STATUS_CONFIG[inv.status]?.label ?? inv.status}
                      </Badge>
                      <span className="mono">{formatNZD(inv.total)}</span>
                    </li>
                  ))}
                </ul>
              </div>
            )}

            {/* Contact changes */}
            <div className="mb-3">
              <h3 className="mb-1 text-[13px] font-medium text-text">Contact details after merge</h3>
              <dl className="space-y-1 text-[13px] text-muted">
                {mergePreview.contact_changes.email && (
                  <div className="flex gap-2"><dt className="w-16 text-muted-2">Email:</dt><dd>{mergePreview.contact_changes.email}</dd></div>
                )}
                {mergePreview.contact_changes.phone && (
                  <div className="flex gap-2"><dt className="w-16 text-muted-2">Phone:</dt><dd className="mono">{mergePreview.contact_changes.phone}</dd></div>
                )}
                {mergePreview.contact_changes.address && (
                  <div className="flex gap-2"><dt className="w-16 text-muted-2">Address:</dt><dd>{mergePreview.contact_changes.address}</dd></div>
                )}
              </dl>
            </div>

            {mergePreview.fleet_account_transfer && (
              <div className="mb-3 rounded-ctl border border-warn/30 bg-warn-soft px-3 py-2 text-[13px] text-warn">
                A fleet account will be transferred to this customer.
              </div>
            )}

            {mergeError && <p className="mt-2 text-[13px] text-danger" role="alert">{mergeError}</p>}

            <div className="mt-4 flex justify-end gap-2">
              <Button variant="ghost" size="sm" onClick={() => { setMergePreview(null); setMergeSourceId(null) }}>
                Back
              </Button>
              <Button variant="danger" size="sm" onClick={handleMergeExecute} loading={merging}>
                Confirm Merge
              </Button>
            </div>
          </div>
        )}

        {!mergePreview && (
          <div className="mt-4 flex justify-end">
            <Button variant="ghost" size="sm" onClick={resetMerge}>Cancel</Button>
          </div>
        )}
      </Modal>

      {/* ---- Privacy Act: Deletion Confirmation Modal ---- */}
      <Modal open={deleteOpen} onClose={() => { setDeleteOpen(false); setDeleteError('') }} title="Process Deletion Request">
        <div className="space-y-3">
          <div className="rounded-ctl border border-warn/30 bg-warn-soft px-4 py-3 text-[13px] text-warn">
            <p className="mb-1 font-medium">Privacy Act 2020 — Customer Data Deletion</p>
            <p>You are about to process a deletion request for <span className="font-medium">{fullName}</span>.</p>
          </div>
          <div className="space-y-2 text-[13px] text-text">
            <p className="font-medium">This action will:</p>
            <ul className="list-disc space-y-1 pl-5">
              <li>Replace the customer name with "Anonymised Customer"</li>
              <li>Clear all contact details (email, phone, address)</li>
              <li>Remove any personal notes</li>
            </ul>
            <p className="mt-3 font-medium">This action will NOT:</p>
            <ul className="list-disc space-y-1 pl-5">
              <li>Delete any invoices — financial records remain intact</li>
              <li>Remove payment history or transaction amounts</li>
              <li>Unlink vehicles from invoice records</li>
            </ul>
          </div>
          <div className="rounded-ctl border border-danger/30 bg-danger-soft px-4 py-3 text-[13px] text-danger">
            This action cannot be undone.
          </div>
        </div>
        {deleteError && <p className="mt-2 text-[13px] text-danger" role="alert">{deleteError}</p>}
        <div className="mt-4 flex justify-end gap-2">
          <Button variant="ghost" size="sm" onClick={() => { setDeleteOpen(false); setDeleteError('') }}>Cancel</Button>
          <Button variant="danger" size="sm" onClick={handleProcessDeletion} loading={deleting}>
            Confirm Anonymisation
          </Button>
        </div>
      </Modal>

      {/* ---- Privacy Act: Export Data Confirmation Modal ---- */}
      <Modal open={exportOpen} onClose={() => { setExportOpen(false); setExportError('') }} title="Export Customer Data">
        <div className="space-y-3">
          <div className="rounded-ctl border border-accent/30 bg-accent-soft px-4 py-3 text-[13px] text-accent">
            <p className="mb-1 font-medium">Privacy Act 2020 — Customer Data Export</p>
            <p>Export all stored data for <span className="font-medium">{fullName}</span> as a JSON file.</p>
          </div>
          <div className="space-y-2 text-[13px] text-text">
            <p className="font-medium">The export will include:</p>
            <ul className="list-disc space-y-1 pl-5">
              <li>Customer profile (name, email, phone, address)</li>
              <li>All linked vehicles</li>
              <li>Complete invoice history</li>
              <li>Payment records</li>
              <li>Any notes or tags</li>
            </ul>
          </div>
          <p className="text-[13px] text-muted">
            The file will be downloaded to your device in JSON format, suitable for providing to the customer upon request.
          </p>
        </div>
        {exportError && <p className="mt-2 text-[13px] text-danger" role="alert">{exportError}</p>}
        <div className="mt-4 flex justify-end gap-2">
          <Button variant="ghost" size="sm" onClick={() => { setExportOpen(false); setExportError('') }}>Cancel</Button>
          <Button size="sm" onClick={handleExportData} loading={exporting}>
            Download Export
          </Button>
        </div>
      </Modal>

      {/* ---- Reminder Config Modal ---- */}
      <Modal open={reminderOpen} onClose={() => { setReminderOpen(false); setReminderError('') }} title="Configure Reminders">
        {reminderLoading ? (
          <Spinner label="Loading reminder settings" />
        ) : (
          <div className="space-y-5">
            <p className="text-[13.5px] text-muted">
              Configure automatic reminders for this customer. Each reminder type can be enabled separately with its own timing and notification channel.
            </p>

            {/* Service Due — vehicle module only */}
            {vehiclesEnabled && (
            <div className="space-y-3 rounded-card border border-border p-4">
              <div className="flex items-center justify-between">
                <h3 className="text-[13px] font-medium text-text">Service Due</h3>
                <label className="relative inline-flex cursor-pointer items-center">
                  <input
                    type="checkbox"
                    checked={reminderConfig.service_due.enabled}
                    onChange={(e) => updateReminder('service_due', { enabled: e.target.checked })}
                    className="peer sr-only"
                  />
                  <div className="peer h-5 w-9 rounded-full bg-border after:absolute after:left-[2px] after:top-[2px] after:h-4 after:w-4 after:rounded-full after:border after:border-border-strong after:bg-white after:transition-all after:content-[''] peer-checked:bg-accent peer-checked:after:translate-x-full peer-checked:after:border-white peer-focus:outline-none peer-focus:ring-2 peer-focus:ring-accent-soft" />
                  <span className="ml-2 text-[13px] text-muted">{reminderConfig.service_due.enabled ? 'Enabled' : 'Disabled'}</span>
                </label>
              </div>
              {reminderConfig.service_due.enabled && (
                <>
                  <div className="grid grid-cols-2 gap-3">
                    <Input
                      label="Days before expiry"
                      type="number"
                      value={String(reminderConfig.service_due.days_before)}
                      onChange={(e) => updateReminder('service_due', { days_before: parseInt(e.target.value) || 30 })}
                    />
                    <Select
                      label="Notify via"
                      options={[
                        { value: 'email', label: 'Email' },
                        ...(smsEnabled ? [
                          { value: 'sms', label: 'SMS' },
                          { value: 'both', label: 'Email & SMS' },
                        ] : []),
                      ]}
                      value={reminderConfig.service_due.channel}
                      onChange={(e) => updateReminder('service_due', { channel: e.target.value as 'email' | 'sms' | 'both' })}
                    />
                  </div>
                  {/* Vehicle service due dates */}
                  {reminderConfig.vehicles.length > 0 ? (
                    <div className="mt-2 space-y-2">
                      <p className="mono text-[11px] font-medium uppercase tracking-wider text-muted-2">Vehicle Service Due Dates</p>
                      {reminderConfig.vehicles.map((v) => {
                        const dateVal = getVehicleDate(v, 'service_due_date')
                        return (
                          <div key={v.global_vehicle_id} className="flex items-center gap-3 rounded-ctl bg-canvas px-3 py-2">
                            <div className="min-w-0 flex-1">
                              <span className="mono text-[13px] font-medium text-text">{v.rego || '—'}</span>
                              <span className="ml-2 text-[13px] text-muted">{[v.year, v.make, v.model].filter(Boolean).join(' ')}</span>
                            </div>
                            <div className="flex items-center gap-2">
                              {dateVal ? (
                                <span className="mono text-[13px] text-text">{dateVal}</span>
                              ) : (
                                <span className="text-[11px] text-warn">Not set</span>
                              )}
                              <input
                                type="date"
                                value={dateVal}
                                onChange={(e) => updateVehicleDate(v.global_vehicle_id, 'service_due_date', e.target.value)}
                                className="rounded-ctl border border-border px-2 py-1 text-[13px] text-text focus:border-accent focus:outline-none focus:shadow-[0_0_0_3px_var(--accent-soft)]"
                                aria-label={`Service due date for ${v.rego || 'vehicle'}`}
                              />
                            </div>
                          </div>
                        )
                      })}
                    </div>
                  ) : (
                    <p className="text-[11px] italic text-muted-2">No vehicles linked to this customer.</p>
                  )}
                </>
              )}
            </div>
            )}

            {/* WOF Expiry — automotive only */}
            {isAutomotive && vehiclesEnabled && (
            <div className="space-y-3 rounded-card border border-border p-4">
              <div className="flex items-center justify-between">
                <h3 className="text-[13px] font-medium text-text">WOF Expiry</h3>
                <label className="relative inline-flex cursor-pointer items-center">
                  <input
                    type="checkbox"
                    checked={reminderConfig.wof_expiry.enabled}
                    onChange={(e) => updateReminder('wof_expiry', { enabled: e.target.checked })}
                    className="peer sr-only"
                  />
                  <div className="peer h-5 w-9 rounded-full bg-border after:absolute after:left-[2px] after:top-[2px] after:h-4 after:w-4 after:rounded-full after:border after:border-border-strong after:bg-white after:transition-all after:content-[''] peer-checked:bg-accent peer-checked:after:translate-x-full peer-checked:after:border-white peer-focus:outline-none peer-focus:ring-2 peer-focus:ring-accent-soft" />
                  <span className="ml-2 text-[13px] text-muted">{reminderConfig.wof_expiry.enabled ? 'Enabled' : 'Disabled'}</span>
                </label>
              </div>
              {reminderConfig.wof_expiry.enabled && (
                <>
                  <div className="grid grid-cols-2 gap-3">
                    <Input
                      label="Days before expiry"
                      type="number"
                      value={String(reminderConfig.wof_expiry.days_before)}
                      onChange={(e) => updateReminder('wof_expiry', { days_before: parseInt(e.target.value) || 30 })}
                    />
                    <Select
                      label="Notify via"
                      options={[
                        { value: 'email', label: 'Email' },
                        ...(smsEnabled ? [
                          { value: 'sms', label: 'SMS' },
                          { value: 'both', label: 'Email & SMS' },
                        ] : []),
                      ]}
                      value={reminderConfig.wof_expiry.channel}
                      onChange={(e) => updateReminder('wof_expiry', { channel: e.target.value as 'email' | 'sms' | 'both' })}
                    />
                  </div>
                  {/* Vehicle WOF expiry dates */}
                  {reminderConfig.vehicles.length > 0 ? (
                    <div className="mt-2 space-y-2">
                      <p className="mono text-[11px] font-medium uppercase tracking-wider text-muted-2">Vehicle WOF Expiry Dates</p>
                      {reminderConfig.vehicles.map((v) => {
                        const dateVal = getVehicleDate(v, 'wof_expiry')
                        return (
                          <div key={v.global_vehicle_id} className="flex items-center gap-3 rounded-ctl bg-canvas px-3 py-2">
                            <div className="min-w-0 flex-1">
                              <span className="mono text-[13px] font-medium text-text">{v.rego || '—'}</span>
                              <span className="ml-2 text-[13px] text-muted">{[v.year, v.make, v.model].filter(Boolean).join(' ')}</span>
                            </div>
                            <div className="flex items-center gap-2">
                              {dateVal ? (
                                <span className="mono text-[13px] text-text">{dateVal}</span>
                              ) : (
                                <span className="text-[11px] text-warn">Not set</span>
                              )}
                              <input
                                type="date"
                                value={dateVal}
                                onChange={(e) => updateVehicleDate(v.global_vehicle_id, 'wof_expiry', e.target.value)}
                                className="rounded-ctl border border-border px-2 py-1 text-[13px] text-text focus:border-accent focus:outline-none focus:shadow-[0_0_0_3px_var(--accent-soft)]"
                                aria-label={`WOF expiry date for ${v.rego || 'vehicle'}`}
                              />
                            </div>
                          </div>
                        )
                      })}
                    </div>
                  ) : (
                    <p className="text-[11px] italic text-muted-2">No vehicles linked to this customer.</p>
                  )}
                </>
              )}
            </div>
            )}

            {/* COF Expiry — shown when customer has COF vehicles */}
            {hasCofVehicles && isAutomotive && vehiclesEnabled && (
            <div className="space-y-3 rounded-card border border-border p-4">
              <div className="flex items-center justify-between">
                <h3 className="text-[13px] font-medium text-text">COF Expiry</h3>
                <label className="relative inline-flex cursor-pointer items-center">
                  <input
                    type="checkbox"
                    checked={reminderConfig?.cof_expiry?.enabled ?? false}
                    onChange={(e) => updateReminder('cof_expiry', { enabled: e.target.checked })}
                    className="peer sr-only"
                  />
                  <div className="peer h-5 w-9 rounded-full bg-border after:absolute after:left-[2px] after:top-[2px] after:h-4 after:w-4 after:rounded-full after:border after:border-border-strong after:bg-white after:transition-all after:content-[''] peer-checked:bg-accent peer-checked:after:translate-x-full peer-checked:after:border-white peer-focus:outline-none peer-focus:ring-2 peer-focus:ring-accent-soft" />
                  <span className="ml-2 text-[13px] text-muted">{reminderConfig?.cof_expiry?.enabled ? 'Enabled' : 'Disabled'}</span>
                </label>
              </div>
              {reminderConfig?.cof_expiry?.enabled && (
                <>
                  <div className="grid grid-cols-2 gap-3">
                    <Input
                      label="Days before expiry"
                      type="number"
                      value={String(reminderConfig?.cof_expiry?.days_before ?? 30)}
                      onChange={(e) => updateReminder('cof_expiry', { days_before: parseInt(e.target.value) || 30 })}
                    />
                    <Select
                      label="Notify via"
                      options={[
                        { value: 'email', label: 'Email' },
                        ...(smsEnabled ? [
                          { value: 'sms', label: 'SMS' },
                          { value: 'both', label: 'Email & SMS' },
                        ] : []),
                      ]}
                      value={reminderConfig?.cof_expiry?.channel ?? 'email'}
                      onChange={(e) => updateReminder('cof_expiry', { channel: e.target.value as 'email' | 'sms' | 'both' })}
                    />
                  </div>
                  {/* Vehicle COF expiry dates */}
                  {(reminderConfig?.vehicles ?? []).filter(v => v.inspection_type === 'cof').length > 0 ? (
                    <div className="mt-2 space-y-2">
                      <p className="mono text-[11px] font-medium uppercase tracking-wider text-muted-2">Vehicle COF Expiry Dates</p>
                      {(reminderConfig?.vehicles ?? []).filter(v => v.inspection_type === 'cof').map((v) => {
                        const dateVal = getVehicleDate(v, 'cof_expiry')
                        return (
                          <div key={v.global_vehicle_id} className="flex items-center gap-3 rounded-ctl bg-canvas px-3 py-2">
                            <div className="min-w-0 flex-1">
                              <span className="mono text-[13px] font-medium text-text">{v.rego || '—'}</span>
                              <span className="ml-2 text-[13px] text-muted">{[v.year, v.make, v.model].filter(Boolean).join(' ')}</span>
                            </div>
                            <div className="flex items-center gap-2">
                              {dateVal ? (
                                <span className="mono text-[13px] text-text">{dateVal}</span>
                              ) : (
                                <span className="text-[11px] text-warn">Not set</span>
                              )}
                              <input
                                type="date"
                                value={dateVal}
                                onChange={(e) => updateVehicleDate(v.global_vehicle_id, 'cof_expiry', e.target.value)}
                                className="rounded-ctl border border-border px-2 py-1 text-[13px] text-text focus:border-accent focus:outline-none focus:shadow-[0_0_0_3px_var(--accent-soft)]"
                                aria-label={`COF expiry date for ${v.rego || 'vehicle'}`}
                              />
                            </div>
                          </div>
                        )
                      })}
                    </div>
                  ) : (
                    <p className="text-[11px] italic text-muted-2">No COF vehicles linked to this customer.</p>
                  )}
                </>
              )}
            </div>
            )}
          </div>
        )}
        {reminderError && <p className="mt-2 text-[13px] text-danger" role="alert">{reminderError}</p>}
        <div className="mt-4 flex justify-end gap-2">
          <Button variant="ghost" size="sm" onClick={() => { setReminderOpen(false); setReminderError('') }}>Cancel</Button>
          <Button size="sm" onClick={handleSaveReminders} loading={reminderSaving}>Save</Button>
        </div>
      </Modal>

      {/* ---- Edit Customer Modal ---- */}
      <CustomerEditModal
        open={editOpen}
        customerId={editOpen ? customer.id : null}
        onClose={() => setEditOpen(false)}
        onSaved={() => { setEditOpen(false); fetchProfile() }}
      />

      <VehiclePickerModal
        open={pickerOpen}
        action={pickerAction}
        vehicles={(customer.vehicles ?? [])
          .filter((v) => !!v.rego)
          .map((v) => ({
            id: v.id,
            rego: v.rego as string,
            make: v.make,
            model: v.model,
            year: v.year,
          }))}
        onClose={() => setPickerOpen(false)}
        onConfirm={(regos) => {
          setPickerOpen(false)
          if (regos.length === 0) return
          const params = new URLSearchParams({ customer_id: customer.id })
          if (regos.length === 1) {
            params.set('vehicle_rego', regos[0])
          } else {
            params.set('vehicle_regos', regos.join(','))
          }
          const path = pickerAction === 'invoice' ? '/invoices/new' : '/quotes/new'
          navigate(`${path}?${params.toString()}`)
        }}
      />
    </div>
  )
}
