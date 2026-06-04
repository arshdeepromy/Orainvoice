/**
 * BookingForm — Task 28 port of frontend/src/pages/bookings/BookingForm.tsx.
 *
 * Modal form to create/edit a booking. ALL logic copied VERBATIM: edit-load
 * (GET /bookings/:id + vehicle lookup), customer typeahead (sequential-char
 * match) + inline CustomerCreateModal, vehicle live search (module-gated,
 * automotive), service-catalogue typeahead + inline new-item create, date/time/
 * duration/status/notes, parts + fluid inventory pickers (automotive), email/SMS
 * confirmation toggles, reminder radio options, and the create/update submit
 * (with past-date guard on create). Trade-family + module gating preserved.
 * Presentation remapped onto the design tokens (FR-2b); `secondary`→`ghost`.
 *
 * Requirements: 64.2, 64.3
 */

import { useState, useEffect } from 'react'
import apiClient from '@/api/client'
import { Button, Input, Select, Modal, Spinner } from '@/components/ui'
import { ModuleGate } from '@/components/common/ModuleGate'
import { useModules } from '@/contexts/ModuleContext'
import { useTenant } from '@/contexts/TenantContext'
import { VehicleLiveSearch } from '@/components/vehicles/VehicleLiveSearch'
import { CustomerCreateModal } from '@/components/customers/CustomerCreateModal'
import type { BookingSearchResult } from './BookingCalendar'
import {
  shouldTriggerCustomerSearch,
  shouldShowAddNewOption,
} from '@/utils/bookingFormHelpers'

/* ------------------------------------------------------------------ */
/*  Types                                                              */
/* ------------------------------------------------------------------ */

interface BookingDetail {
  id: string
  org_id: string
  customer_id: string | null
  customer_name: string | null
  vehicle_rego: string | null
  branch_id: string | null
  service_type: string | null
  service_catalogue_id: string | null
  service_price: string | null
  scheduled_at: string
  duration_minutes: number
  notes: string | null
  status: string
  reminder_sent: boolean
  assigned_to: string | null
  created_by: string
  created_at: string
  updated_at: string
  parts?: unknown[]
  fluid_usage?: unknown[]
}

interface ServiceCatalogueOption {
  id: string
  name: string
  default_price: string
  category: string
  is_active: boolean
}

interface LinkedVehicleOption {
  id: string
  rego: string
  make: string | null
  model: string | null
  year: number | null
  colour: string | null
}

interface CustomerOption {
  id: string
  first_name: string
  last_name: string
  email: string | null
  phone: string | null
  linked_vehicles?: LinkedVehicleOption[]
}

interface BookingFormProps {
  open: boolean
  onClose: () => void
  onSaved: () => void
  editBooking?: BookingSearchResult | null
  initialDate?: string
}

/* ------------------------------------------------------------------ */
/*  Helpers                                                            */
/* ------------------------------------------------------------------ */

const STATUS_OPTIONS = [
  { value: 'scheduled', label: 'Scheduled' },
  { value: 'confirmed', label: 'Confirmed' },
  { value: 'completed', label: 'Completed' },
  { value: 'cancelled', label: 'Cancelled' },
  { value: 'no_show', label: 'No Show' },
]

const DURATION_OPTIONS = [
  { value: '15', label: '15 min' },
  { value: '30', label: '30 min' },
  { value: '45', label: '45 min' },
  { value: '60', label: '1 hour' },
  { value: '90', label: '1.5 hours' },
  { value: '120', label: '2 hours' },
  { value: '180', label: '3 hours' },
  { value: '240', label: '4 hours' },
  { value: '480', label: 'Full day (8h)' },
]

function toLocalDatetimeStr(dateStr: string): string {
  const d = new Date(dateStr)
  const pad = (n: number) => n.toString().padStart(2, '0')
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}T${pad(d.getHours())}:${pad(d.getMinutes())}`
}

function nowLocalStr(): string {
  return toLocalDatetimeStr(new Date().toISOString())
}

const TEXTAREA_CLS = 'rounded-ctl border border-border bg-card px-[13px] py-2 text-[13.5px] text-text shadow-sm placeholder:text-muted-2 focus:border-accent focus:outline-none focus:shadow-[0_0_0_3px_var(--accent-soft)]'
const STOCK_SEARCH_CLS = 'w-full rounded-ctl border border-border bg-card px-3 py-2 text-[13px] text-text focus:border-accent focus:outline-none focus:shadow-[0_0_0_3px_var(--accent-soft)]'

/* ------------------------------------------------------------------ */
/*  Component                                                          */
/* ------------------------------------------------------------------ */

export default function BookingForm({ open, onClose, onSaved, editBooking, initialDate }: BookingFormProps) {
  const isEdit = !!editBooking
  const { isEnabled } = useModules()
  const vehiclesEnabled = isEnabled('vehicles')
  const { tradeFamily } = useTenant()
  const isAutomotive = (tradeFamily ?? 'automotive-transport') === 'automotive-transport'

  /* Form state */
  const [customerId, setCustomerId] = useState('')
  const [customerSearch, setCustomerSearch] = useState('')
  const [customerResults, setCustomerResults] = useState<CustomerOption[]>([])
  const [searchingCustomers, setSearchingCustomers] = useState(false)
  const [showCustomerDropdown, setShowCustomerDropdown] = useState(false)
  const [showCustomerCreateModal, setShowCustomerCreateModal] = useState(false)

  const [vehicleRego, setVehicleRego] = useState('')
  const [selectedVehicle, setSelectedVehicle] = useState<{
    id: string; rego: string; make: string; model: string; year: number | null;
    colour: string; body_type: string; fuel_type: string; engine_size: string;
    wof_expiry: string | null; cof_expiry: string | null; inspection_type: string | null;
    registration_expiry: string | null; odometer?: number | null;
  } | null>(null)
  const [serviceType, setServiceType] = useState('')
  const [serviceSearch, setServiceSearch] = useState('')
  const [serviceResults, setServiceResults] = useState<ServiceCatalogueOption[]>([])
  const [searchingServices, setSearchingServices] = useState(false)
  const [showServiceDropdown, setShowServiceDropdown] = useState(false)
  const [serviceCatalogueId, setServiceCatalogueId] = useState<string | null>(null)
  const [servicePrice, setServicePrice] = useState<string | null>(null)
  const [showInlineServiceForm, setShowInlineServiceForm] = useState(false)
  const [inlineServiceName, setInlineServiceName] = useState('')
  const [inlineServicePrice, setInlineServicePrice] = useState('')
  const [inlineServiceCategory, setInlineServiceCategory] = useState('')
  const [inlineServiceDescription, setInlineServiceDescription] = useState('')
  const [inlineServiceGstExempt, setInlineServiceGstExempt] = useState(false)
  const [inlineServiceError, setInlineServiceError] = useState('')
  const [savingInlineService, setSavingInlineService] = useState(false)

  const [scheduledAt, setScheduledAt] = useState(nowLocalStr())
  const [durationMinutes, setDurationMinutes] = useState('60')
  const [notes, setNotes] = useState('')
  const [status, setStatus] = useState('scheduled')
  const [sendEmailConfirmation, setSendEmailConfirmation] = useState(false)
  const [sendSmsConfirmation, setSendSmsConfirmation] = useState(false)
  const [smsIncluded, setSmsIncluded] = useState(false)
  const [reminderOption, setReminderOption] = useState<'none' | '24' | '6' | 'custom'>('none')
  const [customReminderHours, setCustomReminderHours] = useState('')

  // Inventory parts and fluid usage for reservation
  interface BookingPart { key: string; stock_item_id: string; catalogue_item_id: string; item_name: string; quantity: number; sell_price: number | null; gst_mode: string | null }
  interface BookingFluid { key: string; stock_item_id: string; catalogue_item_id: string; item_name: string; litres: number }
  const [bookingParts, setBookingParts] = useState<BookingPart[]>([])
  const [bookingFluids, setBookingFluids] = useState<BookingFluid[]>([])
  const [partsPickerOpen, setPartsPickerOpen] = useState(false)
  const [fluidPickerOpen, setFluidPickerOpen] = useState(false)
  const [stockItems, setStockItems] = useState<any[]>([])
  const [stockLoading, setStockLoading] = useState(false)
  const [stockSearch, setStockSearch] = useState('')

  const openPartsPicker = async () => {
    setPartsPickerOpen(true); setStockSearch(''); setStockLoading(true)
    try {
      const res = await apiClient.get('/inventory/stock-items', { params: { limit: 500 } })
      setStockItems(((res.data as any).stock_items || []).filter((si: any) => si.catalogue_type !== 'fluid' && si.available_quantity > 0))
    } catch { setStockItems([]) } finally { setStockLoading(false) }
  }
  const openFluidPicker = async () => {
    setFluidPickerOpen(true); setStockSearch(''); setStockLoading(true)
    try {
      const res = await apiClient.get('/inventory/stock-items', { params: { limit: 500 } })
      setStockItems(((res.data as any).stock_items || []).filter((si: any) => si.catalogue_type === 'fluid' && si.available_quantity > 0))
    } catch { setStockItems([]) } finally { setStockLoading(false) }
  }
  const addBookingPart = (si: any) => {
    setBookingParts(prev => [...prev, { key: crypto.randomUUID(), stock_item_id: si.id, catalogue_item_id: si.catalogue_item_id, item_name: si.item_name + (si.subtitle ? ` (${si.subtitle})` : ''), quantity: 1, sell_price: si.sell_price, gst_mode: si.gst_mode }])
    setPartsPickerOpen(false)
  }
  const addBookingFluid = (si: any) => {
    setBookingFluids(prev => [...prev, { key: crypto.randomUUID(), stock_item_id: si.id, catalogue_item_id: si.catalogue_item_id, item_name: si.item_name, litres: 1 }])
    setFluidPickerOpen(false)
  }

  const [saving, setSaving] = useState(false)
  const [loadingDetail, setLoadingDetail] = useState(false)
  const [error, setError] = useState('')

  /* Load booking detail when editing */
  useEffect(() => {
    if (!open) return
    if (editBooking) {
      setLoadingDetail(true)
      apiClient.get<BookingDetail>(`/bookings/${editBooking.id}`)
        .then((res) => {
          const b = res.data
          setCustomerId(b.customer_id ?? '')
          setCustomerSearch(b.customer_name ?? '')
          setVehicleRego(b.vehicle_rego ?? '')
          // Look up full vehicle details if rego is present
          if (b.vehicle_rego) {
            apiClient.get<{ results: Array<{ id: string; rego: string; make: string | null; model: string | null; year: number | null; colour: string | null; odometer?: number | null }> }>(
              '/vehicles/search', { params: { q: b.vehicle_rego } }
            ).then((vRes) => {
              const match = (vRes.data.results || []).find(v => v.rego === b.vehicle_rego)
              if (match) {
                setSelectedVehicle({
                  id: match.id, rego: match.rego, make: match.make ?? '', model: match.model ?? '',
                  year: match.year, colour: match.colour ?? '', body_type: '', fuel_type: '',
                  engine_size: '', wof_expiry: null, cof_expiry: null, inspection_type: null, registration_expiry: null, odometer: match.odometer ?? null,
                })
              } else {
                setSelectedVehicle({
                  id: '', rego: b.vehicle_rego ?? '', make: '', model: '', year: null, colour: '',
                  body_type: '', fuel_type: '', engine_size: '', wof_expiry: null, cof_expiry: null, inspection_type: null, registration_expiry: null,
                })
              }
            }).catch(() => {
              setSelectedVehicle({
                id: '', rego: b.vehicle_rego ?? '', make: '', model: '', year: null, colour: '',
                body_type: '', fuel_type: '', engine_size: '', wof_expiry: null, cof_expiry: null, inspection_type: null, registration_expiry: null,
              })
            })
          } else {
            setSelectedVehicle(null)
          }
          setServiceType(b.service_type ?? '')
          setServiceSearch(b.service_type ?? '')
          setServiceCatalogueId(b.service_catalogue_id ?? null)
          setServicePrice(b.service_price ?? null)
          setScheduledAt(toLocalDatetimeStr(b.scheduled_at))
          setDurationMinutes(String(b.duration_minutes))
          setNotes(b.notes ?? '')
          setStatus(b.status)
          // Load parts and fluid usage from booking_data_json
          setBookingParts((b.parts || []).map((p: any) => ({ key: crypto.randomUUID(), stock_item_id: p.stock_item_id, catalogue_item_id: p.catalogue_item_id, item_name: p.item_name || '', quantity: p.quantity || 1, sell_price: p.sell_price ?? null, gst_mode: p.gst_mode ?? null })))
          setBookingFluids((b.fluid_usage || []).map((f: any) => ({ key: crypto.randomUUID(), stock_item_id: f.stock_item_id, catalogue_item_id: f.catalogue_item_id, item_name: f.item_name || '', litres: f.litres || 1 })))
        })
        .catch(() => setError('Failed to load booking details.'))
        .finally(() => setLoadingDetail(false))
    } else {
      // Reset form for new booking
      setCustomerId('')
      setCustomerSearch('')
      setVehicleRego('')
      setSelectedVehicle(null)
      setServiceType('')
      setServiceSearch('')
      setServiceResults([])
      setSearchingServices(false)
      setShowServiceDropdown(false)
      setServiceCatalogueId(null)
      setServicePrice(null)
      setShowInlineServiceForm(false)
      setInlineServiceName('')
      setInlineServicePrice('')
      setInlineServiceCategory('')
      setInlineServiceDescription('')
      setInlineServiceGstExempt(false)
      setInlineServiceError('')
      setScheduledAt(initialDate || nowLocalStr())
      setDurationMinutes('60')
      setNotes('')
      setStatus('scheduled')
      setSendEmailConfirmation(false)
      setSendSmsConfirmation(false)
      setReminderOption('none')
      setCustomReminderHours('')
      setShowCustomerCreateModal(false)
      setError('')
      setBookingParts([])
      setBookingFluids([])
    }
  }, [open, editBooking, initialDate])

  /* Fetch plan features to determine SMS availability */
  useEffect(() => {
    if (!open) return
    apiClient.get<{ sms_included: boolean }>('/org/plan-features')
      .then((res) => setSmsIncluded(res.data.sms_included ?? false))
      .catch(() => setSmsIncluded(false))
  }, [open])

  /* Customer search */
  useEffect(() => {
    if (!shouldTriggerCustomerSearch(customerSearch)) {
      setCustomerResults([])
      setShowCustomerDropdown(false)
      return
    }
    // Don't re-search if a customer is already selected (user just picked one)
    if (customerId) return
    const timer = setTimeout(async () => {
      setSearchingCustomers(true)
      try {
        const res = await apiClient.get<{ items?: CustomerOption[]; results?: CustomerOption[]; customers?: CustomerOption[] }>('/customers', {
          params: { q: customerSearch, limit: 8, ...(vehiclesEnabled ? { include_vehicles: true } : {}) },
        })
        const items = res.data.items ?? res.data.results ?? res.data.customers ?? []
        // Client-side sequential character matching for precision (ISSUE-060)
        const term = customerSearch.trim().toLowerCase()
        const matchesSeq = (haystack: string, needle: string): boolean => {
          let ni = 0
          const h = haystack.toLowerCase()
          for (let i = 0; i < h.length && ni < needle.length; i++) {
            if (h[i] === needle[ni]) ni++
          }
          return ni === needle.length
        }
        const filtered = term.length > 0 ? items.filter((c) => {
          const regoMatch = (c.linked_vehicles || []).some((v) => matchesSeq(v.rego || '', term))
          return (
            matchesSeq(c.first_name || '', term) ||
            matchesSeq(c.last_name || '', term) ||
            matchesSeq(`${c.first_name} ${c.last_name}`, term) ||
            matchesSeq(c.phone || '', term) ||
            matchesSeq(c.email || '', term) ||
            regoMatch
          )
        }) : items
        setCustomerResults(filtered)
        setShowCustomerDropdown(true)
      } catch {
        setCustomerResults([])
      } finally {
        setSearchingCustomers(false)
      }
    }, 300)
    return () => clearTimeout(timer)
  }, [customerSearch, customerId, vehiclesEnabled])

  /* Service catalogue search */
  useEffect(() => {
    if (serviceSearch.trim().length < 2) {
      setServiceResults([])
      setShowServiceDropdown(false)
      return
    }
    // Don't re-search if a service is already selected (user just picked one)
    if (serviceCatalogueId) return
    const timer = setTimeout(async () => {
      setSearchingServices(true)
      try {
        const res = await apiClient.get<{ items?: ServiceCatalogueOption[] }>('/catalogue/items', {
          params: { active_only: true, limit: 10 },
        })
        const items = res.data.items ?? []
        // Client-side filter by search query
        const query = serviceSearch.trim().toLowerCase()
        const filtered = items.filter((s) => s.name.toLowerCase().includes(query))
        setServiceResults(filtered)
        setShowServiceDropdown(true)
      } catch {
        setServiceResults([])
      } finally {
        setSearchingServices(false)
      }
    }, 300)
    return () => clearTimeout(timer)
  }, [serviceSearch, serviceCatalogueId])

  /* Submit inline service form */
  const handleInlineServiceSubmit = async (e: React.FormEvent) => {
    e.preventDefault()
    if (!inlineServiceName.trim()) {
      setInlineServiceError('Item name is required.')
      return
    }
    if (!inlineServicePrice.trim() || isNaN(parseFloat(inlineServicePrice))) {
      setInlineServiceError('A valid default price is required.')
      return
    }
    setSavingInlineService(true)
    setInlineServiceError('')
    try {
      const res = await apiClient.post<{ item: ServiceCatalogueOption }>('/catalogue/items', {
        name: inlineServiceName.trim(),
        default_price: inlineServicePrice.trim(),
        category: inlineServiceCategory || null,
        description: inlineServiceDescription.trim() || null,
        is_gst_exempt: inlineServiceGstExempt,
      })
      const created = res.data.item
      setServiceCatalogueId(created.id)
      setServiceType(created.name)
      setServicePrice(created.default_price)
      setServiceSearch(created.name)
      setShowInlineServiceForm(false)
    } catch (err: unknown) {
      const detail = (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail
      setInlineServiceError(detail ?? 'Failed to create item.')
    } finally {
      setSavingInlineService(false)
    }
  }

  /* Submit */
  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault()
    if (!customerId) {
      setError('Please select a customer.')
      return
    }

    // Prevent backdated bookings (new only)
    if (!isEdit && new Date(scheduledAt) < new Date()) {
      setError('Cannot create a booking in the past. Please select a future date and time.')
      return
    }

    setSaving(true)
    setError('')

    try {
      if (isEdit) {
        await apiClient.put(`/bookings/${editBooking!.id}`, {
          customer_id: customerId,
          ...(isAutomotive ? { vehicle_rego: vehicleRego || null } : {}),
          service_type: serviceType || null,
          service_catalogue_id: serviceCatalogueId || null,
          service_price: servicePrice ? parseFloat(servicePrice) : null,
          scheduled_at: new Date(scheduledAt).toISOString(),
          duration_minutes: parseInt(durationMinutes, 10),
          notes: notes || null,
          status,
        })
      } else {
        await apiClient.post('/bookings', {
          customer_id: customerId,
          ...(isAutomotive ? { vehicle_rego: vehicleRego || null } : {}),
          service_type: serviceType || null,
          service_catalogue_id: serviceCatalogueId || null,
          service_price: servicePrice ? parseFloat(servicePrice) : null,
          scheduled_at: new Date(scheduledAt).toISOString(),
          duration_minutes: parseInt(durationMinutes, 10),
          notes: notes || null,
          send_email_confirmation: sendEmailConfirmation,
          send_sms_confirmation: sendSmsConfirmation,
          reminder_offset_hours: reminderOption === 'none' ? null : reminderOption === 'custom' ? (customReminderHours && !isNaN(parseFloat(customReminderHours)) ? parseFloat(customReminderHours) : null) : parseFloat(reminderOption),
          ...(isAutomotive ? {
            parts: bookingParts.filter(p => p.quantity > 0).map(p => ({ stock_item_id: p.stock_item_id, catalogue_item_id: p.catalogue_item_id, item_name: p.item_name, quantity: p.quantity, sell_price: p.sell_price, gst_mode: p.gst_mode })),
            fluid_usage: bookingFluids.filter(f => f.litres > 0).map(f => ({ stock_item_id: f.stock_item_id, catalogue_item_id: f.catalogue_item_id, item_name: f.item_name, litres: f.litres })),
          } : {}),
        })
      }
      onSaved()
      onClose()
    } catch (err: unknown) {
      const detail = (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail
      setError(detail ?? 'Failed to save booking.')
    } finally {
      setSaving(false)
    }
  }

  return (
    <Modal open={open} onClose={onClose} title={isEdit ? 'Edit Booking' : 'New Booking'} className="max-w-xl">
      {loadingDetail ? (
        <div className="py-8"><Spinner label="Loading booking" /></div>
      ) : (
        <form onSubmit={handleSubmit} className="space-y-4">
          {error && (
            <div className="rounded-ctl border border-danger/30 bg-danger-soft px-3 py-2 text-[13px] text-danger" role="alert">{error}</div>
          )}

          {/* Customer search */}
          <div className="relative">
            <Input
              label="Customer *"
              placeholder="Search by name, phone, or email…"
              value={customerSearch}
              onChange={(e) => {
                const val = e.target.value
                setCustomerSearch(val)
                // Clear selection when user edits the field so search can re-trigger
                if (customerId) setCustomerId('')
              }}
              onFocus={() => { if (customerResults.length > 0 || customerSearch.trim().length >= 2) setShowCustomerDropdown(true) }}
              aria-label="Search customer"
              aria-expanded={showCustomerDropdown}
              aria-autocomplete="list"
              role="combobox"
            />
            {searchingCustomers && (
              <div className="absolute right-3 top-8">
                <Spinner size="sm" label="" />
              </div>
            )}
            {showCustomerDropdown && (
              <ul
                className="absolute z-10 mt-1 max-h-48 w-full overflow-auto rounded-ctl border border-border bg-card shadow-pop"
                role="listbox"
              >
                {customerResults && customerResults.length > 0 && customerResults.map((c) => (
                  <li
                    key={c.id}
                    role="option"
                    aria-selected={customerId === c.id}
                    className="cursor-pointer px-3 py-2 text-[13px] hover:bg-accent-soft focus:bg-accent-soft"
                    onClick={() => {
                      setCustomerId(c.id)
                      setCustomerSearch(`${c.first_name} ${c.last_name}`)
                      setShowCustomerDropdown(false)
                      // Auto-fill first linked vehicle
                      if (vehiclesEnabled && c.linked_vehicles && c.linked_vehicles.length > 0 && !selectedVehicle) {
                        const v = c.linked_vehicles[0]
                        setSelectedVehicle({
                          id: v.id, rego: v.rego, make: v.make ?? '', model: v.model ?? '',
                          year: v.year, colour: v.colour ?? '', body_type: '', fuel_type: '',
                          engine_size: '', wof_expiry: null, cof_expiry: null, inspection_type: null, registration_expiry: null,
                        })
                        setVehicleRego(v.rego)
                      }
                    }}
                    onKeyDown={(e) => {
                      if (e.key === 'Enter') {
                        setCustomerId(c.id)
                        setCustomerSearch(`${c.first_name} ${c.last_name}`)
                        setShowCustomerDropdown(false)
                        if (vehiclesEnabled && c.linked_vehicles && c.linked_vehicles.length > 0 && !selectedVehicle) {
                          const v = c.linked_vehicles[0]
                          setSelectedVehicle({
                            id: v.id, rego: v.rego, make: v.make ?? '', model: v.model ?? '',
                            year: v.year, colour: v.colour ?? '', body_type: '', fuel_type: '',
                            engine_size: '', wof_expiry: null, cof_expiry: null, inspection_type: null, registration_expiry: null,
                          })
                          setVehicleRego(v.rego)
                        }
                      }
                    }}
                    tabIndex={0}
                  >
                    <div className="flex items-center justify-between">
                      <div>
                        <span className="font-medium text-text">{c.first_name} {c.last_name}</span>
                        {c.phone && <span className="ml-2 text-muted">{c.phone}</span>}
                        {c.email && <span className="ml-2 text-muted-2">{c.email}</span>}
                      </div>
                      {c.linked_vehicles && c.linked_vehicles.length > 0 && (
                        <span className="ml-2 shrink-0 rounded bg-accent-soft px-2 py-0.5 text-[12px] text-accent">
                          {c.linked_vehicles.length} vehicle{c.linked_vehicles.length > 1 ? 's' : ''}
                        </span>
                      )}
                    </div>
                    {c.linked_vehicles && c.linked_vehicles.length > 0 && (
                      <div className="mono mt-0.5 text-[12px] text-muted">
                        {c.linked_vehicles.slice(0, 2).map(v => v.rego).join(', ')}
                        {c.linked_vehicles.length > 2 && ` +${c.linked_vehicles.length - 2} more`}
                      </div>
                    )}
                  </li>
                ))}
                {shouldShowAddNewOption(customerSearch, customerResults.length) && (
                  <li
                    role="option"
                    aria-selected={false}
                    className="cursor-pointer px-3 py-2 text-[13px] font-medium text-accent hover:bg-accent-soft focus:bg-accent-soft"
                    onClick={() => {
                      setShowCustomerCreateModal(true)
                      setShowCustomerDropdown(false)
                    }}
                    onKeyDown={(e) => {
                      if (e.key === 'Enter') {
                        setShowCustomerCreateModal(true)
                        setShowCustomerDropdown(false)
                      }
                    }}
                    tabIndex={0}
                  >
                    + Add new customer
                  </li>
                )}
              </ul>
            )}
          </div>

          {/* Customer create modal (full form) */}
          <CustomerCreateModal
            open={showCustomerCreateModal}
            onClose={() => setShowCustomerCreateModal(false)}
            onCustomerCreated={(created) => {
              setCustomerId(created.id)
              setCustomerSearch(`${created.first_name} ${created.last_name}`)
              setShowCustomerCreateModal(false)
            }}
          />

          {/* Vehicle rego (module-gated) */}
          {isAutomotive && (
            <ModuleGate module="vehicles">
              <VehicleLiveSearch
                vehicle={selectedVehicle}
                onVehicleFound={(v) => {
                  setSelectedVehicle(v)
                  setVehicleRego(v?.rego ?? '')
                }}
                onCustomerAutoSelect={(c) => {
                  if (!customerId) {
                    setCustomerId(c.id)
                    setCustomerSearch(`${c.first_name} ${c.last_name}`)
                  }
                }}
              />
            </ModuleGate>
          )}

          {/* Service type (catalogue typeahead) */}
          <div className="relative">
            <Input
              label="Item"
              placeholder="Search items…"
              value={serviceSearch}
              onChange={(e) => {
                const val = e.target.value
                setServiceSearch(val)
                // Clear selection when user edits the field so search can re-trigger
                if (serviceCatalogueId) {
                  setServiceCatalogueId(null)
                  setServiceType('')
                  setServicePrice(null)
                }
              }}
              onFocus={() => { if (serviceResults.length > 0 || serviceSearch.trim().length >= 2) setShowServiceDropdown(true) }}
              aria-label="Search item"
              aria-expanded={showServiceDropdown}
              aria-autocomplete="list"
              role="combobox"
            />
            {serviceCatalogueId && servicePrice && (
              <span className="mono absolute right-3 top-8 text-[13px] font-medium text-ok" data-testid="selected-service-price">
                ${parseFloat(servicePrice).toFixed(2)}
              </span>
            )}
            {searchingServices && !serviceCatalogueId && (
              <div className="absolute right-3 top-8">
                <Spinner size="sm" label="" />
              </div>
            )}
            {showServiceDropdown && (
              <ul
                className="absolute z-10 mt-1 max-h-48 w-full overflow-auto rounded-ctl border border-border bg-card shadow-pop"
                role="listbox"
              >
                {serviceResults.length > 0 && serviceResults.map((s) => (
                  <li
                    key={s.id}
                    role="option"
                    aria-selected={serviceCatalogueId === s.id}
                    className="cursor-pointer px-3 py-2 text-[13px] hover:bg-accent-soft focus:bg-accent-soft"
                    onClick={() => {
                      setServiceCatalogueId(s.id)
                      setServiceType(s.name)
                      setServicePrice(s.default_price)
                      setServiceSearch(s.name)
                      setShowServiceDropdown(false)
                      setShowInlineServiceForm(false)
                    }}
                    onKeyDown={(e) => {
                      if (e.key === 'Enter') {
                        setServiceCatalogueId(s.id)
                        setServiceType(s.name)
                        setServicePrice(s.default_price)
                        setServiceSearch(s.name)
                        setShowServiceDropdown(false)
                        setShowInlineServiceForm(false)
                      }
                    }}
                    tabIndex={0}
                  >
                    <span className="font-medium text-text">{s.name}</span>
                    <span className="mono ml-2 text-muted">— ${parseFloat(s.default_price).toFixed(2)}</span>
                  </li>
                ))}
                {!searchingServices && serviceSearch.trim().length >= 2 && (
                  <li
                    role="option"
                    aria-selected={false}
                    className="cursor-pointer border-t border-border px-3 py-2 text-[13px] font-medium text-accent hover:bg-accent-soft focus:bg-accent-soft"
                    onClick={() => {
                      setShowInlineServiceForm(true)
                      setInlineServiceName(serviceSearch.trim())
                      setShowServiceDropdown(false)
                    }}
                    onKeyDown={(e) => {
                      if (e.key === 'Enter') {
                        setShowInlineServiceForm(true)
                        setInlineServiceName(serviceSearch.trim())
                        setShowServiceDropdown(false)
                      }
                    }}
                    tabIndex={0}
                  >
                    + Add new item
                  </li>
                )}
              </ul>
            )}
          </div>

          {/* Inline service form */}
          {showInlineServiceForm && (
            <div className="space-y-3 rounded-card border border-border bg-canvas p-4" data-testid="inline-service-form">
              <div className="flex items-center justify-between">
                <h4 className="text-[13px] font-semibold text-text">New Item</h4>
                <button type="button" onClick={() => setShowInlineServiceForm(false)} className="text-lg leading-none text-muted-2 hover:text-text">&times;</button>
              </div>
              <hr className="border-border" />
              <Input
                label="Item name *"
                value={inlineServiceName}
                onChange={(e) => setInlineServiceName(e.target.value)}
                aria-label="Item name"
              />
              <div className="flex flex-col gap-[7px]">
                <label htmlFor="inline-service-desc" className="text-[12.5px] font-medium text-text">Description</label>
                <textarea
                  id="inline-service-desc"
                  value={inlineServiceDescription}
                  onChange={(e) => setInlineServiceDescription(e.target.value)}
                  rows={3}
                  placeholder="Optional item description"
                  className={`w-full ${TEXTAREA_CLS}`}
                />
              </div>
              <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
                <Input
                  label="Default price (ex-GST) *"
                  type="number"
                  placeholder="e.g. 85.00"
                  value={inlineServicePrice}
                  onChange={(e) => setInlineServicePrice(e.target.value)}
                  aria-label="Item default price"
                />
                <Input
                  label="Category"
                  placeholder="e.g. Plumbing, Electrical"
                  value={inlineServiceCategory}
                  onChange={(e) => setInlineServiceCategory(e.target.value)}
                  aria-label="Item category"
                />
              </div>
              <label className="flex cursor-pointer items-center gap-2 text-[13px] text-text">
                <input type="checkbox" checked={inlineServiceGstExempt} onChange={(e) => setInlineServiceGstExempt(e.target.checked)} className="rounded border-border" />
                GST exempt
              </label>
              {inlineServiceError && (
                <div className="rounded-ctl border border-danger/30 bg-danger-soft px-3 py-2 text-[13px] text-danger" role="alert">
                  {inlineServiceError}
                </div>
              )}
              <div className="flex justify-end gap-2">
                <Button
                  type="button"
                  variant="ghost"
                  disabled={savingInlineService}
                  onClick={() => setShowInlineServiceForm(false)}
                >
                  Cancel
                </Button>
                <Button
                  type="button"
                  disabled={savingInlineService}
                  onClick={handleInlineServiceSubmit}
                >
                  {savingInlineService ? 'Saving…' : 'Create Item'}
                </Button>
              </div>
            </div>
          )}

          {/* Date/time and duration */}
          <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
            <Input
              label="Date & Time *"
              type="datetime-local"
              value={scheduledAt}
              onChange={(e) => setScheduledAt(e.target.value)}
              required
              {...(!isEdit ? { min: new Date().toISOString().slice(0, 16) } : {})}
            />
            <Select
              label="Duration"
              options={DURATION_OPTIONS}
              value={durationMinutes}
              onChange={(e) => setDurationMinutes(e.target.value)}
            />
          </div>

          {/* Status (edit only) */}
          {isEdit && (
            <Select
              label="Status"
              options={STATUS_OPTIONS}
              value={status}
              onChange={(e) => setStatus(e.target.value)}
            />
          )}

          {/* Notes */}
          <div className="flex flex-col gap-[7px]">
            <label htmlFor="booking-notes" className="text-[12.5px] font-medium text-text">Notes</label>
            <textarea
              id="booking-notes"
              className={TEXTAREA_CLS}
              rows={3}
              placeholder="Additional notes…"
              value={notes}
              onChange={(e) => setNotes(e.target.value)}
            />
          </div>

          {/* Parts from Inventory (optional — automotive only) */}
          {isAutomotive && (
          <div className="space-y-2 rounded-card border border-accent/30 bg-accent-soft/40 p-3">
            <div className="flex items-center justify-between">
              <span className="text-[13px] font-medium text-accent">Parts (optional)</span>
              <button type="button" onClick={openPartsPicker} className="text-[12px] font-medium text-accent hover:underline">+ Add Part</button>
            </div>
            {bookingParts.map(p => (
              <div key={p.key} className="flex items-center gap-2 rounded-ctl border border-border bg-card px-2 py-1.5">
                <span className="flex-1 truncate text-[13px] text-text">{p.item_name}</span>
                <input type="number" min="1" step="1" value={p.quantity} onChange={e => setBookingParts(prev => prev.map(x => x.key === p.key ? { ...x, quantity: Math.max(1, parseInt(e.target.value) || 1) } : x))} className="w-16 rounded-ctl border border-border px-1.5 py-1 text-right text-[13px]" />
                {p.sell_price != null && <span className="mono text-[12px] text-muted">${p.sell_price.toFixed(2)}</span>}
                <button type="button" onClick={() => setBookingParts(prev => prev.filter(x => x.key !== p.key))} className="text-muted-2 hover:text-danger">✕</button>
              </div>
            ))}
            {bookingParts.length === 0 && <p className="text-[12px] text-accent">No parts added. Click "+ Add Part" to reserve inventory.</p>}
          </div>
          )}

          {/* Fluid / Oil Usage (optional, shown when vehicle is selected) */}
          {isAutomotive && vehiclesEnabled && selectedVehicle && (
            <div className="space-y-2 rounded-card border border-warn/30 bg-warn-soft/40 p-3">
              <div className="flex items-center justify-between">
                <span className="text-[13px] font-medium text-warn">Oil / Fluid (optional)</span>
                <button type="button" onClick={openFluidPicker} className="text-[12px] font-medium text-warn hover:underline">+ Add Fluid</button>
              </div>
              {bookingFluids.map(f => (
                <div key={f.key} className="flex items-center gap-2 rounded-ctl border border-border bg-card px-2 py-1.5">
                  <span className="flex-1 truncate text-[13px] text-text">{f.item_name}</span>
                  <input type="number" min="0.1" step="0.1" value={f.litres} onChange={e => setBookingFluids(prev => prev.map(x => x.key === f.key ? { ...x, litres: Math.max(0.1, parseFloat(e.target.value) || 0.1) } : x))} className="w-16 rounded-ctl border border-border px-1.5 py-1 text-right text-[13px]" />
                  <span className="text-[12px] text-muted">L</span>
                  <button type="button" onClick={() => setBookingFluids(prev => prev.filter(x => x.key !== f.key))} className="text-muted-2 hover:text-danger">✕</button>
                </div>
              ))}
              {bookingFluids.length === 0 && <p className="text-[12px] text-warn">No fluids added. Click "+ Add Fluid" to reserve oil/fluid.</p>}
            </div>
          )}

          {/* Confirmation notifications (create only) */}
          {!isEdit && (
            <div className="space-y-2">
              <label className="flex cursor-pointer items-center gap-2 text-[13px] text-text">
                <input
                  type="checkbox"
                  checked={sendEmailConfirmation}
                  onChange={(e) => setSendEmailConfirmation(e.target.checked)}
                  className="rounded border-border text-accent focus:ring-accent"
                />
                Send email confirmation
              </label>
              {smsIncluded && (
                <label className="flex cursor-pointer items-center gap-2 text-[13px] text-text">
                  <input
                    type="checkbox"
                    checked={sendSmsConfirmation}
                    onChange={(e) => setSendSmsConfirmation(e.target.checked)}
                    className="rounded border-border text-accent focus:ring-accent"
                  />
                  Send SMS confirmation
                </label>
              )}
            </div>
          )}

          {/* Booking Reminder (create only) */}
          {!isEdit && (
            <fieldset className="space-y-2" data-testid="reminder-section">
              <legend className="text-[12.5px] font-medium text-text">Booking Reminder</legend>
              <div className="space-y-1">
                <label className="flex cursor-pointer items-center gap-2 text-[13px] text-text">
                  <input type="radio" name="reminder" value="none" checked={reminderOption === 'none'} onChange={() => setReminderOption('none')} className="text-accent focus:ring-accent" aria-label="No reminder" />
                  None
                </label>
                <label className="flex cursor-pointer items-center gap-2 text-[13px] text-text">
                  <input type="radio" name="reminder" value="24" checked={reminderOption === '24'} onChange={() => setReminderOption('24')} className="text-accent focus:ring-accent" aria-label="24 hours before" />
                  24 hours before
                </label>
                <label className="flex cursor-pointer items-center gap-2 text-[13px] text-text">
                  <input type="radio" name="reminder" value="6" checked={reminderOption === '6'} onChange={() => setReminderOption('6')} className="text-accent focus:ring-accent" aria-label="6 hours before" />
                  6 hours before
                </label>
                <label className="flex cursor-pointer items-center gap-2 text-[13px] text-text">
                  <input type="radio" name="reminder" value="custom" checked={reminderOption === 'custom'} onChange={() => setReminderOption('custom')} className="text-accent focus:ring-accent" aria-label="Custom reminder time" />
                  Custom
                </label>
                {reminderOption === 'custom' && (
                  <div className="ml-6 mt-1">
                    <label htmlFor="custom-reminder-hours" className="sr-only">Hours before booking</label>
                    <input
                      id="custom-reminder-hours"
                      type="number"
                      min="0.5"
                      step="0.5"
                      placeholder="Hours before booking"
                      value={customReminderHours}
                      onChange={(e) => setCustomReminderHours(e.target.value)}
                      className="w-48 rounded-ctl border border-border bg-card px-3 py-1.5 text-[13px] text-text shadow-sm focus:border-accent focus:outline-none focus:shadow-[0_0_0_3px_var(--accent-soft)]"
                      aria-label="Custom reminder hours before booking"
                      data-testid="custom-reminder-hours-input"
                    />
                  </div>
                )}
              </div>
            </fieldset>
          )}

          {/* Actions */}
          <div className="flex justify-end gap-3 border-t border-border pt-2">
            <Button type="button" variant="ghost" onClick={onClose} disabled={saving}>
              Cancel
            </Button>
            <Button type="submit" disabled={saving}>
              {saving ? 'Saving…' : isEdit ? 'Update Booking' : 'Create Booking'}
            </Button>
          </div>
        </form>
      )}

      {/* Parts Picker Modal */}
      <Modal open={partsPickerOpen} onClose={() => setPartsPickerOpen(false)} title="Add Part from Inventory">
        <div className="space-y-3">
          <input type="text" placeholder="Search parts..." value={stockSearch} onChange={e => setStockSearch(e.target.value)} className={STOCK_SEARCH_CLS} />
          {stockLoading ? <div className="py-6 text-center text-[13px] text-muted">Loading...</div> : (
            <div className="max-h-64 divide-y divide-border overflow-y-auto">
              {stockItems.filter(si => !stockSearch || si.item_name.toLowerCase().includes(stockSearch.toLowerCase())).map((si: any) => (
                <button key={si.id} type="button" onClick={() => addBookingPart(si)} className="flex w-full justify-between px-3 py-2 text-left hover:bg-accent-soft">
                  <div><div className="text-[13px] font-medium text-text">{si.item_name}</div><div className="text-[12px] text-muted">{si.part_number && `${si.part_number} · `}{si.brand || ''} · Avail: {si.available_quantity}</div></div>
                  <span className="mono text-[13px] text-text">{si.sell_price != null ? `${si.sell_price.toFixed(2)}` : '—'}</span>
                </button>
              ))}
              {stockItems.length === 0 && <div className="py-6 text-center text-[13px] text-muted">No parts in stock.</div>}
            </div>
          )}
        </div>
      </Modal>

      {/* Fluid Picker Modal */}
      <Modal open={fluidPickerOpen} onClose={() => setFluidPickerOpen(false)} title="Add Oil / Fluid">
        <div className="space-y-3">
          <input type="text" placeholder="Search fluids..." value={stockSearch} onChange={e => setStockSearch(e.target.value)} className={STOCK_SEARCH_CLS} />
          {stockLoading ? <div className="py-6 text-center text-[13px] text-muted">Loading...</div> : (
            <div className="max-h-64 divide-y divide-border overflow-y-auto">
              {stockItems.filter(si => !stockSearch || si.item_name.toLowerCase().includes(stockSearch.toLowerCase())).map((si: any) => (
                <button key={si.id} type="button" onClick={() => addBookingFluid(si)} className="flex w-full justify-between px-3 py-2 text-left hover:bg-warn-soft">
                  <div><div className="text-[13px] font-medium text-text">{si.item_name}</div><div className="text-[12px] text-muted">{si.brand || ''} · Avail: {si.available_quantity}L</div></div>
                </button>
              ))}
              {stockItems.length === 0 && <div className="py-6 text-center text-[13px] text-muted">No fluids in stock.</div>}
            </div>
          )}
        </div>
      </Modal>
    </Modal>
  )
}
