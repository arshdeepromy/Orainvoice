import { useState, useEffect } from 'react'
import apiClient from '../../api/client'
import { Button, Modal, Spinner } from '../ui'

interface CustomerViewModalProps {
  open: boolean
  customerId: string | null
  onClose: () => void
}

const PAYMENT_TERMS_LABELS: Record<string, string> = {
  due_on_receipt: 'Due on Receipt', net_7: 'Net 7', net_15: 'Net 15',
  net_30: 'Net 30', net_45: 'Net 45', net_60: 'Net 60', net_90: 'Net 90',
}

function Field({ label, value }: { label: string; value: string | null | undefined }) {
  return (
    <div>
      <span className="text-xs text-gray-500 block">{label}</span>
      <span className="text-sm text-gray-900">{value || '—'}</span>
    </div>
  )
}

function formatAddress(addr: Record<string, string> | null | undefined): string {
  if (!addr) return '—'
  const parts = [addr.street, addr.city, addr.state, addr.postal_code, addr.country].filter(Boolean)
  return parts.length > 0 ? parts.join(', ') : '—'
}

export function CustomerViewModal({ open, customerId, onClose }: CustomerViewModalProps) {
  const [loading, setLoading] = useState(false)
  const [data, setData] = useState<Record<string, unknown> | null>(null)
  const [error, setError] = useState(false)

  useEffect(() => {
    if (!open || !customerId) return
    setLoading(true)
    setError(false)
    setData(null)
    apiClient.get(`/customers/${customerId}`)
      .then(({ data: d }) => setData(d as Record<string, unknown>))
      .catch(() => setError(true))
      .finally(() => setLoading(false))
  }, [open, customerId])

  const d = data || {}
  const contactPersons = (d.contact_persons as Record<string, unknown>[] | undefined) || []

  return (
    <Modal open={open} onClose={onClose} title="Customer Details" className="max-w-3xl">
      {loading && <div className="py-12"><Spinner label="Loading" /></div>}
      {error && <p className="text-sm text-red-600 py-4">Failed to load customer details.</p>}
      {data && !loading && (
        <div className="space-y-6">
          {/* Identity */}
          <div className="flex items-center gap-3">
            <div className="h-10 w-10 rounded-full bg-blue-100 flex items-center justify-center text-blue-700 font-semibold text-lg">
              {(String(d.first_name || '')).charAt(0).toUpperCase()}
            </div>
            <div>
              <p className="text-lg font-semibold text-gray-900">
                {String(d.display_name || `${d.first_name || ''} ${d.last_name || ''}`.trim() || '—')}
              </p>
              <p className="text-sm text-gray-500 capitalize">{String(d.customer_type || 'individual')}</p>
            </div>
          </div>

          {/* Contact Info */}
          <div className="rounded-lg border border-gray-200 p-4">
            <h4 className="text-sm font-medium text-gray-700 mb-3">Contact Information</h4>
            <div className="grid grid-cols-2 sm:grid-cols-3 gap-4">
              <Field label="Salutation" value={d.salutation as string} />
              <Field label="First Name" value={d.first_name as string} />
              <Field label="Last Name" value={d.last_name as string} />
              {!!d.company_name && <Field label="Company Name" value={d.company_name as string} />}
              <Field label="Email" value={d.email as string} />
              <Field label="Mobile" value={d.mobile_phone as string || d.phone as string} />
              <Field label="Work Phone" value={d.work_phone as string} />
              <Field label="Phone" value={d.phone as string} />
            </div>
          </div>

          {/* Preferences */}
          <div className="rounded-lg border border-gray-200 p-4">
            <h4 className="text-sm font-medium text-gray-700 mb-3">Preferences & Settings</h4>
            <div className="grid grid-cols-2 sm:grid-cols-3 gap-4">
              <Field label="Currency" value={d.currency as string || 'NZD'} />
              <Field label="Language" value={(d.language as string) === 'mi' ? 'Māori' : 'English'} />
              <Field label="Payment Terms" value={PAYMENT_TERMS_LABELS[d.payment_terms as string] || d.payment_terms as string} />
              <Field label="Company ID" value={d.company_id as string} />
              <Field label="Bank Payment" value={(d.enable_bank_payment as boolean) ? 'Enabled' : 'Disabled'} />
              <Field label="Portal Access" value={(d.enable_portal as boolean) ? 'Enabled' : 'Disabled'} />
            </div>
          </div>

          {/* Addresses */}
          <div className="rounded-lg border border-gray-200 p-4">
            <h4 className="text-sm font-medium text-gray-700 mb-3">Addresses</h4>
            <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
              <Field label="Billing Address" value={formatAddress(d.billing_address as Record<string, string>)} />
              <Field label="Shipping Address" value={formatAddress(d.shipping_address as Record<string, string>)} />
            </div>
            {!!d.address && <div className="mt-2"><Field label="Address" value={d.address as string} /></div>}
          </div>

          {/* Contact Persons */}
          {contactPersons.length > 0 && (
            <div className="rounded-lg border border-gray-200 p-4">
              <h4 className="text-sm font-medium text-gray-700 mb-3">Contact Persons</h4>
              <div className="space-y-3">
                {contactPersons.map((cp, i) => (
                  <div key={i} className="rounded border border-gray-100 bg-gray-50 p-3">
                    <div className="grid grid-cols-2 sm:grid-cols-3 gap-3">
                      <Field label="Name" value={`${cp.salutation ? cp.salutation + '. ' : ''}${cp.first_name || ''} ${cp.last_name || ''}`.trim()} />
                      <Field label="Email" value={cp.email as string} />
                      <Field label="Designation" value={cp.designation as string} />
                      <Field label="Work Phone" value={cp.work_phone as string} />
                      <Field label="Mobile" value={cp.mobile_phone as string} />
                    </div>
                  </div>
                ))}
              </div>
            </div>
          )}

          {/* Notes & Remarks */}
          {(!!d.notes || !!d.remarks) && (
            <div className="rounded-lg border border-gray-200 p-4">
              <h4 className="text-sm font-medium text-gray-700 mb-3">Notes & Remarks</h4>
              {!!d.notes && <Field label="Notes" value={d.notes as string} />}
              {!!d.remarks && <div className="mt-2"><Field label="Remarks" value={d.remarks as string} /></div>}
            </div>
          )}

          {/* Financial Summary */}
          {(!!d.total_spend || !!d.outstanding_balance) && (
            <div className="rounded-lg border border-gray-200 p-4">
              <h4 className="text-sm font-medium text-gray-700 mb-3">Financial Summary</h4>
              <div className="grid grid-cols-2 gap-4">
                <Field label="Total Spend" value={d.total_spend ? `NZD ${d.total_spend}` : '—'} />
                <Field label="Outstanding Balance" value={d.outstanding_balance ? `NZD ${d.outstanding_balance}` : '—'} />
              </div>
            </div>
          )}

          {/* Timestamps */}
          <div className="text-xs text-gray-400 flex gap-4">
            <span>Created: {d.created_at ? new Date(d.created_at as string).toLocaleDateString() : '—'}</span>
            <span>Updated: {d.updated_at ? new Date(d.updated_at as string).toLocaleDateString() : '—'}</span>
          </div>

          {/* Actions */}
          <div className="flex justify-end gap-3 pt-4 border-t border-gray-200">
            <Button variant="secondary" onClick={onClose}>Close</Button>
            <Button onClick={() => { window.location.href = `/customers/${String(d.id)}` }}>Full Profile</Button>
          </div>
        </div>
      )}
    </Modal>
  )
}

export default CustomerViewModal
