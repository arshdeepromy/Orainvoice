/**
 * OnlinePaymentsSettings — Stripe Connect settings page for org admins.
 *
 * Tasks 5.1–5.4: Status display, conditional rendering, OAuth connect flow,
 * and disconnect flow with confirmation dialog.
 */
import { useState, useEffect, useCallback } from 'react'
import { useSearchParams } from 'react-router-dom'
import { Button } from '@/components/ui/Button'
import { Badge } from '@/components/ui/Badge'
import { Spinner } from '@/components/ui/Spinner'
import { AlertBanner } from '@/components/ui/AlertBanner'
import { Modal } from '@/components/ui/Modal'
import apiClient from '@/api/client'

/* ── Types ── */

interface OnlinePaymentsStatus {
  is_connected: boolean
  account_id_last4: string
  connect_client_id_configured: boolean
  application_fee_percent: number | null
}

/* ── Component ── */

export default function OnlinePaymentsSettings() {
  const [searchParams, setSearchParams] = useSearchParams()
  const [status, setStatus] = useState<OnlinePaymentsStatus | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [showDisconnectDialog, setShowDisconnectDialog] = useState(false)
  const [connecting, setConnecting] = useState(false)
  const [disconnecting, setDisconnecting] = useState(false)
  const [callbackProcessing, setCallbackProcessing] = useState(false)

  /* ── Fetch status ── */

  const fetchStatus = useCallback(async (signal?: AbortSignal) => {
    try {
      const res = await apiClient.get<OnlinePaymentsStatus>(
        '/payments/online-payments/status',
        { signal },
      )
      setStatus({
        is_connected: res.data?.is_connected ?? false,
        account_id_last4: res.data?.account_id_last4 ?? '',
        connect_client_id_configured: res.data?.connect_client_id_configured ?? false,
        application_fee_percent: res.data?.application_fee_percent ?? null,
      })
      setError(null)
    } catch (err) {
      if (!(err as { name?: string })?.name?.includes('Cancel')) {
        setError('Failed to load online payments status.')
      }
    } finally {
      setLoading(false)
    }
  }, [])

  /* ── Initial load + OAuth callback detection ── */

  useEffect(() => {
    const controller = new AbortController()

    const code = searchParams.get('code')
    const state = searchParams.get('state')

    if (code && state) {
      // OAuth callback — exchange code for account connection
      setCallbackProcessing(true)
      const handleCallback = async () => {
        try {
          await apiClient.get<{ stripe_account_id: string; org_id: string }>(
            '/billing/stripe/connect/callback',
            { params: { code, state }, signal: controller.signal },
          )
          // Clear query params without full page reload
          setSearchParams({}, { replace: true })
          // Re-fetch status to show "Connected"
          await fetchStatus(controller.signal)
        } catch (err) {
          if (!(err as { name?: string })?.name?.includes('Cancel')) {
            const axiosErr = err as { response?: { data?: { detail?: string } } }
            const detail = axiosErr.response?.data?.detail
            setError(detail ?? 'Failed to connect Stripe account. Please try again.')
            // Clear query params even on error
            setSearchParams({}, { replace: true })
          }
        } finally {
          setCallbackProcessing(false)
          setLoading(false)
        }
      }
      handleCallback()
    } else {
      fetchStatus(controller.signal)
    }

    return () => controller.abort()
  }, []) // eslint-disable-line react-hooks/exhaustive-deps

  /* ── OAuth connect flow ── */

  const handleConnect = async () => {
    setConnecting(true)
    setError(null)
    try {
      const res = await apiClient.post<{ authorize_url: string }>(
        '/billing/stripe/connect',
      )
      const authorizeUrl = res.data?.authorize_url
      if (authorizeUrl) {
        window.location.href = authorizeUrl
      } else {
        setError('No authorization URL returned. Please try again.')
      }
    } catch (err) {
      const axiosErr = err as { response?: { data?: { detail?: string } } }
      const detail = axiosErr.response?.data?.detail
      setError(detail ?? 'Failed to initiate Stripe connection. Please try again.')
    } finally {
      setConnecting(false)
    }
  }

  /* ── Disconnect flow ── */

  const handleDisconnect = async () => {
    setDisconnecting(true)
    setError(null)
    setShowDisconnectDialog(false)
    try {
      await apiClient.post<{ message: string; previous_account_last4: string }>(
        '/payments/online-payments/disconnect',
      )
      // Re-fetch status to show "Not Connected"
      await fetchStatus()
    } catch (err) {
      const axiosErr = err as { response?: { data?: { detail?: string } } }
      const detail = axiosErr.response?.data?.detail
      setError(detail ?? 'Failed to disconnect Stripe account. Please try again.')
    } finally {
      setDisconnecting(false)
    }
  }

  /* ── Render ── */

  if (loading || callbackProcessing) {
    return (
      <div className="flex items-center justify-center py-12">
        <Spinner size="lg" label={callbackProcessing ? 'Connecting Stripe account…' : 'Loading online payments settings'} />
      </div>
    )
  }

  return (
    <div className="space-y-6 max-w-3xl">
      <div>
        <h2 className="text-lg font-semibold text-gray-900">Online Payments</h2>
        <p className="text-sm text-gray-600 mt-1">
          Accept online payments from customers via Stripe. Payments are deposited directly into your connected Stripe account.
        </p>
      </div>

      {error && (
        <AlertBanner variant="error" onDismiss={() => setError(null)}>
          {error}
        </AlertBanner>
      )}

      {/* Not configured by platform admin */}
      {!status?.connect_client_id_configured && (
        <div className="rounded-lg border border-gray-200 p-5">
          <div className="flex items-center justify-between mb-3">
            <h3 className="text-lg font-semibold text-gray-900">Stripe</h3>
            <Badge variant="neutral">Unavailable</Badge>
          </div>
          <AlertBanner variant="info">
            Online payments are not available. Contact your platform administrator to configure Stripe Connect.
          </AlertBanner>
        </div>
      )}

      {/* Configured but not connected */}
      {status?.connect_client_id_configured && !status?.is_connected && (
        <div className="rounded-lg border border-gray-200 p-5">
          <div className="flex items-center justify-between mb-3">
            <h3 className="text-lg font-semibold text-gray-900">Stripe</h3>
            <Badge variant="neutral">Not Connected</Badge>
          </div>
          <p className="text-sm text-gray-600 mb-4">
            Connect your Stripe account to start accepting online payments on invoices. Customers will be able to pay via a secure Stripe checkout page.
          </p>
          <Button onClick={handleConnect} loading={connecting}>
            Set Up Now
          </Button>
        </div>
      )}

      {/* Connected */}
      {status?.connect_client_id_configured && status?.is_connected && (
        <div className="rounded-lg border border-gray-200 p-5">
          <div className="flex items-center justify-between mb-3">
            <h3 className="text-lg font-semibold text-gray-900">Stripe</h3>
            <Badge variant="success">Connected</Badge>
          </div>
          <p className="text-sm text-gray-600 mb-1">
            Account: <span className="font-medium text-gray-900">····{status?.account_id_last4 ?? ''}</span>
          </p>
          {(status?.application_fee_percent ?? null) !== null && (
            <p className="text-sm text-gray-600 mb-1">
              Platform fee: <span className="font-medium text-gray-900">{status?.application_fee_percent ?? 0}%</span> per transaction
            </p>
          )}
          <p className="text-sm text-gray-600 mb-4">
            Your customers can pay invoices online via Stripe Checkout. Payments are deposited directly into your Stripe account.
          </p>
          <Button
            variant="danger"
            size="sm"
            onClick={() => setShowDisconnectDialog(true)}
            loading={disconnecting}
          >
            Disconnect
          </Button>
        </div>
      )}

      {/* Disconnect confirmation dialog */}
      <Modal
        open={showDisconnectDialog}
        title="Disconnect Stripe?"
        onClose={() => setShowDisconnectDialog(false)}
      >
        <p className="text-sm text-gray-600 mb-2">
          Are you sure you want to disconnect your Stripe account?
        </p>
        <p className="text-sm text-amber-700 bg-amber-50 border border-amber-200 rounded-md p-3 mb-4">
          Any existing payment links sent to customers will stop working. You will need to reconnect to accept online payments again.
        </p>
        <div className="flex gap-2 justify-end">
          <Button variant="secondary" onClick={() => setShowDisconnectDialog(false)}>
            Cancel
          </Button>
          <Button variant="danger" onClick={handleDisconnect} loading={disconnecting}>
            Disconnect
          </Button>
        </div>
      </Modal>
    </div>
  )
}
