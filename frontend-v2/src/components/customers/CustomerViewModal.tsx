import { useState, useEffect, useCallback } from 'react'
import apiClient from '@/api/client'
import { Button, Modal, Spinner } from '@/components/ui'

/**
 * CustomerViewModal — Task 25 modal pulled forward for Task 23 (CustomerList's
 * "View details" action needs it).
 *
 * ALL logic is copied VERBATIM from frontend/src/components/customers/
 * CustomerViewModal (fetch on open, portal link copy/send with the v2
 * `/api/v2/customers/:id/send-portal-link` endpoint, address/contact-person
 * formatting). Styling is remapped to the design-system tokens; `.mono` is
 * applied to the portal URL / phones. The v2 Button has no `secondary`
 * variant, so it maps to `ghost`.
 *
 * TODO(Task 25): owns the canonical home of this component; ported now so the
 * customer list functions.
 */

interface CustomerViewModalProps {
  open: boolean
  customerId: string | null
  onClose: () => void
}

const PAYMENT_TERMS_LABELS: Record<string, string> = {
  due_on_receipt: 'Due on Receipt', net_7: 'Net 7', net_15: 'Net 15',
  net_30: 'Net 30', net_45: 'Net 45', net_60: 'Net 60', net_90: 'Net 90',
}

function Field({ label, value, mono = false }: { label: string; value: string | null | undefined; mono?: boolean }) {
  return (
    <div>
      <span className="block text-[11px] text-muted">{label}</span>
      <span className={`text-[13.5px] text-text ${mono ? 'mono' : ''}`}>{value || '—'}</span>
    </div>
  )
}

function formatAddress(addr: Record<string, string> | null | undefined): string {
  if (!addr) return '—'
  const parts = [addr.street, addr.city, addr.state, addr.postal_code, addr.country].filter(Boolean)
  return parts.length > 0 ? parts.join(', ') : '—'
}

function PortalAccessSection({
  enablePortal,
  portalToken,
  customerId,
  lastPortalAccessAt,
}: {
  enablePortal: boolean | undefined
  portalToken: string | undefined
  customerId: string | undefined
  lastPortalAccessAt: string | null | undefined
}) {
  const [copyFeedback, setCopyFeedback] = useState(false)
  const [sendStatus, setSendStatus] = useState<'idle' | 'sending' | 'sent' | 'error'>('idle')
  const [sendError, setSendError] = useState('')

  const isEnabled = !!enablePortal && !!portalToken
  const portalUrl = isEnabled ? `${window.location.origin}/portal/${portalToken}` : null

  const handleCopy = useCallback(async () => {
    if (!portalUrl) return
    try {
      await navigator.clipboard.writeText(portalUrl)
      setCopyFeedback(true)
      setTimeout(() => setCopyFeedback(false), 2000)
    } catch {
      // Fallback for older browsers
      const textarea = document.createElement('textarea')
      textarea.value = portalUrl
      textarea.style.position = 'fixed'
      textarea.style.opacity = '0'
      document.body.appendChild(textarea)
      textarea.select()
      document.execCommand('copy')
      document.body.removeChild(textarea)
      setCopyFeedback(true)
      setTimeout(() => setCopyFeedback(false), 2000)
    }
  }, [portalUrl])

  const handleSendLink = useCallback(async () => {
    if (!customerId) return
    setSendStatus('sending')
    setSendError('')
    try {
      await apiClient.post(`/api/v2/customers/${customerId}/send-portal-link`)
      setSendStatus('sent')
      setTimeout(() => setSendStatus('idle'), 3000)
    } catch (err: unknown) {
      const detail =
        (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail ??
        'Failed to send portal link'
      setSendError(detail)
      setSendStatus('error')
      setTimeout(() => setSendStatus('idle'), 4000)
    }
  }, [customerId])

  if (!isEnabled) {
    return (
      <div className="mt-3">
        <span className="block text-[11px] text-muted">Portal Access</span>
        <span className="text-[13.5px] text-text">Disabled</span>
        {lastPortalAccessAt && (
          <div className="mt-1">
            <span className="text-[11px] text-muted">Last Seen: </span>
            <span className="text-[11px] text-muted">{new Date(lastPortalAccessAt).toLocaleString()}</span>
          </div>
        )}
      </div>
    )
  }

  return (
    <div className="mt-3">
      <span className="mb-1 block text-[11px] text-muted">Portal Access</span>
      <div className="flex items-center gap-2 rounded-ctl border border-border bg-canvas px-3 py-2">
        <span className="inline-block h-2 w-2 flex-shrink-0 rounded-full bg-ok" />
        <span className="mono min-w-0 flex-1 truncate text-[13px] text-muted" title={portalUrl ?? ''}>
          {portalUrl}
        </span>
        <button
          type="button"
          onClick={handleCopy}
          className="inline-flex flex-shrink-0 items-center gap-1 rounded-chip bg-accent-soft px-2 py-1 text-[11px] font-medium text-accent transition-colors hover:brightness-95"
        >
          {copyFeedback ? (
            <>
              <svg className="h-3.5 w-3.5" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                <path strokeLinecap="round" strokeLinejoin="round" d="M5 13l4 4L19 7" />
              </svg>
              Copied
            </>
          ) : (
            <>
              <svg className="h-3.5 w-3.5" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                <path strokeLinecap="round" strokeLinejoin="round" d="M8 16H6a2 2 0 01-2-2V6a2 2 0 012-2h8a2 2 0 012 2v2m-6 12h8a2 2 0 002-2v-8a2 2 0 00-2-2h-8a2 2 0 00-2 2v8a2 2 0 002 2z" />
              </svg>
              Copy Link
            </>
          )}
        </button>
        <button
          type="button"
          onClick={handleSendLink}
          disabled={sendStatus === 'sending' || sendStatus === 'sent'}
          className="inline-flex flex-shrink-0 items-center gap-1 rounded-chip bg-ok-soft px-2 py-1 text-[11px] font-medium text-ok transition-colors hover:brightness-95 disabled:cursor-not-allowed disabled:opacity-50"
        >
          {sendStatus === 'sending' ? (
            'Sending…'
          ) : sendStatus === 'sent' ? (
            <>
              <svg className="h-3.5 w-3.5" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                <path strokeLinecap="round" strokeLinejoin="round" d="M5 13l4 4L19 7" />
              </svg>
              Sent
            </>
          ) : (
            <>
              <svg className="h-3.5 w-3.5" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                <path strokeLinecap="round" strokeLinejoin="round" d="M3 8l7.89 5.26a2 2 0 002.22 0L21 8M5 19h14a2 2 0 002-2V7a2 2 0 00-2-2H5a2 2 0 00-2 2v10a2 2 0 002 2z" />
              </svg>
              Send Link
            </>
          )}
        </button>
      </div>
      {sendStatus === 'error' && sendError && (
        <p className="mt-1 text-[11px] text-danger">{sendError}</p>
      )}
      {lastPortalAccessAt && (
        <div className="mt-1">
          <span className="text-[11px] text-muted">Last Seen: </span>
          <span className="text-[11px] text-muted">{new Date(lastPortalAccessAt).toLocaleString()}</span>
        </div>
      )}
    </div>
  )
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
      {error && <p className="py-4 text-[13.5px] text-danger">Failed to load customer details.</p>}
      {data && !loading && (
        <div className="space-y-6">
          {/* Identity */}
          <div className="flex items-center gap-3">
            <div className="flex h-10 w-10 items-center justify-center rounded-full bg-accent-soft text-lg font-semibold text-accent">
              {(String(d.first_name || '')).charAt(0).toUpperCase()}
            </div>
            <div>
              <p className="text-lg font-semibold text-text">
                {String(d.display_name || `${d.first_name || ''} ${d.last_name || ''}`.trim() || '—')}
              </p>
              <p className="text-[13px] capitalize text-muted">{String(d.customer_type || 'individual')}</p>
            </div>
          </div>

          {/* Contact Info */}
          <div className="rounded-card border border-border p-4">
            <h4 className="mb-3 text-[13px] font-medium text-text">Contact Information</h4>
            <div className="grid grid-cols-2 gap-4 sm:grid-cols-3">
              <Field label="Salutation" value={d.salutation as string} />
              <Field label="First Name" value={d.first_name as string} />
              <Field label="Last Name" value={d.last_name as string} />
              {!!d.company_name && <Field label="Company Name" value={d.company_name as string} />}
              <Field label="Email" value={d.email as string} />
              <Field label="Mobile" value={d.mobile_phone as string || d.phone as string} mono />
              <Field label="Work Phone" value={d.work_phone as string} mono />
              <Field label="Phone" value={d.phone as string} mono />
            </div>
          </div>

          {/* Preferences */}
          <div className="rounded-card border border-border p-4">
            <h4 className="mb-3 text-[13px] font-medium text-text">Preferences & Settings</h4>
            <div className="grid grid-cols-2 gap-4 sm:grid-cols-3">
              <Field label="Currency" value={d.currency as string || 'NZD'} />
              <Field label="Language" value={(d.language as string) === 'mi' ? 'Māori' : 'English'} />
              <Field label="Payment Terms" value={PAYMENT_TERMS_LABELS[d.payment_terms as string] || d.payment_terms as string} />
              <Field label="Company ID" value={d.company_id as string} />
              <Field label="Bank Payment" value={(d.enable_bank_payment as boolean) ? 'Enabled' : 'Disabled'} />
            </div>
            {/* Portal Access Section */}
            <PortalAccessSection
              enablePortal={d.enable_portal as boolean | undefined}
              portalToken={d.portal_token as string | undefined}
              customerId={d.id as string | undefined}
              lastPortalAccessAt={d.last_portal_access_at as string | null | undefined}
            />
          </div>

          {/* Addresses */}
          <div className="rounded-card border border-border p-4">
            <h4 className="mb-3 text-[13px] font-medium text-text">Addresses</h4>
            <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
              <Field label="Billing Address" value={formatAddress(d.billing_address as Record<string, string>)} />
              <Field label="Shipping Address" value={formatAddress(d.shipping_address as Record<string, string>)} />
            </div>
            {!!d.address && <div className="mt-2"><Field label="Address" value={d.address as string} /></div>}
          </div>

          {/* Contact Persons */}
          {contactPersons.length > 0 && (
            <div className="rounded-card border border-border p-4">
              <h4 className="mb-3 text-[13px] font-medium text-text">Contact Persons</h4>
              <div className="space-y-3">
                {contactPersons.map((cp, i) => (
                  <div key={i} className="rounded-ctl border border-border bg-canvas p-3">
                    <div className="grid grid-cols-2 gap-3 sm:grid-cols-3">
                      <Field label="Name" value={`${cp.salutation ? cp.salutation + '. ' : ''}${cp.first_name || ''} ${cp.last_name || ''}`.trim()} />
                      <Field label="Email" value={cp.email as string} />
                      <Field label="Designation" value={cp.designation as string} />
                      <Field label="Work Phone" value={cp.work_phone as string} mono />
                      <Field label="Mobile" value={cp.mobile_phone as string} mono />
                    </div>
                  </div>
                ))}
              </div>
            </div>
          )}

          {/* Notes & Remarks */}
          {(!!d.notes || !!d.remarks) && (
            <div className="rounded-card border border-border p-4">
              <h4 className="mb-3 text-[13px] font-medium text-text">Notes & Remarks</h4>
              {!!d.notes && <Field label="Notes" value={d.notes as string} />}
              {!!d.remarks && <div className="mt-2"><Field label="Remarks" value={d.remarks as string} /></div>}
            </div>
          )}

          {/* Financial Summary */}
          {(!!d.total_spend || !!d.outstanding_balance) && (
            <div className="rounded-card border border-border p-4">
              <h4 className="mb-3 text-[13px] font-medium text-text">Financial Summary</h4>
              <div className="grid grid-cols-2 gap-4">
                <Field label="Total Spend" value={d.total_spend ? `NZD ${d.total_spend}` : '—'} mono />
                <Field label="Outstanding Balance" value={d.outstanding_balance ? `NZD ${d.outstanding_balance}` : '—'} mono />
              </div>
            </div>
          )}

          {/* Timestamps */}
          <div className="flex gap-4 text-[11px] text-muted-2">
            <span>Created: {d.created_at ? new Date(d.created_at as string).toLocaleDateString() : '—'}</span>
            <span>Updated: {d.updated_at ? new Date(d.updated_at as string).toLocaleDateString() : '—'}</span>
          </div>

          {/* Actions */}
          <div className="flex justify-end gap-3 border-t border-border pt-4">
            <Button variant="ghost" onClick={onClose}>Close</Button>
            <Button onClick={() => { window.location.href = `/customers/${String(d.id)}` }}>Full Profile</Button>
          </div>
        </div>
      )}
    </Modal>
  )
}

export default CustomerViewModal
