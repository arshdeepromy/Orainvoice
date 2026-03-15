import { useState, useEffect } from 'react'
import { Button } from '@/components/ui/Button'
import { Badge } from '@/components/ui/Badge'
import { Modal } from '@/components/ui/Modal'
import { Spinner } from '@/components/ui/Spinner'
import { AlertBanner } from '@/components/ui/AlertBanner'
import { DataTable, type Column } from '@/components/ui/DataTable'
import { ToastContainer, useToast } from '@/components/ui/Toast'
import apiClient from '@/api/client'

/* ── Types ── */

interface PlanInfo {
  name: string
  monthly_price_nzd: number
  user_seats: number
  storage_quota_gb: number
  carjam_lookups_included: number
  enabled_modules: string[]
}

interface BillingData {
  plan?: PlanInfo
  status: 'trial' | 'active' | 'grace_period' | 'suspended'
  trial_ends_at: string | null
  next_billing_date: string | null
  estimated_next_invoice?: {
    plan_fee: number
    storage_addons: number
    carjam_overage: number
    total: number
  }
  storage?: {
    used_bytes: number
    quota_gb: number
    avg_invoice_bytes: number
  }
  carjam?: {
    lookups_this_month: number
    included: number
  }
  storage_addon_price_per_gb?: number
}

interface PastInvoice {
  id: string
  date: string
  amount: number
  status: string
  pdf_url: string
  [key: string]: unknown
}

/* ── Helpers ── */

function formatNZD(amount: number): string {
  return new Intl.NumberFormat('en-NZ', { style: 'currency', currency: 'NZD' }).format(amount)
}

function formatDate(iso: string | null): string {
  if (!iso) return '—'
  return new Date(iso).toLocaleDateString('en-NZ', { day: 'numeric', month: 'long', year: 'numeric' })
}

function formatBytes(bytes: number): string {
  if (bytes === 0) return '0 MB'
  const gb = bytes / (1024 * 1024 * 1024)
  if (gb >= 1) return `${gb.toFixed(2)} GB`
  const mb = bytes / (1024 * 1024)
  return `${mb.toFixed(1)} MB`
}

function daysUntil(dateStr: string): number {
  const target = new Date(dateStr)
  const now = new Date()
  return Math.max(0, Math.ceil((target.getTime() - now.getTime()) / (1000 * 60 * 60 * 24)))
}

function storagePercentage(usedBytes: number, quotaGb: number): number {
  if (quotaGb <= 0) return 0
  const quotaBytes = quotaGb * 1024 * 1024 * 1024
  return Math.min(100, Math.round((usedBytes / quotaBytes) * 100))
}

function storageBarColour(pct: number): string {
  if (pct >= 90) return 'bg-red-500'
  if (pct >= 80) return 'bg-amber-500'
  return 'bg-blue-500'
}

/* ── Trial Countdown ── */

function TrialCountdown({ trialEndsAt }: { trialEndsAt: string }) {
  const days = daysUntil(trialEndsAt)
  const variant = days <= 3 ? 'warning' : 'info'

  return (
    <AlertBanner variant={variant} title="Free trial">
      {days === 0
        ? 'Your trial ends today. Your card will be charged when the trial ends.'
        : days === 1
          ? 'Your trial ends tomorrow. Your card will be charged when the trial ends.'
          : `You have ${days} days left in your free trial (ends ${formatDate(trialEndsAt)}). Your card will be charged when the trial ends.`}
    </AlertBanner>
  )
}

/* ── Current Plan Card ── */

function CurrentPlanCard({ plan, status }: { plan: PlanInfo | undefined; status: string }) {
  if (!plan) {
    return (
      <div className="rounded-lg border border-gray-200 p-5">
        <h3 className="text-lg font-semibold text-gray-900 mb-3">Your plan</h3>
        <p className="text-sm text-gray-500">Plan information not available</p>
      </div>
    )
  }

  const statusBadge: Record<string, { variant: 'success' | 'warning' | 'error' | 'info'; label: string }> = {
    trial: { variant: 'info', label: 'Trial' },
    active: { variant: 'success', label: 'Active' },
    grace_period: { variant: 'warning', label: 'Grace Period' },
    suspended: { variant: 'error', label: 'Suspended' },
  }
  const badge = statusBadge[status] ?? { variant: 'neutral' as const, label: status }

  return (
    <div className="rounded-lg border border-gray-200 p-5">
      <div className="flex items-center justify-between mb-3">
        <h3 className="text-lg font-semibold text-gray-900">Your plan</h3>
        <Badge variant={badge.variant}>{badge.label}</Badge>
      </div>
      <p className="text-2xl font-bold text-gray-900">{plan.name}</p>
      <p className="text-gray-600 mt-1">{formatNZD(plan.monthly_price_nzd)} / month</p>
      <ul className="mt-3 space-y-1 text-sm text-gray-600">
        <li>Up to {plan.user_seats} users</li>
        <li>{plan.storage_quota_gb} GB storage</li>
        <li>{plan.carjam_lookups_included} Carjam lookups / month</li>
      </ul>
    </div>
  )
}

/* ── Next Bill Estimate ── */

function NextBillEstimate({
  nextBillingDate,
  estimate,
}: {
  nextBillingDate: string | null
  estimate: BillingData['estimated_next_invoice']
}) {
  if (!estimate) {
    return (
      <div className="rounded-lg border border-gray-200 p-5">
        <h3 className="text-lg font-semibold text-gray-900 mb-3">Your next bill</h3>
        <p className="text-sm text-gray-500">Billing estimate not available</p>
      </div>
    )
  }

  return (
    <div className="rounded-lg border border-gray-200 p-5">
      <h3 className="text-lg font-semibold text-gray-900 mb-3">Your next bill</h3>
      {nextBillingDate && (
        <p className="text-sm text-gray-600 mb-3">Due on {formatDate(nextBillingDate)}</p>
      )}
      <div className="space-y-2 text-sm">
        <div className="flex justify-between">
          <span className="text-gray-600">Plan fee</span>
          <span className="text-gray-900 font-medium">{formatNZD(estimate.plan_fee)}</span>
        </div>
        {estimate.storage_addons > 0 && (
          <div className="flex justify-between">
            <span className="text-gray-600">Extra storage</span>
            <span className="text-gray-900 font-medium">{formatNZD(estimate.storage_addons)}</span>
          </div>
        )}
        {estimate.carjam_overage > 0 && (
          <div className="flex justify-between">
            <span className="text-gray-600">Carjam overage</span>
            <span className="text-gray-900 font-medium">{formatNZD(estimate.carjam_overage)}</span>
          </div>
        )}
        <hr className="border-gray-200" />
        <div className="flex justify-between font-semibold">
          <span className="text-gray-900">Estimated total</span>
          <span className="text-gray-900">{formatNZD(estimate.total)}</span>
        </div>
      </div>
    </div>
  )
}

/* ── Storage Usage ── */

function StorageUsage({
  usedBytes,
  quotaGb,
  avgInvoiceBytes,
  onPurchaseAddon,
}: {
  usedBytes: number
  quotaGb: number
  avgInvoiceBytes: number
  onPurchaseAddon: () => void
}) {
  const pct = storagePercentage(usedBytes, quotaGb)
  const barColour = storageBarColour(pct)
  const remainingBytes = Math.max(0, quotaGb * 1024 * 1024 * 1024 - usedBytes)
  const estimatedInvoicesRemaining =
    avgInvoiceBytes > 0 ? Math.floor(remainingBytes / avgInvoiceBytes) : null

  return (
    <div className="rounded-lg border border-gray-200 p-5">
      <div className="flex items-center justify-between mb-3">
        <h3 className="text-lg font-semibold text-gray-900">Storage</h3>
        <Button size="sm" variant="secondary" disabled title="Requires Stripe billing integration">
          Buy more storage
        </Button>
      </div>
      <div className="flex items-baseline gap-2 mb-2">
        <span className="text-2xl font-bold text-gray-900">{formatBytes(usedBytes)}</span>
        <span className="text-sm text-gray-500">of {quotaGb} GB used</span>
      </div>
      <div
        className="w-full h-3 bg-gray-200 rounded-full overflow-hidden"
        role="progressbar"
        aria-valuenow={pct}
        aria-valuemin={0}
        aria-valuemax={100}
        aria-label={`Storage usage: ${pct}%`}
      >
        <div className={`h-full rounded-full transition-all ${barColour}`} style={{ width: `${pct}%` }} />
      </div>
      <p className="text-xs text-gray-500 mt-1">{pct}% used</p>
      {estimatedInvoicesRemaining !== null && (
        <p className="text-xs text-gray-500 mt-1">
          Roughly {estimatedInvoicesRemaining.toLocaleString('en-NZ')} invoices worth of space remaining
        </p>
      )}
      {pct >= 90 && (
        <p className="text-xs text-red-600 mt-1 font-medium">
          You're almost out of storage. Buy more to keep creating invoices.
        </p>
      )}
      {pct >= 80 && pct < 90 && (
        <p className="text-xs text-amber-600 mt-1 font-medium">
          Storage is getting full. Consider buying more soon.
        </p>
      )}
    </div>
  )
}

/* ── Carjam Usage ── */

function CarjamUsage({ lookups, included }: { lookups: number; included: number }) {
  const overage = Math.max(0, lookups - included)

  return (
    <div className="rounded-lg border border-gray-200 p-5">
      <h3 className="text-lg font-semibold text-gray-900 mb-3">Carjam lookups this month</h3>
      <div className="flex items-baseline gap-2">
        <span className="text-2xl font-bold text-gray-900">{lookups}</span>
        <span className="text-sm text-gray-500">of {included} included</span>
      </div>
      {overage > 0 && (
        <p className="text-sm text-amber-600 mt-2 font-medium">
          {overage} extra {overage === 1 ? 'lookup' : 'lookups'} — overage charges will appear on your next bill.
        </p>
      )}
    </div>
  )
}

/* ── Past Invoices ── */

function PastInvoices({ invoices }: { invoices: PastInvoice[] }) {
  const columns: Column<PastInvoice>[] = [
    {
      key: 'date',
      header: 'Date',
      sortable: true,
      render: (row) => formatDate(row.date),
    },
    {
      key: 'amount',
      header: 'Amount',
      sortable: true,
      render: (row) => formatNZD(row.amount),
    },
    {
      key: 'status',
      header: 'Status',
      render: (row) => {
        const variant = row.status === 'paid' ? 'success' : row.status === 'open' ? 'info' : 'neutral'
        return <Badge variant={variant}>{row.status}</Badge>
      },
    },
    {
      key: 'pdf_url',
      header: 'Receipt',
      render: (row) =>
        row.pdf_url ? (
          <a
            href={row.pdf_url}
            target="_blank"
            rel="noopener noreferrer"
            className="text-blue-600 hover:underline text-sm"
          >
            Download PDF
          </a>
        ) : (
          <span className="text-gray-400 text-sm">—</span>
        ),
    },
  ]

  return (
    <div>
      <h3 className="text-lg font-semibold text-gray-900 mb-3">Past invoices</h3>
      <DataTable columns={columns} data={invoices} keyField="id" caption="Past subscription invoices" />
    </div>
  )
}

/* ── Storage Add-on Modal ── */

function StorageAddonModal({
  open,
  onClose,
  pricePerGb,
  onConfirm,
  purchasing,
}: {
  open: boolean
  onClose: () => void
  pricePerGb: number | undefined
  onConfirm: (gb: number) => void
  purchasing: boolean
}) {
  const [gb, setGb] = useState(1)
  const price = pricePerGb || 0

  return (
    <Modal open={open} onClose={onClose} title="Buy more storage">
      <div className="space-y-4">
        <p className="text-sm text-gray-600">
          Extra storage costs {formatNZD(price)} per GB per month, added to your next bill.
        </p>
        <div className="flex items-center gap-3">
          <label htmlFor="storage-gb" className="text-sm font-medium text-gray-700">
            How much?
          </label>
          <select
            id="storage-gb"
            value={gb}
            onChange={(e) => setGb(Number(e.target.value))}
            className="rounded-md border border-gray-300 px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
          >
            {[1, 2, 5, 10, 20].map((v) => (
              <option key={v} value={v}>
                {v} GB
              </option>
            ))}
          </select>
        </div>
        <div className="rounded-md bg-gray-50 p-3 text-sm">
          <div className="flex justify-between">
            <span className="text-gray-600">{gb} GB × {formatNZD(price)}</span>
            <span className="font-medium text-gray-900">{formatNZD(gb * price)} / month</span>
          </div>
          <p className="text-xs text-gray-500 mt-1">
            Your card will be charged immediately and the add-on will appear on future bills.
          </p>
        </div>
        <div className="flex justify-end gap-2 pt-2">
          <Button variant="secondary" onClick={onClose}>Cancel</Button>
          <Button onClick={() => onConfirm(gb)} loading={purchasing}>
            Confirm purchase
          </Button>
        </div>
      </div>
    </Modal>
  )
}

/* ── Main Billing Page ── */

export function Billing() {
  const [billing, setBilling] = useState<BillingData | null>(null)
  const [invoices, setInvoices] = useState<PastInvoice[]>([])
  const [loading, setLoading] = useState(true)
  const { toasts, addToast, dismissToast } = useToast()

  const fetchBilling = async () => {
    setLoading(true)
    try {
      const [billingRes, invoicesRes] = await Promise.all([
        apiClient.get('/billing'),
        apiClient.get('/billing/invoices'),
      ])
      setBilling(billingRes.data)
      // Handle both array and wrapped response formats
      const invoiceData = Array.isArray(invoicesRes.data) ? invoicesRes.data : (invoicesRes.data?.invoices || [])
      setInvoices(invoiceData)
    } catch {
      addToast('error', 'Failed to load billing information')
      setInvoices([])
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => { fetchBilling() }, [])

  if (loading) {
    return (
      <div className="flex items-center justify-center py-20">
        <Spinner label="Loading billing information" />
      </div>
    )
  }

  if (!billing) {
    return (
      <AlertBanner variant="error" title="Something went wrong">
        We couldn't load your billing information. Please refresh the page or try again later.
      </AlertBanner>
    )
  }

  return (
    <div>
      <h1 className="text-2xl font-semibold text-gray-900 mb-6">Billing</h1>
      <ToastContainer toasts={toasts} onDismiss={dismissToast} />

      <div className="space-y-6 max-w-3xl">
        {/* Trial countdown */}
        {billing.status === 'trial' && billing.trial_ends_at && (
          <TrialCountdown trialEndsAt={billing.trial_ends_at} />
        )}

        {/* Grace period warning */}
        {billing.status === 'grace_period' && (
          <AlertBanner variant="warning" title="Payment overdue">
            Your payment is overdue. Please update your payment method to avoid losing access.
          </AlertBanner>
        )}

        {/* Plan + Next bill side by side on larger screens */}
        <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
          <CurrentPlanCard plan={billing.plan} status={billing.status} />
          <NextBillEstimate
            nextBillingDate={billing.next_billing_date}
            estimate={billing.estimated_next_invoice}
          />
        </div>

        {/* Usage cards */}
        <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
          {billing.storage && (
            <StorageUsage
              usedBytes={billing.storage.used_bytes}
              quotaGb={billing.storage.quota_gb}
              avgInvoiceBytes={billing.storage.avg_invoice_bytes}
              onPurchaseAddon={() => setAddonOpen(true)}
            />
          )}
          {billing.carjam && (
            <CarjamUsage
              lookups={billing.carjam.lookups_this_month}
              included={billing.carjam.included}
            />
          )}
        </div>

        {/* Actions */}
        <div className="flex flex-wrap gap-3">
          <Button variant="secondary" disabled title="Stripe integration coming soon — payment method management will be available once Stripe is connected">
            Update payment method
          </Button>
          <Button disabled title="Plan upgrades coming soon — requires Stripe billing integration">
            Upgrade plan
          </Button>
          <Button variant="secondary" disabled title="Plan downgrades coming soon — requires Stripe billing integration">
            Downgrade plan
          </Button>
        </div>
        <p className="text-xs text-gray-500 mt-1">
          Payment method and plan management will be available once Stripe billing integration is complete.
        </p>

        {/* Past invoices */}
        <PastInvoices invoices={invoices} />
      </div>
    </div>
  )
}
