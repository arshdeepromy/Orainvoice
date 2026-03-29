import { useState, useEffect } from 'react'
import apiClient from '../../api/client'
import { Button, Input, Select, Modal, Spinner } from '../../components/ui'
import { ModuleGate } from '../../components/common/ModuleGate'
import { useModules } from '../../contexts/ModuleContext'
import { useTenant } from '../../contexts/TenantContext'
import { VehicleLiveSearch } from '../../components/vehicles/VehicleLiveSearch'
import { CustomerCreateModal } from '../../components/customers/CustomerCreateModal'
import type { BookingSearchResult } from './BookingCalendar'
import {
  shouldTriggerCustomerSearch,
  shouldShowAddNewOption,
} from '../../utils/bookingFormHelpers'

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

/* ------------------------------------------------------------------ */
/*  Component                                                          */
/* ------------------------------------------------------------------ */

/**
 * Modal form for creating or editing a booking/appointment.
 * Links to a customer and optionally a vehicle, with date/time/duration/service type.
 * Supports optional confirmation email/SMS on creation.
 *
 * Requirements: 64.2, 64.3
 */
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
    wof_expiry: string | null; registration_expiry: string | null; odometer?: number | null;
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
                  engine_size: '', wof_expiry: null, registration_expiry: null, odometer: match.odometer ?? null,
                })
              } else {
                setSelectedVehicle({
                  id: '', rego: b.vehicle_rego, make: '', model: '', year: null, colour: '',
                  body_type: '', fuel_type: '', engine_size: '', wof_expiry: null, registration_expiry: null,
                })
              }
            }).catch(() => {
              setSelectedVehicle({
                id: '', rego: b.vehicle_rego!, make: '', model: '', year: null, colour: '',
                body_type: '', fuel_type: '', engine_size: '', wof_expiry: null, registration_expiry: null,
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
  }, [customerSearch, customerId])

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
          vehicle_rego: vehicleRego || null,
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
          vehicle_rego: vehicleRego || null,
          service_type: serviceType || null,
          service_catalogue_id: serviceCatalogueId || null,
          service_price: servicePrice ? parseFloat(servicePrice) : null,
          scheduled_at: new Date(scheduledAt).toISOString(),
          duration_minutes: parseInt(durationMinutes, 10),
          notes: notes || null,
          send_email_confirmation: sendEmailConfirmation,
          send_sms_confirmation: sendSmsConfirmation,
          reminder_offset_hours: reminderOption === 'none' ? null : reminderOption === 'custom' ? (customReminderHours && !isNaN(parseFloat(customReminderHours)) ? parseFloat(customReminderHours) : null) : parseFloat(reminderOption),
          parts: bookingParts.filter(p => p.quantity > 0).map(p => ({ stock_item_id: p.stock_item_id, catalogue_item_id: p.catalogue_item_id, item_name: p.item_name, quantity: p.quantity, sell_price: p.sell_price, gst_mode: p.gst_mode })),
          fluid_usage: bookingFluids.filter(f => f.litres > 0).map(f => ({ stock_item_id: f.stock_item_id, catalogue_item_id: f.catalogue_item_id, item_name: f.item_name, litres: f.litres })),
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
            <div className="rounded-md border border-red-200 bg-red-50 px-3 py-2 text-sm text-red-700" role="alert">{error}</div>
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
                <Spinner label="" />
              </div>
            )}
            {showCustomerDropdown && (
              <ul
                className="absolute z-10 mt-1 w-full rounded-md border border-gray-200 bg-white shadow-lg max-h-48 overflow-auto"
                role="listbox"
              >
                {customerResults && customerResults.length > 0 && customerResults.map((c) => (
                  <li
                    key={c.id}
                    role="option"
                    aria-selected={customerId === c.id}
                    className="cursor-pointer px-3 py-2 text-sm hover:bg-blue-50 focus:bg-blue-50"
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
                          engine_size: '', wof_expiry: null, registration_expiry: null,
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
                            engine_size: '', wof_expiry: null, registration_expiry: null,
                          })
                          setVehicleRego(v.rego)
                        }
                      }
                    }}
                    tabIndex={0}
                  >
                    <div className="flex items-center justify-between">
                      <div>
                        <span className="font-medium">{c.first_name} {c.last_name}</span>
                        {c.phone && <span className="ml-2 text-gray-500">{c.phone}</span>}
                        {c.email && <span className="ml-2 text-gray-400">{c.email}</span>}
                      </div>
                      {c.linked_vehicles && c.linked_vehicles.length > 0 && (
                        <span className="text-xs text-blue-600 bg-blue-50 px-2 py-0.5 rounded ml-2 shrink-0">
                          {c.linked_vehicles.length} vehicle{c.linked_vehicles.length > 1 ? 's' : ''}
                        </span>
                      )}
                    </div>
                    {c.linked_vehicles && c.linked_vehicles.length > 0 && (
                      <div className="mt-0.5 text-xs text-gray-500">
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
                    className="cursor-pointer px-3 py-2 text-sm text-blue-600 hover:bg-blue-50 focus:bg-blue-50 font-medium"
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
              <span className="absolute right-3 top-8 text-sm font-medium text-green-700" data-testid="selected-service-price">
                ${parseFloat(servicePrice).toFixed(2)}
              </span>
            )}
            {searchingServices && !serviceCatalogueId && (
              <div className="absolute right-3 top-8">
                <Spinner label="" />
              </div>
            )}
            {showServiceDropdown && (
              <ul
                className="absolute z-10 mt-1 w-full rounded-md border border-gray-200 bg-white shadow-lg max-h-48 overflow-auto"
                role="listbox"
              >
                {serviceResults.length > 0 && serviceResults.map((s) => (
                  <li
                    key={s.id}
                    role="option"
                    aria-selected={serviceCatalogueId === s.id}
                    className="cursor-pointer px-3 py-2 text-sm hover:bg-blue-50 focus:bg-blue-50"
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
                    <span className="font-medium">{s.name}</span>
                    <span className="ml-2 text-gray-500">— ${parseFloat(s.default_price).toFixed(2)}</span>
                  </li>
                ))}
                {!searchingServices && serviceSearch.trim().length >= 2 && (
                  <li
                    role="option"
                    aria-selected={false}
                    className="cursor-pointer px-3 py-2 text-sm text-blue-600 hover:bg-blue-50 focus:bg-blue-50 font-medium border-t border-gray-100"
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
            <div className="rounded-md border border-gray-200 bg-gray-50 p-4 space-y-3" data-testid="inline-service-form">
              <div className="flex items-center justify-between">
                <h4 className="text-sm font-semibold text-gray-900">New Item</h4>
                <button type="button" onClick={() => setShowInlineServiceForm(false)} className="text-gray-400 hover:text-gray-600 text-lg leading-none">&times;</button>
              </div>
              <hr className="border-gray-200" />
              <Input
                label="Item name *"
                value={inlineServiceName}
                onChange={(e) => setInlineServiceName(e.target.value)}
                aria-label="Item name"
              />
              <div>
                <label htmlFor="inline-service-desc" className="block text-sm font-medium text-gray-700 mb-1">Description</label>
                <textarea
                  id="inline-service-desc"
                  value={inlineServiceDescription}
                  onChange={(e) => setInlineServiceDescription(e.target.value)}
                  rows={3}
                  placeholder="Optional item description"
                  className="w-full rounded-md border border-gray-300 px-3 py-2 text-sm text-gray-900 focus:outline-none focus:ring-2 focus:ring-blue-500 focus:border-blue-500"
                />
              </div>
              <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
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
              <label className="flex items-center gap-2 text-sm text-gray-700 cursor-pointer">
                <input type="checkbox" checked={inlineServiceGstExempt} onChange={(e) => setInlineServiceGstExempt(e.target.checked)} className="rounded border-gray-300" />
                GST exempt
              </label>
              {inlineServiceError && (
                <div className="rounded-md border border-red-200 bg-red-50 px-3 py-2 text-sm text-red-700" role="alert">
                  {inlineServiceError}
                </div>
              )}
              <div className="flex justify-end gap-2">
                <Button
                  type="button"
                  variant="secondary"
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
          <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
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
          <div className="flex flex-col gap-1">
            <label htmlFor="booking-notes" className="text-sm font-medium text-gray-700">Notes</label>
            <textarea
              id="booking-notes"
              className="rounded-md border border-gray-300 px-3 py-2 text-gray-900 shadow-sm focus:outline-none focus:ring-2 focus:ring-blue-500 focus:border-blue-500"
              rows={3}
              placeholder="Additional notes…"
              value={notes}
              onChange={(e) => setNotes(e.target.value)}
            />
          </div>

          {/* Parts from Inventory (optional) */}
          <div className="rounded-lg border border-blue-200 bg-blue-50/50 p-3 space-y-2">
            <div className="flex items-center justify-between">
              <span className="text-sm font-medium text-blue-900">Parts (optional)</span>
              <button type="button" onClick={openPartsPicker} className="text-xs font-medium text-blue-600 hover:underline">+ Add Part</button>
            </div>
            {bookingParts.map(p => (
              <div key={p.key} className="flex items-center gap-2 bg-white rounded border border-blue-100 px-2 py-1.5">
                <span className="flex-1 text-sm text-gray-900 truncate">{p.item_name}</span>
                <input type="number" min="1" step="1" value={p.quantity} onChange={e => setBookingParts(prev => prev.map(x => x.key === p.key ? { ...x, quantity: Math.max(1, parseInt(e.target.value) || 1) } : x))} className="w-16 rounded border border-gray-300 px-1.5 py-1 text-sm text-right" />
                {p.sell_price != null && <span className="text-xs text-gray-500">${p.sell_price.toFixed(2)}</span>}
                <button type="button" onClick={() => setBookingParts(prev => prev.filter(x => x.key !== p.key))} className="text-gray-400 hover:text-red-500">✕</button>
              </div>
            ))}
            {bookingParts.length === 0 && <p className="text-xs text-blue-700">No parts added. Click "+ Add Part" to reserve inventory.</p>}
          </div>

          {/* Fluid / Oil Usage (optional, shown when vehicle is selected) */}
          {isAutomotive && vehiclesEnabled && selectedVehicle && (
            <div className="rounded-lg border border-amber-200 bg-amber-50/50 p-3 space-y-2">
              <div className="flex items-center justify-between">
                <span className="text-sm font-medium text-amber-900">Oil / Fluid (optional)</span>
                <button type="button" onClick={openFluidPicker} className="text-xs font-medium text-amber-700 hover:underline">+ Add Fluid</button>
              </div>
              {bookingFluids.map(f => (
                <div key={f.key} className="flex items-center gap-2 bg-white rounded border border-amber-100 px-2 py-1.5">
                  <span className="flex-1 text-sm text-gray-900 truncate">{f.item_name}</span>
                  <input type="number" min="0.1" step="0.1" value={f.litres} onChange={e => setBookingFluids(prev => prev.map(x => x.key === f.key ? { ...x, litres: Math.max(0.1, parseFloat(e.target.value) || 0.1) } : x))} className="w-16 rounded border border-gray-300 px-1.5 py-1 text-sm text-right" />
                  <span className="text-xs text-gray-500">L</span>
                  <button type="button" onClick={() => setBookingFluids(prev => prev.filter(x => x.key !== f.key))} className="text-gray-400 hover:text-red-500">✕</button>
                </div>
              ))}
              {bookingFluids.length === 0 && <p className="text-xs text-amber-700">No fluids added. Click "+ Add Fluid" to reserve oil/fluid.</p>}
            </div>
          )}

          {/* Confirmation notifications (create only) */}
          {!isEdit && (
            <div className="space-y-2">
              <label className="flex items-center gap-2 text-sm text-gray-700 cursor-pointer">
                <input
                  type="checkbox"
                  checked={sendEmailConfirmation}
                  onChange={(e) => setSendEmailConfirmation(e.target.checked)}
                  className="rounded border-gray-300 text-blue-600 focus:ring-blue-500"
                />
                Send email confirmation
              </label>
              {smsIncluded && (
                <label className="flex items-center gap-2 text-sm text-gray-700 cursor-pointer">
                  <input
                    type="checkbox"
                    checked={sendSmsConfirmation}
                    onChange={(e) => setSendSmsConfirmation(e.target.checked)}
                    className="rounded border-gray-300 text-blue-600 focus:ring-blue-500"
                  />
                  Send SMS confirmation
                </label>
              )}
            </div>
          )}

          {/* Booking Reminder (create only) */}
          {!isEdit && (
            <fieldset className="space-y-2" data-testid="reminder-section">
              <legend className="text-sm font-medium text-gray-700">Booking Reminder</legend>
              <div className="space-y-1">
                <label className="flex items-center gap-2 text-sm text-gray-700 cursor-pointer">
                  <input
                    type="radio"
                    name="reminder"
                    value="none"
                    checked={reminderOption === 'none'}
                    onChange={() => setReminderOption('none')}
                    className="text-blue-600 focus:ring-blue-500"
                    aria-label="No reminder"
                  />
                  None
                </label>
                <label className="flex items-center gap-2 text-sm text-gray-700 cursor-pointer">
                  <input
                    type="radio"
                    name="reminder"
                    value="24"
                    checked={reminderOption === '24'}
                    onChange={() => setReminderOption('24')}
                    className="text-blue-600 focus:ring-blue-500"
                    aria-label="24 hours before"
                  />
                  24 hours before
                </label>
                <label className="flex items-center gap-2 text-sm text-gray-700 cursor-pointer">
                  <input
                    type="radio"
                    name="reminder"
                    value="6"
                    checked={reminderOption === '6'}
                    onChange={() => setReminderOption('6')}
                    className="text-blue-600 focus:ring-blue-500"
                    aria-label="6 hours before"
                  />
                  6 hours before
                </label>
                <label className="flex items-center gap-2 text-sm text-gray-700 cursor-pointer">
                  <input
                    type="radio"
                    name="reminder"
                    value="custom"
                    checked={reminderOption === 'custom'}
                    onChange={() => setReminderOption('custom')}
                    className="text-blue-600 focus:ring-blue-500"
                    aria-label="Custom reminder time"
                  />
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
                      className="w-48 rounded-md border border-gray-300 px-3 py-1.5 text-sm text-gray-900 shadow-sm focus:outline-none focus:ring-2 focus:ring-blue-500 focus:border-blue-500"
                      aria-label="Custom reminder hours before booking"
                      data-testid="custom-reminder-hours-input"
                    />
                  </div>
                )}
              </div>
            </fieldset>
          )}

          {/* Actions */}
          <div className="flex justify-end gap-3 pt-2 border-t border-gray-100">
            <Button type="button" variant="secondary" onClick={onClose} disabled={saving}>
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
          <input type="text" placeholder="Search parts..." value={stockSearch} onChange={e => setStockSearch(e.target.value)} className="w-full rounded-md border border-gray-300 px-3 py-2 text-sm" />
          {stockLoading ? <div className="py-6 text-center text-sm text-gray-500">Loading...</div> : (
            <div className="max-h-64 overflow-y-auto divide-y divide-gray-100">
              {stockItems.filter(si => !stockSearch || si.item_name.toLowerCase().includes(stockSearch.toLowerCase())).map((si: any) => (
                <button key={si.id} type="button" onClick={() => addBookingPart(si)} className="w-full text-left px-3 py-2 hover:bg-blue-50 flex justify-between">
                  <div><div className="text-sm font-medium text-gray-900">{si.item_name}</div><div className="text-xs text-gray-500">{si.part_number && `${si.part_number} · `}{si.brand || ''} · Avail: {si.available_quantity}</div></div>
                  <span className="text-sm text-gray-900">{si.sell_price != null ? `$${si.sell_price.toFixed(2)}` : '—'}</span>
                </button>
              ))}
              {stockItems.length === 0 && <div className="py-6 text-center text-sm text-gray-500">No parts in stock.</div>}
            </div>
          )}
        </div>
      </Modal>

      {/* Fluid Picker Modal */}
      <Modal open={fluidPickerOpen} onClose={() => setFluidPickerOpen(false)} title="Add Oil / Fluid">
        <div className="space-y-3">
          <input type="text" placeholder="Search fluids..." value={stockSearch} onChange={e => setStockSearch(e.target.value)} className="w-full rounded-md border border-gray-300 px-3 py-2 text-sm" />
          {stockLoading ? <div className="py-6 text-center text-sm text-gray-500">Loading...</div> : (
            <div className="max-h-64 overflow-y-auto divide-y divide-gray-100">
              {stockItems.filter(si => !stockSearch || si.item_name.toLowerCase().includes(stockSearch.toLowerCase())).map((si: any) => (
                <button key={si.id} type="button" onClick={() => addBookingFluid(si)} className="w-full text-left px-3 py-2 hover:bg-amber-50 flex justify-between">
                  <div><div className="text-sm font-medium text-gray-900">{si.item_name}</div><div className="text-xs text-gray-500">{si.brand || ''} · Avail: {si.available_quantity}L</div></div>
                </button>
              ))}
              {stockItems.length === 0 && <div className="py-6 text-center text-sm text-gray-500">No fluids in stock.</div>}
            </div>
          )}
        </div>
      </Modal>
    </Modal>
  )
}
