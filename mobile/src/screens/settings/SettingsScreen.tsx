import { useState, useCallback } from 'react'
import { useAuth } from '@/contexts/AuthContext'
import { useTenant } from '@/contexts/TenantContext'
import { MobileCard, MobileButton, MobileInput } from '@/components/ui'
import { ModuleGate } from '@/components/common/ModuleGate'
import apiClient from '@/api/client'

import { useBiometric } from '@/contexts/BiometricContext'

/* ------------------------------------------------------------------ */
/* Biometric toggle (safe wrapper)                                    */
/* ------------------------------------------------------------------ */

function useBiometricSafe() {
  try {
    return useBiometric()
  } catch {
    return { isAvailable: false, isEnabled: false, setEnabled: (_enabled: boolean) => {} } as const
  }
}

/* ------------------------------------------------------------------ */
/* Section component                                                  */
/* ------------------------------------------------------------------ */

function SettingsSection({
  title,
  children,
}: {
  title: string
  children: React.ReactNode
}) {
  return (
    <MobileCard>
      <h2 className="mb-3 text-base font-semibold text-gray-900 dark:text-gray-100">{title}</h2>
      {children}
    </MobileCard>
  )
}

function ToggleRow({
  label,
  description,
  checked,
  onChange,
  disabled,
}: {
  label: string
  description?: string
  checked: boolean
  onChange: (checked: boolean) => void
  disabled?: boolean
}) {
  return (
    <div className="flex min-h-[44px] items-center justify-between py-2">
      <div className="min-w-0 flex-1">
        <p className="text-sm font-medium text-gray-900 dark:text-gray-100">{label}</p>
        {description && (
          <p className="text-xs text-gray-500 dark:text-gray-400">{description}</p>
        )}
      </div>
      <button
        type="button"
        role="switch"
        aria-checked={checked}
        disabled={disabled}
        onClick={() => onChange(!checked)}
        className={`relative inline-flex h-6 w-11 flex-shrink-0 cursor-pointer rounded-full border-2 border-transparent transition-colors ${
          checked ? 'bg-blue-600' : 'bg-gray-200 dark:bg-gray-600'
        } ${disabled ? 'cursor-not-allowed opacity-50' : ''}`}
      >
        <span
          className={`pointer-events-none inline-block h-5 w-5 transform rounded-full bg-white shadow transition-transform ${
            checked ? 'translate-x-5' : 'translate-x-0'
          }`}
        />
      </button>
    </div>
  )
}

/* ------------------------------------------------------------------ */
/* Settings Screen                                                    */
/* ------------------------------------------------------------------ */

function SettingsContent() {
  const { user, refreshProfile } = useAuth()
  const { branding } = useTenant()
  const biometric = useBiometricSafe()

  const [orgName, setOrgName] = useState(branding?.name ?? '')
  const [isSaving, setIsSaving] = useState(false)
  const [saveResult, setSaveResult] = useState<{ success: boolean; message: string } | null>(null)

  // Notification toggles
  const [invoicePayments, setInvoicePayments] = useState(true)
  const [jobUpdates, setJobUpdates] = useState(true)
  const [expiryReminders, setExpiryReminders] = useState(true)

  const handleSave = useCallback(async () => {
    setIsSaving(true)
    setSaveResult(null)
    try {
      await apiClient.put('/api/v1/org/settings', {
        name: orgName.trim(),
        notifications: {
          invoice_payments: invoicePayments,
          job_updates: jobUpdates,
          expiry_reminders: expiryReminders,
        },
      })
      await refreshProfile()
      setSaveResult({ success: true, message: 'Settings saved' })
    } catch {
      setSaveResult({ success: false, message: 'Failed to save settings' })
    } finally {
      setIsSaving(false)
    }
  }, [orgName, invoicePayments, jobUpdates, expiryReminders, refreshProfile])

  return (
    <div className="flex flex-col gap-4 p-4">
      <h1 className="text-xl font-semibold text-gray-900 dark:text-gray-100">Settings</h1>

      {/* Profile */}
      <SettingsSection title="Profile">
        <div className="flex flex-col gap-2 text-sm">
          <div className="flex justify-between">
            <span className="text-gray-500 dark:text-gray-400">Name</span>
            <span className="text-gray-900 dark:text-gray-100">{user?.name ?? 'N/A'}</span>
          </div>
          <div className="flex justify-between">
            <span className="text-gray-500 dark:text-gray-400">Email</span>
            <span className="text-gray-900 dark:text-gray-100">{user?.email ?? 'N/A'}</span>
          </div>
          <div className="flex justify-between">
            <span className="text-gray-500 dark:text-gray-400">Role</span>
            <span className="capitalize text-gray-900 dark:text-gray-100">
              {(user?.role ?? 'user').replace('_', ' ')}
            </span>
          </div>
        </div>
      </SettingsSection>

      {/* Organisation */}
      <SettingsSection title="Organisation">
        <MobileInput
          label="Organisation Name"
          value={orgName}
          onChange={(e) => setOrgName(e.target.value)}
          placeholder="Organisation name"
        />
      </SettingsSection>

      {/* Notifications */}
      <SettingsSection title="Notifications">
        <ToggleRow
          label="Invoice Payments"
          description="Notify when payments are received"
          checked={invoicePayments}
          onChange={setInvoicePayments}
        />
        <ToggleRow
          label="Job Updates"
          description="Notify on job status changes"
          checked={jobUpdates}
          onChange={setJobUpdates}
        />
        <ToggleRow
          label="Expiry Reminders"
          description="Remind before documents expire"
          checked={expiryReminders}
          onChange={setExpiryReminders}
        />
      </SettingsSection>

      {/* Biometric */}
      {biometric.isAvailable && (
        <SettingsSection title="Security">
          <ToggleRow
            label="Biometric Login"
            description="Use Face ID / fingerprint to unlock"
            checked={biometric.isEnabled}
            onChange={() => biometric.setEnabled(!biometric.isEnabled)}
          />
        </SettingsSection>
      )}

      {/* Save result */}
      {saveResult && (
        <div
          role="alert"
          className={`rounded-lg p-3 text-sm ${
            saveResult.success
              ? 'bg-green-50 text-green-700 dark:bg-green-900/30 dark:text-green-300'
              : 'bg-red-50 text-red-700 dark:bg-red-900/30 dark:text-red-300'
          }`}
        >
          {saveResult.message}
        </div>
      )}

      {/* Save button */}
      <MobileButton variant="primary" fullWidth onClick={handleSave} isLoading={isSaving}>
        Save Settings
      </MobileButton>
    </div>
  )
}

/**
 * Settings screen — profile, organisation, notifications, biometric toggle.
 * Restricted to org_admin/global_admin roles.
 *
 * Requirements: 41.1, 41.2, 41.3, 41.4, 4.1, 4.4
 */
export default function SettingsScreen() {
  return (
    <ModuleGate moduleSlug="*" roles={['org_admin', 'owner', 'admin']}>
      <SettingsContent />
    </ModuleGate>
  )
}
