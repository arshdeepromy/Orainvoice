import { useState, useEffect, useCallback } from 'react'
import { useParams, useNavigate, Link } from 'react-router-dom'
import apiClient from '@/api/client'
import { Spinner } from '@/components/ui/Spinner'
import { AlertBanner } from '@/components/ui/AlertBanner'
import { Button } from '@/components/ui/Button'
import { Badge } from '@/components/ui/Badge'
import { Modal } from '@/components/ui/Modal'
import { Input } from '@/components/ui/Input'
import { Select } from '@/components/ui/Select'
import { ToastContainer, useToast } from '@/components/ui/Toast'
import { SuspendModal } from '@/components/admin/SuspendModal'
import { DeleteModal } from '@/components/admin/DeleteModal'
import { MovePlanModal } from '@/components/admin/MovePlanModal'
import { ApplyCouponModal } from '@/components/admin/ApplyCouponModal'
import type { Plan } from '@/pages/admin/Organisations'

/* ── TypeScript Interfaces ── */

interface OrgDetailPaymentMethod {
  brand: string
  last4: string
  exp_month: number
  exp_year: number
}

interface OrgDetailCoupon {
  coupon_code: string
  discount_type: string
  discount_value: number
  duration_months: number | null
  billing_months_used: number
  is_expired: boolean
}

interface OrgDetailStorageAddon {
  package_name: string | null
  quantity_gb: number
  price_nzd_per_month: number
  is_custom: boolean
}

interface OrgDetailBilling {
  plan_name: string
  monthly_price_nzd: number
  billing_interval: string
  next_billing_date: string | null
  payment_method: OrgDetailPaymentMethod | null
  coupons: OrgDetailCoupon[]
  storage_addon: OrgDetailStorageAddon | null
  receipts_success_90d: number
  receipts_failed_90d: number
  last_failure_date: string | null
}

interface OrgDetailUsage {
  invoice_count: number
  quote_count: number
  customer_count: number
  vehicle_count: number
  storage_used_bytes: number
  storage_quota_gb: number
  carjam_lookups_this_month: number
  carjam_lookups_included: number
  sms_sent_this_month: number
  sms_included_quota: number
}

interface OrgDetailUser {
  id: string
  name: string
  email: string
  role: string
  is_active: boolean
  last_login_at: string | null
  mfa_enabled: boolean
}

interface OrgDetailUserSection {
  users: OrgDetailUser[]
  active_count: number
  seat_limit: number
}

interface OrgDetailLoginAttempt {
  user_email: string
  success: boolean
  ip_address: string | null
  device_info: string | null
  timestamp: string
}

interface OrgDetailAdminAction {
  action: string
  admin_email: string | null
  ip_address: string | null
  timestamp: string
}

interface OrgDetailSecurity {
  login_attempts: OrgDetailLoginAttempt[]
  admin_actions: OrgDetailAdminAction[]
  mfa_enrolled_count: number
  mfa_total_users: number
  failed_payments_90d: number
}

interface OrgDetailHealth {
  billing_ok: boolean
  storage_ok: boolean
  storage_warning: boolean
  seats_ok: boolean
  mfa_ok: boolean
  status_ok: boolean
}

interface OrgDetailOverview {
  id: string
  name: string
  status: string
  plan_name: string
  plan_id: string
  signup_date: string
  business_type: string | null
  trade_category_name: string | null
  billing_interval: string
  trial_ends_at: string | null
  timezone: string
  locale: string
}

interface OrgDetailData {
  overview: OrgDetailOverview
  billing: OrgDetailBilling
  usage: OrgDetailUsage
  users: OrgDetailUserSection
  security: OrgDetailSecurity
  health: OrgDetailHealth
}

/* ── Health Indicator Row ── */

function HealthIndicatorRow({ health }: { health: OrgDetailHealth }) {
  const billingOk = health?.billing_ok ?? true
  const storageOk = health?.storage_ok ?? true
  const storageWarning = health?.storage_warning ?? false
  const seatsOk = health?.seats_ok ?? true
  const mfaOk = health?.mfa_ok ?? true
  const statusOk = health?.status_ok ?? true

  // Derive storage colour: red if not ok, amber if warning, green otherwise
  const storageColour = !storageOk
    ? 'text-red-600'
    : storageWarning
      ? 'text-amber-500'
      : 'text-green-600'
  const storageIcon = !storageOk ? '✗' : storageWarning ? '⚠' : '✓'
  const storageLabel = !storageOk
    ? 'Storage Critical'
    : storageWarning
      ? 'Storage Warning'
      : 'Storage OK'

  const indicators = [
    {
      label: billingOk ? 'Billing OK' : 'Billing Issue',
      icon: billingOk ? '✓' : '✗',
      colour: billingOk ? 'text-green-600' : 'text-red-600',
    },
    {
      label: storageLabel,
      icon: storageIcon,
      colour: storageColour,
    },
    {
      label: seatsOk ? 'Seats OK' : 'Seats Full',
      icon: seatsOk ? '✓' : '⚠',
      colour: seatsOk ? 'text-green-600' : 'text-amber-500',
    },
    {
      label: mfaOk ? 'MFA OK' : 'MFA Low',
      icon: mfaOk ? '✓' : '⚠',
      colour: mfaOk ? 'text-green-600' : 'text-amber-500',
    },
    {
      label: statusOk ? 'Status OK' : 'Status Issue',
      icon: statusOk ? '✓' : '✗',
      colour: statusOk ? 'text-green-600' : 'text-red-600',
    },
  ]

  return (
    <section className="bg-white rounded-lg border border-gray-200 p-4">
      <h2 className="text-sm font-semibold text-gray-700 mb-2">Health Indicators</h2>
      <div className="flex flex-wrap gap-4">
        {indicators.map((ind) => (
          <div key={ind.label} className="flex items-center gap-1.5">
            <span className={`text-base font-bold ${ind.colour}`} aria-hidden="true">
              {ind.icon}
            </span>
            <span className={`text-sm font-medium ${ind.colour}`}>
              {ind.label}
            </span>
          </div>
        ))}
      </div>
    </section>
  )
}

/* ── Overview Card ── */

const STATUS_VARIANT_MAP: Record<string, 'success' | 'info' | 'warning' | 'error' | 'neutral'> = {
  active: 'success',
  trial: 'info',
  payment_pending: 'warning',
  suspended: 'error',
  deleted: 'neutral',
}

const STATUS_LABEL_MAP: Record<string, string> = {
  active: 'Active',
  trial: 'Trial',
  payment_pending: 'Payment Pending',
  suspended: 'Suspended',
  deleted: 'Deleted',
}

function formatSignupDate(dateStr: string | undefined | null, locale: string | undefined | null): string {
  if (!dateStr) return '—'
  try {
    const date = new Date(dateStr)
    if (isNaN(date.getTime())) return dateStr
    return date.toLocaleDateString(locale ?? 'en-NZ', {
      year: 'numeric',
      month: 'long',
      day: 'numeric',
    })
  } catch {
    return dateStr
  }
}

function formatTrialEnd(dateStr: string | undefined | null, locale: string | undefined | null): string {
  if (!dateStr) return '—'
  try {
    const date = new Date(dateStr)
    if (isNaN(date.getTime())) return dateStr
    return date.toLocaleDateString(locale ?? 'en-NZ', {
      year: 'numeric',
      month: 'long',
      day: 'numeric',
    })
  } catch {
    return dateStr
  }
}

function OverviewCard({ overview }: { overview: OrgDetailOverview }) {
  const name = overview?.name ?? 'Unknown'
  const status = overview?.status ?? 'unknown'
  const planName = overview?.plan_name ?? '—'
  const signupDate = formatSignupDate(overview?.signup_date, overview?.locale)
  const businessType = overview?.business_type ?? '—'
  const tradeCategoryName = overview?.trade_category_name ?? '—'
  const billingInterval = overview?.billing_interval ?? '—'
  const trialEndsAt = overview?.trial_ends_at
  const timezone = overview?.timezone ?? '—'
  const locale = overview?.locale ?? '—'

  const badgeVariant = STATUS_VARIANT_MAP[status] ?? 'neutral'
  const badgeLabel = STATUS_LABEL_MAP[status] ?? status

  return (
    <section className="bg-white rounded-lg border border-gray-200 p-6">
      <h2 className="text-lg font-semibold text-gray-900 mb-4">Overview</h2>

      {/* Name + Status + Plan */}
      <div className="flex flex-wrap items-center gap-3 mb-4">
        <span
          className="text-base font-semibold text-gray-900 truncate max-w-xs"
          title={name}
        >
          {name}
        </span>
        <Badge variant={badgeVariant}>{badgeLabel}</Badge>
        <span
          className="text-sm text-gray-600 truncate max-w-xs"
          title={planName}
        >
          {planName}
        </span>
      </div>

      {/* Detail grid */}
      <dl className="grid grid-cols-1 sm:grid-cols-2 gap-x-6 gap-y-3 text-sm">
        <div>
          <dt className="text-gray-500">Signup Date</dt>
          <dd className="text-gray-900 truncate" title={signupDate}>{signupDate}</dd>
        </div>
        <div>
          <dt className="text-gray-500">Business Type</dt>
          <dd className="text-gray-900 truncate" title={businessType}>{businessType}</dd>
        </div>
        <div>
          <dt className="text-gray-500">Trade Category</dt>
          <dd className="text-gray-900 truncate" title={tradeCategoryName}>{tradeCategoryName}</dd>
        </div>
        <div>
          <dt className="text-gray-500">Billing Interval</dt>
          <dd className="text-gray-900 truncate" title={billingInterval}>{billingInterval}</dd>
        </div>
        {trialEndsAt && (
          <div>
            <dt className="text-gray-500">Trial Ends</dt>
            <dd className="text-gray-900 truncate" title={formatTrialEnd(trialEndsAt, overview?.locale)}>
              {formatTrialEnd(trialEndsAt, overview?.locale)}
            </dd>
          </div>
        )}
        <div>
          <dt className="text-gray-500">Timezone</dt>
          <dd className="text-gray-900 truncate" title={timezone}>{timezone}</dd>
        </div>
        <div>
          <dt className="text-gray-500">Locale</dt>
          <dd className="text-gray-900 truncate" title={locale}>{locale}</dd>
        </div>
      </dl>
    </section>
  )
}

/* ── Billing Card ── */

function formatDate(dateStr: string | undefined | null): string {
  if (!dateStr) return '—'
  try {
    const date = new Date(dateStr)
    if (isNaN(date.getTime())) return dateStr
    return date.toLocaleDateString('en-NZ', {
      year: 'numeric',
      month: 'short',
      day: 'numeric',
    })
  } catch {
    return dateStr
  }
}

function formatCurrency(value: number | undefined | null): string {
  return `$${(value ?? 0).toFixed(2)}`
}

function BillingCard({ billing }: { billing: OrgDetailBilling }) {
  const planName = billing?.plan_name ?? '—'
  const monthlyPrice = billing?.monthly_price_nzd ?? 0
  const billingInterval = billing?.billing_interval ?? '—'
  const nextBillingDate = formatDate(billing?.next_billing_date)
  const pm = billing?.payment_method
  const coupons = billing?.coupons ?? []
  const storageAddon = billing?.storage_addon
  const receiptsSuccess = billing?.receipts_success_90d ?? 0
  const receiptsFailed = billing?.receipts_failed_90d ?? 0
  const lastFailureDate = billing?.last_failure_date

  return (
    <section className="bg-white rounded-lg border border-gray-200 p-6">
      <h2 className="text-lg font-semibold text-gray-900 mb-4">Billing</h2>

      {/* Plan & Billing Info */}
      <dl className="grid grid-cols-1 sm:grid-cols-2 gap-x-6 gap-y-3 text-sm mb-4">
        <div>
          <dt className="text-gray-500">Plan</dt>
          <dd className="text-gray-900 truncate" title={planName}>{planName}</dd>
        </div>
        <div>
          <dt className="text-gray-500">Monthly Price</dt>
          <dd className="text-gray-900 text-right" title={formatCurrency(monthlyPrice)}>
            {formatCurrency(monthlyPrice)}
          </dd>
        </div>
        <div>
          <dt className="text-gray-500">Billing Interval</dt>
          <dd className="text-gray-900 truncate" title={billingInterval}>{billingInterval}</dd>
        </div>
        <div>
          <dt className="text-gray-500">Next Billing Date</dt>
          <dd className="text-gray-900 truncate" title={nextBillingDate}>{nextBillingDate}</dd>
        </div>
      </dl>

      {/* Payment Method */}
      <div className="mb-4">
        <h3 className="text-sm font-medium text-gray-700 mb-1">Payment Method</h3>
        {pm ? (
          <p className="text-sm text-gray-900 truncate" title={`${pm?.brand ?? ''} •••• ${pm?.last4 ?? ''} — Exp ${String(pm?.exp_month ?? '').padStart(2, '0')}/${pm?.exp_year ?? ''}`}>
            {pm?.brand ?? ''} •••• {pm?.last4 ?? ''} — Exp {String(pm?.exp_month ?? '').padStart(2, '0')}/{pm?.exp_year ?? ''}
          </p>
        ) : (
          <p className="text-sm text-amber-600 flex items-center gap-1">
            <span aria-hidden="true">⚠</span> No payment method
          </p>
        )}
      </div>

      {/* Coupons */}
      <div className="mb-4">
        <h3 className="text-sm font-medium text-gray-700 mb-1">Active Coupons</h3>
        {coupons.length > 0 ? (
          <div className="overflow-x-auto">
            <table className="min-w-full text-sm">
              <thead>
                <tr className="text-left text-gray-500 border-b border-gray-100">
                  <th className="pb-1 pr-4 font-medium">Code</th>
                  <th className="pb-1 pr-4 font-medium">Type</th>
                  <th className="pb-1 pr-4 font-medium text-right">Value</th>
                  <th className="pb-1 font-medium text-right">Remaining</th>
                </tr>
              </thead>
              <tbody>
                {coupons.map((coupon, idx) => {
                  const code = coupon?.coupon_code ?? '—'
                  const discountType = coupon?.discount_type ?? '—'
                  const discountValue = coupon?.discount_value ?? 0
                  const durationMonths = coupon?.duration_months
                  const monthsUsed = coupon?.billing_months_used ?? 0
                  const remaining = durationMonths != null
                    ? Math.max((durationMonths ?? 0) - monthsUsed, 0)
                    : '∞'

                  const valueDisplay = discountType === 'percentage'
                    ? `${discountValue}%`
                    : formatCurrency(discountValue)

                  return (
                    <tr key={`${code}-${idx}`} className="border-b border-gray-50">
                      <td className="py-1 pr-4 truncate max-w-[120px]" title={code}>{code}</td>
                      <td className="py-1 pr-4 truncate" title={discountType}>{discountType}</td>
                      <td className="py-1 pr-4 text-right" title={valueDisplay}>{valueDisplay}</td>
                      <td className="py-1 text-right" title={`${remaining} months`}>
                        {remaining === '∞' ? '∞' : `${remaining} mo`}
                      </td>
                    </tr>
                  )
                })}
              </tbody>
            </table>
          </div>
        ) : (
          <p className="text-sm text-gray-500">No active coupons</p>
        )}
      </div>

      {/* Storage Add-on */}
      <div className="mb-4">
        <h3 className="text-sm font-medium text-gray-700 mb-1">Storage Add-on</h3>
        {storageAddon ? (
          <dl className="grid grid-cols-1 sm:grid-cols-2 gap-x-6 gap-y-1 text-sm">
            <div>
              <dt className="text-gray-500">Package</dt>
              <dd className="text-gray-900 truncate" title={storageAddon?.package_name ?? 'Custom'}>
                {storageAddon?.package_name ?? 'Custom'}
                {storageAddon?.is_custom ? ' (Custom)' : ''}
              </dd>
            </div>
            <div>
              <dt className="text-gray-500">Quantity</dt>
              <dd className="text-gray-900 text-right">{storageAddon?.quantity_gb ?? 0} GB</dd>
            </div>
            <div>
              <dt className="text-gray-500">Price</dt>
              <dd className="text-gray-900 text-right">
                {formatCurrency(storageAddon?.price_nzd_per_month)}/mo
              </dd>
            </div>
          </dl>
        ) : (
          <p className="text-sm text-gray-500">No storage add-on</p>
        )}
      </div>

      {/* Billing Receipt Summary */}
      <div>
        <h3 className="text-sm font-medium text-gray-700 mb-1">Receipts (Last 90 Days)</h3>
        <dl className="grid grid-cols-1 sm:grid-cols-2 gap-x-6 gap-y-1 text-sm">
          <div>
            <dt className="text-gray-500">Successful</dt>
            <dd className="text-gray-900 text-right">{(receiptsSuccess ?? 0).toLocaleString()}</dd>
          </div>
          <div>
            <dt className="text-gray-500">Failed</dt>
            <dd className={`text-right ${receiptsFailed > 0 ? 'text-red-600 font-medium' : 'text-gray-900'}`}>
              {(receiptsFailed ?? 0).toLocaleString()}
            </dd>
          </div>
          {receiptsFailed > 0 && lastFailureDate && (
            <div className="sm:col-span-2">
              <dt className="text-gray-500">Most Recent Failure</dt>
              <dd className="text-red-600 truncate" title={formatDate(lastFailureDate)}>
                {formatDate(lastFailureDate)}
              </dd>
            </div>
          )}
        </dl>
      </div>
    </section>
  )
}

/* ── Progress Bar Helper ── */

function ProgressBar({
  used,
  total,
  label,
  amberThreshold = 0.8,
  redThreshold = 0.95,
}: {
  used: number
  total: number
  label: string
  amberThreshold?: number
  redThreshold?: number
}) {
  const safeDenominator = Math.max(total, 1)
  const ratio = used / safeDenominator
  const pct = Math.min(ratio * 100, 100)

  let barColour = 'bg-blue-500'
  if (ratio > redThreshold) {
    barColour = 'bg-red-500'
  } else if (ratio > amberThreshold) {
    barColour = 'bg-amber-500'
  }

  return (
    <div className="flex items-center gap-3">
      <div className="flex-1 h-2.5 bg-gray-200 rounded-full overflow-hidden" aria-hidden="true">
        <div
          className={`h-full rounded-full ${barColour}`}
          style={{ width: `${pct}%` }}
        />
      </div>
      <span className="text-sm text-gray-700 whitespace-nowrap text-right min-w-[80px]">
        {label}
      </span>
    </div>
  )
}

/* ── Usage Metrics Card ── */

function UsageMetricsCard({ usage }: { usage: OrgDetailUsage }) {
  const invoiceCount = usage?.invoice_count ?? 0
  const quoteCount = usage?.quote_count ?? 0
  const customerCount = usage?.customer_count ?? 0
  const vehicleCount = usage?.vehicle_count ?? 0
  const storageUsedBytes = usage?.storage_used_bytes ?? 0
  const storageQuotaGb = usage?.storage_quota_gb ?? 0
  const carjamUsed = usage?.carjam_lookups_this_month ?? 0
  const carjamIncluded = usage?.carjam_lookups_included ?? 0
  const smsSent = usage?.sms_sent_this_month ?? 0
  const smsQuota = usage?.sms_included_quota ?? 0

  // Convert bytes to GB for display (1 GB = 1,073,741,824 bytes)
  const storageUsedGb = storageUsedBytes / 1_073_741_824
  const storageLabel = `${storageUsedGb.toFixed(1)} / ${(storageQuotaGb ?? 0).toLocaleString()} GB`
  const carjamLabel = `${(carjamUsed ?? 0).toLocaleString()} / ${(carjamIncluded ?? 0).toLocaleString()}`
  const smsLabel = `${(smsSent ?? 0).toLocaleString()} / ${(smsQuota ?? 0).toLocaleString()}`

  return (
    <section className="bg-white rounded-lg border border-gray-200 p-6">
      <h2 className="text-lg font-semibold text-gray-900 mb-4">Usage Metrics</h2>

      {/* Aggregate counts */}
      <dl className="grid grid-cols-2 sm:grid-cols-4 gap-x-6 gap-y-3 text-sm mb-5">
        <div>
          <dt className="text-gray-500">Invoices</dt>
          <dd className="text-gray-900 text-right font-medium">{(invoiceCount ?? 0).toLocaleString()}</dd>
        </div>
        <div>
          <dt className="text-gray-500">Quotes</dt>
          <dd className="text-gray-900 text-right font-medium">{(quoteCount ?? 0).toLocaleString()}</dd>
        </div>
        <div>
          <dt className="text-gray-500">Customers</dt>
          <dd className="text-gray-900 text-right font-medium">{(customerCount ?? 0).toLocaleString()}</dd>
        </div>
        <div>
          <dt className="text-gray-500">Vehicles</dt>
          <dd className="text-gray-900 text-right font-medium">{(vehicleCount ?? 0).toLocaleString()}</dd>
        </div>
      </dl>

      {/* Progress bars */}
      <div className="space-y-4">
        <div>
          <h3 className="text-sm font-medium text-gray-700 mb-1">Storage</h3>
          <ProgressBar
            used={storageUsedBytes}
            total={storageQuotaGb * 1_073_741_824}
            label={storageLabel}
            amberThreshold={0.8}
            redThreshold={0.95}
          />
        </div>

        <div>
          <h3 className="text-sm font-medium text-gray-700 mb-1">Carjam Lookups (This Month)</h3>
          <ProgressBar
            used={carjamUsed}
            total={carjamIncluded}
            label={carjamLabel}
          />
        </div>

        <div>
          <h3 className="text-sm font-medium text-gray-700 mb-1">SMS Sent (This Month)</h3>
          <ProgressBar
            used={smsSent}
            total={smsQuota}
            label={smsLabel}
          />
        </div>
      </div>
    </section>
  )
}

/* ── User Management Card ── */

const ROLE_DISPLAY_NAMES: Record<string, string> = {
  org_admin: 'Org Admin',
  staff: 'Staff',
  accountant: 'Accountant',
  branch_manager: 'Branch Manager',
  technician: 'Technician',
  receptionist: 'Receptionist',
  global_admin: 'Global Admin',
}

function isStaleLogin(lastLoginAt: string | null | undefined): boolean {
  if (!lastLoginAt) return true
  try {
    const loginDate = new Date(lastLoginAt)
    if (isNaN(loginDate.getTime())) return true
    const ninetyDaysAgo = new Date()
    ninetyDaysAgo.setDate(ninetyDaysAgo.getDate() - 90)
    return loginDate < ninetyDaysAgo
  } catch {
    return true
  }
}

function formatLastLogin(dateStr: string | null | undefined): string {
  if (!dateStr) return 'Never'
  try {
    const date = new Date(dateStr)
    if (isNaN(date.getTime())) return dateStr
    return date.toLocaleDateString('en-NZ', {
      year: 'numeric',
      month: 'short',
      day: 'numeric',
    })
  } catch {
    return dateStr
  }
}

function UserManagementCard({ users }: { users: OrgDetailUserSection }) {
  const userList = users?.users ?? []
  const activeCount = users?.active_count ?? 0
  const seatLimit = users?.seat_limit ?? 0
  const atLimit = activeCount >= seatLimit && seatLimit > 0

  return (
    <section className="bg-white rounded-lg border border-gray-200 p-6">
      <h2 className="text-lg font-semibold text-gray-900 mb-4">User Management</h2>

      {/* Seat count */}
      <div className="flex items-center gap-2 mb-4">
        <span className="text-sm text-gray-700">
          {(activeCount ?? 0).toLocaleString()} / {(seatLimit ?? 0).toLocaleString()} seats
        </span>
        {atLimit && (
          <span className="text-amber-600 text-sm font-medium flex items-center gap-1">
            <span aria-hidden="true">⚠</span> At seat limit
          </span>
        )}
      </div>

      {/* User table */}
      {userList.length > 0 ? (
        <div className="overflow-x-auto">
          <table className="min-w-full text-sm">
            <thead>
              <tr className="text-left text-gray-500 border-b border-gray-200">
                <th className="pb-2 pr-4 font-medium">Name</th>
                <th className="pb-2 pr-4 font-medium">Email</th>
                <th className="pb-2 pr-4 font-medium">Role</th>
                <th className="pb-2 pr-4 font-medium">Last Login</th>
                <th className="pb-2 font-medium">MFA</th>
              </tr>
            </thead>
            <tbody>
              {userList.map((user) => {
                const name = user?.name ?? '—'
                const email = user?.email ?? '—'
                const role = user?.role ?? ''
                const roleDisplay = ROLE_DISPLAY_NAMES[role] ?? role
                const lastLogin = user?.last_login_at
                const mfaEnabled = user?.mfa_enabled ?? false
                const stale = isStaleLogin(lastLogin)

                return (
                  <tr
                    key={user?.id ?? email}
                    className={`border-b border-gray-50 ${stale ? 'bg-amber-50' : ''}`}
                  >
                    <td
                      className={`py-2 pr-4 truncate max-w-[160px] ${stale ? 'text-amber-800' : 'text-gray-900'}`}
                      title={name}
                    >
                      {name}
                    </td>
                    <td
                      className={`py-2 pr-4 truncate max-w-[200px] ${stale ? 'text-amber-800' : 'text-gray-900'}`}
                      title={email}
                    >
                      {email}
                    </td>
                    <td
                      className={`py-2 pr-4 truncate ${stale ? 'text-amber-800' : 'text-gray-900'}`}
                      title={roleDisplay}
                    >
                      {roleDisplay}
                    </td>
                    <td
                      className={`py-2 pr-4 whitespace-nowrap ${stale ? 'text-amber-800' : 'text-gray-900'}`}
                      title={formatLastLogin(lastLogin)}
                    >
                      {formatLastLogin(lastLogin)}
                    </td>
                    <td className="py-2 whitespace-nowrap">
                      {mfaEnabled ? (
                        <span className="text-green-600 font-medium">Enabled</span>
                      ) : (
                        <span className="text-gray-500">Not enrolled</span>
                      )}
                    </td>
                  </tr>
                )
              })}
            </tbody>
          </table>
        </div>
      ) : (
        <p className="text-sm text-gray-500">No users found</p>
      )}
    </section>
  )
}

/* ── Security & Audit Card ── */

const ADMIN_ACTION_DISPLAY_NAMES: Record<string, string> = {
  org_suspended: 'Suspended',
  org_reinstated: 'Reinstated',
  org_plan_changed: 'Plan Changed',
  org_coupon_applied: 'Coupon Applied',
  org_deleted: 'Deleted',
  org_detail_viewed: 'Detail Viewed',
}

function formatTimestamp(dateStr: string | null | undefined): string {
  if (!dateStr) return '—'
  try {
    const date = new Date(dateStr)
    if (isNaN(date.getTime())) return dateStr
    return date.toLocaleDateString('en-NZ', {
      year: 'numeric',
      month: 'short',
      day: 'numeric',
      hour: '2-digit',
      minute: '2-digit',
    })
  } catch {
    return dateStr
  }
}

function SecurityAuditCard({ security }: { security: OrgDetailSecurity }) {
  const loginAttempts = security?.login_attempts ?? []
  const adminActions = security?.admin_actions ?? []
  const mfaEnrolled = security?.mfa_enrolled_count ?? 0
  const mfaTotal = security?.mfa_total_users ?? 0
  const failedPayments = security?.failed_payments_90d ?? 0

  return (
    <section className="bg-white rounded-lg border border-gray-200 p-6 lg:col-span-2">
      <h2 className="text-lg font-semibold text-gray-900 mb-4">Security &amp; Audit</h2>

      {/* MFA Enrollment Summary */}
      <div className="mb-4">
        <h3 className="text-sm font-medium text-gray-700 mb-1">MFA Enrollment</h3>
        <p className="text-sm text-gray-900">
          {(mfaEnrolled ?? 0).toLocaleString()} of {(mfaTotal ?? 0).toLocaleString()} users have MFA enabled
        </p>
      </div>

      {/* Failed Payments (Last 90 Days) */}
      <div className="mb-5">
        <h3 className="text-sm font-medium text-gray-700 mb-1">Failed Payments (Last 90 Days)</h3>
        <p className={`text-sm ${failedPayments > 0 ? 'text-red-600 font-medium' : 'text-gray-900'}`}>
          {(failedPayments ?? 0).toLocaleString()}
        </p>
      </div>

      {/* Login Attempts Table */}
      <div className="mb-5">
        <h3 className="text-sm font-medium text-gray-700 mb-2">Login Attempts (Last 30 Days)</h3>
        {loginAttempts.length > 0 ? (
          <div className="overflow-x-auto">
            <table className="min-w-full text-sm">
              <thead>
                <tr className="text-left text-gray-500 border-b border-gray-200">
                  <th className="pb-2 pr-4 font-medium">Email</th>
                  <th className="pb-2 pr-4 font-medium">Status</th>
                  <th className="pb-2 pr-4 font-medium">IP Address</th>
                  <th className="pb-2 pr-4 font-medium">Device</th>
                  <th className="pb-2 font-medium">Timestamp</th>
                </tr>
              </thead>
              <tbody>
                {loginAttempts.map((attempt, idx) => {
                  const email = attempt?.user_email ?? '—'
                  const success = attempt?.success ?? false
                  const ip = attempt?.ip_address ?? '—'
                  const device = attempt?.device_info ?? '—'
                  const ts = formatTimestamp(attempt?.timestamp)

                  return (
                    <tr key={`login-${idx}`} className="border-b border-gray-50">
                      <td className="py-2 pr-4 truncate max-w-[200px]" title={email}>{email}</td>
                      <td className="py-2 pr-4">
                        <Badge variant={success ? 'success' : 'error'}>
                          {success ? 'Success' : 'Failed'}
                        </Badge>
                      </td>
                      <td className="py-2 pr-4 truncate max-w-[140px]" title={ip}>{ip}</td>
                      <td className="py-2 pr-4 truncate max-w-[200px]" title={device}>{device}</td>
                      <td className="py-2 whitespace-nowrap" title={ts}>{ts}</td>
                    </tr>
                  )
                })}
              </tbody>
            </table>
          </div>
        ) : (
          <p className="text-sm text-gray-500">No login attempts in the last 30 days</p>
        )}
      </div>

      {/* Admin Actions Table */}
      <div>
        <h3 className="text-sm font-medium text-gray-700 mb-2">Admin Actions (Last 90 Days)</h3>
        {adminActions.length > 0 ? (
          <div className="overflow-x-auto">
            <table className="min-w-full text-sm">
              <thead>
                <tr className="text-left text-gray-500 border-b border-gray-200">
                  <th className="pb-2 pr-4 font-medium">Action</th>
                  <th className="pb-2 pr-4 font-medium">Admin</th>
                  <th className="pb-2 pr-4 font-medium">IP Address</th>
                  <th className="pb-2 font-medium">Timestamp</th>
                </tr>
              </thead>
              <tbody>
                {adminActions.map((action, idx) => {
                  const actionType = action?.action ?? ''
                  const actionDisplay = ADMIN_ACTION_DISPLAY_NAMES[actionType] ?? actionType
                  const adminEmail = action?.admin_email ?? '—'
                  const ip = action?.ip_address ?? '—'
                  const ts = formatTimestamp(action?.timestamp)

                  return (
                    <tr key={`action-${idx}`} className="border-b border-gray-50">
                      <td className="py-2 pr-4 truncate max-w-[160px]" title={actionDisplay}>{actionDisplay}</td>
                      <td className="py-2 pr-4 truncate max-w-[200px]" title={adminEmail}>{adminEmail}</td>
                      <td className="py-2 pr-4 truncate max-w-[140px]" title={ip}>{ip}</td>
                      <td className="py-2 whitespace-nowrap" title={ts}>{ts}</td>
                    </tr>
                  )
                })}
              </tbody>
            </table>
          </div>
        ) : (
          <p className="text-sm text-gray-500">No admin actions in the last 90 days</p>
        )}
      </div>
    </section>
  )
}

/* ── Quick Actions Bar ── */

function QuickActionsBar({
  status,
  onSuspend,
  onReinstate,
  onDelete,
  onChangePlan,
  onApplyCoupon,
  onSendNotification,
}: {
  status: string
  onSuspend: () => void
  onReinstate: () => void
  onDelete: () => void
  onChangePlan: () => void
  onApplyCoupon: () => void
  onSendNotification: () => void
}) {
  const normalizedStatus = (status ?? '').toLowerCase()

  return (
    <section className="bg-white rounded-lg border border-gray-200 p-4">
      <h2 className="text-sm font-semibold text-gray-700 mb-2">Quick Actions</h2>
      <div className="flex flex-wrap gap-3">
        {(normalizedStatus === 'active' || normalizedStatus === 'trial') && (
          <Button variant="danger" size="sm" onClick={onSuspend}>
            Suspend
          </Button>
        )}
        {normalizedStatus === 'suspended' && (
          <Button variant="primary" size="sm" onClick={onReinstate}>
            Reinstate
          </Button>
        )}
        <Button variant="secondary" size="sm" onClick={onChangePlan}>
          Change Plan
        </Button>
        <Button variant="secondary" size="sm" onClick={onApplyCoupon}>
          Apply Coupon
        </Button>
        <Button variant="secondary" size="sm" onClick={onSendNotification}>
          Send Notification
        </Button>
        {normalizedStatus !== 'deleted' && (
          <Button variant="danger" size="sm" onClick={onDelete}>
            Delete
          </Button>
        )}
      </div>
    </section>
  )
}

/* ── Send Notification Modal ── */

type NotificationType = 'maintenance' | 'alert' | 'feature' | 'info'
type NotificationSeverity = 'info' | 'warning' | 'critical'

const SEVERITY_OPTIONS = [
  { value: 'info', label: 'Info' },
  { value: 'warning', label: 'Warning' },
  { value: 'critical', label: 'Critical' },
]

const TYPE_OPTIONS = [
  { value: 'maintenance', label: 'Maintenance' },
  { value: 'alert', label: 'Alert' },
  { value: 'feature', label: 'Feature' },
  { value: 'info', label: 'Info' },
]

function SendNotificationModal({
  orgId,
  orgName,
  open,
  onClose,
}: {
  orgId: string
  orgName: string
  open: boolean
  onClose: () => void
}) {
  const [title, setTitle] = useState('')
  const [message, setMessage] = useState('')
  const [severity, setSeverity] = useState<NotificationSeverity>('info')
  const [notificationType, setNotificationType] = useState<NotificationType>('info')
  const [submitting, setSubmitting] = useState(false)
  const [formError, setFormError] = useState<string | null>(null)
  const { toasts, addToast, dismissToast } = useToast()

  // Reset form when modal opens
  useEffect(() => {
    if (open) {
      setTitle('')
      setMessage('')
      setSeverity('info')
      setNotificationType('info')
      setFormError(null)
    }
  }, [open])

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault()
    setFormError(null)

    if (!title.trim()) {
      setFormError('Title is required')
      return
    }
    if (!message.trim()) {
      setFormError('Message is required')
      return
    }

    setSubmitting(true)
    try {
      await apiClient.post('/api/v2/admin/notifications', {
        notification_type: notificationType,
        title: title.trim(),
        message: message.trim(),
        severity,
        target_type: 'specific_orgs',
        target_value: orgId,
      })
      addToast('success', 'Notification sent successfully')
      onClose()
    } catch (err: unknown) {
      const detail = (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail
      addToast('error', detail ?? 'Failed to send notification')
    } finally {
      setSubmitting(false)
    }
  }

  return (
    <>
      <Modal open={open} onClose={onClose} title="Send Notification">
        <form onSubmit={handleSubmit} className="space-y-4">
          {/* Target org (read-only) */}
          <div className="flex flex-col gap-1">
            <label className="text-sm font-medium text-gray-700">Target Organisation</label>
            <p
              className="h-[42px] w-full rounded-md border border-gray-200 bg-gray-50 px-3 py-2 text-gray-700 truncate"
              title={orgName ?? ''}
            >
              {orgName ?? 'Unknown'}
            </p>
          </div>

          <Input
            label="Title"
            value={title}
            onChange={(e) => setTitle(e.target.value)}
            placeholder="Notification title"
            required
          />

          {/* Message textarea */}
          <div className="flex flex-col gap-1">
            <label htmlFor="notification-message" className="text-sm font-medium text-gray-700">
              Message
            </label>
            <textarea
              id="notification-message"
              value={message}
              onChange={(e) => setMessage(e.target.value)}
              placeholder="Notification message"
              rows={4}
              required
              className="w-full rounded-md border border-gray-300 px-3 py-2 text-gray-900 shadow-sm transition-colors
                placeholder:text-gray-400
                focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-blue-500 focus-visible:ring-offset-2 focus-visible:border-blue-500"
            />
          </div>

          <Select
            label="Severity"
            options={SEVERITY_OPTIONS}
            value={severity}
            onChange={(e) => setSeverity(e.target.value as NotificationSeverity)}
          />

          <Select
            label="Type"
            options={TYPE_OPTIONS}
            value={notificationType}
            onChange={(e) => setNotificationType(e.target.value as NotificationType)}
          />

          {formError && (
            <p className="text-sm text-red-600" role="alert">{formError}</p>
          )}

          <div className="flex justify-end gap-3 pt-2">
            <Button type="button" variant="secondary" onClick={onClose}>
              Cancel
            </Button>
            <Button type="submit" variant="primary" loading={submitting}>
              Send Notification
            </Button>
          </div>
        </form>
      </Modal>
      <ToastContainer toasts={toasts} onDismiss={dismissToast} />
    </>
  )
}

/* ── Main Component ── */

export function OrganisationDetail() {
  const { orgId } = useParams<{ orgId: string }>()
  const navigate = useNavigate()

  const [data, setData] = useState<OrgDetailData | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [is404, setIs404] = useState(false)

  // Modal states for quick actions
  const [suspendOpen, setSuspendOpen] = useState(false)
  const [deleteOpen, setDeleteOpen] = useState(false)
  const [planChangeOpen, setPlanChangeOpen] = useState(false)
  const [couponOpen, setCouponOpen] = useState(false)
  const [notificationOpen, setNotificationOpen] = useState(false)

  // Plans for MovePlanModal
  const [plans, setPlans] = useState<Plan[]>([])

  // Saving state for modals
  const [saving, setSaving] = useState(false)

  const { toasts, addToast, dismissToast } = useToast()

  const fetchDetail = useCallback(
    (signal?: AbortSignal) => {
      setLoading(true)
      setError(null)
      setIs404(false)

      const doFetch = async () => {
        try {
          const res = await apiClient.get<OrgDetailData>(
            `/admin/organisations/${orgId}/detail`,
            { signal },
          )
          setData(res.data ?? null)
        } catch (err: unknown) {
          if (signal?.aborted) return
          const status = (err as { response?: { status?: number } })?.response?.status
          if (status === 404) {
            setIs404(true)
            setError('Organisation not found')
          } else {
            setError('Failed to load organisation details')
          }
        } finally {
          if (!signal?.aborted) setLoading(false)
        }
      }
      doFetch()
    },
    [orgId],
  )

  // Fetch plans for MovePlanModal
  useEffect(() => {
    const controller = new AbortController()
    const fetchPlans = async () => {
      try {
        const res = await apiClient.get<{ plans: Plan[]; total: number }>('/admin/plans', { signal: controller.signal })
        setPlans(res.data?.plans ?? [])
      } catch {
        // Plans fetch failure is non-critical — modal will show empty list
      }
    }
    fetchPlans()
    return () => controller.abort()
  }, [])

  useEffect(() => {
    const controller = new AbortController()
    fetchDetail(controller.signal)
    return () => controller.abort()
  }, [fetchDetail])

  /* ── Quick Action Handlers ── */

  const refreshDetail = () => fetchDetail()

  const handleSuspend = async (reason: string) => {
    if (!orgId) return
    setSaving(true)
    try {
      await apiClient.put(`/admin/organisations/${orgId}`, { action: 'suspend', reason })
      addToast('success', 'Organisation suspended')
      setSuspendOpen(false)
      refreshDetail()
    } catch {
      addToast('error', 'Failed to suspend organisation')
    } finally {
      setSaving(false)
    }
  }

  const handleReinstate = async () => {
    if (!orgId) return
    setSaving(true)
    try {
      await apiClient.put(`/admin/organisations/${orgId}`, { action: 'reinstate' })
      addToast('success', 'Organisation reinstated')
      setSuspendOpen(false)
      refreshDetail()
    } catch {
      addToast('error', 'Failed to reinstate organisation')
    } finally {
      setSaving(false)
    }
  }

  const handleDelete = async (reason: string) => {
    if (!orgId) return
    setSaving(true)
    try {
      const res = await apiClient.put(`/admin/organisations/${orgId}`, {
        action: 'delete_request',
        reason,
      })
      const token = res.data.confirmation_token
      await apiClient.delete(`/admin/organisations/${orgId}`, {
        data: { reason, confirmation_token: token },
      })
      addToast('success', 'Organisation soft deleted')
      setDeleteOpen(false)
      refreshDetail()
    } catch {
      addToast('error', 'Failed to delete organisation')
    } finally {
      setSaving(false)
    }
  }

  const handleMovePlan = async (planId: string) => {
    if (!orgId) return
    setSaving(true)
    try {
      await apiClient.put(`/admin/organisations/${orgId}`, {
        action: 'move_plan',
        new_plan_id: planId,
      })
      addToast('success', 'Plan changed successfully')
      setPlanChangeOpen(false)
      refreshDetail()
    } catch {
      addToast('error', 'Failed to change plan')
    } finally {
      setSaving(false)
    }
  }

  const handleApplyCouponSuccess = () => {
    addToast('success', 'Coupon applied successfully')
    setCouponOpen(false)
    refreshDetail()
  }

  /* ── Loading state ── */
  if (loading) {
    return (
      <div className="max-w-7xl mx-auto px-4 py-6 sm:px-6 lg:px-8">
        <div className="py-16 text-center">
          <Spinner label="Loading organisation details" />
        </div>
      </div>
    )
  }

  /* ── 404 error state ── */
  if (is404) {
    return (
      <div className="max-w-7xl mx-auto px-4 py-6 sm:px-6 lg:px-8">
        <AlertBanner variant="error" title="Not found">
          Organisation not found. It may have been deleted or the ID is invalid.
        </AlertBanner>
        <div className="mt-4">
          <Link
            to="/admin/organisations"
            className="text-blue-600 hover:text-blue-800 hover:underline text-sm"
          >
            ← Back to Organisations
          </Link>
        </div>
      </div>
    )
  }

  /* ── Generic error state ── */
  if (error) {
    return (
      <div className="max-w-7xl mx-auto px-4 py-6 sm:px-6 lg:px-8">
        <AlertBanner variant="error" title="Error">
          {error}
        </AlertBanner>
        <div className="mt-4">
          <Button variant="secondary" onClick={() => fetchDetail()}>
            Retry
          </Button>
        </div>
      </div>
    )
  }

  /* ── No data fallback ── */
  if (!data) return null

  const org = data.overview

  return (
    <div className="max-w-7xl mx-auto px-4 py-6 sm:px-6 lg:px-8">
      {/* Breadcrumb */}
      <nav className="text-sm text-gray-500 mb-4" aria-label="Breadcrumb">
        <ol className="flex items-center gap-1">
          <li>
            <Link
              to="/admin/organisations"
              className="text-blue-600 hover:text-blue-800 hover:underline"
            >
              Organisations
            </Link>
          </li>
          <li aria-hidden="true">&gt;</li>
          <li
            className="truncate max-w-xs text-gray-900 font-medium"
            title={org?.name ?? ''}
          >
            {org?.name ?? 'Unknown'}
          </li>
        </ol>
      </nav>

      {/* Back button */}
      <div className="mb-6">
        <Button
          variant="secondary"
          size="sm"
          onClick={() => navigate('/admin/organisations')}
        >
          ← Back
        </Button>
      </div>

      {/* Page content */}
      <div className="space-y-6">
        {/* Health Indicators */}
        <HealthIndicatorRow health={data.health} />

        {/* Responsive two-column grid */}
        <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
          {/* Overview */}
          <OverviewCard overview={data.overview} />

          {/* Billing */}
          <BillingCard billing={data.billing} />

          {/* Usage Metrics */}
          <UsageMetricsCard usage={data.usage} />

          {/* User Management */}
          <UserManagementCard users={data.users} />

          {/* Security & Audit */}
          <SecurityAuditCard security={data.security} />
        </div>

        {/* Quick Actions */}
        <QuickActionsBar
          status={org?.status ?? ''}
          onSuspend={() => setSuspendOpen(true)}
          onReinstate={handleReinstate}
          onDelete={() => setDeleteOpen(true)}
          onChangePlan={() => setPlanChangeOpen(true)}
          onApplyCoupon={() => setCouponOpen(true)}
          onSendNotification={() => setNotificationOpen(true)}
        />

        {/* Send Notification Modal */}
        <SendNotificationModal
          orgId={orgId ?? ''}
          orgName={org?.name ?? ''}
          open={notificationOpen}
          onClose={() => setNotificationOpen(false)}
        />

        {/* Suspend Modal */}
        <SuspendModal
          open={suspendOpen}
          onClose={() => setSuspendOpen(false)}
          onConfirm={handleSuspend}
          saving={saving}
          orgName={org?.name ?? ''}
        />

        {/* Delete Modal */}
        <DeleteModal
          open={deleteOpen}
          onClose={() => setDeleteOpen(false)}
          onConfirm={handleDelete}
          saving={saving}
          orgName={org?.name ?? ''}
        />

        {/* Plan Change Modal */}
        <MovePlanModal
          open={planChangeOpen}
          onClose={() => setPlanChangeOpen(false)}
          onConfirm={handleMovePlan}
          saving={saving}
          orgName={org?.name ?? ''}
          currentPlanId={org?.plan_id ?? ''}
          plans={plans}
        />

        {/* Apply Coupon Modal */}
        <ApplyCouponModal
          open={couponOpen}
          onClose={() => setCouponOpen(false)}
          onSuccess={handleApplyCouponSuccess}
          orgName={org?.name ?? ''}
          orgId={orgId ?? ''}
        />
      </div>

      <ToastContainer toasts={toasts} onDismiss={dismissToast} />
    </div>
  )
}
