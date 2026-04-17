import { useState, useEffect, useCallback } from 'react'
import { useParams, useNavigate } from 'react-router-dom'
import apiClient from '../../api/client'
import { Button, Badge, Spinner, Modal, Tabs, Input, Select } from '../../components/ui'
import { useTenant } from '../../contexts/TenantContext'
import { useModules } from '../../contexts/ModuleContext'
import { useCustomerClaims } from '../../hooks/useCustomerClaims'

/* ------------------------------------------------------------------ */
/*  Types                                                              */
/* ------------------------------------------------------------------ */

type BadgeVariant = 'success' | 'warning' | 'error' | 'info' | 'neutral'

interface LinkedVehicle {
  id: string
  rego: string | null
  make: string | null
  model: string | null
  year: number | null
  colour: string | null
  source: string
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
}

interface CustomerReminderConfig {
  service_due: ReminderEntry
  wof_expiry: ReminderEntry
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

const INVOICE_STATUS_CONFIG: Record<string, { label: string; variant: BadgeVariant }> = {
  draft: { label: 'Draft', variant: 'neutral' },
  issued: { label: 'Issued', variant: 'info' },
  partially_paid: { label: 'Partially Paid', variant: 'warning' },
  paid: { label: 'Paid', variant: 'success' },
  overdue: { label: 'Overdue', variant: 'error' },
  voided: { label: 'Voided', variant: 'neutral' },
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
    vehicles: [],
  }
  const [reminderOpen, setReminderOpen] = useState(false)
  const [reminderConfig, setReminderConfig] = useState<CustomerReminderConfig>(defaultReminderConfig)
  const [reminderLoading, setReminderLoading] = useState(false)
  const [reminderSaving, setReminderSaving] = useState(false)
  const [reminderError, setReminderError] = useState('')
  const [remindersConfigured, setRemindersConfigured] = useState(false)
  const [vehicleDateEdits, setVehicleDateEdits] = useState<Record<string, { service_due_date?: string; wof_expiry?: string }>>({})

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
      const hasAny = res.data.service_due.enabled || res.data.wof_expiry.enabled
      setRemindersConfigured(hasAny)
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
        .filter(([, v]) => v.service_due_date !== undefined || v.wof_expiry !== undefined)
        .map(([gvId, dates]) => ({ global_vehicle_id: gvId, ...dates }))

      if (dateUpdates.length > 0) {
        await apiClient.put(`/customers/${id}/vehicle-dates`, { vehicles: dateUpdates })
      }

      // Save reminder config
      const { vehicles: _v, ...configOnly } = reminderConfig
      await apiClient.put(`/customers/${id}/reminders`, configOnly)
      const hasAny = reminderConfig.service_due.enabled || reminderConfig.wof_expiry.enabled
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

  const updateReminder = (type: 'service_due' | 'wof_expiry', updates: Partial<ReminderEntry>) => {
    setReminderConfig(prev => ({
      ...prev,
      [type]: { ...prev[type], ...updates },
    }))
  }

  const updateVehicleDate = (globalVehicleId: string, field: 'service_due_date' | 'wof_expiry', value: string) => {
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

  const getVehicleDate = (v: VehicleExpiryData, field: 'service_due_date' | 'wof_expiry'): string => {
    const edit = vehicleDateEdits[v.global_vehicle_id]
    if (edit && edit[field] !== undefined) return edit[field] || ''
    return v[field] || ''
  }

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
      <div className="px-4 py-6 sm:px-6 lg:px-8">
        <div className="rounded-md border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700" role="alert">
          {error || 'Customer not found.'}
        </div>
        <Button variant="secondary" className="mt-4" onClick={() => { window.location.href = '/customers' }}>
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
        <p className="text-sm text-gray-500">No vehicles linked to this customer.</p>
      ) : (
        <div className="overflow-x-auto rounded-lg border border-gray-200">
          <table className="min-w-full divide-y divide-gray-200">
            <caption className="sr-only">Linked vehicles</caption>
            <thead className="bg-gray-50">
              <tr>
                <th scope="col" className="px-4 py-3 text-left text-xs font-medium uppercase tracking-wider text-gray-500">Rego</th>
                <th scope="col" className="px-4 py-3 text-left text-xs font-medium uppercase tracking-wider text-gray-500">Vehicle</th>
                <th scope="col" className="px-4 py-3 text-left text-xs font-medium uppercase tracking-wider text-gray-500">Colour</th>
                <th scope="col" className="px-4 py-3 text-left text-xs font-medium uppercase tracking-wider text-gray-500">Source</th>
                <th scope="col" className="px-4 py-3 text-left text-xs font-medium uppercase tracking-wider text-gray-500">Linked</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-gray-200 bg-white">
              {customer.vehicles.map((v) => (
                <tr key={v.id} className="hover:bg-gray-50">
                  <td className="whitespace-nowrap px-4 py-3 text-sm font-mono font-medium text-blue-600">{v.rego || '—'}</td>
                  <td className="whitespace-nowrap px-4 py-3 text-sm text-gray-900">
                    {[v.year, v.make, v.model].filter(Boolean).join(' ') || '—'}
                  </td>
                  <td className="whitespace-nowrap px-4 py-3 text-sm text-gray-700">{v.colour || '—'}</td>
                  <td className="whitespace-nowrap px-4 py-3 text-sm">
                    <Badge variant={v.source === 'global' ? 'info' : 'neutral'}>{v.source === 'global' ? 'Carjam' : 'Manual'}</Badge>
                  </td>
                  <td className="whitespace-nowrap px-4 py-3 text-sm text-gray-700">{formatDate(v.linked_at)}</td>
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
        <p className="text-sm text-gray-500">No invoices for this customer.</p>
      ) : (
        <div className="overflow-x-auto rounded-lg border border-gray-200">
          <table className="min-w-full divide-y divide-gray-200">
            <caption className="sr-only">Invoice history</caption>
            <thead className="bg-gray-50">
              <tr>
                <th scope="col" className="px-4 py-3 text-left text-xs font-medium uppercase tracking-wider text-gray-500">Invoice #</th>
                <th scope="col" className="px-4 py-3 text-left text-xs font-medium uppercase tracking-wider text-gray-500">Rego</th>
                <th scope="col" className="px-4 py-3 text-left text-xs font-medium uppercase tracking-wider text-gray-500">Status</th>
                <th scope="col" className="px-4 py-3 text-left text-xs font-medium uppercase tracking-wider text-gray-500">Date</th>
                <th scope="col" className="px-4 py-3 text-right text-xs font-medium uppercase tracking-wider text-gray-500">Total</th>
                <th scope="col" className="px-4 py-3 text-right text-xs font-medium uppercase tracking-wider text-gray-500">Balance</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-gray-200 bg-white">
              {customer.invoices.map((inv) => {
                const cfg = INVOICE_STATUS_CONFIG[inv.status] ?? { label: inv.status, variant: 'neutral' as BadgeVariant }
                return (
                  <tr
                    key={inv.id}
                    className="hover:bg-gray-50 cursor-pointer"
                    onClick={() => { window.location.href = `/invoices/${inv.id}` }}
                  >
                    <td className="whitespace-nowrap px-4 py-3 text-sm font-medium text-blue-600">
                      {inv.invoice_number || <span className="text-gray-400 italic">Draft</span>}
                    </td>
                    <td className="whitespace-nowrap px-4 py-3 text-sm text-gray-700 font-mono">{inv.vehicle_rego || '—'}</td>
                    <td className="whitespace-nowrap px-4 py-3 text-sm"><Badge variant={cfg.variant}>{cfg.label}</Badge></td>
                    <td className="whitespace-nowrap px-4 py-3 text-sm text-gray-700">{formatDate(inv.issue_date)}</td>
                    <td className="whitespace-nowrap px-4 py-3 text-sm text-gray-900 text-right tabular-nums">{formatNZD(inv.total)}</td>
                    <td className="whitespace-nowrap px-4 py-3 text-sm text-right tabular-nums">
                      <span className={parseFloat(inv.balance_due) > 0 ? 'text-red-600 font-medium' : 'text-gray-700'}>
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

  return (
    <div className="px-4 py-6 sm:px-6 lg:px-8">
      {/* Header */}
      <div className="flex flex-col gap-4 sm:flex-row sm:items-center sm:justify-between mb-6">
        <div className="flex items-center gap-3">
          <button
            onClick={() => { window.location.href = '/customers' }}
            className="rounded p-1 text-gray-400 hover:text-gray-600 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-blue-500"
            aria-label="Back to customers"
          >
            ←
          </button>
          <h1 className="text-2xl font-semibold text-gray-900">{fullName}</h1>
          {customer.is_anonymised && <Badge variant="neutral">Anonymised</Badge>}
        </div>
        <div className="flex flex-wrap items-center gap-2">
          {remindersConfigured ? (
            <Button
              size="sm"
              variant="secondary"
              className="bg-green-600 text-white hover:bg-green-700 focus-visible:ring-green-500"
              onClick={handleOpenReminders}
            >
              ✓ Reminders Configured
            </Button>
          ) : (
            <Button size="sm" variant="secondary" onClick={handleOpenReminders}>
              Configure Reminders
            </Button>
          )}
          <Button size="sm" variant="secondary" onClick={() => setNotifyOpen(true)}>
            {smsEnabled ? 'Send Email / SMS' : 'Send Email'}
          </Button>
          <Button size="sm" variant="secondary" onClick={() => setMergeOpen(true)}>
            Merge Customer
          </Button>
          {!customer.is_anonymised && (
            <>
              <Button size="sm" variant="secondary" onClick={() => setExportOpen(true)}>
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
        <div className="mb-4 rounded-md border border-green-200 bg-green-50 px-4 py-2 text-sm text-green-700" role="status">
          {notifyResult}
        </div>
      )}

      {/* Summary cards */}
      <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-4 mb-6">
        <div className="rounded-lg border border-gray-200 p-4">
          <p className="text-xs font-medium text-gray-500 uppercase tracking-wider">Total Spend</p>
          <p className="mt-1 text-xl font-semibold text-gray-900 tabular-nums">{formatNZD(customer.total_spend)}</p>
        </div>
        <div className="rounded-lg border border-gray-200 p-4">
          <p className="text-xs font-medium text-gray-500 uppercase tracking-wider">Outstanding</p>
          <p className={`mt-1 text-xl font-semibold tabular-nums ${outstandingNum > 0 ? 'text-red-600' : 'text-green-600'}`}>
            {formatNZD(customer.outstanding_balance)}
          </p>
        </div>
        {vehiclesEnabled && (
        <div className="rounded-lg border border-gray-200 p-4">
          <p className="text-xs font-medium text-gray-500 uppercase tracking-wider">Vehicles</p>
          <p className="mt-1 text-xl font-semibold text-gray-900">{customer.vehicles.length}</p>
        </div>
        )}
        <div className="rounded-lg border border-gray-200 p-4">
          <p className="text-xs font-medium text-gray-500 uppercase tracking-wider">Invoices</p>
          <p className="mt-1 text-xl font-semibold text-gray-900">{customer.invoices.length}</p>
        </div>
      </div>

      {/* Contact details */}
      <section className="rounded-lg border border-gray-200 p-4 mb-6">
        <h2 className="text-sm font-medium text-gray-500 uppercase tracking-wider mb-2">Contact Details</h2>
        <dl className="grid grid-cols-1 gap-2 sm:grid-cols-2 text-sm">
          <div>
            <dt className="text-gray-500">Email</dt>
            <dd className="text-gray-900">{customer.email || '—'}</dd>
          </div>
          <div>
            <dt className="text-gray-500">Phone</dt>
            <dd className="text-gray-900">{customer.phone || '—'}</dd>
          </div>
          <div className="sm:col-span-2">
            <dt className="text-gray-500">Address</dt>
            <dd className="text-gray-900">{customer.address || '—'}</dd>
          </div>
          {customer.notes && (
            <div className="sm:col-span-2">
              <dt className="text-gray-500">Notes</dt>
              <dd className="text-gray-900 whitespace-pre-wrap">{customer.notes}</dd>
            </div>
          )}
        </dl>
      </section>

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
                  <div className="rounded-lg border border-gray-200 p-4">
                    <p className="text-xs font-medium text-gray-500 uppercase tracking-wider">Total Claims</p>
                    <p className="mt-1 text-xl font-semibold text-gray-900">{(claimsData?.total_claims ?? 0).toLocaleString()}</p>
                  </div>
                  <div className="rounded-lg border border-gray-200 p-4">
                    <p className="text-xs font-medium text-gray-500 uppercase tracking-wider">Open Claims</p>
                    <p className="mt-1 text-xl font-semibold text-amber-600">{(claimsData?.open_claims ?? 0).toLocaleString()}</p>
                  </div>
                  <div className="rounded-lg border border-gray-200 p-4">
                    <p className="text-xs font-medium text-gray-500 uppercase tracking-wider">Total Cost to Business</p>
                    <p className="mt-1 text-xl font-semibold text-red-600">{formatNZD(claimsData?.total_cost_to_business ?? 0)}</p>
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
                  <p className="text-sm text-gray-500">No claims for this customer.</p>
                ) : (
                  <div className="overflow-x-auto rounded-lg border border-gray-200">
                    <table className="min-w-full divide-y divide-gray-200">
                      <caption className="sr-only">Customer claims</caption>
                      <thead className="bg-gray-50">
                        <tr>
                          <th scope="col" className="px-4 py-3 text-left text-xs font-medium uppercase tracking-wider text-gray-500">Type</th>
                          <th scope="col" className="px-4 py-3 text-left text-xs font-medium uppercase tracking-wider text-gray-500">Status</th>
                          <th scope="col" className="px-4 py-3 text-left text-xs font-medium uppercase tracking-wider text-gray-500">Description</th>
                          <th scope="col" className="px-4 py-3 text-left text-xs font-medium uppercase tracking-wider text-gray-500">Created</th>
                          <th scope="col" className="px-4 py-3 text-right text-xs font-medium uppercase tracking-wider text-gray-500">Cost</th>
                        </tr>
                      </thead>
                      <tbody className="divide-y divide-gray-200 bg-white">
                        {(claimsData?.claims ?? []).map((claim) => {
                          const statusCfg: Record<string, { label: string; variant: BadgeVariant }> = {
                            open: { label: 'Open', variant: 'info' },
                            investigating: { label: 'Investigating', variant: 'warning' },
                            approved: { label: 'Approved', variant: 'success' },
                            rejected: { label: 'Rejected', variant: 'error' },
                            resolved: { label: 'Resolved', variant: 'neutral' },
                          }
                          const cfg = statusCfg[claim.status] ?? { label: claim.status, variant: 'neutral' as BadgeVariant }
                          return (
                            <tr
                              key={claim.id}
                              className="hover:bg-gray-50 cursor-pointer"
                              onClick={() => navigate(`/claims/${claim.id}`)}
                            >
                              <td className="whitespace-nowrap px-4 py-3 text-sm text-gray-900 capitalize">{(claim.claim_type ?? '').replace(/_/g, ' ')}</td>
                              <td className="whitespace-nowrap px-4 py-3 text-sm"><Badge variant={cfg.variant}>{cfg.label}</Badge></td>
                              <td className="px-4 py-3 text-sm text-gray-700 max-w-xs truncate">{claim.description}</td>
                              <td className="whitespace-nowrap px-4 py-3 text-sm text-gray-700">{formatDate(claim.created_at)}</td>
                              <td className="whitespace-nowrap px-4 py-3 text-sm text-gray-900 text-right tabular-nums">{formatNZD(claim.cost_to_business ?? 0)}</td>
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
            <label className="block text-sm font-medium text-gray-700 mb-1">Message</label>
            <textarea
              value={notifyMessage}
              onChange={(e) => setNotifyMessage(e.target.value)}
              rows={4}
              className="w-full rounded-md border border-gray-300 px-3 py-2 text-sm text-gray-900 shadow-sm placeholder:text-gray-400 focus:outline-none focus:ring-2 focus:ring-blue-500 focus:border-blue-500"
              placeholder={notifyChannel === 'email' ? 'Email body…' : 'SMS message…'}
            />
          </div>
        </div>
        {notifyError && <p className="mt-2 text-sm text-red-600" role="alert">{notifyError}</p>}
        <div className="mt-4 flex justify-end gap-2">
          <Button variant="secondary" size="sm" onClick={() => { setNotifyOpen(false); setNotifyError('') }}>Cancel</Button>
          <Button size="sm" onClick={handleNotify} loading={notifying}>Send</Button>
        </div>
      </Modal>

      {/* ---- Merge Modal ---- */}
      <Modal open={mergeOpen} onClose={resetMerge} title="Merge Customer" className="max-w-2xl">
        {!mergePreview ? (
          /* Step 1: Search for source customer */
          <div>
            <p className="text-sm text-gray-600 mb-3">
              Search for the duplicate customer to merge into <span className="font-medium">{fullName}</span>.
              The selected customer's data will be combined into this profile.
            </p>
            <Input
              label="Search customer"
              placeholder="Name, email, or phone…"
              value={mergeSearch}
              onChange={(e) => handleMergeSearch(e.target.value)}
            />
            {mergeResults.length > 0 && (
              <ul className="mt-2 rounded-md border border-gray-200 divide-y divide-gray-100 max-h-48 overflow-auto">
                {mergeResults.map((c) => (
                  <li key={c.id}>
                    <button
                      onClick={() => handleMergePreview(c.id)}
                      className="w-full text-left px-3 py-2 text-sm hover:bg-gray-50 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-blue-500"
                    >
                      <span className="font-medium text-gray-900">{c.first_name} {c.last_name}</span>
                      {c.email && <span className="text-gray-500 ml-2">{c.email}</span>}
                      {c.phone && <span className="text-gray-500 ml-2">{c.phone}</span>}
                    </button>
                  </li>
                ))}
              </ul>
            )}
            {mergeLoading && <div className="mt-3"><Spinner label="Loading preview" /></div>}
            {mergeError && <p className="mt-2 text-sm text-red-600" role="alert">{mergeError}</p>}
          </div>
        ) : (
          /* Step 2: Confirmation preview */
          <div>
            <p className="text-sm text-gray-600 mb-4">
              Review what will be combined when merging{' '}
              <span className="font-medium">{mergePreview.source_customer.first_name} {mergePreview.source_customer.last_name}</span>
              {' '}into{' '}
              <span className="font-medium">{mergePreview.target_customer.first_name} {mergePreview.target_customer.last_name}</span>.
            </p>

            {/* Vehicles to transfer */}
            {mergePreview.vehicles_to_transfer.length > 0 && (
              <div className="mb-3">
                <h3 className="text-sm font-medium text-gray-700 mb-1">
                  Vehicles to transfer ({mergePreview.vehicles_to_transfer.length})
                </h3>
                <ul className="text-sm text-gray-600 space-y-1">
                  {mergePreview.vehicles_to_transfer.map((v) => (
                    <li key={v.id} className="flex items-center gap-2">
                      <span className="font-mono">{v.rego || 'No rego'}</span>
                      <span>{[v.make, v.model].filter(Boolean).join(' ')}</span>
                    </li>
                  ))}
                </ul>
              </div>
            )}

            {/* Invoices to transfer */}
            {mergePreview.invoices_to_transfer.length > 0 && (
              <div className="mb-3">
                <h3 className="text-sm font-medium text-gray-700 mb-1">
                  Invoices to transfer ({mergePreview.invoices_to_transfer.length})
                </h3>
                <ul className="text-sm text-gray-600 space-y-1">
                  {mergePreview.invoices_to_transfer.map((inv) => (
                    <li key={inv.id} className="flex items-center gap-2">
                      <span className="font-medium">{inv.invoice_number || 'Draft'}</span>
                      <Badge variant={(INVOICE_STATUS_CONFIG[inv.status]?.variant ?? 'neutral') as BadgeVariant}>
                        {INVOICE_STATUS_CONFIG[inv.status]?.label ?? inv.status}
                      </Badge>
                      <span className="tabular-nums">{formatNZD(inv.total)}</span>
                    </li>
                  ))}
                </ul>
              </div>
            )}

            {/* Contact changes */}
            <div className="mb-3">
              <h3 className="text-sm font-medium text-gray-700 mb-1">Contact details after merge</h3>
              <dl className="text-sm text-gray-600 space-y-1">
                {mergePreview.contact_changes.email && (
                  <div className="flex gap-2"><dt className="text-gray-500 w-16">Email:</dt><dd>{mergePreview.contact_changes.email}</dd></div>
                )}
                {mergePreview.contact_changes.phone && (
                  <div className="flex gap-2"><dt className="text-gray-500 w-16">Phone:</dt><dd>{mergePreview.contact_changes.phone}</dd></div>
                )}
                {mergePreview.contact_changes.address && (
                  <div className="flex gap-2"><dt className="text-gray-500 w-16">Address:</dt><dd>{mergePreview.contact_changes.address}</dd></div>
                )}
              </dl>
            </div>

            {mergePreview.fleet_account_transfer && (
              <div className="mb-3 rounded-md border border-amber-200 bg-amber-50 px-3 py-2 text-sm text-amber-700">
                A fleet account will be transferred to this customer.
              </div>
            )}

            {mergeError && <p className="mt-2 text-sm text-red-600" role="alert">{mergeError}</p>}

            <div className="mt-4 flex justify-end gap-2">
              <Button variant="secondary" size="sm" onClick={() => { setMergePreview(null); setMergeSourceId(null) }}>
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
            <Button variant="secondary" size="sm" onClick={resetMerge}>Cancel</Button>
          </div>
        )}
      </Modal>

      {/* ---- Privacy Act: Deletion Confirmation Modal ---- */}
      <Modal open={deleteOpen} onClose={() => { setDeleteOpen(false); setDeleteError('') }} title="Process Deletion Request">
        <div className="space-y-3">
          <div className="rounded-md border border-amber-200 bg-amber-50 px-4 py-3 text-sm text-amber-800">
            <p className="font-medium mb-1">Privacy Act 2020 — Customer Data Deletion</p>
            <p>You are about to process a deletion request for <span className="font-medium">{fullName}</span>.</p>
          </div>
          <div className="text-sm text-gray-700 space-y-2">
            <p className="font-medium">This action will:</p>
            <ul className="list-disc pl-5 space-y-1">
              <li>Replace the customer name with "Anonymised Customer"</li>
              <li>Clear all contact details (email, phone, address)</li>
              <li>Remove any personal notes</li>
            </ul>
            <p className="font-medium mt-3">This action will NOT:</p>
            <ul className="list-disc pl-5 space-y-1">
              <li>Delete any invoices — financial records remain intact</li>
              <li>Remove payment history or transaction amounts</li>
              <li>Unlink vehicles from invoice records</li>
            </ul>
          </div>
          <div className="rounded-md border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700">
            This action cannot be undone.
          </div>
        </div>
        {deleteError && <p className="mt-2 text-sm text-red-600" role="alert">{deleteError}</p>}
        <div className="mt-4 flex justify-end gap-2">
          <Button variant="secondary" size="sm" onClick={() => { setDeleteOpen(false); setDeleteError('') }}>Cancel</Button>
          <Button variant="danger" size="sm" onClick={handleProcessDeletion} loading={deleting}>
            Confirm Anonymisation
          </Button>
        </div>
      </Modal>

      {/* ---- Privacy Act: Export Data Confirmation Modal ---- */}
      <Modal open={exportOpen} onClose={() => { setExportOpen(false); setExportError('') }} title="Export Customer Data">
        <div className="space-y-3">
          <div className="rounded-md border border-blue-200 bg-blue-50 px-4 py-3 text-sm text-blue-800">
            <p className="font-medium mb-1">Privacy Act 2020 — Customer Data Export</p>
            <p>Export all stored data for <span className="font-medium">{fullName}</span> as a JSON file.</p>
          </div>
          <div className="text-sm text-gray-700 space-y-2">
            <p className="font-medium">The export will include:</p>
            <ul className="list-disc pl-5 space-y-1">
              <li>Customer profile (name, email, phone, address)</li>
              <li>All linked vehicles</li>
              <li>Complete invoice history</li>
              <li>Payment records</li>
              <li>Any notes or tags</li>
            </ul>
          </div>
          <p className="text-sm text-gray-500">
            The file will be downloaded to your device in JSON format, suitable for providing to the customer upon request.
          </p>
        </div>
        {exportError && <p className="mt-2 text-sm text-red-600" role="alert">{exportError}</p>}
        <div className="mt-4 flex justify-end gap-2">
          <Button variant="secondary" size="sm" onClick={() => { setExportOpen(false); setExportError('') }}>Cancel</Button>
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
            <p className="text-sm text-gray-600">
              Configure automatic reminders for this customer. Each reminder type can be enabled separately with its own timing and notification channel.
            </p>

            {/* Service Due — vehicle module only */}
            {vehiclesEnabled && (
            <div className="rounded-lg border border-gray-200 p-4 space-y-3">
              <div className="flex items-center justify-between">
                <h3 className="text-sm font-medium text-gray-900">Service Due</h3>
                <label className="relative inline-flex items-center cursor-pointer">
                  <input
                    type="checkbox"
                    checked={reminderConfig.service_due.enabled}
                    onChange={(e) => updateReminder('service_due', { enabled: e.target.checked })}
                    className="sr-only peer"
                  />
                  <div className="w-9 h-5 bg-gray-200 peer-focus:outline-none peer-focus:ring-2 peer-focus:ring-blue-300 rounded-full peer peer-checked:after:translate-x-full peer-checked:after:border-white after:content-[''] after:absolute after:top-[2px] after:left-[2px] after:bg-white after:border-gray-300 after:border after:rounded-full after:h-4 after:w-4 after:transition-all peer-checked:bg-blue-600" />
                  <span className="ml-2 text-sm text-gray-600">{reminderConfig.service_due.enabled ? 'Enabled' : 'Disabled'}</span>
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
                      <p className="text-xs font-medium text-gray-500 uppercase tracking-wider">Vehicle Service Due Dates</p>
                      {reminderConfig.vehicles.map((v) => {
                        const dateVal = getVehicleDate(v, 'service_due_date')
                        return (
                          <div key={v.global_vehicle_id} className="flex items-center gap-3 rounded-md bg-gray-50 px-3 py-2">
                            <div className="flex-1 min-w-0">
                              <span className="text-sm font-mono font-medium text-gray-900">{v.rego || '—'}</span>
                              <span className="ml-2 text-sm text-gray-500">{[v.year, v.make, v.model].filter(Boolean).join(' ')}</span>
                            </div>
                            <div className="flex items-center gap-2">
                              {dateVal ? (
                                <span className="text-sm text-gray-700">{dateVal}</span>
                              ) : (
                                <span className="text-xs text-amber-600">Not set</span>
                              )}
                              <input
                                type="date"
                                value={dateVal}
                                onChange={(e) => updateVehicleDate(v.global_vehicle_id, 'service_due_date', e.target.value)}
                                className="rounded-md border border-gray-300 px-2 py-1 text-sm text-gray-900 focus:outline-none focus:ring-2 focus:ring-blue-500 focus:border-blue-500"
                                aria-label={`Service due date for ${v.rego || 'vehicle'}`}
                              />
                            </div>
                          </div>
                        )
                      })}
                    </div>
                  ) : (
                    <p className="text-xs text-gray-400 italic">No vehicles linked to this customer.</p>
                  )}
                </>
              )}
            </div>
            )}

            {/* WOF Expiry — automotive only */}
            {isAutomotive && vehiclesEnabled && (
            <div className="rounded-lg border border-gray-200 p-4 space-y-3">
              <div className="flex items-center justify-between">
                <h3 className="text-sm font-medium text-gray-900">WOF Expiry</h3>
                <label className="relative inline-flex items-center cursor-pointer">
                  <input
                    type="checkbox"
                    checked={reminderConfig.wof_expiry.enabled}
                    onChange={(e) => updateReminder('wof_expiry', { enabled: e.target.checked })}
                    className="sr-only peer"
                  />
                  <div className="w-9 h-5 bg-gray-200 peer-focus:outline-none peer-focus:ring-2 peer-focus:ring-blue-300 rounded-full peer peer-checked:after:translate-x-full peer-checked:after:border-white after:content-[''] after:absolute after:top-[2px] after:left-[2px] after:bg-white after:border-gray-300 after:border after:rounded-full after:h-4 after:w-4 after:transition-all peer-checked:bg-blue-600" />
                  <span className="ml-2 text-sm text-gray-600">{reminderConfig.wof_expiry.enabled ? 'Enabled' : 'Disabled'}</span>
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
                      <p className="text-xs font-medium text-gray-500 uppercase tracking-wider">Vehicle WOF Expiry Dates</p>
                      {reminderConfig.vehicles.map((v) => {
                        const dateVal = getVehicleDate(v, 'wof_expiry')
                        return (
                          <div key={v.global_vehicle_id} className="flex items-center gap-3 rounded-md bg-gray-50 px-3 py-2">
                            <div className="flex-1 min-w-0">
                              <span className="text-sm font-mono font-medium text-gray-900">{v.rego || '—'}</span>
                              <span className="ml-2 text-sm text-gray-500">{[v.year, v.make, v.model].filter(Boolean).join(' ')}</span>
                            </div>
                            <div className="flex items-center gap-2">
                              {dateVal ? (
                                <span className="text-sm text-gray-700">{dateVal}</span>
                              ) : (
                                <span className="text-xs text-amber-600">Not set</span>
                              )}
                              <input
                                type="date"
                                value={dateVal}
                                onChange={(e) => updateVehicleDate(v.global_vehicle_id, 'wof_expiry', e.target.value)}
                                className="rounded-md border border-gray-300 px-2 py-1 text-sm text-gray-900 focus:outline-none focus:ring-2 focus:ring-blue-500 focus:border-blue-500"
                                aria-label={`WOF expiry date for ${v.rego || 'vehicle'}`}
                              />
                            </div>
                          </div>
                        )
                      })}
                    </div>
                  ) : (
                    <p className="text-xs text-gray-400 italic">No vehicles linked to this customer.</p>
                  )}
                </>
              )}
            </div>
            )}
          </div>
        )}
        {reminderError && <p className="mt-2 text-sm text-red-600" role="alert">{reminderError}</p>}
        <div className="mt-4 flex justify-end gap-2">
          <Button variant="secondary" size="sm" onClick={() => { setReminderOpen(false); setReminderError('') }}>Cancel</Button>
          <Button size="sm" onClick={handleSaveReminders} loading={reminderSaving}>Save</Button>
        </div>
      </Modal>
    </div>
  )
}
