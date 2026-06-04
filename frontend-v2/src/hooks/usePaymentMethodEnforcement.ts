/**
 * Hook: usePaymentMethodEnforcement
 *
 * Checks whether the current org_admin's organisation has a valid payment
 * method on file. Returns enforcement state consumed by OrgLayout to render
 * a blocking modal (no card) or a warning modal (card expiring within 30 days).
 *
 * Non-org_admin roles skip the check entirely (fail-open).
 *
 * Requirements: 1.1, 1.2, 1.4, 1.5, 1.6, 5.1, 5.2, 5.3, 5.4, 5.5, 5.6
 */

import { useState, useEffect, useCallback, useRef } from 'react'
import { useAuth } from '@/contexts/AuthContext'
import apiClient from '@/api/client'

/* ------------------------------------------------------------------ */
/*  Types                                                              */
/* ------------------------------------------------------------------ */

export interface ExpiringMethod {
  brand: string
  last4: string
  exp_month: number
  exp_year: number
}

export interface PaymentMethodStatus {
  has_payment_method: boolean
  has_expiring_soon: boolean
  expiring_method: ExpiringMethod | null
}

export interface EnforcementState {
  showBlockingModal: boolean
  showWarningModal: boolean
  expiringMethod: ExpiringMethod | null
  loading: boolean
  dismissWarning: () => void
  refetchStatus: () => void
}

/* ------------------------------------------------------------------ */
/*  Hook                                                               */
/* ------------------------------------------------------------------ */

export function usePaymentMethodEnforcement(): EnforcementState {
  const { user } = useAuth()

  const [showBlockingModal, setShowBlockingModal] = useState(false)
  const [showWarningModal, setShowWarningModal] = useState(false)
  const [expiringMethod, setExpiringMethod] = useState<ExpiringMethod | null>(null)
  const [loading, setLoading] = useState(false)

  // Track the current AbortController so refetchStatus can abort a prior request
  const abortRef = useRef<AbortController | undefined>(undefined)

  // Trigger counter — incrementing this re-fires the useEffect fetch
  const [fetchTrigger, setFetchTrigger] = useState(0)

  const isOrgAdmin = user?.role === 'org_admin'

  useEffect(() => {
    // Requirement 1.2 / 5.1-5.6: only org_admin fetches status
    if (!isOrgAdmin) {
      setShowBlockingModal(false)
      setShowWarningModal(false)
      setExpiringMethod(null)
      setLoading(false)
      return
    }

    // Requirement 1.5: AbortController cleanup (ISSUE-014 pattern)
    const controller = new AbortController()
    abortRef.current = controller

    const fetchStatus = async () => {
      setLoading(true)
      try {
        const res = await apiClient.get<PaymentMethodStatus>(
          '/billing/payment-method-status',
          { signal: controller.signal },
        )

        // Requirement 1.6: guard all response access with ?. and ?? fallback
        const hasPaymentMethod = res.data?.has_payment_method ?? true
        const hasExpiringSoon = res.data?.has_expiring_soon ?? false
        const expiring = res.data?.expiring_method ?? null

        setShowBlockingModal(!hasPaymentMethod)
        setShowWarningModal(hasPaymentMethod && hasExpiringSoon)
        setExpiringMethod(expiring)
      } catch (err: unknown) {
        // Requirement 1.4: fail-open on API error — user proceeds normally
        if (!controller.signal.aborted) {
          console.error('[PaymentMethodEnforcement] Status check failed:', err)
          setShowBlockingModal(false)
          setShowWarningModal(false)
          setExpiringMethod(null)
        }
      } finally {
        if (!controller.signal.aborted) {
          setLoading(false)
        }
      }
    }

    fetchStatus()

    return () => {
      controller.abort()
    }
  }, [isOrgAdmin, fetchTrigger])

  /** Dismiss the warning modal for the current session. */
  const dismissWarning = useCallback(() => {
    setShowWarningModal(false)
  }, [])

  /** Re-fetch payment method status (e.g. after adding a card). */
  const refetchStatus = useCallback(() => {
    setFetchTrigger((prev) => prev + 1)
  }, [])

  return {
    showBlockingModal,
    showWarningModal,
    expiringMethod,
    loading,
    dismissWarning,
    refetchStatus,
  }
}
