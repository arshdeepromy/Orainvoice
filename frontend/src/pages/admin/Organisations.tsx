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

export type OrgStatus = 'active' | 'trial' | 'suspended' | 'deleted'
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
  [key: string]: unknown
}

export interface Plan {
  id: string
  name: string
  [key: string]: unknown
}

const STATUS_BADGE_MAP: Record<OrgStatus, { variant: 'success' | 'info' | 'warning' | 'error' | 'neutral'; label: string }> = {
  active: { variant: 'success', label: 'Active' },
  trial: { variant: 'info', label: 'Trial' },
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
    <Modal open={open} onClose={onClose} title="Delete organisation">
      {step === 1 ? (
        <form onSubmit={handleStep1} className="space-y-4">
          <AlertBanner variant="error" title="This action is permanent">
            Deleting <span className="font-semibold">{orgName}</span> will permanently remove all data including customers, invoices, and settings. This cannot be undone.
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
            To confirm deletion, type the organisation name: <span className="font-semibold">{orgName}</span>
          </p>
          <Input
            label="Confirm organisation name"
            value={confirmText}
            onChange={(e) => setConfirmText(e.target.value)}
            error={error}
          />
          <div className="flex justify-end gap-3 pt-2">
            <Button type="button" variant="secondary" onClick={() => setStep(1)}>Back</Button>
            <Button type="submit" variant="danger" loading={saving}>Delete permanently</Button>
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
  const [movePlanOrg, setMovePlanOrg] = useState<Organisation | null>(null)
  const [saving, setSaving] = useState(false)

  const { toasts, addToast, dismissToast } = useToast()

  const fetchData = async () => {
    setLoading(true)
    setError(false)
    try {
      const [orgsRes, plansRes] = await Promise.all([
        apiClient.get<Organisation[]>('/admin/organisations'),
        apiClient.get<Plan[]>('/admin/plans'),
      ])
      setOrgs(orgsRes.data)
      setPlans(plansRes.data)
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
      await apiClient.put(`/admin/organisations/${suspendOrg.id}`, { status: 'suspended', reason })
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
      await apiClient.put(`/admin/organisations/${org.id}`, { status: 'active' })
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
      await apiClient.delete(`/admin/organisations/${deleteOrg.id}`, { data: { reason } })
      addToast('success', `Organisation "${deleteOrg.name}" deleted`)
      setDeleteOrg(null)
      fetchData()
    } catch {
      addToast('error', 'Failed to delete organisation')
    } finally {
      setSaving(false)
    }
  }

  const handleMovePlan = async (planId: string) => {
    if (!movePlanOrg) return
    setSaving(true)
    try {
      await apiClient.put(`/admin/organisations/${movePlanOrg.id}`, { plan_id: planId })
      addToast('success', `Organisation "${movePlanOrg.name}" moved to new plan`)
      setMovePlanOrg(null)
      fetchData()
    } catch {
      addToast('error', 'Failed to move organisation to new plan')
    } finally {
      setSaving(false)
    }
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
        <div className="flex gap-2">
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
            <Button size="sm" variant="danger" onClick={() => setDeleteOrg(row)}>
              Delete
            </Button>
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
        <Button onClick={() => setProvisionOpen(true)}>Provision new organisation</Button>
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
      <MovePlanModal
        open={!!movePlanOrg}
        onClose={() => setMovePlanOrg(null)}
        onConfirm={handleMovePlan}
        saving={saving}
        orgName={movePlanOrg?.name ?? ''}
        currentPlanId={movePlanOrg?.plan_id ?? ''}
        plans={plans}
      />
    </div>
  )
}
