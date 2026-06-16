/**
 * CustomerList — Task 23 port of frontend/src/pages/customers/CustomerList.tsx.
 *
 * ALL logic is copied VERBATIM from the original: paginated fetch with
 * search/limit/offset + AbortController, debounced search (300ms), reminder
 * toggle + the full Configure-Reminders modal (service due / WOF / COF with
 * per-vehicle date editing, automotive-only gating), view/edit/create modal
 * wiring, row-click navigation to /customers/:id, the Receivables + Unused
 * Credits columns (ISSUE-036), and NZD formatting (`?? 0`-safe).
 *
 * The presentation is reframed onto the design-system tokens per the
 * OraInvoice_Handoff/app/Customers.html prototype (page-head + eyebrow, a
 * search toolbar, a card-wrapped token table, and the ds.css pagination
 * footer). The prototype's columns differ from production (it shows
 * Open balance / Lifetime); FR-1 wins, so production's full column set is
 * preserved and styled in the prototype's language (FR-2b). `.mono` is applied
 * to money / phone / dates per FR-2. The reminder modal has no prototype, so it
 * is designed on the fly with the token system (FR-2b).
 */

import { useState, useEffect, useRef, useCallback } from 'react'
import apiClient from '@/api/client'
import { Button, Input, Spinner, Pagination, PageSizeSelect, Modal, Select } from '@/components/ui'
import { CustomerCreateModal } from '@/components/customers/CustomerCreateModal'
import { CustomerEditModal } from '@/components/customers/CustomerEditModal'
import { CustomerViewModal } from '@/components/customers/CustomerViewModal'
import { useTenant } from '@/contexts/TenantContext'
import { useBranch } from '@/contexts/BranchContext'
import { computeMissingConsent, type MissingConsentPair } from '@/api/customers'
import ConsentConfirmationModal from './ConsentConfirmationModal'

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
  has_reminder_consent?: boolean
  last_portal_access_at?: string | null
  branch_id?: string | null
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
  cof_expiry: string | null
  inspection_type: string | null
}

interface CustomerReminderConfig {
  service_due: ReminderEntry
  wof_expiry: ReminderEntry
  cof_expiry: ReminderEntry
  registration_expiry: ReminderEntry
  vehicles: VehicleExpiryData[]
}

const DEFAULT_REMINDER_CONFIG: CustomerReminderConfig = {
  service_due: { enabled: false, days_before: 30, channel: 'email' },
  wof_expiry: { enabled: false, days_before: 30, channel: 'email' },
  cof_expiry: { enabled: false, days_before: 30, channel: 'email' },
  registration_expiry: { enabled: false, days_before: 30, channel: 'email' },
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
  const { tradeFamily, settings } = useTenant()
  const consentColumnVisible = settings?.branding?.customers_consent_column_visible ?? false
  const { branches: branchList } = useBranch()
  const isAutomotive = (tradeFamily ?? 'automotive-transport') === 'automotive-transport'

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

  const debounceRef = useRef<ReturnType<typeof setTimeout>>(undefined)
  const abortRef = useRef<AbortController>(undefined)

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
  }, [pageSize])

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

  /* Consent confirmation modal state (F3/F4) */
  const [consentModalOpen, setConsentModalOpen] = useState(false)
  const [consentMissing, setConsentMissing] = useState<MissingConsentPair[]>([])
  const [reminderError, setReminderError] = useState('')
  const [vehicleDateEdits, setVehicleDateEdits] = useState<Record<string, { service_due_date?: string; wof_expiry?: string; cof_expiry?: string }>>({})

  const updateReminder = (type: 'service_due' | 'wof_expiry' | 'cof_expiry' | 'registration_expiry', updates: Partial<ReminderEntry>) => {
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
    setReminderConfig(prev => ({
      ...prev,
      vehicles: (prev?.vehicles ?? []).map(v =>
        v.global_vehicle_id === globalVehicleId ? { ...v, [field]: value || null } : v
      ),
    }))
  }

  const getVehicleDate = (v: VehicleExpiryData, field: 'service_due_date' | 'wof_expiry' | 'cof_expiry'): string => {
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
          cof_expiry: { enabled: false, days_before: 30, channel: 'email' },
          registration_expiry: { enabled: false, days_before: 30, channel: 'email' },
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

    // F3: Pre-submit check for missing consent coverage
    const { vehicles: _v, ...configOnly } = reminderConfig
    const missing = computeMissingConsent(null, configOnly as any)
    console.log('[Consent Gate] configOnly:', configOnly, 'missing:', missing)
    if (missing.length > 0) {
      // Open consent confirmation modal instead of saving directly
      setConsentMissing(missing)
      setConsentModalOpen(true)
      return
    }

    // No missing consent — save directly
    setReminderSaving(true)
    setReminderError('')
    try {
      const dateUpdates = Object.entries(vehicleDateEdits)
        .filter(([, v]) => v.service_due_date !== undefined || v.wof_expiry !== undefined || v.cof_expiry !== undefined)
        .map(([gvId, dates]) => ({ global_vehicle_id: gvId, ...dates }))

      if (dateUpdates.length > 0) {
        await apiClient.put(`/customers/${reminderCustomerId}/vehicle-dates`, { vehicles: dateUpdates })
      }

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

  /** Called by ConsentConfirmationModal after consent is recorded + PUT succeeds */
  const handleConsentConfirmed = async () => {
    setConsentModalOpen(false)
    setConsentMissing([])
    setReminderOpen(false)
    setVehicleDateEdits({})
    await fetchCustomers(searchQuery, page)
  }

  return (
    <div className="page page-wide">
      {/* Header */}
      <div className="page-head">
        <div>
          <div className="eyebrow">People</div>
          <h1>Active Customers</h1>
          {data && (
            <p className="sub">
              <span className="mono">{data.total}</span> customer{data.total !== 1 ? 's' : ''}
            </p>
          )}
        </div>
        <div className="head-actions">
          <Button
            leftIcon={
              <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={2.2}>
                <path strokeLinecap="round" strokeLinejoin="round" d="M12 5v14M5 12h14" />
              </svg>
            }
            onClick={() => setCreateOpen(true)}
          >
            New customer
          </Button>
        </div>
      </div>

      {/* Search toolbar */}
      <div className="mb-[22px]">
        <div className="flex h-10 max-w-[340px] items-center gap-2.5 rounded-ctl border border-border bg-card px-3 focus-within:border-accent focus-within:shadow-[0_0_0_3px_var(--accent-soft)]">
          <svg className="h-4 w-4 shrink-0 text-muted-2" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={2}>
            <path strokeLinecap="round" strokeLinejoin="round" d="M21 21l-5-5m2-5a7 7 0 11-14 0 7 7 0 0114 0z" />
          </svg>
          <input
            placeholder="Search name, email or phone…"
            value={searchQuery}
            onChange={(e) => setSearchQuery(e.target.value)}
            aria-label="Search customers"
            className="w-full border-none bg-transparent text-[13.5px] text-text outline-none placeholder:text-muted-2"
          />
        </div>
        {searchQuery && data && (
          <p className="mt-1.5 text-[13px] text-muted">
            <span className="mono">{data.total}</span> result{data.total !== 1 ? 's' : ''}
            {!data.has_exact_match && data.total === 0 && (
              <>
                {' — '}
                <button
                  onClick={() => setCreateOpen(true)}
                  className="rounded text-accent hover:text-accent-press focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent"
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
        <div className="mb-4 rounded-ctl border border-danger/30 bg-danger-soft px-4 py-3 text-[13px] text-danger" role="alert">
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
          <section className="overflow-hidden rounded-card border border-border bg-card shadow-card">
            <div className="overflow-x-auto">
              <table className="w-full border-collapse" role="grid">
                <caption className="sr-only">Customer list</caption>
                <thead>
                  <tr>
                    <th scope="col" className="mono border-b border-border px-5 py-[11px] text-left text-[10.5px] font-medium uppercase tracking-[0.08em] text-muted-2">Name</th>
                    <th scope="col" className="mono border-b border-border px-5 py-[11px] text-left text-[10.5px] font-medium uppercase tracking-[0.08em] text-muted-2">Company Name</th>
                    <th scope="col" className="mono border-b border-border px-5 py-[11px] text-left text-[10.5px] font-medium uppercase tracking-[0.08em] text-muted-2">Branch</th>
                    <th scope="col" className="mono border-b border-border px-5 py-[11px] text-left text-[10.5px] font-medium uppercase tracking-[0.08em] text-muted-2">Email</th>
                    <th scope="col" className="mono border-b border-border px-5 py-[11px] text-left text-[10.5px] font-medium uppercase tracking-[0.08em] text-muted-2">Work Phone</th>
                    <th scope="col" className="mono border-b border-border px-5 py-[11px] text-right text-[10.5px] font-medium uppercase tracking-[0.08em] text-muted-2">Receivables (BCY)</th>
                    <th scope="col" className="mono border-b border-border px-5 py-[11px] text-right text-[10.5px] font-medium uppercase tracking-[0.08em] text-muted-2">Unused Credits (BCY)</th>
                    <th scope="col" className="mono border-b border-border px-5 py-[11px] text-left text-[10.5px] font-medium uppercase tracking-[0.08em] text-muted-2">Last Portal Access</th>
                    {isAutomotive && (
                    <th scope="col" className="mono border-b border-border px-5 py-[11px] text-center text-[10.5px] font-medium uppercase tracking-[0.08em] text-muted-2">Reminders WOF/COF/Service</th>
                    )}
                    {consentColumnVisible && (
                    <th scope="col" className="mono border-b border-border px-5 py-[11px] text-center text-[10.5px] font-medium uppercase tracking-[0.08em] text-muted-2">Reminder Consent</th>
                    )}
                    <th scope="col" className="mono border-b border-border px-5 py-[11px] text-center text-[10.5px] font-medium uppercase tracking-[0.08em] text-muted-2">Actions</th>
                  </tr>
                </thead>
                <tbody>
                  {!data.customers || data.customers.length === 0 ? (
                    <tr>
                      <td colSpan={(isAutomotive ? 10 : 9) + (consentColumnVisible ? 1 : 0)} className="px-5 py-12 text-center text-[13px] text-muted">
                        {searchQuery ? 'No customers match your search.' : 'No customers yet. Create your first customer to get started.'}
                      </td>
                    </tr>
                  ) : (
                    data.customers.map((c) => (
                      <tr
                        key={c.id}
                        className="cursor-pointer border-b border-border transition-colors last:border-b-0 hover:bg-canvas"
                        onClick={() => { window.location.href = `/customers/${c.id}` }}
                      >
                        <td className="whitespace-nowrap px-5 py-3 text-[13.5px] font-medium text-accent">
                          {c.display_name || `${c.first_name} ${c.last_name}`}
                        </td>
                        <td className="whitespace-nowrap px-5 py-3 text-[13.5px] text-text">
                          {c.company_name || '—'}
                        </td>
                        <td className="whitespace-nowrap px-5 py-3 text-[13.5px] text-muted">
                          {c.branch_id ? ((branchList ?? []).find(b => b.id === c.branch_id)?.name ?? '—') : 'All'}
                        </td>
                        <td className="whitespace-nowrap px-5 py-3 text-[13.5px] text-text">
                          {c.email || '—'}
                        </td>
                        <td className="mono whitespace-nowrap px-5 py-3 text-[13.5px] text-text">
                          {c.work_phone || c.phone || c.mobile_phone || '—'}
                        </td>
                        <td className="mono whitespace-nowrap px-5 py-3 text-right text-[13.5px] text-text">
                          {formatNZD(c.receivables)}
                        </td>
                        <td className="mono whitespace-nowrap px-5 py-3 text-right text-[13.5px] text-text">
                          {formatNZD(c.unused_credits)}
                        </td>
                        <td className="mono whitespace-nowrap px-5 py-3 text-[13.5px] text-muted">
                          {c.last_portal_access_at
                            ? new Date(c.last_portal_access_at).toLocaleDateString()
                            : '—'}
                        </td>
                        {isAutomotive && (
                        <td className="whitespace-nowrap px-5 py-3 text-center">
                          <button
                            onClick={(e) => { e.stopPropagation(); handleToggleReminder(c) }}
                            disabled={togglingReminder === c.id}
                            className="relative inline-flex h-6 w-11 items-center rounded-full transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent focus-visible:ring-offset-2 disabled:opacity-50"
                            style={{ backgroundColor: c.reminders_enabled ? 'var(--ok)' : 'var(--danger)' }}
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
                        )}
                        {consentColumnVisible && (
                        <td className="whitespace-nowrap px-5 py-3 text-center text-[13px]">
                          {c.has_reminder_consent ? (
                            <span className="font-medium text-ok">Yes</span>
                          ) : (
                            <span className="text-muted-2">No</span>
                          )}
                        </td>
                        )}
                        <td className="whitespace-nowrap px-5 py-3 text-center">
                          <div className="flex items-center justify-center gap-1">
                            <button
                              onClick={(e) => { e.stopPropagation(); handleView(c) }}
                              className="rounded p-1.5 text-muted-2 transition-colors hover:bg-accent-soft hover:text-accent"
                              title="View details"
                              aria-label={`View ${c.first_name} ${c.last_name}`}
                            >
                              <svg className="h-4 w-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                                <path strokeLinecap="round" strokeLinejoin="round" d="M2.036 12.322a1.012 1.012 0 010-.639C3.423 7.51 7.36 4.5 12 4.5c4.638 0 8.573 3.007 9.963 7.178.07.207.07.431 0 .639C20.577 16.49 16.64 19.5 12 19.5c-4.638 0-8.573-3.007-9.963-7.178z" />
                                <path strokeLinecap="round" strokeLinejoin="round" d="M15 12a3 3 0 11-6 0 3 3 0 016 0z" />
                              </svg>
                            </button>
                            <button
                              onClick={(e) => { e.stopPropagation(); handleEditOpen(c) }}
                              className="rounded p-1.5 text-muted-2 transition-colors hover:bg-ok-soft hover:text-ok"
                              title="Edit customer"
                              aria-label={`Edit ${c.first_name} ${c.last_name}`}
                            >
                              <svg className="h-4 w-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
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
              <div className="flex items-center justify-between border-t border-border px-5 py-3.5">
                <p className="text-[12.5px] text-muted">
                  Showing <span className="mono text-text">{(page - 1) * pageSize + 1}–{Math.min(page * pageSize, data.total)}</span> of <span className="mono text-text">{data.total}</span>
                </p>
                <Pagination currentPage={page} totalPages={totalPages} onPageChange={setPage} />
              </div>
            )}
          </section>
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
            <p className="text-[13.5px] text-muted">
              Configure automatic reminders for this customer. Each reminder type can be enabled separately with its own timing and notification channel.
            </p>

            {/* Service Due */}
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
                        { value: 'sms', label: 'SMS' },
                        { value: 'both', label: 'Email & SMS' },
                      ]}
                      value={reminderConfig.service_due.channel}
                      onChange={(e) => updateReminder('service_due', { channel: e.target.value as 'email' | 'sms' | 'both' })}
                    />
                  </div>
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

            {/* WOF Expiry — show if customer has WOF vehicles (inspection_type 'wof' or null = legacy WOF default) */}
            {isAutomotive && (reminderConfig?.vehicles ?? []).some(v => !v?.inspection_type || v.inspection_type === 'wof') && (
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
                        { value: 'sms', label: 'SMS' },
                        { value: 'both', label: 'Email & SMS' },
                      ]}
                      value={reminderConfig.wof_expiry.channel}
                      onChange={(e) => updateReminder('wof_expiry', { channel: e.target.value as 'email' | 'sms' | 'both' })}
                    />
                  </div>
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

            {/* COF Expiry — only if customer has a COF-type vehicle */}
            {isAutomotive && (reminderConfig?.vehicles ?? []).some(v => v?.inspection_type === 'cof') && (
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
                        { value: 'sms', label: 'SMS' },
                        { value: 'both', label: 'Email & SMS' },
                      ]}
                      value={reminderConfig?.cof_expiry?.channel ?? 'email'}
                      onChange={(e) => updateReminder('cof_expiry', { channel: e.target.value as 'email' | 'sms' | 'both' })}
                    />
                  </div>
                  {(reminderConfig?.vehicles ?? []).filter(v => v?.inspection_type === 'cof').length > 0 ? (
                    <div className="mt-2 space-y-2">
                      <p className="mono text-[11px] font-medium uppercase tracking-wider text-muted-2">Vehicle COF Expiry Dates</p>
                      {(reminderConfig?.vehicles ?? []).filter(v => v?.inspection_type === 'cof').map((v) => {
                        const dateVal = getVehicleDate(v, 'cof_expiry')
                        return (
                          <div key={v.global_vehicle_id} className="flex items-center gap-3 rounded-ctl bg-canvas px-3 py-2">
                            <div className="min-w-0 flex-1">
                              <span className="mono text-[13px] font-medium text-text">{v?.rego || '—'}</span>
                              <span className="ml-2 text-[13px] text-muted">{[v?.year, v?.make, v?.model].filter(Boolean).join(' ')}</span>
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
                                aria-label={`COF expiry date for ${v?.rego || 'vehicle'}`}
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

      {/* Consent Confirmation Modal (F3/F4 — consent gate) */}
      <ConsentConfirmationModal
        open={consentModalOpen}
        customerId={reminderCustomerId ?? ''}
        missing={consentMissing}
        config={(() => {
          const { vehicles: _v, ...configOnly } = reminderConfig
          return configOnly as any
        })()}
        onConfirmed={handleConsentConfirmed}
        onCancel={() => { setConsentModalOpen(false); setConsentMissing([]) }}
      />
    </div>
  )
}
