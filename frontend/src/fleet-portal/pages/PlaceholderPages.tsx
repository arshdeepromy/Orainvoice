/**
 * Remaining fleet portal pages — Invoices and Security.
 * These have limited backend support currently but show meaningful UI.
 */
import { useEffect, useState } from 'react'
import type { FormEvent } from 'react'

import { fleetClient } from '../api/client'
import { useFleetSession } from '../contexts/FleetSessionContext'

export default function VehicleDetailPlaceholder() {
  return null // Not used — real VehicleDetail.tsx is imported directly
}

interface InvoiceRow {
  invoice_id: string
  invoice_number: string
  issue_date: string
  due_date: string | null
  total: string
  amount_paid: string
  amount_outstanding: string
  status: string
}

interface InvoiceDetail {
  invoice_id: string
  invoice_number: string
  status: string
  issue_date: string | null
  due_date: string | null
  currency: string
  subtotal: string
  discount_amount: string
  gst_amount: string
  total: string
  amount_paid: string
  balance_due: string
  notes_customer: string | null
  vehicle_rego: string | null
  vehicle_make: string | null
  vehicle_model: string | null
  vehicle_year: number | null
  line_items: Array<{
    id: string
    description: string
    quantity: string
    unit_price: string
    amount: string
    gst_amount: string
  }>
}

export function InvoicesPage() {
  const [invoices, setInvoices] = useState<InvoiceRow[]>([])
  const [loading, setLoading] = useState(true)
  const [filter, setFilter] = useState('all')
  const [selectedInvoice, setSelectedInvoice] = useState<InvoiceDetail | null>(null)
  const [detailLoading, setDetailLoading] = useState(false)
  const [downloadingPdf, setDownloadingPdf] = useState<string | null>(null)

  useEffect(() => {
    const controller = new AbortController()
    const fetchInvoices = async () => {
      setLoading(true)
      try {
        const res = await fleetClient.get<{ items: InvoiceRow[]; total: number }>('/invoices', {
          params: { limit: 50, status: filter !== 'all' ? filter : undefined },
          signal: controller.signal,
        })
        setInvoices(res.data?.items ?? [])
      } catch {
        if (!controller.signal.aborted) setInvoices([])
      } finally {
        if (!controller.signal.aborted) setLoading(false)
      }
    }
    fetchInvoices()
    return () => controller.abort()
  }, [filter])

  const viewDetail = async (invoiceId: string) => {
    setDetailLoading(true)
    try {
      const res = await fleetClient.get<InvoiceDetail>(`/invoices/${invoiceId}`)
      setSelectedInvoice(res.data ?? null)
    } catch {
      setSelectedInvoice(null)
    } finally {
      setDetailLoading(false)
    }
  }

  const downloadPdf = async (invoiceId: string) => {
    setDownloadingPdf(invoiceId)
    try {
      const res = await fleetClient.get(`/invoices/${invoiceId}/pdf`, {
        responseType: 'blob',
      })
      const blob = new Blob([res.data], { type: 'application/pdf' })
      const url = URL.createObjectURL(blob)
      const a = document.createElement('a')
      a.href = url
      a.download = `invoice-${invoiceId.slice(0, 8)}.pdf`
      document.body.appendChild(a)
      a.click()
      document.body.removeChild(a)
      URL.revokeObjectURL(url)
    } catch {
      alert('Failed to download PDF.')
    } finally {
      setDownloadingPdf(null)
    }
  }

  if (loading) return <div className="p-4 text-sm text-gray-500">Loading…</div>

  // Detail view
  if (selectedInvoice) {
    return (
      <div className="space-y-4">
        <button
          onClick={() => setSelectedInvoice(null)}
          className="text-sm text-indigo-600 hover:underline min-h-[44px] flex items-center gap-1"
        >
          ← Back to invoices
        </button>

        <div className="rounded-lg border border-gray-200 bg-white p-6 dark:border-gray-800 dark:bg-gray-950">
          <div className="flex items-center justify-between mb-4">
            <div>
              <h1 className="text-xl font-semibold">Invoice #{selectedInvoice.invoice_number}</h1>
              {selectedInvoice.vehicle_rego && (
                <p className="text-sm text-gray-500 mt-1">
                  {selectedInvoice.vehicle_rego} — {selectedInvoice.vehicle_make} {selectedInvoice.vehicle_model} {selectedInvoice.vehicle_year ?? ''}
                </p>
              )}
            </div>
            <div className="flex items-center gap-2">
              <span className={`text-xs px-2 py-0.5 rounded-full font-medium ${
                selectedInvoice.status === 'paid' ? 'bg-green-100 text-green-800' :
                selectedInvoice.status === 'overdue' ? 'bg-red-100 text-red-800' :
                'bg-blue-100 text-blue-800'
              }`}>
                {selectedInvoice.status}
              </span>
              <button
                onClick={() => downloadPdf(selectedInvoice.invoice_id)}
                disabled={downloadingPdf === selectedInvoice.invoice_id}
                className="rounded-md bg-indigo-600 px-3 py-2 text-sm font-medium text-white min-h-[44px] hover:bg-indigo-700 disabled:opacity-50"
              >
                {downloadingPdf === selectedInvoice.invoice_id ? 'Downloading…' : 'Download PDF'}
              </button>
            </div>
          </div>

          <div className="grid grid-cols-2 gap-4 text-sm mb-6">
            <div><span className="text-gray-500">Issue Date:</span> {selectedInvoice.issue_date ?? '—'}</div>
            <div><span className="text-gray-500">Due Date:</span> {selectedInvoice.due_date ?? '—'}</div>
          </div>

          {/* Line items */}
          <div className="overflow-x-auto rounded border border-gray-200 dark:border-gray-700 mb-4">
            <table className="min-w-full divide-y divide-gray-200 dark:divide-gray-700 text-sm">
              <thead className="bg-gray-50 dark:bg-gray-900">
                <tr>
                  <th className="px-3 py-2 text-left text-xs font-medium uppercase text-gray-500">Description</th>
                  <th className="px-3 py-2 text-right text-xs font-medium uppercase text-gray-500">Qty</th>
                  <th className="px-3 py-2 text-right text-xs font-medium uppercase text-gray-500">Unit Price</th>
                  <th className="px-3 py-2 text-right text-xs font-medium uppercase text-gray-500">Amount</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-gray-200 dark:divide-gray-700 bg-white dark:bg-gray-950">
                {(selectedInvoice.line_items ?? []).map(li => (
                  <tr key={li.id}>
                    <td className="px-3 py-2">{li.description}</td>
                    <td className="px-3 py-2 text-right tabular-nums">{parseFloat(li.quantity ?? '0')}</td>
                    <td className="px-3 py-2 text-right tabular-nums">${parseFloat(li.unit_price ?? '0').toFixed(2)}</td>
                    <td className="px-3 py-2 text-right tabular-nums">${parseFloat(li.amount ?? '0').toFixed(2)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>

          {/* Totals */}
          <div className="flex justify-end">
            <div className="w-64 space-y-1 text-sm">
              <div className="flex justify-between"><span className="text-gray-500">Subtotal</span><span className="tabular-nums">${parseFloat(selectedInvoice.subtotal ?? '0').toFixed(2)}</span></div>
              {parseFloat(selectedInvoice.discount_amount ?? '0') > 0 && (
                <div className="flex justify-between"><span className="text-gray-500">Discount</span><span className="tabular-nums text-red-600">-${parseFloat(selectedInvoice.discount_amount ?? '0').toFixed(2)}</span></div>
              )}
              <div className="flex justify-between"><span className="text-gray-500">GST</span><span className="tabular-nums">${parseFloat(selectedInvoice.gst_amount ?? '0').toFixed(2)}</span></div>
              <div className="flex justify-between font-semibold border-t border-gray-200 dark:border-gray-700 pt-1"><span>Total</span><span className="tabular-nums">${parseFloat(selectedInvoice.total ?? '0').toFixed(2)}</span></div>
              <div className="flex justify-between"><span className="text-gray-500">Paid</span><span className="tabular-nums text-green-600">${parseFloat(selectedInvoice.amount_paid ?? '0').toFixed(2)}</span></div>
              <div className="flex justify-between font-semibold"><span>Balance Due</span><span className="tabular-nums">${parseFloat(selectedInvoice.balance_due ?? '0').toFixed(2)}</span></div>
            </div>
          </div>

          {selectedInvoice.notes_customer && (
            <div className="mt-4 rounded border border-gray-200 bg-gray-50 p-3 dark:border-gray-700 dark:bg-gray-900">
              <p className="text-xs text-gray-500 mb-1">Notes</p>
              <p className="text-sm">{selectedInvoice.notes_customer}</p>
            </div>
          )}
        </div>
      </div>
    )
  }

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between">
        <h1 className="text-xl font-semibold">Invoices</h1>
        <select value={filter} onChange={e => setFilter(e.target.value)} className="rounded border border-gray-300 px-2 py-1 text-sm min-h-[44px] dark:border-gray-700 dark:bg-gray-900 dark:text-white">
          <option value="all">All</option>
          <option value="unpaid">Unpaid</option>
          <option value="paid">Paid</option>
          <option value="overdue">Overdue</option>
        </select>
      </div>
      {(invoices ?? []).length === 0 ? (
        <div className="rounded-lg border border-dashed border-gray-300 p-8 text-center dark:border-gray-700">
          <p className="text-sm text-gray-500">No invoices found.</p>
        </div>
      ) : (
        <div className="overflow-x-auto rounded-lg border border-gray-200 dark:border-gray-800">
          <table className="min-w-full divide-y divide-gray-200 dark:divide-gray-800 text-sm">
            <thead className="bg-gray-50 dark:bg-gray-900">
              <tr>
                <th className="px-3 py-2 text-left text-xs font-medium uppercase text-gray-500">Invoice #</th>
                <th className="px-3 py-2 text-left text-xs font-medium uppercase text-gray-500">Date</th>
                <th className="px-3 py-2 text-left text-xs font-medium uppercase text-gray-500">Due</th>
                <th className="px-3 py-2 text-right text-xs font-medium uppercase text-gray-500">Total</th>
                <th className="px-3 py-2 text-right text-xs font-medium uppercase text-gray-500">Outstanding</th>
                <th className="px-3 py-2 text-left text-xs font-medium uppercase text-gray-500">Status</th>
                <th className="px-3 py-2 text-left text-xs font-medium uppercase text-gray-500">Actions</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-gray-200 dark:divide-gray-800 bg-white dark:bg-gray-950">
              {(invoices ?? []).map(inv => (
                <tr key={inv.invoice_id}>
                  <td className="px-3 py-2 font-medium">{inv.invoice_number}</td>
                  <td className="px-3 py-2 text-gray-500">{inv.issue_date}</td>
                  <td className="px-3 py-2 text-gray-500">{inv.due_date ?? '—'}</td>
                  <td className="px-3 py-2 text-right tabular-nums">${parseFloat(inv.total ?? '0').toFixed(2)}</td>
                  <td className="px-3 py-2 text-right tabular-nums">${parseFloat(inv.amount_outstanding ?? '0').toFixed(2)}</td>
                  <td className="px-3 py-2">
                    <span className={`text-xs px-2 py-0.5 rounded-full font-medium ${inv.status === 'paid' ? 'bg-green-100 text-green-800' : inv.status === 'overdue' ? 'bg-red-100 text-red-800' : 'bg-blue-100 text-blue-800'}`}>
                      {inv.status}
                    </span>
                  </td>
                  <td className="px-3 py-2">
                    <div className="flex gap-2">
                      <button
                        onClick={() => viewDetail(inv.invoice_id)}
                        className="text-xs text-indigo-600 hover:underline min-h-[36px]"
                      >
                        View
                      </button>
                      <button
                        onClick={() => downloadPdf(inv.invoice_id)}
                        disabled={downloadingPdf === inv.invoice_id}
                        className="text-xs text-gray-600 hover:underline min-h-[36px] disabled:opacity-50"
                      >
                        {downloadingPdf === inv.invoice_id ? '…' : 'PDF'}
                      </button>
                    </div>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      {detailLoading && <div className="text-sm text-gray-500">Loading invoice detail…</div>}
    </div>
  )
}

export function SecurityPage() {
  const { user, logout, refresh } = useFleetSession()
  const [currentPw, setCurrentPw] = useState('')
  const [newPw, setNewPw] = useState('')
  const [confirmPw, setConfirmPw] = useState('')
  const [pwMsg, setPwMsg] = useState<{ type: 'ok' | 'err'; text: string } | null>(null)
  const [submitting, setSubmitting] = useState(false)

  const handleChangePassword = async (e: FormEvent) => {
    e.preventDefault()
    if (newPw.length < 8) { setPwMsg({ type: 'err', text: 'Password must be at least 8 characters.' }); return }
    if (newPw !== confirmPw) { setPwMsg({ type: 'err', text: 'Passwords do not match.' }); return }
    if (newPw === currentPw) { setPwMsg({ type: 'err', text: 'New password must differ from the current password.' }); return }
    setSubmitting(true); setPwMsg(null)
    try {
      await fleetClient.post('/auth/change-password', {
        current_password: currentPw,
        new_password: newPw,
      })
      setPwMsg({ type: 'ok', text: 'Password updated.' })
      setCurrentPw(''); setNewPw(''); setConfirmPw('')
      await refresh()
    } catch (err: unknown) {
      const detail =
        (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail ??
        'Failed to change password.'
      setPwMsg({ type: 'err', text: detail })
    } finally { setSubmitting(false) }
  }

  return (
    <div className="space-y-6">
      <h1 className="text-xl font-semibold">My Security</h1>

      {/* Account info */}
      <div className="rounded-lg border border-gray-200 bg-white p-4 dark:border-gray-800 dark:bg-gray-950">
        <h2 className="text-sm font-medium text-gray-900 dark:text-white mb-2">Account</h2>
        <dl className="grid grid-cols-1 gap-2 sm:grid-cols-2 text-sm">
          <div><dt className="text-xs text-gray-500">Email</dt><dd>{user?.email}</dd></div>
          <div><dt className="text-xs text-gray-500">Name</dt><dd>{[user?.first_name, user?.last_name].filter(Boolean).join(' ') || '—'}</dd></div>
          <div><dt className="text-xs text-gray-500">Role</dt><dd className="capitalize">{user?.portal_user_role?.replace('_', ' ')}</dd></div>
        </dl>
      </div>

      {/* Change password */}
      <div className="rounded-lg border border-gray-200 bg-white p-4 dark:border-gray-800 dark:bg-gray-950">
        <h2 className="text-sm font-medium text-gray-900 dark:text-white mb-3">Change Password</h2>
        {pwMsg && <p className={`text-xs mb-2 ${pwMsg.type === 'ok' ? 'text-green-600' : 'text-red-600'}`}>{pwMsg.text}</p>}
        <form onSubmit={handleChangePassword} className="space-y-3 max-w-sm">
          <input type="password" value={currentPw} onChange={e => setCurrentPw(e.target.value)} placeholder="Current password"
            className="w-full rounded-md border border-gray-300 px-3 py-2 text-sm min-h-[44px] dark:border-gray-700 dark:bg-gray-900 dark:text-white" />
          <input type="password" value={newPw} onChange={e => setNewPw(e.target.value)} placeholder="New password (min 8 chars)"
            className="w-full rounded-md border border-gray-300 px-3 py-2 text-sm min-h-[44px] dark:border-gray-700 dark:bg-gray-900 dark:text-white" />
          <input type="password" value={confirmPw} onChange={e => setConfirmPw(e.target.value)} placeholder="Confirm new password"
            className="w-full rounded-md border border-gray-300 px-3 py-2 text-sm min-h-[44px] dark:border-gray-700 dark:bg-gray-900 dark:text-white" />
          <button type="submit" disabled={submitting}
            className="rounded-md bg-indigo-600 px-4 py-2 text-sm font-medium text-white min-h-[44px] disabled:opacity-50 hover:bg-indigo-700">
            Update Password
          </button>
        </form>
      </div>

      {/* MFA section */}
      <div className="rounded-lg border border-gray-200 bg-white p-4 dark:border-gray-800 dark:bg-gray-950">
        <h2 className="text-sm font-medium text-gray-900 dark:text-white mb-2">Multi-Factor Authentication</h2>
        <p className="text-xs text-gray-500 mb-3">Add an extra layer of security to your account with TOTP authenticator app.</p>
        <MfaSection />
      </div>

      {/* Active session */}
      <div className="rounded-lg border border-gray-200 bg-white p-4 dark:border-gray-800 dark:bg-gray-950">
        <h2 className="text-sm font-medium text-gray-900 dark:text-white mb-2">Active Session</h2>
        <p className="text-xs text-gray-500 mb-3">You are currently signed in. Sign out to end this session.</p>
        <button onClick={() => { void logout() }}
          className="rounded-md border border-red-300 px-3 py-2 text-sm font-medium text-red-700 min-h-[44px] hover:bg-red-50 dark:border-red-800 dark:text-red-400 dark:hover:bg-red-950/20">
          Sign out
        </button>
      </div>

      {/* Check for updates (Req 22.4) */}
      <div className="rounded-lg border border-gray-200 bg-white p-4 dark:border-gray-800 dark:bg-gray-950">
        <h2 className="text-sm font-medium text-gray-900 dark:text-white mb-2">App Version</h2>
        <CheckForUpdatesPanel />
      </div>
    </div>
  )
}

export function ResetPasswordPage() {
  return null // Not used — real ResetPassword.tsx is imported directly
}

export function AcceptInvitePage() {
  return null // Not used — real AcceptInvite.tsx is imported directly
}

/* --- MFA Section --- */

function MfaSection() {
  const [methods, setMethods] = useState<Array<{ id: string; method: string; verified: boolean }>>([])
  const [loading, setLoading] = useState(true)
  const [enrolling, setEnrolling] = useState(false)
  const [totpSecret, setTotpSecret] = useState<string | null>(null)
  const [totpUri, setTotpUri] = useState<string | null>(null)
  const [verifyCode, setVerifyCode] = useState('')
  const [error, setError] = useState<string | null>(null)
  const [success, setSuccess] = useState<string | null>(null)

  const fetchMethods = async () => {
    try {
      const res = await fleetClient.get<Array<{ id: string; method: string; verified: boolean }>>('/auth/mfa/methods')
      setMethods(res.data ?? [])
    } catch {} finally { setLoading(false) }
  }

  useEffect(() => { fetchMethods() }, [])

  const startTotpEnrol = async () => {
    setError(null); setSuccess(null)
    try {
      const res = await fleetClient.post<{ secret: string; provisioning_uri: string }>('/auth/mfa/enroll/totp/start')
      setTotpSecret(res.data?.secret ?? null)
      setTotpUri(res.data?.provisioning_uri ?? null)
      setEnrolling(true)
    } catch (err: unknown) {
      setError((err as { response?: { data?: { detail?: string } } })?.response?.data?.detail ?? 'Failed to start TOTP enrolment.')
    }
  }

  const confirmTotpEnrol = async (e: FormEvent) => {
    e.preventDefault()
    if (!verifyCode || verifyCode.length !== 6) { setError('Enter the 6-digit code from your authenticator app.'); return }
    setError(null)
    try {
      await fleetClient.post('/auth/mfa/enroll/totp/confirm', { code: verifyCode, secret: totpSecret })
      setSuccess('TOTP authenticator enrolled successfully!')
      setEnrolling(false)
      setTotpSecret(null)
      setTotpUri(null)
      setVerifyCode('')
      await fetchMethods()
    } catch (err: unknown) {
      setError((err as { response?: { data?: { detail?: string } } })?.response?.data?.detail ?? 'Invalid code. Please try again.')
    }
  }

  const removeMfa = async (methodId: string) => {
    if (!confirm('Remove this MFA method? You will no longer need it to sign in.')) return
    try {
      await fleetClient.delete(`/auth/mfa/${methodId}`)
      await fetchMethods()
      setSuccess('MFA method removed.')
    } catch {}
  }

  if (loading) return <p className="text-xs text-gray-400">Loading MFA status…</p>

  return (
    <div className="space-y-3">
      {error && <p className="text-xs text-red-600">{error}</p>}
      {success && <p className="text-xs text-green-600">{success}</p>}

      {/* Enrolled methods */}
      {(methods ?? []).length > 0 && (
        <div className="space-y-2">
          {(methods ?? []).map(m => (
            <div key={m.id} className="flex items-center justify-between rounded border border-gray-200 px-3 py-2 dark:border-gray-700">
              <div className="flex items-center gap-2">
                <span className="text-sm font-medium capitalize">{m.method === 'totp' ? '🔐 Authenticator App' : m.method}</span>
                {m.verified && <span className="text-xs bg-green-100 text-green-800 px-1.5 py-0.5 rounded">Active</span>}
              </div>
              <button onClick={() => removeMfa(m.id)} className="text-xs text-red-600 hover:underline min-h-[44px]">Remove</button>
            </div>
          ))}
        </div>
      )}

      {/* Enrol TOTP */}
      {!enrolling && (methods ?? []).filter(m => m.method === 'totp').length === 0 && (
        <button onClick={startTotpEnrol} className="rounded-md bg-indigo-600 px-3 py-2 text-sm font-medium text-white min-h-[44px] hover:bg-indigo-700">
          Set up Authenticator App
        </button>
      )}

      {/* TOTP enrolment flow */}
      {enrolling && totpUri && (
        <div className="rounded-lg border border-indigo-200 bg-indigo-50/50 p-4 dark:border-indigo-900 dark:bg-indigo-950/20 space-y-3">
          <h3 className="text-sm font-medium">Set up Authenticator</h3>
          <p className="text-xs text-gray-600">
            1. Open your authenticator app (Google Authenticator, Authy, etc.)<br />
            2. Scan the QR code or enter the secret key manually<br />
            3. Enter the 6-digit code shown in the app
          </p>

          {/* QR code placeholder — in production this would render a QR image */}
          <div className="rounded border border-gray-300 bg-white p-3 dark:border-gray-700 dark:bg-gray-900">
            <p className="text-xs text-gray-500 mb-1">Secret key (enter manually if you can't scan):</p>
            <code className="text-xs font-mono bg-gray-100 px-2 py-1 rounded break-all dark:bg-gray-800">{totpSecret}</code>
          </div>

          <form onSubmit={confirmTotpEnrol} className="flex gap-2">
            <input type="text" value={verifyCode} onChange={e => setVerifyCode(e.target.value.replace(/\D/g, '').slice(0, 6))}
              placeholder="6-digit code" maxLength={6} inputMode="numeric" autoComplete="one-time-code"
              className="w-32 rounded-md border border-gray-300 px-3 py-2 text-sm text-center tracking-widest min-h-[44px] dark:border-gray-700 dark:bg-gray-900 dark:text-white" />
            <button type="submit" className="rounded-md bg-green-600 px-4 py-2 text-sm font-medium text-white min-h-[44px] hover:bg-green-700">Verify</button>
            <button type="button" onClick={() => { setEnrolling(false); setTotpSecret(null); setTotpUri(null) }}
              className="rounded-md border border-gray-300 px-3 py-2 text-sm min-h-[44px] dark:border-gray-700">Cancel</button>
          </form>
        </div>
      )}

      {(methods ?? []).length === 0 && !enrolling && (
        <p className="text-xs text-gray-400">No MFA methods enrolled. We recommend setting up an authenticator app for added security.</p>
      )}
    </div>
  )
}


/* --- App version check panel --- */

import { useVersionCheck } from '../hooks/useVersionCheck'

function CheckForUpdatesPanel() {
  const { currentVersion, latestVersion, updateAvailable, checkNow } = useVersionCheck()
  const [checking, setChecking] = useState(false)
  const [lastChecked, setLastChecked] = useState<string | null>(null)

  const handleCheck = async () => {
    setChecking(true)
    try {
      await checkNow()
      setLastChecked(new Date().toLocaleTimeString())
    } finally {
      setChecking(false)
    }
  }

  return (
    <div className="space-y-2">
      <p className="text-xs text-gray-500">
        Current build:&nbsp;
        <code className="rounded bg-gray-100 px-1 py-0.5 text-xs dark:bg-gray-800">
          {currentVersion}
        </code>
        {latestVersion && latestVersion !== currentVersion ? (
          <>
            {' '}· Server:&nbsp;
            <code className="rounded bg-gray-100 px-1 py-0.5 text-xs dark:bg-gray-800">
              {latestVersion}
            </code>
          </>
        ) : null}
      </p>
      <div className="flex gap-2">
        <button
          onClick={handleCheck}
          disabled={checking}
          className="rounded-md border border-gray-300 px-3 py-2 text-sm font-medium text-gray-700 min-h-[44px] hover:bg-gray-50 disabled:opacity-50 dark:border-gray-700 dark:text-gray-300 dark:hover:bg-gray-800"
        >
          {checking ? 'Checking…' : 'Check for updates'}
        </button>
        {updateAvailable ? (
          <button
            onClick={() => window.location.reload()}
            className="rounded-md bg-blue-600 px-3 py-2 text-sm font-medium text-white min-h-[44px] hover:bg-blue-700"
          >
            Reload to update
          </button>
        ) : null}
      </div>
      {lastChecked ? (
        <p className="text-xs text-gray-400">Last checked at {lastChecked}</p>
      ) : null}
    </div>
  )
}
