import { useState, useEffect, useCallback } from 'react'
import apiClient from '@/api/client'
import { Modal } from '@/components/ui/Modal'
import { MfaMethodCard } from '@/components/mfa/MfaMethodCard'
import { TotpEnrolWizard } from '@/components/mfa/TotpEnrolWizard'
import { SmsEnrolWizard } from '@/components/mfa/SmsEnrolWizard'
import { EmailEnrolWizard } from '@/components/mfa/EmailEnrolWizard'
import { PasskeyManager } from '@/components/mfa/PasskeyManager'
import { BackupCodesPanel } from '@/components/mfa/BackupCodesPanel'
import { PasswordConfirmModal } from '@/components/mfa/PasswordConfirmModal'

export interface MfaMethodStatus {
  method: string
  enabled: boolean
  verified_at: string | null
  phone_number: string | null
  is_default: boolean
}

type EnrolMethod = 'totp' | 'sms' | 'email'

export function MfaSettings() {
  const [methods, setMethods] = useState<MfaMethodStatus[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const [successMsg, setSuccessMsg] = useState('')

  // Enrolment wizard state
  const [enrolMethod, setEnrolMethod] = useState<EnrolMethod | null>(null)

  // Disable flow state
  const [disableMethod, setDisableMethod] = useState<string | null>(null)
  const [disabling, setDisabling] = useState(false)

  const fetchMethods = useCallback(async () => {
    try {
      const res = await apiClient.get<MfaMethodStatus[]>('/auth/mfa/methods')
      setMethods(res.data)
      setError('')
    } catch {
      setError('Failed to load MFA methods')
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => { fetchMethods() }, [fetchMethods])

  const showSuccess = (msg: string) => {
    setSuccessMsg(msg)
    setTimeout(() => setSuccessMsg(''), 4000)
  }

  const handleEnable = (method: string) => {
    if (method === 'totp' || method === 'sms' || method === 'email') {
      setEnrolMethod(method)
    }
    // Passkey enrolment is handled inside PasskeyManager
  }

  const handleDisable = (method: string) => {
    setDisableMethod(method)
  }

  const handleSetDefault = async (method: string) => {
    setError('')
    try {
      await apiClient.put('/auth/mfa/default', { method })
      showSuccess(`${method.toUpperCase()} set as default method`)
      await fetchMethods()
    } catch (err: unknown) {
      const detail = (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail
      setError(detail ?? 'Failed to set default method')
    }
  }

  const handleDisableConfirm = async (password: string) => {
    if (!disableMethod) return
    setDisabling(true)
    try {
      await apiClient.delete(`/auth/mfa/methods/${disableMethod}`, {
        data: { password },
      })
      setDisableMethod(null)
      showSuccess(`${disableMethod.toUpperCase()} has been disabled`)
      await fetchMethods()
    } catch (err: unknown) {
      const detail = (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail
      setError(detail ?? 'Failed to disable method')
    } finally {
      setDisabling(false)
    }
  }

  const handleEnrolComplete = async () => {
    const method = enrolMethod
    setEnrolMethod(null)
    showSuccess(`${method?.toUpperCase()} has been enabled`)
    await fetchMethods()
  }

  const getMethodStatus = (method: string): MfaMethodStatus | undefined =>
    methods.find(m => m.method === method)

  if (loading) {
    return (
      <div className="flex items-center justify-center py-12">
        <div className="animate-spin rounded-full h-8 w-8 border-b-2 border-blue-600" role="status" aria-label="Loading MFA settings" />
      </div>
    )
  }

  return (
    <div className="space-y-6">
      <div>
        <h3 className="text-sm font-medium text-gray-900">Multi-Factor Authentication</h3>
        <p className="text-sm text-gray-500 mt-1">
          Manage your second-factor authentication methods for extra account security.
        </p>
      </div>

      {error && (
        <div className="rounded-md bg-red-50 border border-red-200 p-3" role="alert">
          <p className="text-sm text-red-700">{error}</p>
        </div>
      )}

      {successMsg && (
        <div className="rounded-md bg-green-50 border border-green-200 p-3" role="status">
          <p className="text-sm text-green-700">{successMsg}</p>
        </div>
      )}

      {/* Method cards */}
      <div className="space-y-3">
        <MfaMethodCard
          method="totp"
          label="Authenticator App (TOTP)"
          description="Use an authenticator app like Google Authenticator or Authy"
          status={getMethodStatus('totp')}
          onEnable={() => handleEnable('totp')}
          onDisable={() => handleDisable('totp')}
          onSetDefault={() => handleSetDefault('totp')}
        />
        <MfaMethodCard
          method="sms"
          label="SMS"
          description="Receive verification codes via text message"
          status={getMethodStatus('sms')}
          onEnable={() => handleEnable('sms')}
          onDisable={() => handleDisable('sms')}
          onSetDefault={() => handleSetDefault('sms')}
        />
        <MfaMethodCard
          method="email"
          label="Email"
          description="Receive verification codes at your registered email"
          status={getMethodStatus('email')}
          onEnable={() => handleEnable('email')}
          onDisable={() => handleDisable('email')}
          onSetDefault={() => handleSetDefault('email')}
        />
      </div>

      {/* Passkey section */}
      <PasskeyManager onUpdate={fetchMethods} onSuccess={showSuccess} />

      {/* Backup codes section */}
      <BackupCodesPanel />

      {/* Enrolment wizard modals */}
      <Modal
        open={enrolMethod === 'totp'}
        onClose={() => setEnrolMethod(null)}
        title="Set Up Authenticator App"
      >
        <TotpEnrolWizard onComplete={handleEnrolComplete} onCancel={() => setEnrolMethod(null)} />
      </Modal>

      <Modal
        open={enrolMethod === 'sms'}
        onClose={() => setEnrolMethod(null)}
        title="Set Up SMS Verification"
      >
        <SmsEnrolWizard onComplete={handleEnrolComplete} onCancel={() => setEnrolMethod(null)} />
      </Modal>

      <Modal
        open={enrolMethod === 'email'}
        onClose={() => setEnrolMethod(null)}
        title="Set Up Email Verification"
      >
        <EmailEnrolWizard onComplete={handleEnrolComplete} onCancel={() => setEnrolMethod(null)} />
      </Modal>

      {/* Password confirmation for disable */}
      <PasswordConfirmModal
        open={disableMethod !== null}
        onClose={() => setDisableMethod(null)}
        onConfirm={handleDisableConfirm}
        loading={disabling}
        title={`Disable ${disableMethod?.toUpperCase() ?? ''}`}
        description="Enter your password to confirm disabling this MFA method."
      />
    </div>
  )
}
