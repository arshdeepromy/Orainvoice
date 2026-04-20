import { useState, useEffect, useMemo } from 'react'
import { Modal } from '@/components/ui/Modal'
import { Input } from '@/components/ui/Input'
import { Button } from '@/components/ui/Button'
import { Badge } from '@/components/ui/Badge'
import { Spinner } from '@/components/ui/Spinner'
import apiClient from '@/api/client'

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

function generateBenefitDescription(discountType: string, discountValue: number, durationMonths: number | null): string {
  const formatted = discountValue % 1 === 0 ? String(Math.floor(discountValue)) : discountValue.toFixed(2)
  if (discountType === 'percentage') {
    const duration = durationMonths ? `for ${durationMonths} months` : 'ongoing'
    return `${formatted}% discount on your subscription ${duration}`
  }
  if (discountType === 'fixed_amount') {
    const duration = durationMonths ? `for ${durationMonths} months` : 'ongoing'
    return `${formatted} off per billing cycle ${duration}`
  }
  if (discountType === 'trial_extension') {
    return `Trial extended by ${formatted} days`
  }
  return `Coupon applied (type: ${discountType})`
}

export interface ApplyCouponModalProps {
  open: boolean
  onClose: () => void
  onSuccess: () => void
  orgName: string
  orgId: string
}

export function ApplyCouponModal({ open, onClose, onSuccess, orgName, orgId }: ApplyCouponModalProps) {
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
                  <span>Value: {coupon.discount_type === 'percentage' ? `${coupon.discount_value}%` : `${coupon.discount_value}`}</span>
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
