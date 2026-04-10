/**
 * Claim creation form — customer selector, type, description, optional invoice/job card.
 *
 * Requirements: 1.1, 1.2, 1.5, 1.6, 8.2, 8.3
 */

import { useState, useEffect, useRef, useCallback } from 'react'
import { useNavigate, useSearchParams } from 'react-router-dom'
import { Button, Spinner } from '../../components/ui'
import { useCreateClaim } from '../../hooks/useClaims'
import apiClient from '../../api/client'

/* ------------------------------------------------------------------ */
/*  Types                                                              */
/* ------------------------------------------------------------------ */

interface CustomerOption {
  id: string
  first_name: string
  last_name: string
  email: string | null
}

interface InvoiceOption {
  id: string
  invoice_number: string | null
  customer_name?: string | null
  total: number | string
  status: string
}

interface JobCardOption {
  id: string
  description: string | null
  status: string
  vehicle_rego: string | null
}

interface LineItemOption {
  id: string
  description: string
  item_type: string
  quantity: number | string
  line_total: number | string
}

const CLAIM_TYPES = [
  { value: 'warranty', label: 'Warranty' },
  { value: 'defect', label: 'Defect' },
  { value: 'service_redo', label: 'Service Redo' },
  { value: 'exchange', label: 'Exchange' },
  { value: 'refund_request', label: 'Refund Request' },
]

/* ------------------------------------------------------------------ */
/*  Component                                                          */
/* ------------------------------------------------------------------ */

export default function ClaimCreateForm() {
  const navigate = useNavigate()
  const [searchParams] = useSearchParams()
  const { create, loading: submitting, error: submitError } = useCreateClaim()

  /* Pre-populated from query params (e.g. from invoice "Report Issue") */
  const preInvoiceId = searchParams.get('invoice_id') || ''
  const preCustomerId = searchParams.get('customer_id') || ''

  /* Form state */
  const [customerId, setCustomerId] = useState(preCustomerId)
  const [customerSearch, setCustomerSearch] = useState('')
  const [customers, setCustomers] = useState<CustomerOption[]>([])
  const [customersLoading, setCustomersLoading] = useState(false)
  const [showCustomerDropdown, setShowCustomerDropdown] = useState(false)
  const [selectedCustomerName, setSelectedCustomerName] = useState('')

  const [claimType, setClaimType] = useState('')
  const [description, setDescription] = useState('')

  const [invoiceId, setInvoiceId] = useState(preInvoiceId)
  const [invoices, setInvoices] = useState<InvoiceOption[]>([])
  const [invoicesLoading, setInvoicesLoading] = useState(false)

  const [jobCardId, setJobCardId] = useState('')
  const [jobCards, setJobCards] = useState<JobCardOption[]>([])
  const [jobCardsLoading, setJobCardsLoading] = useState(false)

  const [lineItems, setLineItems] = useState<LineItemOption[]>([])
  const [selectedLineItemIds, setSelectedLineItemIds] = useState<string[]>([])

  const customerSearchRef = useRef<AbortController>()
  const dropdownRef = useRef<HTMLDivElement>(null)

  /* Close dropdown on outside click */
  useEffect(() => {
    const handler = (e: MouseEvent) => {
      if (dropdownRef.current && !dropdownRef.current.contains(e.target as Node)) {
        setShowCustomerDropdown(false)
      }
    }
    document.addEventListener('mousedown', handler)
    return () => document.removeEventListener('mousedown', handler)
  }, [])

  /* Search customers */
  const searchCustomers = useCallback(async (query: string) => {
    if (customerSearchRef.current) customerSearchRef.current.abort()
    if (!query.trim()) { setCustomers([]); return }
    const controller = new AbortController()
    customerSearchRef.current = controller
    setCustomersLoading(true)
    try {
      const res = await apiClient.get<{ customers: CustomerOption[] }>('/customers', {
        params: { q: query, limit: 10 },
        signal: controller.signal,
      })
      setCustomers(res.data?.customers ?? [])
      setShowCustomerDropdown(true)
    } catch (err: unknown) {
      if ((err as { name?: string })?.name !== 'CanceledError') setCustomers([])
    } finally {
      setCustomersLoading(false)
    }
  }, [])

  useEffect(() => {
    const t = setTimeout(() => searchCustomers(customerSearch), 300)
    return () => clearTimeout(t)
  }, [customerSearch, searchCustomers])

  /* Fetch invoices when customer selected */
  /* Fetch invoices when customer selected */
  useEffect(() => {
    if (!customerId) { setInvoices([]); return }
    const controller = new AbortController()
    setInvoicesLoading(true)
    apiClient.get<{ invoices: InvoiceOption[] }>('/invoices', {
      params: { limit: 100 },
      signal: controller.signal,
    }).then(res => {
      // Filter client-side to only show invoices matching the selected customer name
      const all = res.data?.invoices ?? []
      if (selectedCustomerName) {
        const name = selectedCustomerName.toLowerCase()
        const filtered = all.filter((inv: InvoiceOption & { customer_name?: string | null }) =>
          inv.customer_name?.toLowerCase()?.includes(name)
        )
        setInvoices(filtered.length > 0 ? filtered : all)
      } else {
        setInvoices(all)
      }
    }).catch(() => {
      setInvoices([])
    }).finally(() => setInvoicesLoading(false))
    return () => controller.abort()
  }, [customerId, selectedCustomerName])

  /* Fetch job cards when customer selected */
  useEffect(() => {
    if (!customerId) { setJobCards([]); return }
    const controller = new AbortController()
    setJobCardsLoading(true)
    apiClient.get<{ job_cards: JobCardOption[] }>('/job-cards', {
      params: { limit: 100 },
      signal: controller.signal,
    }).then(res => {
      setJobCards(res.data?.job_cards ?? [])
    }).catch(() => {
      setJobCards([])
    }).finally(() => setJobCardsLoading(false))
    return () => controller.abort()
  }, [customerId])

  /* Fetch line items when invoice selected */
  useEffect(() => {
    if (!invoiceId) { setLineItems([]); setSelectedLineItemIds([]); return }
    const controller = new AbortController()
    apiClient.get<{ line_items?: LineItemOption[]; invoice?: { line_items?: LineItemOption[] } }>(`/invoices/${invoiceId}`, {
      signal: controller.signal,
    }).then(res => {
      const items = res.data?.line_items ?? res.data?.invoice?.line_items ?? []
      setLineItems(items)
    }).catch(() => {
      setLineItems([])
    })
    return () => controller.abort()
  }, [invoiceId])

  /* Pre-fetch customer name if pre-populated */
  useEffect(() => {
    if (!preCustomerId) return
    const controller = new AbortController()
    apiClient.get<{ first_name: string; last_name: string }>(`/customers/${preCustomerId}`, {
      signal: controller.signal,
    }).then(res => {
      const name = `${res.data?.first_name ?? ''} ${res.data?.last_name ?? ''}`.trim()
      setSelectedCustomerName(name || preCustomerId)
    }).catch(() => {
      setSelectedCustomerName(preCustomerId)
    })
    return () => controller.abort()
  }, [preCustomerId])

  const selectCustomer = (c: CustomerOption) => {
    setCustomerId(c.id)
    setSelectedCustomerName(`${c.first_name} ${c.last_name}`)
    setCustomerSearch('')
    setShowCustomerDropdown(false)
    setInvoiceId('')
    setJobCardId('')
    setLineItems([])
    setSelectedLineItemIds([])
  }

  const toggleLineItem = (id: string) => {
    setSelectedLineItemIds(prev =>
      prev.includes(id) ? prev.filter(x => x !== id) : [...prev, id]
    )
  }

  const canSubmit = customerId && claimType && description.trim() && (invoiceId || jobCardId)

  const handleSubmit = async () => {
    if (!canSubmit) return
    const result = await create({
      customer_id: customerId,
      claim_type: claimType,
      description: description.trim(),
      invoice_id: invoiceId || undefined,
      job_card_id: jobCardId || undefined,
      line_item_ids: selectedLineItemIds.length > 0 ? selectedLineItemIds : undefined,
    })
    if (result) {
      navigate(`/claims/${result.id}`)
    }
  }

  return (
    <div className="max-w-2xl mx-auto space-y-6">
      <div className="flex items-center justify-between">
        <h1 className="text-2xl font-bold text-gray-900">New Claim</h1>
        <Button variant="secondary" size="sm" onClick={() => navigate('/claims')}>
          Cancel
        </Button>
      </div>

      <div className="rounded-lg border border-gray-200 bg-white p-6 space-y-5">
        {/* Customer selector */}
        <div ref={dropdownRef} className="relative">
          <label htmlFor="customer-search" className="block text-sm font-medium text-gray-700 mb-1">
            Customer <span className="text-red-500">*</span>
          </label>
          {customerId && selectedCustomerName ? (
            <div className="flex items-center gap-2">
              <span className="text-sm text-gray-800">{selectedCustomerName}</span>
              <button
                type="button"
                onClick={() => { setCustomerId(''); setSelectedCustomerName(''); setInvoices([]); setJobCards([]) }}
                className="text-xs text-red-500 hover:underline"
              >
                Change
              </button>
            </div>
          ) : (
            <>
              <input
                id="customer-search"
                type="text"
                value={customerSearch}
                onChange={e => setCustomerSearch(e.target.value)}
                placeholder="Search customers…"
                className="w-full rounded-md border border-gray-300 px-3 py-2 text-sm focus:border-blue-400 focus:ring-1 focus:ring-blue-400 outline-none"
                autoComplete="off"
              />
              {showCustomerDropdown && customers.length > 0 && (
                <ul className="absolute z-10 mt-1 w-full max-h-48 overflow-y-auto rounded-md border border-gray-200 bg-white shadow-lg">
                  {customers.map(c => (
                    <li key={c.id}>
                      <button
                        type="button"
                        onClick={() => selectCustomer(c)}
                        className="w-full text-left px-3 py-2 text-sm hover:bg-blue-50"
                      >
                        {c.first_name} {c.last_name}
                        {c.email && <span className="text-gray-400 ml-2">{c.email}</span>}
                      </button>
                    </li>
                  ))}
                </ul>
              )}
              {customersLoading && <Spinner size="sm" className="mt-1" />}
            </>
          )}
        </div>

        {/* Claim type */}
        <div>
          <label htmlFor="claim-type" className="block text-sm font-medium text-gray-700 mb-1">
            Claim Type <span className="text-red-500">*</span>
          </label>
          <select
            id="claim-type"
            value={claimType}
            onChange={e => setClaimType(e.target.value)}
            className="w-full rounded-md border border-gray-300 px-3 py-2 text-sm focus:border-blue-400 focus:ring-1 focus:ring-blue-400 outline-none"
          >
            <option value="">Select type…</option>
            {CLAIM_TYPES.map(t => <option key={t.value} value={t.value}>{t.label}</option>)}
          </select>
        </div>

        {/* Description */}
        <div>
          <label htmlFor="claim-description" className="block text-sm font-medium text-gray-700 mb-1">
            Description <span className="text-red-500">*</span>
          </label>
          <textarea
            id="claim-description"
            value={description}
            onChange={e => setDescription(e.target.value)}
            rows={4}
            placeholder="Describe the customer's complaint…"
            className="w-full rounded-md border border-gray-300 px-3 py-2 text-sm focus:border-blue-400 focus:ring-1 focus:ring-blue-400 outline-none resize-y"
          />
        </div>

        {/* Invoice selector */}
        <div>
          <label htmlFor="claim-invoice" className="block text-sm font-medium text-gray-700 mb-1">
            Invoice {!jobCardId && <span className="text-red-500">*</span>}
          </label>
          {invoicesLoading ? (
            <Spinner size="sm" />
          ) : (
            <select
              id="claim-invoice"
              value={invoiceId}
              onChange={e => { setInvoiceId(e.target.value); setSelectedLineItemIds([]) }}
              className="w-full rounded-md border border-gray-300 px-3 py-2 text-sm focus:border-blue-400 focus:ring-1 focus:ring-blue-400 outline-none"
              disabled={!customerId}
            >
              <option value="">None</option>
              {(invoices ?? []).map(inv => (
                <option key={inv.id} value={inv.id}>
                  {inv.invoice_number ?? inv.id.slice(0, 8)} — ${Number(inv.total ?? 0).toFixed(2)}
                </option>
              ))}
            </select>
          )}
        </div>

        {/* Line items (when invoice selected) */}
        {invoiceId && (lineItems ?? []).length > 0 && (
          <div>
            <p className="text-sm font-medium text-gray-700 mb-1">Line Items (optional)</p>
            <div className="space-y-1 max-h-40 overflow-y-auto border border-gray-200 rounded-md p-2">
              {(lineItems ?? []).map(li => (
                <label key={li.id} className="flex items-center gap-2 text-sm cursor-pointer hover:bg-gray-50 px-1 py-0.5 rounded">
                  <input
                    type="checkbox"
                    checked={selectedLineItemIds.includes(li.id)}
                    onChange={() => toggleLineItem(li.id)}
                    className="rounded border-gray-300"
                  />
                  <span className="flex-1 truncate">{li.description}</span>
                  <span className="text-gray-400 text-xs">${Number(li.line_total ?? 0).toFixed(2)}</span>
                </label>
              ))}
            </div>
          </div>
        )}

        {/* Job card selector */}
        <div>
          <label htmlFor="claim-jobcard" className="block text-sm font-medium text-gray-700 mb-1">
            Job Card {!invoiceId && <span className="text-red-500">*</span>}
          </label>
          {jobCardsLoading ? (
            <Spinner size="sm" />
          ) : (
            <select
              id="claim-jobcard"
              value={jobCardId}
              onChange={e => setJobCardId(e.target.value)}
              className="w-full rounded-md border border-gray-300 px-3 py-2 text-sm focus:border-blue-400 focus:ring-1 focus:ring-blue-400 outline-none"
              disabled={!customerId}
            >
              <option value="">None</option>
              {(jobCards ?? []).map(jc => (
                <option key={jc.id} value={jc.id}>
                  {jc.description ?? jc.id.slice(0, 8)}
                  {jc.vehicle_rego ? ` (${jc.vehicle_rego})` : ''}
                </option>
              ))}
            </select>
          )}
        </div>

        {/* Validation hint */}
        {customerId && !invoiceId && !jobCardId && (
          <p className="text-xs text-amber-600">At least one of Invoice or Job Card is required.</p>
        )}

        {submitError && (
          <div className="rounded-md border border-red-200 bg-red-50 p-3 text-sm text-red-700">{submitError}</div>
        )}

        {/* Submit */}
        <div className="flex justify-end gap-2 pt-2">
          <Button variant="secondary" size="sm" onClick={() => navigate('/claims')}>
            Cancel
          </Button>
          <Button size="sm" onClick={handleSubmit} disabled={!canSubmit} loading={submitting}>
            Create Claim
          </Button>
        </div>
      </div>
    </div>
  )
}
