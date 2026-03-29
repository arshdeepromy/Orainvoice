import { useState, useEffect } from 'react'
import { loadStripe, type Stripe } from '@stripe/stripe-js'
import { Elements } from '@stripe/react-stripe-js'
import { Button } from '@/components/ui/Button'
import { Badge } from '@/components/ui/Badge'
import { Modal } from '@/components/ui/Modal'
import { Spinner } from '@/components/ui/Spinner'
import { AlertBanner } from '@/components/ui/AlertBanner'
import { DataTable, type Column } from '@/components/ui/DataTable'
import { ToastContainer, useToast } from '@/components/ui/Toast'
import { PaymentMethodManager } from '@/components/billing/PaymentMethodManager'
import { CardForm } from '@/components/billing/CardForm'
import apiClient from '@/api/client'

/* ── Types ── */

interface PlanInfo {
  name: string
  monthly_price_nzd: number
  user_seats: number
  storage_quota_gb: number
  carjam_lookups_included: number
  enabled_modules: string[]
  sms_included: boolean
  sms_included_quota: number
  per_sms_cost_nzd: number
}

interface CouponInfo {
  code: string
  discount_type: string
  discount_value: number
  duration_months: number | null
  effective_price_nzd: number
  is_expired: boolean
}

interface BillingData {
  plan?: PlanInfo
  coupon?: CouponInfo | null
  status: 'trial' | 'active' | 'grace_period' | 'suspended'
  trial_ends_at: string | null
  next_billing_date: string | null
  estimated_next_invoice?: {
    plan_fee: number
    storage_addons: number
    carjam_overage: number
    sms_overage: number
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
  storage_addon_gb?: number | null
  storage_addon_price_nzd?: number | null
  storage_addon_package_name?: string | null
  sms?: {
    sent_this_month: number
    included_quota: number
    credits_remaining: number
    per_sms_cost_nzd: number
    overage_charge_nzd: number
    sms_included: boolean
  }
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

function CurrentPlanCard({ plan, status, coupon }: { plan: PlanInfo | undefined; status: string; coupon?: CouponInfo | null }) {
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
      {coupon && !coupon.is_expired ? (
        <div className="mt-1">
          <p className="text-gray-400 line-through text-sm">{formatNZD(plan.monthly_price_nzd)} / month</p>
          <p className="text-green-700 font-semibold">{formatNZD(coupon.effective_price_nzd)} / month</p>
          <span className="inline-flex items-center gap-1 mt-1 rounded-full bg-green-100 px-2.5 py-0.5 text-xs font-medium text-green-800">
            Coupon: {coupon.code} — {coupon.discount_type === 'percentage' ? `${coupon.discount_value}% off` : coupon.discount_type === 'fixed_amount' ? `${formatNZD(coupon.discount_value)} off` : 'Trial extension'}
            {coupon.duration_months ? ` (${coupon.duration_months} months)` : ' (perpetual)'}
          </span>
        </div>
      ) : (
        <p className="text-gray-600 mt-1">{formatNZD(plan.monthly_price_nzd)} / month</p>
      )}
      <ul className="mt-3 space-y-1 text-sm text-gray-600">
        <li>Up to {plan.user_seats} users</li>
        <li>{plan.storage_quota_gb} GB storage</li>
        <li>{plan.carjam_lookups_included} Carjam lookups / month</li>
        {plan.sms_included && (
          <li>{plan.sms_included_quota > 0 ? `${plan.sms_included_quota} SMS / month` : 'SMS included (pay per use)'}</li>
        )}
      </ul>
    </div>
  )
}

/* ── Next Bill Estimate ── */

function NextBillEstimate({
  nextBillingDate,
  estimate,
  coupon,
  addonGb,
  addonPriceNzd,
}: {
  nextBillingDate: string | null
  estimate: BillingData['estimated_next_invoice']
  coupon?: CouponInfo | null
  addonGb?: number | null
  addonPriceNzd?: number | null
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
          {coupon && !coupon.is_expired ? (
            <span className="text-green-700 font-medium">{formatNZD(coupon.effective_price_nzd)}</span>
          ) : (
            <span className="text-gray-900 font-medium">{formatNZD(estimate.plan_fee)}</span>
          )}
        </div>
        {addonGb != null && addonGb > 0 && addonPriceNzd != null && (
          <div className="flex justify-between">
            <span className="text-gray-600">Storage add-on ({addonGb} GB)</span>
            <span className="text-gray-900 font-medium">{formatNZD(addonPriceNzd)}</span>
          </div>
        )}
        {(!addonGb || !addonPriceNzd) && estimate.storage_addons > 0 && (
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
        {estimate.sms_overage > 0 && (
          <div className="flex justify-between">
            <span className="text-gray-600">SMS overage</span>
            <span className="text-gray-900 font-medium">{formatNZD(estimate.sms_overage)}</span>
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
  addonGb,
  addonPriceNzd,
  addonPackageName,
}: {
  usedBytes: number
  quotaGb: number
  avgInvoiceBytes: number
  onPurchaseAddon: () => void
  addonGb?: number | null
  addonPriceNzd?: number | null
  addonPackageName?: string | null
}) {
  const pct = storagePercentage(usedBytes, quotaGb)
  const barColour = storageBarColour(pct)
  const remainingBytes = Math.max(0, quotaGb * 1024 * 1024 * 1024 - usedBytes)
  const estimatedInvoicesRemaining =
    avgInvoiceBytes > 0 ? Math.floor(remainingBytes / avgInvoiceBytes) : null
  const baseQuotaGb = addonGb ? quotaGb - addonGb : quotaGb

  return (
    <div className="rounded-lg border border-gray-200 p-5">
      <div className="flex items-center justify-between mb-3">
        <h3 className="text-lg font-semibold text-gray-900">Storage</h3>
        <Button size="sm" variant="secondary" onClick={onPurchaseAddon}>
          Manage storage
        </Button>
      </div>
      <div className="flex items-baseline gap-2 mb-2">
        <span className="text-2xl font-bold text-gray-900">{formatBytes(usedBytes)}</span>
        <span className="text-sm text-gray-500">
          of {addonGb ? `${quotaGb} GB used (${baseQuotaGb} GB plan + ${addonGb} GB add-on)` : `${quotaGb} GB used`}
        </span>
      </div>
      {addonGb != null && addonGb > 0 && (
        <p className="text-xs text-gray-600 mb-2">
          {addonPackageName ?? 'Custom'} add-on — {formatNZD(addonPriceNzd ?? 0)}/month
        </p>
      )}
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

/* ── SMS Usage ── */

function SmsUsageCard({
  sentThisMonth,
  includedQuota,
  creditsRemaining,
  perSmsCost,
  smsIncluded,
}: {
  sentThisMonth: number
  includedQuota: number
  creditsRemaining: number
  perSmsCost: number
  smsIncluded: boolean
}) {
  if (!smsIncluded) {
    return (
      <div className="rounded-lg border border-gray-200 p-5">
        <h3 className="text-lg font-semibold text-gray-900 mb-3">SMS usage this month</h3>
        <p className="text-sm text-gray-500">SMS is not included in your current plan.</p>
      </div>
    )
  }

  const beyondIncluded = Math.max(0, sentThisMonth - includedQuota)
  const beyondCredits = Math.max(0, beyondIncluded - creditsRemaining)

  return (
    <div className="rounded-lg border border-gray-200 p-5">
      <h3 className="text-lg font-semibold text-gray-900 mb-3">SMS usage this month</h3>
      <div className="flex items-baseline gap-2">
        <span className="text-2xl font-bold text-gray-900">{sentThisMonth}</span>
        <span className="text-sm text-gray-500">of {includedQuota} included</span>
      </div>
      {creditsRemaining > 0 && (
        <p className="text-sm text-gray-600 mt-2">
          {creditsRemaining} prepaid credits remaining
        </p>
      )}
      {beyondCredits > 0 && (
        <p className="text-sm text-amber-600 mt-2 font-medium">
          {beyondCredits} overage {beyondCredits === 1 ? 'message' : 'messages'} at {formatNZD(perSmsCost)} each — charges will appear on your next bill.
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

/* ── Storage Manage Modal ── */

interface StoragePackageOption {
  id: string
  name: string
  storage_gb: number
  price_nzd_per_month: number
  description: string | null
  is_active: boolean
  sort_order: number
}

interface StorageAddonInfo {
  id: string
  package_name: string | null
  quantity_gb: number
  price_nzd_per_month: number
  is_custom: boolean
  purchased_at: string
}

interface StorageAddonStatus {
  current_addon: StorageAddonInfo | null
  available_packages: StoragePackageOption[]
  fallback_price_per_gb_nzd: number
  base_quota_gb: number
  total_quota_gb: number
  storage_used_gb: number
}

type ModalStep = 'select' | 'confirm' | 'remove-confirm'
type ModalAction = 'purchase' | 'resize' | 'remove'

function StorageManageModal({
  open,
  onClose,
  onComplete,
  addToast,
}: {
  open: boolean
  onClose: () => void
  onComplete: () => void
  addToast: (variant: 'success' | 'error' | 'warning' | 'info', message: string) => void
}) {
  const [status, setStatus] = useState<StorageAddonStatus | null>(null)
  const [loading, setLoading] = useState(false)
  const [submitting, setSubmitting] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [step, setStep] = useState<ModalStep>('select')
  const [selectedPackageId, setSelectedPackageId] = useState<string | null>(null)
  const [customGb, setCustomGb] = useState<string>('')
  const [useCustom, setUseCustom] = useState(false)

  const fetchStatus = async () => {
    setLoading(true)
    setError(null)
    try {
      const res = await apiClient.get('/billing/storage-addon')
      setStatus(res.data)
    } catch {
      setError('Failed to load storage options')
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    if (open) {
      fetchStatus()
      setStep('select')
      setSelectedPackageId(null)
      setCustomGb('')
      setUseCustom(false)
    }
  }, [open])

  const selectedPackage = status?.available_packages.find((p) => p.id === selectedPackageId) ?? null
  const customGbNum = parseInt(customGb, 10)
  const validCustomGb = useCustom && !isNaN(customGbNum) && customGbNum > 0
  const customPrice = validCustomGb ? customGbNum * (status?.fallback_price_per_gb_nzd ?? 0) : 0

  const hasSelection = selectedPackageId != null || validCustomGb
  const selectedGb = useCustom ? (validCustomGb ? customGbNum : 0) : (selectedPackage?.storage_gb ?? 0)
  const selectedPrice = useCustom ? customPrice : (selectedPackage?.price_nzd_per_month ?? 0)
  const selectedLabel = useCustom ? `Custom (${selectedGb} GB)` : (selectedPackage?.name ?? '')

  const action: ModalAction = status?.current_addon ? 'resize' : 'purchase'
  const newTotalQuota = (status?.base_quota_gb ?? 0) + selectedGb

  const handleConfirm = async () => {
    if (!status) return
    setSubmitting(true)
    setError(null)
    try {
      const body = useCustom ? { custom_gb: customGbNum } : { package_id: selectedPackageId }
      if (action === 'purchase') {
        await apiClient.post('/billing/storage-addon', body)
        addToast('success', `Purchased ${selectedGb} GB storage add-on`)
      } else {
        await apiClient.put('/billing/storage-addon', body)
        addToast('success', `Resized storage add-on to ${selectedGb} GB`)
      }
      onComplete()
      onClose()
    } catch (err: unknown) {
      const msg = (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail ?? 'Operation failed'
      setError(msg)
    } finally {
      setSubmitting(false)
    }
  }

  const handleRemove = async () => {
    setSubmitting(true)
    setError(null)
    try {
      await apiClient.delete('/billing/storage-addon')
      addToast('success', 'Storage add-on removed')
      onComplete()
      onClose()
    } catch (err: unknown) {
      const msg = (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail ?? 'Failed to remove add-on'
      setError(msg)
    } finally {
      setSubmitting(false)
    }
  }

  const title = step === 'remove-confirm'
    ? 'Remove storage add-on'
    : step === 'confirm'
      ? (action === 'purchase' ? 'Confirm purchase' : 'Confirm resize')
      : 'Manage storage'

  return (
    <Modal open={open} onClose={onClose} title={title} className="max-w-2xl">
      <div className="space-y-4">
        {loading && (
          <div className="flex justify-center py-8">
            <Spinner label="Loading storage options" />
          </div>
        )}

        {error && <AlertBanner variant="error" title="Error">{error}</AlertBanner>}

        {!loading && status && step === 'select' && (
          <>
            {/* Current add-on info */}
            {status.current_addon && (
              <div className="rounded-md bg-blue-50 p-4 mb-4">
                <p className="text-sm font-medium text-blue-900">Current add-on</p>
                <p className="text-sm text-blue-800 mt-1">
                  {status.current_addon.package_name ?? 'Custom'} — {status.current_addon.quantity_gb} GB at {formatNZD(status.current_addon.price_nzd_per_month)}/month
                </p>
              </div>
            )}

            {/* Package cards */}
            <p className="text-sm text-gray-600">
              {status.current_addon ? 'Select a new package to resize your add-on:' : 'Select a storage package:'}
            </p>
            <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
              {status.available_packages.map((pkg) => (
                <button
                  key={pkg.id}
                  onClick={() => { setSelectedPackageId(pkg.id); setUseCustom(false) }}
                  className={`rounded-lg border-2 p-4 text-left transition-colors ${
                    selectedPackageId === pkg.id && !useCustom
                      ? 'border-blue-500 bg-blue-50'
                      : 'border-gray-200 hover:border-gray-300'
                  }`}
                >
                  <p className="font-semibold text-gray-900">{pkg.name}</p>
                  <p className="text-sm text-gray-600 mt-1">{pkg.storage_gb} GB</p>
                  <p className="text-sm font-medium text-gray-900 mt-1">{formatNZD(pkg.price_nzd_per_month)}/month</p>
                  {pkg.description && <p className="text-xs text-gray-500 mt-1">{pkg.description}</p>}
                </button>
              ))}
            </div>

            {/* Custom option */}
            <div
              className={`rounded-lg border-2 p-4 transition-colors ${
                useCustom ? 'border-blue-500 bg-blue-50' : 'border-gray-200'
              }`}
            >
              <button
                onClick={() => { setUseCustom(true); setSelectedPackageId(null) }}
                className="w-full text-left"
              >
                <p className="font-semibold text-gray-900">Custom amount</p>
                <p className="text-xs text-gray-500">
                  {formatNZD(status.fallback_price_per_gb_nzd)} per GB/month
                </p>
              </button>
              {useCustom && (
                <div className="mt-3 flex items-center gap-3">
                  <label htmlFor="custom-gb-input" className="text-sm font-medium text-gray-700">GB:</label>
                  <input
                    id="custom-gb-input"
                    type="number"
                    min="1"
                    value={customGb}
                    onChange={(e) => setCustomGb(e.target.value)}
                    className="w-24 rounded-md border border-gray-300 px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
                    placeholder="e.g. 15"
                  />
                  {validCustomGb && (
                    <span className="text-sm text-gray-700">{formatNZD(customPrice)}/month</span>
                  )}
                </div>
              )}
            </div>

            {/* Actions */}
            <div className="flex justify-between items-center pt-2">
              <div>
                {status.current_addon && (
                  <Button variant="danger" size="sm" onClick={() => setStep('remove-confirm')}>
                    Remove add-on
                  </Button>
                )}
              </div>
              <div className="flex gap-2">
                <Button variant="secondary" onClick={onClose}>Cancel</Button>
                <Button disabled={!hasSelection} onClick={() => setStep('confirm')}>
                  {status.current_addon ? 'Review resize' : 'Review purchase'}
                </Button>
              </div>
            </div>
          </>
        )}

        {/* Confirmation step */}
        {!loading && status && step === 'confirm' && (
          <>
            <div className="rounded-md bg-gray-50 p-4 space-y-2 text-sm">
              <div className="flex justify-between">
                <span className="text-gray-600">Package</span>
                <span className="font-medium text-gray-900">{selectedLabel}</span>
              </div>
              <div className="flex justify-between">
                <span className="text-gray-600">Storage</span>
                <span className="font-medium text-gray-900">{selectedGb} GB</span>
              </div>
              <div className="flex justify-between">
                <span className="text-gray-600">Monthly charge</span>
                <span className="font-medium text-gray-900">{formatNZD(selectedPrice)}</span>
              </div>
              <hr className="border-gray-200" />
              <div className="flex justify-between">
                <span className="text-gray-600">New total quota</span>
                <span className="font-medium text-gray-900">{newTotalQuota} GB</span>
              </div>
              {status.current_addon && (
                <div className="flex justify-between">
                  <span className="text-gray-600">Previous charge</span>
                  <span className="text-gray-500 line-through">{formatNZD(status.current_addon.price_nzd_per_month)}</span>
                </div>
              )}
            </div>
            {status.current_addon && selectedGb < status.current_addon.quantity_gb && status.storage_used_gb > newTotalQuota && (
              <AlertBanner variant="warning" title="Usage exceeds new quota">
                Current usage ({status.storage_used_gb.toFixed(2)} GB) exceeds the new total quota ({newTotalQuota} GB). Free up space before downgrading.
              </AlertBanner>
            )}
            <div className="flex justify-end gap-2 pt-2">
              <Button variant="secondary" onClick={() => setStep('select')}>Back</Button>
              <Button onClick={handleConfirm} loading={submitting}>
                {action === 'purchase' ? 'Confirm purchase' : 'Confirm resize'}
              </Button>
            </div>
          </>
        )}

        {/* Remove confirmation step */}
        {!loading && status && step === 'remove-confirm' && (
          <>
            <p className="text-sm text-gray-600">
              This will remove your storage add-on and revert to your plan's base quota of {status.base_quota_gb} GB.
            </p>
            {status.storage_used_gb > status.base_quota_gb && (
              <AlertBanner variant="warning" title="Usage exceeds base quota">
                Current usage ({status.storage_used_gb.toFixed(2)} GB) exceeds the base quota ({status.base_quota_gb} GB). Free up space before removing the add-on.
              </AlertBanner>
            )}
            <div className="flex justify-end gap-2 pt-2">
              <Button variant="secondary" onClick={() => setStep('select')}>Back</Button>
              <Button
                variant="danger"
                onClick={handleRemove}
                loading={submitting}
                disabled={status.storage_used_gb > status.base_quota_gb}
              >
                Remove add-on
              </Button>
            </div>
          </>
        )}
      </div>
    </Modal>
  )
}

/* ── Plan Change Modal ── */

interface AvailablePlan {
  id: string
  name: string
  monthly_price_nzd: number | string
  user_seats: number
  storage_quota_gb: number
  carjam_lookups_included: number
  trial_duration: number
}

function PlanChangeModal({
  open,
  onClose,
  onComplete,
  addToast,
  currentPlanName,
  currentPriceNzd,
}: {
  open: boolean
  onClose: () => void
  onComplete: () => void
  addToast: (type: 'success' | 'error' | 'info', msg: string) => void
  currentPlanName: string
  currentPriceNzd: number
}) {
  const [plans, setPlans] = useState<AvailablePlan[]>([])
  const [loading, setLoading] = useState(true)
  const [selectedPlanId, setSelectedPlanId] = useState<string | null>(null)
  const [submitting, setSubmitting] = useState(false)
  const [result, setResult] = useState<{ success: boolean; message: string; warnings?: string[] } | null>(null)

  useEffect(() => {
    if (!open) return
    setResult(null)
    setSelectedPlanId(null)
    setLoading(true)
    apiClient.get<{ plans: AvailablePlan[] }>('/auth/plans')
      .then(res => setPlans(res.data?.plans ?? []))
      .catch(() => addToast('error', 'Failed to load available plans'))
      .finally(() => setLoading(false))
  }, [open, addToast])

  const selectedPlan = plans.find(p => p.id === selectedPlanId)
  const selectedPrice = selectedPlan ? Number(selectedPlan.monthly_price_nzd) : 0
  const isUpgrade = selectedPrice > currentPriceNzd
  const isDowngrade = selectedPrice < currentPriceNzd

  async function handleConfirm() {
    if (!selectedPlanId) return
    setSubmitting(true)
    setResult(null)
    try {
      const endpoint = isUpgrade ? '/billing/upgrade' : '/billing/downgrade'
      const res = await apiClient.post<{ success: boolean; message: string; warnings?: string[] }>(
        endpoint,
        { new_plan_id: selectedPlanId },
      )
      setResult(res.data)
      if (res.data.success) {
        addToast('success', res.data.message)
        onComplete()
      }
    } catch (err: unknown) {
      const detail = (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail
      setResult({ success: false, message: detail ?? 'Failed to change plan' })
    } finally {
      setSubmitting(false)
    }
  }

  return (
    <Modal open={open} onClose={onClose} title="Change plan" className="max-w-lg">
      <div className="space-y-4">
        {loading ? (
          <div className="flex justify-center py-8"><Spinner label="Loading plans..." /></div>
        ) : (
          <>
            <p className="text-sm text-gray-600">
              Current plan: <span className="font-semibold">{currentPlanName}</span> ({formatNZD(currentPriceNzd)}/mo)
            </p>
            <div className="space-y-2 max-h-64 overflow-y-auto">
              {plans
                .filter(p => p.name !== currentPlanName)
                .map(plan => {
                  const price = Number(plan.monthly_price_nzd)
                  const up = price > currentPriceNzd
                  return (
                    <label
                      key={plan.id}
                      className={`flex items-center justify-between rounded-md border p-3 cursor-pointer transition-colors ${
                        selectedPlanId === plan.id ? 'border-blue-500 bg-blue-50' : 'border-gray-200 hover:border-gray-300'
                      }`}
                    >
                      <div className="flex items-center gap-3">
                        <input
                          type="radio"
                          name="change_plan"
                          value={plan.id}
                          checked={selectedPlanId === plan.id}
                          onChange={() => setSelectedPlanId(plan.id)}
                          className="h-4 w-4 text-blue-600"
                        />
                        <div>
                          <span className="font-medium text-gray-900">{plan.name}</span>
                          <span className={`ml-2 text-xs font-medium ${up ? 'text-green-600' : 'text-amber-600'}`}>
                            {up ? 'Upgrade' : 'Downgrade'}
                          </span>
                          <div className="text-xs text-gray-500">
                            {plan.user_seats} seats · {plan.storage_quota_gb} GB · {plan.carjam_lookups_included} Carjam lookups
                          </div>
                        </div>
                      </div>
                      <span className="text-sm font-semibold text-gray-900">{formatNZD(price)}/mo</span>
                    </label>
                  )
                })}
            </div>

            {selectedPlan && (
              <div className="rounded-md bg-gray-50 p-3 text-sm">
                {isUpgrade ? (
                  <p className="text-gray-700">
                    Upgrading to <span className="font-semibold">{selectedPlan.name}</span> takes effect immediately.
                    A prorated charge will be applied for the remainder of this billing period.
                  </p>
                ) : (
                  <p className="text-gray-700">
                    Downgrading to <span className="font-semibold">{selectedPlan.name}</span> takes effect at the start
                    of your next billing period. You'll keep your current plan until then.
                  </p>
                )}
              </div>
            )}

            {result && !result.success && (
              <AlertBanner variant="error">{result.message}</AlertBanner>
            )}
            {result?.warnings && result.warnings.length > 0 && (
              <AlertBanner variant="warning" title="Action required">
                <ul className="list-disc pl-4 space-y-1">
                  {result.warnings.map((w, i) => <li key={i}>{w}</li>)}
                </ul>
              </AlertBanner>
            )}
            {result?.success && (
              <AlertBanner variant="success">{result.message}</AlertBanner>
            )}

            <div className="flex gap-3 pt-2">
              <Button
                onClick={handleConfirm}
                loading={submitting}
                disabled={!selectedPlanId || result?.success}
              >
                {isUpgrade ? 'Confirm upgrade' : isDowngrade ? 'Confirm downgrade' : 'Select a plan'}
              </Button>
              <Button variant="secondary" onClick={onClose}>Cancel</Button>
            </div>
          </>
        )}
      </div>
    </Modal>
  )
}

/* ── Main Billing Page ── */

export function Billing() {
  const [billing, setBilling] = useState<BillingData | null>(null)
  const [invoices, setInvoices] = useState<PastInvoice[]>([])
  const [loading, setLoading] = useState(true)
  const [addonOpen, setAddonOpen] = useState(false)
  const [planChangeOpen, setPlanChangeOpen] = useState(false)
  const [stripePromise, setStripePromise] = useState<Promise<Stripe | null> | null>(null)
  const [showCardForm, setShowCardForm] = useState(false)
  const [pmRefreshKey, setPmRefreshKey] = useState(0)
  const { toasts, addToast, dismissToast } = useToast()

  // Load Stripe publishable key on mount
  useEffect(() => {
    async function loadStripeKey() {
      try {
        const res = await apiClient.get<{ publishable_key: string }>('/auth/stripe-publishable-key')
        if (res.data.publishable_key) {
          setStripePromise(loadStripe(res.data.publishable_key))
        }
      } catch {
        // Stripe not configured — payment methods section will show a fallback
      }
    }
    loadStripeKey()
  }, [])

  const fetchBilling = async () => {
    setLoading(true)
    try {
      const [billingRes, invoicesRes] = await Promise.all([
        apiClient.get('/billing'),
        apiClient.get('/billing/invoices'),
      ])
      // Transform flat backend response to the nested BillingData shape
      const raw = billingRes.data
      const transformed: BillingData = {
        plan: {
          name: raw.current_plan ?? 'Unknown',
          monthly_price_nzd: Number(raw.plan_monthly_price_nzd ?? 0),
          user_seats: raw.user_seats ?? 0,
          storage_quota_gb: raw.storage_quota_gb ?? 0,
          carjam_lookups_included: raw.carjam_lookups_included ?? 0,
          enabled_modules: raw.enabled_modules ?? [],
          sms_included: raw.sms_included ?? false,
          sms_included_quota: raw.sms_included_quota ?? 0,
          per_sms_cost_nzd: Number(raw.per_sms_cost_nzd ?? 0),
        },
        coupon: raw.active_coupon_code ? {
          code: raw.active_coupon_code,
          discount_type: raw.discount_type,
          discount_value: Number(raw.discount_value ?? 0),
          duration_months: raw.duration_months ?? null,
          effective_price_nzd: Number(raw.effective_price_nzd ?? 0),
          is_expired: raw.coupon_is_expired ?? false,
        } : null,
        status: raw.org_status ?? 'trial',
        trial_ends_at: raw.trial_ends_at ?? null,
        next_billing_date: raw.next_billing_date ?? null,
        estimated_next_invoice: {
          plan_fee: Number(raw.plan_monthly_price_nzd ?? 0),
          storage_addons: Number(raw.storage_addon_charge_nzd ?? 0),
          carjam_overage: Number(raw.carjam_overage_charge_nzd ?? 0),
          sms_overage: Number(raw.sms_overage_charge_nzd ?? 0),
          total: Number(raw.estimated_next_invoice_nzd ?? 0),
        },
        storage: {
          used_bytes: (raw.storage_used_gb ?? 0) * 1024 * 1024 * 1024,
          quota_gb: raw.storage_quota_gb ?? 0,
          avg_invoice_bytes: raw.avg_invoice_bytes ?? 0,
        },
        carjam: {
          lookups_this_month: raw.carjam_lookups_used ?? 0,
          included: raw.carjam_lookups_included ?? 0,
        },
        storage_addon_gb: raw.storage_addon_gb ?? null,
        storage_addon_price_nzd: raw.storage_addon_price_nzd ?? null,
        storage_addon_package_name: raw.storage_addon_package_name ?? null,
        sms: {
          sent_this_month: raw.sms_sent_this_month ?? 0,
          included_quota: raw.sms_included_quota ?? 0,
          credits_remaining: raw.sms_credits_remaining ?? 0,
          per_sms_cost_nzd: Number(raw.per_sms_cost_nzd ?? 0),
          overage_charge_nzd: Number(raw.sms_overage_charge_nzd ?? 0),
          sms_included: raw.sms_included ?? false,
        },
      }
      setBilling(transformed)
      // Handle both array and wrapped response formats
      const rawInvoices = Array.isArray(invoicesRes.data) ? invoicesRes.data : (invoicesRes.data?.invoices || [])
      // Transform backend SubscriptionInvoiceResponse to frontend PastInvoice shape
      const transformedInvoices: PastInvoice[] = rawInvoices.map((inv: Record<string, unknown>) => ({
        id: inv.id as string,
        date: inv.created ? new Date((inv.created as number) * 1000).toISOString() : '',
        amount: ((inv.amount_paid as number) ?? (inv.amount_due as number) ?? 0) / 100,
        status: (inv.status as string) ?? 'unknown',
        pdf_url: (inv.invoice_pdf as string) ?? '',
      }))
      setInvoices(transformedInvoices)
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
          <CurrentPlanCard plan={billing.plan} status={billing.status} coupon={billing.coupon} />
          <NextBillEstimate
            nextBillingDate={billing.next_billing_date}
            estimate={billing.estimated_next_invoice}
            coupon={billing.coupon}
            addonGb={billing.storage_addon_gb}
            addonPriceNzd={billing.storage_addon_price_nzd}
          />
        </div>

        {/* Usage cards */}
        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
          {billing.storage && (
            <StorageUsage
              usedBytes={billing.storage.used_bytes}
              quotaGb={billing.storage.quota_gb}
              avgInvoiceBytes={billing.storage.avg_invoice_bytes}
              onPurchaseAddon={() => setAddonOpen(true)}
              addonGb={billing.storage_addon_gb}
              addonPriceNzd={billing.storage_addon_price_nzd}
              addonPackageName={billing.storage_addon_package_name}
            />
          )}
          {billing.carjam && (
            <CarjamUsage
              lookups={billing.carjam.lookups_this_month}
              included={billing.carjam.included}
            />
          )}
          {billing.sms && (
            <SmsUsageCard
              sentThisMonth={billing.sms.sent_this_month}
              includedQuota={billing.sms.included_quota}
              creditsRemaining={billing.sms.credits_remaining}
              perSmsCost={billing.sms.per_sms_cost_nzd}
              smsIncluded={billing.sms.sms_included}
            />
          )}
        </div>

        {/* Actions */}
        <div className="flex flex-wrap gap-3">
          <Button onClick={() => setPlanChangeOpen(true)}>
            Change plan
          </Button>
        </div>

        {/* Payment methods */}
        {stripePromise ? (
          <Elements stripe={stripePromise}>
            <PaymentMethodManager
              key={pmRefreshKey}
              onAddCard={() => setShowCardForm(true)}
              showAddForm={showCardForm}
            />
            {showCardForm && (
              <CardForm
                onSuccess={() => {
                  setShowCardForm(false)
                  setPmRefreshKey((k) => k + 1)
                }}
                onCancel={() => setShowCardForm(false)}
              />
            )}
          </Elements>
        ) : (
          <div className="rounded-lg border border-gray-200 p-5">
            <h3 className="text-lg font-semibold text-gray-900 mb-3">Payment Methods</h3>
            <p className="text-sm text-gray-500">Stripe is not configured. Payment method management is unavailable.</p>
          </div>
        )}

        {/* Past invoices */}
        <PastInvoices invoices={invoices} />
      </div>

      {/* Storage manage modal */}
      <StorageManageModal
        open={addonOpen}
        onClose={() => setAddonOpen(false)}
        onComplete={fetchBilling}
        addToast={addToast}
      />

      {/* Plan change modal */}
      <PlanChangeModal
        open={planChangeOpen}
        onClose={() => setPlanChangeOpen(false)}
        onComplete={fetchBilling}
        addToast={addToast}
        currentPlanName={billing.plan?.name ?? 'Unknown'}
        currentPriceNzd={billing.plan?.monthly_price_nzd ?? 0}
      />
    </div>
  )
}
