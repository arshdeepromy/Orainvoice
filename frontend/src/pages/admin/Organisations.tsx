import { useState, useEffect, useMemo } from 'react'
import { Button } from '@/components/ui/Button'
import { Badge } from '@/components/ui/Badge'
import { Spinner } from '@/components/ui/Spinner'
import { AlertBanner } from '@/components/ui/AlertBanner'
import { DataTable, type Column } from '@/components/ui/DataTable'
import { Modal } from '@/components/ui/Modal'
import { Input } from '@/components/ui/Input'
import { Select } from '@/components/ui/Select'
import { ToastContainer, useToast } from '@/components/ui/Toast'
import apiClient from '@/api/client'

/* ── Types ── */

export type OrgStatus = 'active' | 'trial' | 'suspended' | 'deleted' | 'payment_pending'
export type BillingStatus = 'current' | 'overdue' | 'unpaid' | 'trial'

export interface Organisation {
  id: string
  name: string
  plan_name: string
  plan_id: string
  status: OrgStatus
  billing_status: BillingStatus
  signup_date: string
  storage_used_gb: number
  storage_quota_gb: number
  last_login: string | null
  next_billing_date: string | null
  billing_interval: string
  [key: string]: unknown
}

export interface Plan {
  id: string
  name: string
  [key: string]: unknown
}

interface CouponItem {
  id: string
  code: string
  description: string | null
  discount_type: string
  discount_value: number
  duration_months: number | null
  usage_limit: number | null
  times_redeemed: number
  is_active: boolean
}

const STATUS_BADGE_MAP: Record<OrgStatus, { variant: 'success' | 'info' | 'warning' | 'error' | 'neutral'; label: string }> = {
  active: { variant: 'success', label: 'Active' },
  trial: { variant: 'info', label: 'Trial' },
  payment_pending: { variant: 'warning', label: 'Payment Pending' },
  suspended: { variant: 'warning', label: 'Suspended' },
  deleted: { variant: 'error', label: 'Deleted' },
}

const BILLING_BADGE_MAP: Record<BillingStatus, { variant: 'success' | 'info' | 'warning' | 'error' | 'neutral'; label: string }> = {
  current: { variant: 'success', label: 'Current' },
  trial: { variant: 'info', label: 'Trial' },
  overdue: { variant: 'warning', label: 'Overdue' },
  unpaid: { variant: 'error', label: 'Unpaid' },
}

/* ── Helpers ── */

function formatDate(iso: string | null): string {
  if (!iso) return '—'
  return new Date(iso).toLocaleDateString('en-NZ', {
    day: 'numeric',
    month: 'short',
    year: 'numeric',
  })
}

function formatStorage(usedGb: number, quotaGb: number): string {
  return `${usedGb.toFixed(1)} / ${quotaGb} GB`
}

/* ── Provision New Org Modal ── */

function ProvisionModal({
  open,
  onClose,
  onSave,
  saving,
  plans,
}: {
  open: boolean
  onClose: () => void
  onSave: (data: { name: string; plan_id: string; admin_email: string }) => void
  saving: boolean
  plans: Plan[]
}) {
  const [name, setName] = useState('')
  const [planId, setPlanId] = useState('')
  const [adminEmail, setAdminEmail] = useState('')
  const [errors, setErrors] = useState<Record<string, string>>({})

  useEffect(() => {
    if (open) {
      setName('')
      setPlanId(plans[0]?.id ?? '')
      setAdminEmail('')
      setErrors({})
    }
  }, [open, plans])

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault()
    const newErrors: Record<string, string> = {}
    if (!name.trim()) newErrors.name = 'Organisation name is required'
    if (!planId) newErrors.plan_id = 'Please select a plan'
    if (!adminEmail.trim()) newErrors.admin_email = 'Admin email is required'
    else if (!/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(adminEmail)) newErrors.admin_email = 'Please enter a valid email'
    if (Object.keys(newErrors).length > 0) {
      setErrors(newErrors)
      return
    }
    onSave({ name: name.trim(), plan_id: planId, admin_email: adminEmail.trim() })
  }

  return (
    <Modal open={open} onClose={onClose} title="Provision new organisation">
      <form onSubmit={handleSubmit} className="space-y-4">
        <Input
          label="Organisation name"
          value={name}
          onChange={(e) => setName(e.target.value)}
          error={errors.name}
        />
        <Select
          label="Subscription plan"
          options={plans.map((p) => ({ value: p.id, label: p.name }))}
          value={planId}
          onChange={(e) => setPlanId(e.target.value)}
          error={errors.plan_id}
        />
        <Input
          label="Org Admin email"
          type="email"
          value={adminEmail}
          onChange={(e) => setAdminEmail(e.target.value)}
          error={errors.admin_email}
          helperText="An invitation email will be sent to this address"
        />
        <div className="flex justify-end gap-3 pt-2">
          <Button type="button" variant="secondary" onClick={onClose}>Cancel</Button>
          <Button type="submit" loading={saving}>Provision organisation</Button>
        </div>
      </form>
    </Modal>
  )
}

/* ── Suspend Modal (requires reason) ── */

function SuspendModal({
  open,
  onClose,
  onConfirm,
  saving,
  orgName,
}: {
  open: boolean
  onClose: () => void
  onConfirm: (reason: string) => void
  saving: boolean
  orgName: string
}) {
  const [reason, setReason] = useState('')
  const [error, setError] = useState('')

  useEffect(() => {
    if (open) { setReason(''); setError('') }
  }, [open])

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault()
    if (!reason.trim()) { setError('A reason is required to suspend an organisation'); return }
    onConfirm(reason.trim())
  }

  return (
    <Modal open={open} onClose={onClose} title="Suspend organisation">
      <form onSubmit={handleSubmit} className="space-y-4">
        <p className="text-sm text-gray-600">
          You are about to suspend <span className="font-semibold">{orgName}</span>. All users will lose access immediately.
        </p>
        <Input
          label="Reason for suspension"
          value={reason}
          onChange={(e) => setReason(e.target.value)}
          error={error}
        />
        <div className="flex justify-end gap-3 pt-2">
          <Button type="button" variant="secondary" onClick={onClose}>Cancel</Button>
          <Button type="submit" variant="danger" loading={saving}>Suspend</Button>
        </div>
      </form>
    </Modal>
  )
}

/* ── Delete Modal (multi-step confirmation with reason) ── */

function DeleteModal({
  open,
  onClose,
  onConfirm,
  saving,
  orgName,
}: {
  open: boolean
  onClose: () => void
  onConfirm: (reason: string) => void
  saving: boolean
  orgName: string
}) {
  const [step, setStep] = useState<1 | 2>(1)
  const [reason, setReason] = useState('')
  const [confirmText, setConfirmText] = useState('')
  const [error, setError] = useState('')

  useEffect(() => {
    if (open) { setStep(1); setReason(''); setConfirmText(''); setError('') }
  }, [open])

  const handleStep1 = (e: React.FormEvent) => {
    e.preventDefault()
    if (!reason.trim()) { setError('A reason is required to delete an organisation'); return }
    setError('')
    setStep(2)
  }

  const handleStep2 = (e: React.FormEvent) => {
    e.preventDefault()
    if (confirmText !== orgName) { setError(`Please type "${orgName}" to confirm`); return }
    onConfirm(reason.trim())
  }

  return (
    <Modal open={open} onClose={onClose} title="Soft delete organisation">
      {step === 1 ? (
        <form onSubmit={handleStep1} className="space-y-4">
          <AlertBanner variant="warning" title="Soft delete (data retained)">
            Soft deleting <span className="font-semibold">{orgName}</span> will mark it as deleted but keep all data in the database. The organisation can potentially be recovered.
          </AlertBanner>
          <Input
            label="Reason for deletion"
            value={reason}
            onChange={(e) => setReason(e.target.value)}
            error={error}
          />
          <div className="flex justify-end gap-3 pt-2">
            <Button type="button" variant="secondary" onClick={onClose}>Cancel</Button>
            <Button type="submit" variant="danger">Continue</Button>
          </div>
        </form>
      ) : (
        <form onSubmit={handleStep2} className="space-y-4">
          <p className="text-sm text-gray-600">
            To confirm soft deletion, type the organisation name: <span className="font-semibold">{orgName}</span>
          </p>
          <Input
            label="Confirm organisation name"
            value={confirmText}
            onChange={(e) => setConfirmText(e.target.value)}
            error={error}
          />
          <div className="flex justify-end gap-3 pt-2">
            <Button type="button" variant="secondary" onClick={() => setStep(1)}>Back</Button>
            <Button type="submit" variant="danger" loading={saving}>Soft delete</Button>
          </div>
        </form>
      )}
    </Modal>
  )
}

/* ── Hard Delete Modal (permanent deletion with extra confirmation) ── */

function HardDeleteModal({
  open,
  onClose,
  onConfirm,
  saving,
  orgName,
}: {
  open: boolean
  onClose: () => void
  onConfirm: (reason: string) => void
  saving: boolean
  orgName: string
}) {
  const [step, setStep] = useState<1 | 2>(1)
  const [reason, setReason] = useState('')
  const [confirmText, setConfirmText] = useState('')
  const [error, setError] = useState('')

  useEffect(() => {
    if (open) { setStep(1); setReason(''); setConfirmText(''); setError('') }
  }, [open])

  const handleStep1 = (e: React.FormEvent) => {
    e.preventDefault()
    if (!reason.trim()) { setError('A reason is required for permanent deletion'); return }
    setError('')
    setStep(2)
  }

  const handleStep2 = (e: React.FormEvent) => {
    e.preventDefault()
    if (confirmText !== 'PERMANENTLY DELETE') { 
      setError('You must type "PERMANENTLY DELETE" exactly to confirm'); 
      return 
    }
    onConfirm(reason.trim())
  }

  return (
    <Modal open={open} onClose={onClose} title="⚠️ PERMANENT DELETION">
      {step === 1 ? (
        <form onSubmit={handleStep1} className="space-y-4">
          <AlertBanner variant="error" title="THIS ACTION CANNOT BE UNDONE">
            Permanently deleting <span className="font-semibold">{orgName}</span> will:
            <ul className="list-disc list-inside mt-2 space-y-1">
              <li>Remove ALL data from the database</li>
              <li>Delete all users, vehicles, customers, invoices</li>
              <li>Delete all quotes, bookings, and settings</li>
              <li>This is IRREVERSIBLE - data cannot be recovered</li>
            </ul>
          </AlertBanner>
          <Input
            label="Reason for permanent deletion"
            value={reason}
            onChange={(e) => setReason(e.target.value)}
            error={error}
            helperText="This will be logged for compliance"
          />
          <div className="flex justify-end gap-3 pt-2">
            <Button type="button" variant="secondary" onClick={onClose}>Cancel</Button>
            <Button type="submit" variant="danger">Continue</Button>
          </div>
        </form>
      ) : (
        <form onSubmit={handleStep2} className="space-y-4">
          <p className="text-sm text-gray-600 font-semibold">
            To confirm PERMANENT deletion, type exactly: <span className="font-mono bg-red-100 px-2 py-1 rounded">PERMANENTLY DELETE</span>
          </p>
          <Input
            label="Type to confirm"
            value={confirmText}
            onChange={(e) => setConfirmText(e.target.value)}
            error={error}
            placeholder="PERMANENTLY DELETE"
          />
          <div className="flex justify-end gap-3 pt-2">
            <Button type="button" variant="secondary" onClick={() => setStep(1)}>Back</Button>
            <Button type="submit" variant="danger" loading={saving}>⚠️ DELETE PERMANENTLY</Button>
          </div>
        </form>
      )}
    </Modal>
  )
}

/* ── Move Plan Modal ── */

function MovePlanModal({
  open,
  onClose,
  onConfirm,
  saving,
  orgName,
  currentPlanId,
  plans,
}: {
  open: boolean
  onClose: () => void
  onConfirm: (planId: string) => void
  saving: boolean
  orgName: string
  currentPlanId: string
  plans: Plan[]
}) {
  const [planId, setPlanId] = useState('')
  const [error, setError] = useState('')

  useEffect(() => {
    if (open) { setPlanId(''); setError('') }
  }, [open])

  const availablePlans = plans.filter((p) => p.id !== currentPlanId)

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault()
    if (!planId) { setError('Please select a new plan'); return }
    onConfirm(planId)
  }

  return (
    <Modal open={open} onClose={onClose} title="Move to different plan">
      <form onSubmit={handleSubmit} className="space-y-4">
        <p className="text-sm text-gray-600">
          Change the subscription plan for <span className="font-semibold">{orgName}</span>.
        </p>
        <Select
          label="New plan"
          options={availablePlans.map((p) => ({ value: p.id, label: p.name }))}
          value={planId}
          onChange={(e) => setPlanId(e.target.value)}
          placeholder="Select a plan"
          error={error}
        />
        <div className="flex justify-end gap-3 pt-2">
          <Button type="button" variant="secondary" onClick={onClose}>Cancel</Button>
          <Button type="submit" loading={saving}>Move plan</Button>
        </div>
      </form>
    </Modal>
  )
}

/* ── Billing Date Modal ── */

function BillingDateModal({
  open,
  onClose,
  onConfirm,
  saving,
  orgName,
  currentDate,
}: {
  open: boolean
  onClose: () => void
  onConfirm: (date: string) => void
  saving: boolean
  orgName: string
  currentDate: string | null
}) {
  const [date, setDate] = useState('')
  const [error, setError] = useState('')

  useEffect(() => {
    if (open) {
      setDate(currentDate ? currentDate.split('T')[0] : '')
      setError('')
    }
  }, [open, currentDate])

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault()
    if (!date) { setError('Please select a billing date'); return }
    onConfirm(date)
  }

  return (
    <Modal open={open} onClose={onClose} title="Set next billing date">
      <form onSubmit={handleSubmit} className="space-y-4">
        <p className="text-sm text-gray-600">
          Set or change the next billing date for <span className="font-semibold">{orgName}</span>.
          {currentDate && (
            <span className="block mt-1 text-gray-500">
              Current: {new Date(currentDate).toLocaleDateString('en-NZ', { day: 'numeric', month: 'short', year: 'numeric' })}
            </span>
          )}
        </p>
        <Input
          label="Next billing date"
          type="date"
          value={date}
          onChange={(e) => setDate(e.target.value)}
          error={error}
        />
        <div className="flex justify-end gap-3 pt-2">
          <Button type="button" variant="secondary" onClick={onClose}>Cancel</Button>
          <Button type="submit" loading={saving}>Save date</Button>
        </div>
      </form>
    </Modal>
  )
}

/* ── Apply Coupon Modal ── */

function generateBenefitDescription(discountType: string, discountValue: number, durationMonths: number | null): string {
  const formatted = discountValue % 1 === 0 ? String(Math.floor(discountValue)) : discountValue.toFixed(2)
  if (discountType === 'percentage') {
    const duration = durationMonths ? `for ${durationMonths} months` : 'ongoing'
    return `${formatted}% discount on your subscription ${duration}`
  }
  if (discountType === 'fixed_amount') {
    const duration = durationMonths ? `for ${durationMonths} months` : 'ongoing'
    return `$${formatted} off per billing cycle ${duration}`
  }
  if (discountType === 'trial_extension') {
    return `Trial extended by ${formatted} days`
  }
  return `Coupon applied (type: ${discountType})`
}

interface ApplyCouponModalProps {
  open: boolean
  onClose: () => void
  onSuccess: () => void
  orgName: string
  orgId: string
}

function ApplyCouponModal({ open, onClose, onSuccess, orgName, orgId }: ApplyCouponModalProps) {
  const [coupons, setCoupons] = useState<CouponItem[]>([])
  const [search, setSearch] = useState('')
  const [selectedCouponId, setSelectedCouponId] = useState<string | null>(null)
  const [loading, setLoading] = useState(false)
  const [applying, setApplying] = useState(false)
  const [error, setError] = useState('')

  useEffect(() => {
    if (!open) return
    const controller = new AbortController()
    const fetchCoupons = async () => {
      setLoading(true)
      setError('')
      setSearch('')
      setSelectedCouponId(null)
      try {
        const res = await apiClient.get<{ coupons: CouponItem[] }>('/admin/coupons', { signal: controller.signal })
        setCoupons(res.data?.coupons ?? [])
      } catch (err: unknown) {
        if (!controller.signal.aborted) {
          setError('Failed to load coupons')
        }
      } finally {
        if (!controller.signal.aborted) {
          setLoading(false)
        }
      }
    }
    fetchCoupons()
    return () => controller.abort()
  }, [open])

  const filteredCoupons = useMemo(() => {
    if (!search.trim()) return coupons
    const q = search.toLowerCase()
    return (coupons ?? []).filter(
      (c) =>
        c.code.toLowerCase().includes(q) ||
        (c.description ?? '').toLowerCase().includes(q),
    )
  }, [coupons, search])

  const selectedCoupon = useMemo(
    () => (coupons ?? []).find((c) => c.id === selectedCouponId) ?? null,
    [coupons, selectedCouponId],
  )

  const handleApply = async () => {
    if (!selectedCouponId) return
    setApplying(true)
    setError('')
    try {
      await apiClient.post<{ message: string; organisation_coupon_id: string; coupon_code: string; benefit_description: string }>(
        `/admin/organisations/${orgId}/apply-coupon`,
        { coupon_id: selectedCouponId },
      )
      onSuccess()
    } catch (err: unknown) {
      const axiosErr = err as { response?: { status?: number; data?: { detail?: string } } }
      const status = axiosErr?.response?.status
      const detail = axiosErr?.response?.data?.detail
      if (status === 409) {
        setError('This coupon has already been applied to this organisation')
      } else if (detail) {
        setError(detail)
      } else {
        setError('Failed to apply coupon. Please try again.')
      }
    } finally {
      setApplying(false)
    }
  }

  return (
    <Modal open={open} onClose={onClose} title={`Apply coupon to ${orgName}`}>
      <div className="space-y-4">
        {/* Search input */}
        <Input
          label="Search coupons"
          placeholder="Search by code or description..."
          value={search}
          onChange={(e) => setSearch(e.target.value)}
        />

        {/* Error banner */}
        {error && <div className="text-sm text-red-600 bg-red-50 p-3 rounded">{error}</div>}

        {/* Loading state */}
        {loading && (
          <div className="flex justify-center py-4">
            <Spinner label="Loading coupons" />
          </div>
        )}

        {/* Coupon list */}
        {!loading && (
          <div className="max-h-64 overflow-y-auto border rounded divide-y">
            {(filteredCoupons ?? []).map((coupon) => (
              <div
                key={coupon.id}
                className={`p-3 cursor-pointer hover:bg-gray-50 ${selectedCouponId === coupon.id ? 'bg-blue-50 border-l-4 border-blue-500' : ''}`}
                onClick={() => setSelectedCouponId(coupon.id)}
              >
                <div className="flex items-center justify-between">
                  <span className="font-medium text-sm">{coupon.code}</span>
                  <Badge variant="neutral">{coupon.discount_type}</Badge>
                </div>
                <p className="text-xs text-gray-500 mt-1">{coupon.description ?? 'No description'}</p>
                <div className="flex gap-4 text-xs text-gray-400 mt-1">
                  <span>Value: {coupon.discount_type === 'percentage' ? `${coupon.discount_value}%` : `$${coupon.discount_value}`}</span>
                  <span>Remaining: {coupon.usage_limit != null ? Math.max(0, (coupon.usage_limit ?? 0) - (coupon.times_redeemed ?? 0)) : 'Unlimited'}</span>
                </div>
              </div>
            ))}
            {filteredCoupons.length === 0 && !loading && (
              <p className="text-sm text-gray-500 p-4 text-center">No coupons found</p>
            )}
          </div>
        )}

        {/* Benefit preview */}
        {selectedCoupon && (
          <div className="bg-gray-50 p-3 rounded text-sm">
            <span className="font-medium">Benefit: </span>
            {generateBenefitDescription(selectedCoupon.discount_type, selectedCoupon.discount_value, selectedCoupon.duration_months)}
          </div>
        )}

        {/* Actions */}
        <div className="flex justify-end gap-3 pt-2">
          <Button type="button" variant="secondary" onClick={onClose}>Cancel</Button>
          <Button onClick={handleApply} loading={applying} disabled={!selectedCouponId || applying}>Apply coupon</Button>
        </div>
      </div>
    </Modal>
  )
}

/* ── Main Page ── */

export function Organisations() {
  const [orgs, setOrgs] = useState<Organisation[]>([])
  const [plans, setPlans] = useState<Plan[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(false)
  const [search, setSearch] = useState('')
  const [statusFilter, setStatusFilter] = useState<string>('')

  // Modal state
  const [provisionOpen, setProvisionOpen] = useState(false)
  const [suspendOrg, setSuspendOrg] = useState<Organisation | null>(null)
  const [deleteOrg, setDeleteOrg] = useState<Organisation | null>(null)
  const [hardDeleteOrg, setHardDeleteOrg] = useState<Organisation | null>(null)
  const [movePlanOrg, setMovePlanOrg] = useState<Organisation | null>(null)
  const [billingDateOrg, setBillingDateOrg] = useState<Organisation | null>(null)
  const [applyCouponOrg, setApplyCouponOrg] = useState<Organisation | null>(null)
  const [saving, setSaving] = useState(false)

  const { toasts, addToast, dismissToast } = useToast()

  const fetchData = async () => {
    setLoading(true)
    setError(false)
    try {
      const [orgsRes, plansRes] = await Promise.all([
        apiClient.get<{ organisations: Array<Record<string, any>>; total: number }>('/admin/organisations'),
        apiClient.get<{ plans: Plan[]; total: number }>('/admin/plans'),
      ])
      setOrgs((orgsRes.data.organisations ?? []).map((o) => ({
        id: o.id,
        name: o.name,
        plan_name: o.plan_name,
        plan_id: o.plan_id,
        status: o.status as OrgStatus,
        billing_status: (o.status === 'active' ? 'current' : o.status === 'trial' ? 'trial' : 'overdue') as BillingStatus,
        signup_date: o.created_at,
        storage_used_gb: Math.round((o.storage_used_bytes ?? 0) / (1024 * 1024 * 1024) * 10) / 10,
        storage_quota_gb: o.storage_quota_gb,
        last_login: o.last_login_at || null,
        next_billing_date: o.next_billing_date ?? null,
        billing_interval: o.billing_interval ?? 'monthly',
      })))
      setPlans(plansRes.data.plans)
    } catch {
      setError(true)
      addToast('error', 'Failed to load organisations')
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => { fetchData() }, [])

  const filteredOrgs = useMemo(() => {
    let result = orgs
    if (search.trim()) {
      const q = search.toLowerCase()
      result = result.filter(
        (o) =>
          o.name.toLowerCase().includes(q) ||
          o.plan_name.toLowerCase().includes(q),
      )
    }
    if (statusFilter) {
      result = result.filter((o) => o.status === statusFilter)
    }
    return result
  }, [orgs, search, statusFilter])

  /* ── Actions ── */

  const handleProvision = async (data: { name: string; plan_id: string; admin_email: string }) => {
    setSaving(true)
    try {
      await apiClient.post('/admin/organisations', data)
      addToast('success', `Organisation "${data.name}" provisioned`)
      setProvisionOpen(false)
      fetchData()
    } catch {
      addToast('error', 'Failed to provision organisation')
    } finally {
      setSaving(false)
    }
  }

  const handleSuspend = async (reason: string) => {
    if (!suspendOrg) return
    setSaving(true)
    try {
      await apiClient.put(`/admin/organisations/${suspendOrg.id}`, { action: 'suspend', reason })
      addToast('success', `Organisation "${suspendOrg.name}" suspended`)
      setSuspendOrg(null)
      fetchData()
    } catch {
      addToast('error', 'Failed to suspend organisation')
    } finally {
      setSaving(false)
    }
  }

  const handleReinstate = async (org: Organisation) => {
    try {
      await apiClient.put(`/admin/organisations/${org.id}`, { action: 'reinstate' })
      addToast('success', `Organisation "${org.name}" reinstated`)
      fetchData()
    } catch {
      addToast('error', 'Failed to reinstate organisation')
    }
  }

  const handleDelete = async (reason: string) => {
    if (!deleteOrg) return
    setSaving(true)
    try {
      // Step 1: Request deletion (get confirmation token)
      const res = await apiClient.put(`/admin/organisations/${deleteOrg.id}`, {
        action: 'delete_request',
        reason,
      })
      const token = res.data.confirmation_token
      // Step 2: Confirm deletion
      await apiClient.delete(`/admin/organisations/${deleteOrg.id}`, {
        data: { reason, confirmation_token: token },
      })
      addToast('success', `Organisation "${deleteOrg.name}" soft deleted`)
      setDeleteOrg(null)
      fetchData()
    } catch {
      addToast('error', 'Failed to delete organisation')
    } finally {
      setSaving(false)
    }
  }

  const handleHardDelete = async (reason: string) => {
    if (!hardDeleteOrg) return
    setSaving(true)
    try {
      // Step 1: Request hard deletion (get confirmation token)
      const res = await apiClient.put(`/admin/organisations/${hardDeleteOrg.id}`, {
        action: 'hard_delete_request',
        reason,
      })
      const token = res.data.confirmation_token
      // Step 2: Confirm hard deletion
      await apiClient.delete(`/admin/organisations/${hardDeleteOrg.id}/hard`, {
        data: { 
          reason, 
          confirmation_token: token,
          confirm_text: 'PERMANENTLY DELETE',
        },
      })
      addToast('success', `Organisation "${hardDeleteOrg.name}" permanently deleted`)
      // Immediately remove from UI without refetching
      setOrgs((prev) => prev.filter((o) => o.id !== hardDeleteOrg.id))
      setHardDeleteOrg(null)
    } catch (err: any) {
      const errorMsg = err?.response?.data?.detail || 'Failed to permanently delete organisation'
      addToast('error', errorMsg)
    } finally {
      setSaving(false)
    }
  }

  const handleMovePlan = async (planId: string) => {
    if (!movePlanOrg) return
    setSaving(true)
    try {
      await apiClient.put(`/admin/organisations/${movePlanOrg.id}`, {
        action: 'move_plan',
        new_plan_id: planId,
      })
      addToast('success', `Organisation "${movePlanOrg.name}" moved to new plan`)
      setMovePlanOrg(null)
      fetchData()
    } catch {
      addToast('error', 'Failed to move organisation to new plan')
    } finally {
      setSaving(false)
    }
  }

  const handleSetBillingDate = async (date: string) => {
    if (!billingDateOrg) return
    setSaving(true)
    try {
      await apiClient.put(`/admin/organisations/${billingDateOrg.id}`, {
        action: 'set_billing_date',
        next_billing_date: date,
      })
      addToast('success', `Billing date updated for "${billingDateOrg.name}"`)
      setBillingDateOrg(null)
      fetchData()
    } catch {
      addToast('error', 'Failed to update billing date')
    } finally {
      setSaving(false)
    }
  }

  const handleApplyCouponSuccess = () => {
    addToast('success', `Coupon applied to ${applyCouponOrg?.name}`)
    setApplyCouponOrg(null)
    fetchData()
  }

  /* ── Table columns ── */

  const columns: Column<Organisation>[] = [
    { key: 'name', header: 'Organisation', sortable: true },
    { key: 'plan_name', header: 'Plan', sortable: true },
    {
      key: 'status',
      header: 'Status',
      sortable: true,
      render: (row) => {
        const badge = STATUS_BADGE_MAP[row.status] ?? { variant: 'neutral' as const, label: row.status }
        return <Badge variant={badge.variant}>{badge.label}</Badge>
      },
    },
    {
      key: 'signup_date',
      header: 'Signup date',
      sortable: true,
      render: (row) => formatDate(row.signup_date),
    },
    {
      key: 'next_billing_date',
      header: 'Next billing',
      sortable: true,
      render: (row) => row.next_billing_date ? formatDate(row.next_billing_date) : '—',
    },
    {
      key: 'billing_status',
      header: 'Billing',
      sortable: true,
      render: (row) => {
        const badge = BILLING_BADGE_MAP[row.billing_status] ?? { variant: 'neutral' as const, label: row.billing_status }
        return <Badge variant={badge.variant}>{badge.label}</Badge>
      },
    },
    {
      key: 'storage_used_gb',
      header: 'Storage',
      sortable: true,
      render: (row) => formatStorage(row.storage_used_gb, row.storage_quota_gb),
    },
    {
      key: 'last_login',
      header: 'Last login',
      sortable: true,
      render: (row) => formatDate(row.last_login),
    },
    {
      key: 'id',
      header: 'Actions',
      render: (row) => (
        <div className="flex gap-2 flex-wrap">
          {row.status !== 'suspended' && row.status !== 'deleted' && (
            <Button size="sm" variant="secondary" onClick={() => setSuspendOrg(row)}>
              Suspend
            </Button>
          )}
          {row.status === 'suspended' && (
            <Button size="sm" variant="secondary" onClick={() => handleReinstate(row)}>
              Reinstate
            </Button>
          )}
          {row.status !== 'deleted' && (
            <Button size="sm" variant="secondary" onClick={() => setMovePlanOrg(row)}>
              Move plan
            </Button>
          )}
          {row.status !== 'deleted' && (
            <Button size="sm" variant="secondary" onClick={() => setBillingDateOrg(row)}>
              Billing date
            </Button>
          )}
          {row.status !== 'deleted' && (
            <Button size="sm" variant="secondary" onClick={() => setApplyCouponOrg(row)}>
              Apply Coupon
            </Button>
          )}
          {row.status !== 'deleted' && (
            <>
              <Button size="sm" variant="danger" onClick={() => setDeleteOrg(row)}>
                Soft Delete
              </Button>
              <Button size="sm" variant="danger" onClick={() => setHardDeleteOrg(row)}>
                Hard Delete
              </Button>
            </>
          )}
        </div>
      ),
    },
  ]

  /* ── Render ── */

  if (loading) {
    return (
      <div className="flex items-center justify-center py-20">
        <Spinner label="Loading organisations" />
      </div>
    )
  }

  if (error && orgs.length === 0) {
    return (
      <AlertBanner variant="error" title="Something went wrong">
        We couldn't load the organisations list. Please refresh the page or try again later.
      </AlertBanner>
    )
  }

  return (
    <div>
      <div className="flex items-center justify-between mb-6">
        <h1 className="text-2xl font-semibold text-gray-900">Organisations</h1>
        <div className="flex gap-2">
          <Button variant="secondary" onClick={async () => {
            if (!confirm('Reset the Demo Workshop account? This will delete all demo data (invoices, customers, vehicles, SMS) and reset the password to demo123.')) return
            try {
              await apiClient.post('/admin/demo/reset')
              addToast('success', 'Demo account reset successfully')
              fetchData()
            } catch {
              addToast('error', 'Failed to reset demo account')
            }
          }}>
            Reset Demo Account
          </Button>
          <Button onClick={() => setProvisionOpen(true)}>Provision new organisation</Button>
        </div>
      </div>

      <ToastContainer toasts={toasts} onDismiss={dismissToast} />

      <div className="flex flex-col sm:flex-row gap-3 mb-4">
        <Input
          label="Search organisations"
          placeholder="Search by name or plan..."
          value={search}
          onChange={(e) => setSearch(e.target.value)}
          className="sm:w-72"
        />
        <Select
          label="Filter by status"
          options={[
            { value: '', label: 'All statuses' },
            { value: 'active', label: 'Active' },
            { value: 'trial', label: 'Trial' },
            { value: 'suspended', label: 'Suspended' },
            { value: 'deleted', label: 'Deleted' },
          ]}
          value={statusFilter}
          onChange={(e) => setStatusFilter(e.target.value)}
        />
      </div>

      <DataTable
        columns={columns}
        data={filteredOrgs}
        keyField="id"
        caption="Organisations management table"
      />

      {/* Modals */}
      <ProvisionModal
        open={provisionOpen}
        onClose={() => setProvisionOpen(false)}
        onSave={handleProvision}
        saving={saving}
        plans={plans}
      />
      <SuspendModal
        open={!!suspendOrg}
        onClose={() => setSuspendOrg(null)}
        onConfirm={handleSuspend}
        saving={saving}
        orgName={suspendOrg?.name ?? ''}
      />
      <DeleteModal
        open={!!deleteOrg}
        onClose={() => setDeleteOrg(null)}
        onConfirm={handleDelete}
        saving={saving}
        orgName={deleteOrg?.name ?? ''}
      />
      <HardDeleteModal
        open={!!hardDeleteOrg}
        onClose={() => setHardDeleteOrg(null)}
        onConfirm={handleHardDelete}
        saving={saving}
        orgName={hardDeleteOrg?.name ?? ''}
      />
      <MovePlanModal
        open={!!movePlanOrg}
        onClose={() => setMovePlanOrg(null)}
        onConfirm={handleMovePlan}
        saving={saving}
        orgName={movePlanOrg?.name ?? ''}
        currentPlanId={movePlanOrg?.plan_id ?? ''}
        plans={plans}
      />
      <BillingDateModal
        open={!!billingDateOrg}
        onClose={() => setBillingDateOrg(null)}
        onConfirm={handleSetBillingDate}
        saving={saving}
        orgName={billingDateOrg?.name ?? ''}
        currentDate={billingDateOrg?.next_billing_date ?? null}
      />
      <ApplyCouponModal
        open={!!applyCouponOrg}
        onClose={() => setApplyCouponOrg(null)}
        onSuccess={handleApplyCouponSuccess}
        orgName={applyCouponOrg?.name ?? ''}
        orgId={applyCouponOrg?.id ?? ''}
      />
    </div>
  )
}
