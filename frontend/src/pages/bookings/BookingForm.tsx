import { useState, useEffect } from 'react'
import apiClient from '../../api/client'
import { Button, Input, Select, Modal, Spinner } from '../../components/ui'
import { ModuleGate } from '../../components/common/ModuleGate'
import { useModules } from '../../contexts/ModuleContext'
import { VehicleLiveSearch } from '../../components/vehicles/VehicleLiveSearch'
import type { BookingSearchResult } from './BookingCalendar'
import {
  shouldTriggerCustomerSearch,
  shouldShowAddNewOption,
  getPrePopulatedFirstName,
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
export default function BookingForm({ open, onClose, onSaved, editBooking }: BookingFormProps) {
  const isEdit = !!editBooking
  const { isEnabled } = useModules()
  const vehiclesEnabled = isEnabled('vehicles')

  /* Form state */
  const [customerId, setCustomerId] = useState('')
  const [customerSearch, setCustomerSearch] = useState('')
  const [customerResults, setCustomerResults] = useState<CustomerOption[]>([])
  const [searchingCustomers, setSearchingCustomers] = useState(false)
  const [showCustomerDropdown, setShowCustomerDropdown] = useState(false)
  const [showInlineCustomerForm, setShowInlineCustomerForm] = useState(false)
  const [inlineFirstName, setInlineFirstName] = useState('')
  const [inlineLastName, setInlineLastName] = useState('')
  const [inlineEmail, setInlineEmail] = useState('')
  const [inlinePhone, setInlinePhone] = useState('')
  const [inlineCustomerError, setInlineCustomerError] = useState('')
  const [savingInlineCustomer, setSavingInlineCustomer] = useState(false)

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
      setScheduledAt(nowLocalStr())
      setDurationMinutes('60')
      setNotes('')
      setStatus('scheduled')
      setSendEmailConfirmation(false)
      setSendSmsConfirmation(false)
      setReminderOption('none')
      setCustomReminderHours('')
      setShowInlineCustomerForm(false)
      setInlineFirstName('')
      setInlineLastName('')
      setInlineEmail('')
      setInlinePhone('')
      setInlineCustomerError('')
      setError('')
    }
  }, [open, editBooking])

  /* Fetch plan features to determine SMS availability */
  useEffect(() => {
    if (!open) return
    apiClient.get<{ sms_included: boolean }>('/org/plan-features')
      .then((res) => setSmsIncluded(res.data.sms_included ?? false))
      .catch(() => setSmsIncluded(false))
  }, [open])

  /* Pre-populate inline customer first name from search query if it looks like a name */
  useEffect(() => {
    if (showInlineCustomerForm) {
      setInlineFirstName(getPrePopulatedFirstName(customerSearch))
      setInlineLastName('')
      setInlineEmail('')
      setInlinePhone('')
      setInlineCustomerError('')
    }
  }, [showInlineCustomerForm]) // eslint-disable-line react-hooks/exhaustive-deps

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
          params: { search: customerSearch, page_size: 8, ...(vehiclesEnabled ? { include_vehicles: true } : {}) },
        })
        const items = res.data.items ?? res.data.results ?? res.data.customers ?? []
        setCustomerResults(items)
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

  /* Submit inline customer form */
  const handleInlineCustomerSubmit = async (e: React.FormEvent) => {
    e.preventDefault()
    if (!inlineFirstName.trim() || !inlineLastName.trim()) {
      setInlineCustomerError('First name and last name are required.')
      return
    }
    setSavingInlineCustomer(true)
    setInlineCustomerError('')
    try {
      const res = await apiClient.post<{ id: string; first_name: string; last_name: string }>('/customers', {
        first_name: inlineFirstName.trim(),
        last_name: inlineLastName.trim(),
        email: inlineEmail.trim() || null,
        phone: inlinePhone.trim() || null,
      })
      const created = res.data
      setCustomerId(created.id)
      setCustomerSearch(`${created.first_name} ${created.last_name}`)
      setShowInlineCustomerForm(false)
    } catch (err: unknown) {
      const detail = (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail
      setInlineCustomerError(detail ?? 'Failed to create customer.')
    } finally {
      setSavingInlineCustomer(false)
    }
  }

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
                      setShowInlineCustomerForm(false)
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
                        setShowInlineCustomerForm(false)
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
                      setShowInlineCustomerForm(true)
                      setShowCustomerDropdown(false)
                    }}
                    onKeyDown={(e) => {
                      if (e.key === 'Enter') {
                        setShowInlineCustomerForm(true)
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

          {/* Inline customer form */}
          {showInlineCustomerForm && (
            <div className="rounded-md border border-gray-200 bg-gray-50 p-4 space-y-3" data-testid="inline-customer-form">
              <h4 className="text-sm font-medium text-gray-700">New Customer</h4>
              <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
                <Input
                  label="First Name *"
                  placeholder="First name"
                  value={inlineFirstName}
                  onChange={(e) => setInlineFirstName(e.target.value)}
                  aria-label="Customer first name"
                />
                <Input
                  label="Last Name *"
                  placeholder="Last name"
                  value={inlineLastName}
                  onChange={(e) => setInlineLastName(e.target.value)}
                  aria-label="Customer last name"
                />
              </div>
              <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
                <Input
                  label="Email"
                  placeholder="email@example.com"
                  type="email"
                  value={inlineEmail}
                  onChange={(e) => setInlineEmail(e.target.value)}
                  aria-label="Customer email"
                />
                <Input
                  label="Phone"
                  placeholder="Phone number"
                  type="tel"
                  value={inlinePhone}
                  onChange={(e) => setInlinePhone(e.target.value)}
                  aria-label="Customer phone"
                />
              </div>
              {inlineCustomerError && (
                <div className="rounded-md border border-red-200 bg-red-50 px-3 py-2 text-sm text-red-700" role="alert">
                  {inlineCustomerError}
                </div>
              )}
              <div className="flex gap-2">
                <Button
                  type="button"
                  disabled={savingInlineCustomer}
                  onClick={handleInlineCustomerSubmit}
                >
                  {savingInlineCustomer ? 'Saving…' : 'Create Customer'}
                </Button>
                <Button
                  type="button"
                  variant="secondary"
                  disabled={savingInlineCustomer}
                  onClick={() => setShowInlineCustomerForm(false)}
                >
                  Cancel
                </Button>
              </div>
            </div>
          )}

          {/* Vehicle rego (module-gated) */}
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
                {shouldShowAddNewOption(serviceSearch, serviceResults.length) && !searchingServices && (
                  <li
                    role="option"
                    aria-selected={false}
                    className="cursor-pointer px-3 py-2 text-sm text-blue-600 hover:bg-blue-50 focus:bg-blue-50 font-medium"
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
    </Modal>
  )
}
