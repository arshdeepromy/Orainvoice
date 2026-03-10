import { useState, useEffect, useMemo, useRef } from 'react'
import apiClient from '../../api/client'
import { Button, Input, Select, Modal, Spinner, PhoneInput } from '../ui'

/* ------------------------------------------------------------------ */
/*  Types                                                              */
/* ------------------------------------------------------------------ */

interface AddressFields {
  street: string
  city: string
  state: string
  postal_code: string
  country: string
}

interface ContactPerson {
  salutation: string
  first_name: string
  last_name: string
  email: string
  work_phone: string
  mobile_phone: string
  designation: string
  is_primary: boolean
}

interface CustomerEditModalProps {
  open: boolean
  customerId: string | null
  onClose: () => void
  onSaved: () => void
}

const EMPTY_ADDRESS: AddressFields = { street: '', city: '', state: '', postal_code: '', country: 'New Zealand' }

const EMPTY_CONTACT: ContactPerson = {
  salutation: '', first_name: '', last_name: '', email: '',
  work_phone: '', mobile_phone: '', designation: '', is_primary: false,
}

const SALUTATION_OPTIONS = [
  { value: '', label: 'Select' },
  { value: 'Mr', label: 'Mr' },
  { value: 'Mrs', label: 'Mrs' },
  { value: 'Ms', label: 'Ms' },
  { value: 'Miss', label: 'Miss' },
  { value: 'Dr', label: 'Dr' },
  { value: 'Prof', label: 'Prof' },
]

const PAYMENT_TERMS_OPTIONS = [
  { value: 'due_on_receipt', label: 'Due on Receipt' },
  { value: 'net_7', label: 'Net 7' },
  { value: 'net_15', label: 'Net 15' },
  { value: 'net_30', label: 'Net 30' },
  { value: 'net_45', label: 'Net 45' },
  { value: 'net_60', label: 'Net 60' },
  { value: 'net_90', label: 'Net 90' },
]

const CURRENCY_OPTIONS = [
  { value: 'NZD', label: 'NZD - New Zealand Dollar' },
  { value: 'AUD', label: 'AUD - Australian Dollar' },
  { value: 'USD', label: 'USD - US Dollar' },
  { value: 'GBP', label: 'GBP - British Pound' },
  { value: 'EUR', label: 'EUR - Euro' },
]

const LANGUAGE_OPTIONS = [
  { value: 'en', label: 'English' },
  { value: 'mi', label: 'Māori' },
]

type TabId = 'details' | 'address' | 'contacts' | 'custom' | 'remarks'

/* ------------------------------------------------------------------ */
/*  Display Name Selector                                              */
/* ------------------------------------------------------------------ */

function DisplayNameSelector({
  salutation, firstName, lastName, companyName, customerType, value, onChange,
}: {
  salutation: string; firstName: string; lastName: string; companyName: string
  customerType: 'individual' | 'business'; value: string; onChange: (v: string) => void
}) {
  const [showDropdown, setShowDropdown] = useState(false)
  const containerRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
    const handler = (e: MouseEvent) => {
      if (containerRef.current && !containerRef.current.contains(e.target as Node)) setShowDropdown(false)
    }
    document.addEventListener('mousedown', handler)
    return () => document.removeEventListener('mousedown', handler)
  }, [])

  const suggestions = useMemo(() => {
    const opts: string[] = []
    const f = firstName.trim(), l = lastName.trim(), s = salutation.trim(), c = companyName.trim()
    if (f && l) opts.push(`${f} ${l}`)
    if (s && f && l) opts.push(`${s}. ${f} ${l}`)
    if (f && l) opts.push(`${l}, ${f}`)
    if (s && l) opts.push(`${s}. ${l}`)
    if (customerType === 'business' && c) opts.push(c)
    if (customerType === 'business' && c && f && l) opts.push(`${c} (${f} ${l})`)
    if (f && !l) opts.push(f)
    if (l && !f) opts.push(l)
    return [...new Set(opts)].filter(Boolean)
  }, [salutation, firstName, lastName, companyName, customerType])

  return (
    <div ref={containerRef} className="relative flex flex-col gap-1">
      <label className="text-sm font-medium text-gray-700">Display Name</label>
      <div className="relative">
        <input
          type="text" value={value} onChange={(e) => onChange(e.target.value)}
          onFocus={() => setShowDropdown(true)}
          placeholder="Select or type to add"
          className="h-[42px] w-full rounded-md border border-gray-300 px-3 py-2 pr-10 text-gray-900 shadow-sm placeholder:text-gray-400 focus:outline-none focus:ring-2 focus:ring-blue-500 focus:border-blue-500"
        />
        <button type="button" onClick={() => setShowDropdown(!showDropdown)}
          className="absolute right-2 top-1/2 -translate-y-1/2 p-1 text-gray-400 hover:text-gray-600">
          <svg className="h-5 w-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M19 9l-7 7-7-7" />
          </svg>
        </button>
      </div>
      {showDropdown && suggestions.length > 0 && (
        <div className="absolute top-full left-0 right-0 z-30 mt-1 max-h-48 overflow-auto rounded-md border border-gray-200 bg-white shadow-lg">
          {suggestions.map((s, i) => (
            <button key={i} type="button" onClick={() => { onChange(s); setShowDropdown(false) }}
              className={`w-full px-4 py-2 text-left text-sm hover:bg-blue-50 ${value === s ? 'bg-blue-50 text-blue-700' : 'text-gray-900'}`}>
              {s}
            </button>
          ))}
        </div>
      )}
    </div>
  )
}

/* ------------------------------------------------------------------ */
/*  Component                                                          */
/* ------------------------------------------------------------------ */

export function CustomerEditModal({ open, customerId, onClose, onSaved }: CustomerEditModalProps) {
  const [loading, setLoading] = useState(false)
  const [activeTab, setActiveTab] = useState<TabId>('details')

  // Form fields (mirrors create modal)
  const [customerType, setCustomerType] = useState<'individual' | 'business'>('business')
  const [salutation, setSalutation] = useState('')
  const [firstName, setFirstName] = useState('')
  const [lastName, setLastName] = useState('')
  const [companyName, setCompanyName] = useState('')
  const [displayName, setDisplayName] = useState('')
  const [email, setEmail] = useState('')
  const [workPhone, setWorkPhone] = useState('')
  const [mobilePhone, setMobilePhone] = useState('')
  const [phone, setPhone] = useState('')
  const [currency, setCurrency] = useState('NZD')
  const [language, setLanguage] = useState('en')
  const [companyId, setCompanyId] = useState('')
  const [paymentTerms, setPaymentTerms] = useState('due_on_receipt')
  const [enableBankPayment, setEnableBankPayment] = useState(false)
  const [enablePortal, setEnablePortal] = useState(false)
  const [billingAddress, setBillingAddress] = useState<AddressFields>(EMPTY_ADDRESS)
  const [shippingAddress, setShippingAddress] = useState<AddressFields>(EMPTY_ADDRESS)
  const [sameAsBilling, setSameAsBilling] = useState(true)
  const [contactPersons, setContactPersons] = useState<ContactPerson[]>([])
  const [notes, setNotes] = useState('')
  const [remarks, setRemarks] = useState('')

  const [saving, setSaving] = useState(false)
  const [errors, setErrors] = useState<Record<string, string>>({})

  // Load customer data when modal opens
  useEffect(() => {
    if (!open || !customerId) return
    setLoading(true)
    setActiveTab('details')
    apiClient.get(`/customers/${customerId}`).then(({ data: d }) => {
      setCustomerType(d.customer_type === 'individual' ? 'individual' : 'business')
      setSalutation(d.salutation || '')
      setFirstName(d.first_name || '')
      setLastName(d.last_name || '')
      setCompanyName(d.company_name || '')
      setDisplayName(d.display_name || '')
      setEmail(d.email || '')
      setWorkPhone(d.work_phone || '')
      setMobilePhone(d.mobile_phone || '')
      setPhone(d.phone || '')
      setCurrency(d.currency || 'NZD')
      setLanguage(d.language || 'en')
      setCompanyId(d.company_id || '')
      setPaymentTerms(d.payment_terms || 'due_on_receipt')
      setEnableBankPayment(d.enable_bank_payment || false)
      setEnablePortal(d.enable_portal || false)
      const ba = d.billing_address || {}
      setBillingAddress({ street: ba.street || '', city: ba.city || '', state: ba.state || '', postal_code: ba.postal_code || '', country: ba.country || 'New Zealand' })
      const sa = d.shipping_address || {}
      setShippingAddress({ street: sa.street || '', city: sa.city || '', state: sa.state || '', postal_code: sa.postal_code || '', country: sa.country || 'New Zealand' })
      // Check if shipping matches billing
      const baStr = JSON.stringify(ba), saStr = JSON.stringify(sa)
      setSameAsBilling(baStr === saStr || !sa.street)
      setContactPersons((d.contact_persons || []).map((cp: Record<string, unknown>) => ({
        salutation: (cp.salutation as string) || '', first_name: (cp.first_name as string) || '',
        last_name: (cp.last_name as string) || '', email: (cp.email as string) || '',
        work_phone: (cp.work_phone as string) || '', mobile_phone: (cp.mobile_phone as string) || '',
        designation: (cp.designation as string) || '', is_primary: !!cp.is_primary,
      })))
      setNotes(d.notes || '')
      setRemarks(d.remarks || '')
    }).catch(() => {
      setErrors({ submit: 'Failed to load customer data.' })
    }).finally(() => setLoading(false))
  }, [open, customerId])

  const validate = (): boolean => {
    const errs: Record<string, string> = {}
    if (!firstName.trim()) errs.first_name = 'First name is required'
    if (!lastName.trim()) errs.last_name = 'Last name is required'
    if (!email.trim()) errs.email = 'Email is required'
    if (email && !/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(email)) errs.email = 'Invalid email format'
    if (!mobilePhone.trim() && !phone.trim()) errs.mobile_phone = 'Mobile phone is required'
    setErrors(errs)
    return Object.keys(errs).length === 0
  }

  const handleSave = async () => {
    if (!validate() || !customerId) return
    setSaving(true)
    try {
      const payload: Record<string, unknown> = {
        customer_type: customerType,
        salutation: salutation || undefined,
        first_name: firstName.trim(),
        last_name: lastName.trim(),
        company_name: companyName.trim() || undefined,
        display_name: displayName.trim() || undefined,
        email: email.trim(),
        mobile_phone: mobilePhone.trim() || phone.trim(),
        phone: phone.trim() || mobilePhone.trim(),
        work_phone: workPhone.trim() || undefined,
        currency, language,
        company_id: companyId.trim() || undefined,
        payment_terms: paymentTerms,
        enable_bank_payment: enableBankPayment,
        enable_portal: enablePortal,
        notes: notes.trim() || undefined,
        remarks: remarks.trim() || undefined,
      }
      if (Object.values(billingAddress).some(v => v.trim())) payload.billing_address = billingAddress
      if (sameAsBilling) payload.shipping_address = billingAddress
      else if (Object.values(shippingAddress).some(v => v.trim())) payload.shipping_address = shippingAddress
      if (contactPersons.length > 0) payload.contact_persons = contactPersons.filter(cp => cp.first_name.trim() && cp.last_name.trim())

      await apiClient.put(`/customers/${customerId}`, payload)
      onSaved()
      onClose()
    } catch {
      setErrors({ submit: 'Failed to update customer.' })
    } finally {
      setSaving(false)
    }
  }

  const addContactPerson = () => setContactPersons([...contactPersons, { ...EMPTY_CONTACT }])
  const updateContactPerson = (i: number, field: keyof ContactPerson, value: string | boolean) =>
    setContactPersons(prev => prev.map((cp, idx) => idx === i ? { ...cp, [field]: value } : cp))
  const removeContactPerson = (i: number) => setContactPersons(prev => prev.filter((_, idx) => idx !== i))

  const tabs: { id: TabId; label: string }[] = [
    { id: 'details', label: 'Other Details' },
    { id: 'address', label: 'Address' },
    { id: 'contacts', label: 'Contact Persons' },
    { id: 'custom', label: 'Custom Fields' },
    { id: 'remarks', label: 'Remarks' },
  ]

  return (
    <Modal open={open} onClose={onClose} title="Edit Customer" className="max-w-3xl">
      {loading ? (
        <div className="py-12"><Spinner label="Loading customer" /></div>
      ) : (
      <div className="space-y-6">
        {/* Customer Type Toggle */}
        <div className="flex items-center gap-4">
          <span className="text-sm font-medium text-gray-700">Customer Type</span>
          <div className="flex items-center gap-4">
            <label className="flex items-center gap-2 cursor-pointer">
              <input type="radio" name="editCustomerType" checked={customerType === 'business'}
                onChange={() => setCustomerType('business')} className="h-4 w-4 text-blue-600 focus:ring-blue-500" />
              <span className="text-sm text-gray-700">Business</span>
            </label>
            <label className="flex items-center gap-2 cursor-pointer">
              <input type="radio" name="editCustomerType" checked={customerType === 'individual'}
                onChange={() => setCustomerType('individual')} className="h-4 w-4 text-blue-600 focus:ring-blue-500" />
              <span className="text-sm text-gray-700">Individual</span>
            </label>
          </div>
        </div>

        {/* Primary Contact */}
        <div className="grid grid-cols-1 gap-4 sm:grid-cols-12">
          <div className="sm:col-span-3">
            <Select label="Salutation" options={SALUTATION_OPTIONS} value={salutation}
              onChange={(e) => setSalutation(e.target.value)} />
          </div>
          <div className="sm:col-span-4">
            <Input label="First Name *" value={firstName} onChange={(e) => setFirstName(e.target.value)} error={errors.first_name} />
          </div>
          <div className="sm:col-span-5">
            <Input label="Last Name *" value={lastName} onChange={(e) => setLastName(e.target.value)} error={errors.last_name} />
          </div>
        </div>

        {customerType === 'business' && (
          <Input label="Company Name" value={companyName} onChange={(e) => setCompanyName(e.target.value)} />
        )}

        <DisplayNameSelector salutation={salutation} firstName={firstName} lastName={lastName}
          companyName={companyName} customerType={customerType} value={displayName} onChange={setDisplayName} />

        <Select label="Currency" options={CURRENCY_OPTIONS} value={currency} onChange={(e) => setCurrency(e.target.value)} />

        <Input label="Email Address *" type="email" value={email} onChange={(e) => setEmail(e.target.value)} error={errors.email} />

        <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
          <PhoneInput label="Work Phone" value={workPhone} onChange={setWorkPhone} countryCode="NZ" placeholder="Work phone" />
          <PhoneInput label="Mobile *" value={mobilePhone || phone} onChange={(v) => { setMobilePhone(v); setPhone(v) }}
            countryCode="NZ" placeholder="Mobile" required error={errors.mobile_phone} />
        </div>

        <Select label="Customer Language" options={LANGUAGE_OPTIONS} value={language} onChange={(e) => setLanguage(e.target.value)} />

        {/* Tabs */}
        <div className="border-b border-gray-200">
          <nav className="-mb-px flex space-x-6" aria-label="Tabs">
            {tabs.map((tab) => (
              <button key={tab.id} type="button" onClick={() => setActiveTab(tab.id)}
                className={`whitespace-nowrap border-b-2 py-2 px-1 text-sm font-medium ${
                  activeTab === tab.id ? 'border-blue-500 text-blue-600' : 'border-transparent text-gray-500 hover:border-gray-300 hover:text-gray-700'
                }`}>
                {tab.label}
              </button>
            ))}
          </nav>
        </div>

        <div className="min-h-[200px]">
          {activeTab === 'details' && (
            <div className="space-y-4">
              <Select label="Payment Terms" options={PAYMENT_TERMS_OPTIONS} value={paymentTerms}
                onChange={(e) => setPaymentTerms(e.target.value)} />
              <Input label="Company ID" value={companyId} onChange={(e) => setCompanyId(e.target.value)} placeholder="Business registration number" />
              <div className="space-y-3">
                <label className="flex items-center gap-3 cursor-pointer">
                  <input type="checkbox" checked={enableBankPayment} onChange={(e) => setEnableBankPayment(e.target.checked)}
                    className="h-4 w-4 rounded border-gray-300 text-blue-600 focus:ring-blue-500" />
                  <span className="text-sm text-gray-700">Allow this customer to pay via their bank account</span>
                </label>
                <label className="flex items-center gap-3 cursor-pointer">
                  <input type="checkbox" checked={enablePortal} onChange={(e) => setEnablePortal(e.target.checked)}
                    className="h-4 w-4 rounded border-gray-300 text-blue-600 focus:ring-blue-500" />
                  <span className="text-sm text-gray-700">Allow portal access for this customer</span>
                </label>
              </div>
            </div>
          )}

          {activeTab === 'address' && (
            <div className="space-y-6">
              <div>
                <h4 className="text-sm font-medium text-gray-900 mb-3">Billing Address</h4>
                <div className="space-y-3">
                  <Input label="Street" value={billingAddress.street} onChange={(e) => setBillingAddress({ ...billingAddress, street: e.target.value })} />
                  <div className="grid grid-cols-2 gap-3">
                    <Input label="City" value={billingAddress.city} onChange={(e) => setBillingAddress({ ...billingAddress, city: e.target.value })} />
                    <Input label="State/Region" value={billingAddress.state} onChange={(e) => setBillingAddress({ ...billingAddress, state: e.target.value })} />
                  </div>
                  <div className="grid grid-cols-2 gap-3">
                    <Input label="Postal Code" value={billingAddress.postal_code} onChange={(e) => setBillingAddress({ ...billingAddress, postal_code: e.target.value })} />
                    <Input label="Country" value={billingAddress.country} onChange={(e) => setBillingAddress({ ...billingAddress, country: e.target.value })} />
                  </div>
                </div>
              </div>
              <label className="flex items-center gap-2 cursor-pointer">
                <input type="checkbox" checked={sameAsBilling} onChange={(e) => setSameAsBilling(e.target.checked)}
                  className="h-4 w-4 rounded border-gray-300 text-blue-600 focus:ring-blue-500" />
                <span className="text-sm text-gray-700">Shipping address same as billing</span>
              </label>
              {!sameAsBilling && (
                <div>
                  <h4 className="text-sm font-medium text-gray-900 mb-3">Shipping Address</h4>
                  <div className="space-y-3">
                    <Input label="Street" value={shippingAddress.street} onChange={(e) => setShippingAddress({ ...shippingAddress, street: e.target.value })} />
                    <div className="grid grid-cols-2 gap-3">
                      <Input label="City" value={shippingAddress.city} onChange={(e) => setShippingAddress({ ...shippingAddress, city: e.target.value })} />
                      <Input label="State/Region" value={shippingAddress.state} onChange={(e) => setShippingAddress({ ...shippingAddress, state: e.target.value })} />
                    </div>
                    <div className="grid grid-cols-2 gap-3">
                      <Input label="Postal Code" value={shippingAddress.postal_code} onChange={(e) => setShippingAddress({ ...shippingAddress, postal_code: e.target.value })} />
                      <Input label="Country" value={shippingAddress.country} onChange={(e) => setShippingAddress({ ...shippingAddress, country: e.target.value })} />
                    </div>
                  </div>
                </div>
              )}
            </div>
          )}

          {activeTab === 'contacts' && (
            <div className="space-y-4">
              {contactPersons.map((cp, index) => (
                <div key={index} className="rounded-lg border border-gray-200 p-4 space-y-3">
                  <div className="flex items-center justify-between">
                    <span className="text-sm font-medium text-gray-700">Contact Person {index + 1}</span>
                    <button type="button" onClick={() => removeContactPerson(index)} className="text-red-500 hover:text-red-700 text-sm">Remove</button>
                  </div>
                  <div className="grid grid-cols-1 gap-3 sm:grid-cols-3">
                    <Select label="Salutation" options={SALUTATION_OPTIONS} value={cp.salutation} onChange={(e) => updateContactPerson(index, 'salutation', e.target.value)} />
                    <Input label="First Name" value={cp.first_name} onChange={(e) => updateContactPerson(index, 'first_name', e.target.value)} />
                    <Input label="Last Name" value={cp.last_name} onChange={(e) => updateContactPerson(index, 'last_name', e.target.value)} />
                  </div>
                  <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
                    <Input label="Email" type="email" value={cp.email} onChange={(e) => updateContactPerson(index, 'email', e.target.value)} />
                    <Input label="Designation" value={cp.designation} onChange={(e) => updateContactPerson(index, 'designation', e.target.value)} placeholder="Job title" />
                  </div>
                  <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
                    <PhoneInput label="Work Phone" value={cp.work_phone} onChange={(val) => updateContactPerson(index, 'work_phone', val)} countryCode="NZ" placeholder="Work phone" />
                    <PhoneInput label="Mobile" value={cp.mobile_phone} onChange={(val) => updateContactPerson(index, 'mobile_phone', val)} countryCode="NZ" placeholder="Mobile" />
                  </div>
                </div>
              ))}
              <Button type="button" variant="secondary" size="sm" onClick={addContactPerson}>+ Add Contact Person</Button>
            </div>
          )}

          {activeTab === 'custom' && (
            <div className="space-y-4">
              <p className="text-sm text-gray-500">Custom fields can be used to store additional information about this customer.</p>
              <Input label="Notes" value={notes} onChange={(e) => setNotes(e.target.value)} placeholder="Internal notes about this customer" />
            </div>
          )}

          {activeTab === 'remarks' && (
            <div className="space-y-4">
              <div>
                <label className="block text-sm font-medium text-gray-700 mb-1">Remarks</label>
                <textarea value={remarks} onChange={(e) => setRemarks(e.target.value)} rows={4}
                  className="w-full rounded-md border border-gray-300 px-3 py-2 text-sm text-gray-900 shadow-sm placeholder:text-gray-400 focus:outline-none focus:ring-2 focus:ring-blue-500 focus:border-blue-500"
                  placeholder="Additional remarks or comments..." />
              </div>
            </div>
          )}
        </div>

        {errors.submit && <p className="text-sm text-red-600" role="alert">{errors.submit}</p>}

        <div className="flex justify-end gap-3 pt-4 border-t border-gray-200">
          <Button variant="secondary" onClick={onClose}>Cancel</Button>
          <Button onClick={handleSave} loading={saving}>Save Changes</Button>
        </div>
      </div>
      )}
    </Modal>
  )
}

export default CustomerEditModal
