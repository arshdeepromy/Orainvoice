import { useState, useEffect, useRef, useCallback } from 'react'
import apiClient from '../../api/client'
import { Button, Input, Spinner, Pagination, PageSizeSelect, Modal, Select } from '../../components/ui'
import { CustomerCreateModal } from '../../components/customers/CustomerCreateModal'
import { CustomerEditModal } from '../../components/customers/CustomerEditModal'
import { CustomerViewModal } from '../../components/customers/CustomerViewModal'

/* ------------------------------------------------------------------ */
/*  Types                                                              */
/* ------------------------------------------------------------------ */

interface CustomerSearchResult {
  id: string
  first_name: string
  last_name: string
  company_name?: string | null
  display_name?: string | null
  email: string | null
  phone: string | null
  mobile_phone?: string | null
  work_phone?: string | null
  customer_type?: string
  receivables?: number
  unused_credits?: number
  reminders_enabled?: boolean
}

interface CustomerListResponse {
  customers: CustomerSearchResult[]
  total: number
  has_exact_match: boolean
}

const DEFAULT_PAGE_SIZE = 10

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

const DEFAULT_REMINDER_CONFIG: CustomerReminderConfig = {
  service_due: { enabled: false, days_before: 30, channel: 'email' },
  wof_expiry: { enabled: false, days_before: 30, channel: 'email' },
  vehicles: [],
}

function formatNZD(amount: number | null | undefined): string {
  if (amount == null || isNaN(Number(amount))) return 'NZD0.00'
  return `NZD${Number(amount).toLocaleString('en-NZ', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`
}

/* ------------------------------------------------------------------ */
/*  Component                                                          */
/* ------------------------------------------------------------------ */

export default function CustomerList() {
  const [searchQuery, setSearchQuery] = useState('')
  const [page, setPage] = useState(1)
  const [pageSize, setPageSize] = useState(DEFAULT_PAGE_SIZE)
  const [data, setData] = useState<CustomerListResponse | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')

  /* Create modal */
  const [createOpen, setCreateOpen] = useState(false)

  /* Edit modal */
  const [editOpen, setEditOpen] = useState(false)
  const [editCustomerId, setEditCustomerId] = useState<string | null>(null)

  /* View modal */
  const [viewOpen, setViewOpen] = useState(false)
  const [viewCustomerId, setViewCustomerId] = useState<string | null>(null)

  const debounceRef = useRef<ReturnType<typeof setTimeout>>()
  const abortRef = useRef<AbortController>()

  const totalPages = data ? Math.max(1, Math.ceil(data.total / pageSize)) : 1

  /* --- Fetch customers --- */
  const fetchCustomers = useCallback(async (search: string, pg: number) => {
    if (abortRef.current) abortRef.current.abort()
    const controller = new AbortController()
    abortRef.current = controller

    setLoading(true)
    setError('')
    try {
      const params: Record<string, string | number> = {
        limit: pageSize,
        offset: (pg - 1) * pageSize,
      }
      if (search.trim()) params.q = search.trim()

      const res = await apiClient.get<CustomerListResponse>('/customers', {
        params,
        signal: controller.signal,
      })
      setData(res.data)
    } catch (err: unknown) {
      if ((err as { name?: string })?.name === 'CanceledError') return
      setError('Failed to load customers. Please try again.')
    } finally {
      setLoading(false)
    }
  }, [])

  /* --- Debounced search --- */
  useEffect(() => {
    if (debounceRef.current) clearTimeout(debounceRef.current)
    debounceRef.current = setTimeout(() => {
      setPage(1)
      fetchCustomers(searchQuery, 1)
    }, 300)
    return () => { if (debounceRef.current) clearTimeout(debounceRef.current) }
  }, [searchQuery, fetchCustomers])

  useEffect(() => {
    fetchCustomers(searchQuery, page)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [page, pageSize])

  /* --- Handle customer created --- */
  const handleCustomerCreated = (customer: { id: string }) => {
    setCreateOpen(false)
    window.location.href = `/customers/${customer.id}`
  }

  /* --- Open view modal --- */
  const handleView = (c: CustomerSearchResult) => {
    setViewCustomerId(c.id)
    setViewOpen(true)
  }

  /* --- Open edit modal --- */
  const handleEditOpen = (c: CustomerSearchResult) => {
    setEditCustomerId(c.id)
    setEditOpen(true)
  }

  /* --- Toggle reminders on/off --- */
  const [togglingReminder, setTogglingReminder] = useState<string | null>(null)

  /* Reminder config modal state */
  const [reminderOpen, setReminderOpen] = useState(false)
  const [reminderCustomerId, setReminderCustomerId] = useState<string | null>(null)
  const [reminderConfig, setReminderConfig] = useState<CustomerReminderConfig>(DEFAULT_REMINDER_CONFIG)
  const [reminderLoading, setReminderLoading] = useState(false)
  const [reminderSaving, setReminderSaving] = useState(false)
  const [reminderError, setReminderError] = useState('')
  const [vehicleDateEdits, setVehicleDateEdits] = useState<Record<string, { service_due_date?: string; wof_expiry?: string }>>({})

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

  const handleToggleReminder = async (c: CustomerSearchResult) => {
    if (c.reminders_enabled) {
      // Turn off directly
      setTogglingReminder(c.id)
      try {
        await apiClient.put(`/customers/${c.id}/reminders`, {
          service_due: { enabled: false, days_before: 30, channel: 'email' },
          wof_expiry: { enabled: false, days_before: 30, channel: 'email' },
        })
        await fetchCustomers(searchQuery, page)
      } catch { /* silent */ }
      finally { setTogglingReminder(null) }
    } else {
      // Turn on: open the Configure Reminders modal
      setReminderCustomerId(c.id)
      setReminderOpen(true)
      setReminderError('')
      setReminderLoading(true)
      setVehicleDateEdits({})
      try {
        const res = await apiClient.get<CustomerReminderConfig>(`/customers/${c.id}/reminders`)
        setReminderConfig(res.data)
      } catch {
        setReminderError('Failed to load reminder settings.')
      } finally {
        setReminderLoading(false)
      }
    }
  }

  const handleSaveReminders = async () => {
    if (!reminderCustomerId) return
    setReminderSaving(true)
    setReminderError('')
    try {
      const dateUpdates = Object.entries(vehicleDateEdits)
        .filter(([, v]) => v.service_due_date !== undefined || v.wof_expiry !== undefined)
        .map(([gvId, dates]) => ({ global_vehicle_id: gvId, ...dates }))

      if (dateUpdates.length > 0) {
        await apiClient.put(`/customers/${reminderCustomerId}/vehicle-dates`, { vehicles: dateUpdates })
      }

      const { vehicles: _v, ...configOnly } = reminderConfig
      await apiClient.put(`/customers/${reminderCustomerId}/reminders`, configOnly)
      setReminderOpen(false)
      setVehicleDateEdits({})
      await fetchCustomers(searchQuery, page)
    } catch {
      setReminderError('Failed to save reminder settings.')
    } finally {
      setReminderSaving(false)
    }
  }

  return (
    <div className="px-4 py-6 sm:px-6 lg:px-8">
      {/* Header */}
      <div className="flex flex-col gap-4 sm:flex-row sm:items-center sm:justify-between mb-6">
        <h1 className="text-2xl font-semibold text-gray-900">Active Customers</h1>
        <Button onClick={() => setCreateOpen(true)}>+ New</Button>
      </div>

      {/* Search */}
      <div className="mb-4">
        <Input
          label="Search"
          placeholder="Search by name, phone, or email…"
          value={searchQuery}
          onChange={(e) => setSearchQuery(e.target.value)}
          aria-label="Search customers"
        />
        {searchQuery && data && (
          <p className="mt-1 text-sm text-gray-500">
            {data.total} result{data.total !== 1 ? 's' : ''}
            {!data.has_exact_match && data.total === 0 && (
              <>
                {' — '}
                <button
                  onClick={() => setCreateOpen(true)}
                  className="text-blue-600 hover:text-blue-800 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-blue-500 rounded"
                >
                  Create new customer
                </button>
              </>
            )}
          </p>
        )}
      </div>

      {/* Error */}
      {error && (
        <div className="mb-4 rounded-md border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700" role="alert">
          {error}
        </div>
      )}

      {/* Loading */}
      {loading && !data && (
        <div className="py-16"><Spinner label="Loading customers" /></div>
      )}

      {/* Customer table */}
      {data && (
        <>
          <div className="overflow-x-auto rounded-lg border border-gray-200">
            <table className="min-w-full divide-y divide-gray-200" role="grid">
              <caption className="sr-only">Customer list</caption>
              <thead className="bg-gray-50">
                <tr>
                  <th scope="col" className="px-4 py-3 text-left text-xs font-medium uppercase tracking-wider text-gray-500">Name</th>
                  <th scope="col" className="px-4 py-3 text-left text-xs font-medium uppercase tracking-wider text-gray-500">Company Name</th>
                  <th scope="col" className="px-4 py-3 text-left text-xs font-medium uppercase tracking-wider text-gray-500">Email</th>
                  <th scope="col" className="px-4 py-3 text-left text-xs font-medium uppercase tracking-wider text-gray-500">Work Phone</th>
                  <th scope="col" className="px-4 py-3 text-right text-xs font-medium uppercase tracking-wider text-gray-500">Receivables (BCY)</th>
                  <th scope="col" className="px-4 py-3 text-right text-xs font-medium uppercase tracking-wider text-gray-500">Unused Credits (BCY)</th>
                  <th scope="col" className="px-4 py-3 text-center text-xs font-medium uppercase tracking-wider text-gray-500">Reminders WOF/Rego</th>
                  <th scope="col" className="px-4 py-3 text-center text-xs font-medium uppercase tracking-wider text-gray-500">Actions</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-gray-200 bg-white">
                {!data.customers || data.customers.length === 0 ? (
                  <tr>
                    <td colSpan={8} className="px-4 py-12 text-center text-sm text-gray-500">
                      {searchQuery ? 'No customers match your search.' : 'No customers yet. Create your first customer to get started.'}
                    </td>
                  </tr>
                ) : (
                  data.customers.map((c) => (
                    <tr
                      key={c.id}
                      className="hover:bg-gray-50 cursor-pointer"
                      onClick={() => { window.location.href = `/customers/${c.id}` }}
                    >
                      <td className="whitespace-nowrap px-4 py-3 text-sm font-medium text-blue-600">
                        {c.display_name || `${c.first_name} ${c.last_name}`}
                      </td>
                      <td className="whitespace-nowrap px-4 py-3 text-sm text-gray-700">
                        {c.company_name || '—'}
                      </td>
                      <td className="whitespace-nowrap px-4 py-3 text-sm text-gray-700">
                        {c.email || '—'}
                      </td>
                      <td className="whitespace-nowrap px-4 py-3 text-sm text-gray-700">
                        {c.work_phone || c.phone || c.mobile_phone || '—'}
                      </td>
                      <td className="whitespace-nowrap px-4 py-3 text-sm text-right tabular-nums text-gray-900">
                        {formatNZD(c.receivables)}
                      </td>
                      <td className="whitespace-nowrap px-4 py-3 text-sm text-right tabular-nums text-gray-900">
                        {formatNZD(c.unused_credits)}
                      </td>
                      <td className="whitespace-nowrap px-4 py-3 text-sm text-center">
                        <button
                          onClick={(e) => { e.stopPropagation(); handleToggleReminder(c) }}
                          disabled={togglingReminder === c.id}
                          className="relative inline-flex h-6 w-11 items-center rounded-full transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-blue-500 focus-visible:ring-offset-2 disabled:opacity-50"
                          style={{ backgroundColor: c.reminders_enabled ? '#16a34a' : '#dc2626' }}
                          role="switch"
                          aria-checked={c.reminders_enabled ?? false}
                          aria-label={`Reminders ${c.reminders_enabled ? 'on' : 'off'} for ${c.first_name} ${c.last_name}`}
                          title={c.reminders_enabled ? 'Reminders ON — click to disable' : 'Reminders OFF — click to enable'}
                        >
                          <span
                            className={`inline-block h-4 w-4 transform rounded-full bg-white shadow transition-transform ${c.reminders_enabled ? 'translate-x-6' : 'translate-x-1'}`}
                          />
                        </button>
                      </td>
                      <td className="whitespace-nowrap px-4 py-3 text-sm text-center">
                        <div className="flex items-center justify-center gap-1">
                          <button
                            onClick={(e) => { e.stopPropagation(); handleView(c) }}
                            className="rounded p-1.5 text-gray-400 hover:text-blue-600 hover:bg-blue-50 transition-colors"
                            title="View details"
                            aria-label={`View ${c.first_name} ${c.last_name}`}
                          >
                            <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                              <path strokeLinecap="round" strokeLinejoin="round" d="M2.036 12.322a1.012 1.012 0 010-.639C3.423 7.51 7.36 4.5 12 4.5c4.638 0 8.573 3.007 9.963 7.178.07.207.07.431 0 .639C20.577 16.49 16.64 19.5 12 19.5c-4.638 0-8.573-3.007-9.963-7.178z" />
                              <path strokeLinecap="round" strokeLinejoin="round" d="M15 12a3 3 0 11-6 0 3 3 0 016 0z" />
                            </svg>
                          </button>
                          <button
                            onClick={(e) => { e.stopPropagation(); handleEditOpen(c) }}
                            className="rounded p-1.5 text-gray-400 hover:text-emerald-600 hover:bg-emerald-50 transition-colors"
                            title="Edit customer"
                            aria-label={`Edit ${c.first_name} ${c.last_name}`}
                          >
                            <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                              <path strokeLinecap="round" strokeLinejoin="round" d="M16.862 4.487l1.687-1.688a1.875 1.875 0 112.652 2.652L10.582 16.07a4.5 4.5 0 01-1.897 1.13L6 18l.8-2.685a4.5 4.5 0 011.13-1.897l8.932-8.931z" />
                            </svg>
                          </button>
                        </div>
                      </td>
                    </tr>
                  ))
                )}
              </tbody>
            </table>
          </div>

          {totalPages > 1 && (
            <div className="mt-4 flex items-center justify-between">
              <p className="text-sm text-gray-500">
                Showing {(page - 1) * pageSize + 1}–{Math.min(page * pageSize, data.total)} of {data.total}
              </p>
              <Pagination currentPage={page} totalPages={totalPages} onPageChange={setPage} />
            </div>
          )}
          <div className="mt-3 flex justify-end">
            <PageSizeSelect value={pageSize} onChange={(size) => { setPageSize(size); setPage(1) }} />
          </div>
        </>
      )}

      {/* Create Customer Modal */}
      <CustomerCreateModal
        open={createOpen}
        onClose={() => setCreateOpen(false)}
        onCustomerCreated={handleCustomerCreated}
      />

      {/* View Customer Modal */}
      <CustomerViewModal
        open={viewOpen}
        customerId={viewCustomerId}
        onClose={() => setViewOpen(false)}
      />

      {/* Edit Customer Modal */}
      <CustomerEditModal
        open={editOpen}
        customerId={editCustomerId}
        onClose={() => setEditOpen(false)}
        onSaved={() => fetchCustomers(searchQuery, page)}
      />

      {/* Configure Reminders Modal */}
      <Modal open={reminderOpen} onClose={() => { setReminderOpen(false); setReminderError('') }} title="Configure Reminders">
        {reminderLoading ? (
          <Spinner label="Loading reminder settings" />
        ) : (
          <div className="space-y-5">
            <p className="text-sm text-gray-600">
              Configure automatic reminders for this customer. Each reminder type can be enabled separately with its own timing and notification channel.
            </p>

            {/* Service Due */}
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
                        { value: 'sms', label: 'SMS' },
                        { value: 'both', label: 'Email & SMS' },
                      ]}
                      value={reminderConfig.service_due.channel}
                      onChange={(e) => updateReminder('service_due', { channel: e.target.value as 'email' | 'sms' | 'both' })}
                    />
                  </div>
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

            {/* WOF Expiry */}
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
                        { value: 'sms', label: 'SMS' },
                        { value: 'both', label: 'Email & SMS' },
                      ]}
                      value={reminderConfig.wof_expiry.channel}
                      onChange={(e) => updateReminder('wof_expiry', { channel: e.target.value as 'email' | 'sms' | 'both' })}
                    />
                  </div>
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
