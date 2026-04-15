import { useState, useEffect } from 'react'
import { Collapsible } from '@/components/ui/Collapsible'
import { useToast, ToastContainer } from '@/components/ui/Toast'
import apiClient from '@/api/client'
import { MfaEnforcementSection } from '@/components/settings/security/MfaEnforcementSection'
import { PasswordPolicySection } from '@/components/settings/security/PasswordPolicySection'
import { LockoutPolicySection } from '@/components/settings/security/LockoutPolicySection'
import { RolesPermissionsSection } from '@/components/settings/security/RolesPermissionsSection'
import { SessionPolicySection } from '@/components/settings/security/SessionPolicySection'
import { SecurityAuditLogSection } from '@/components/settings/security/SecurityAuditLogSection'

interface MfaPolicy {
  mode: 'optional' | 'mandatory_all' | 'mandatory_admins_only'
  excluded_user_ids: string[]
}

interface PasswordPolicy {
  min_length: number
  require_uppercase: boolean
  require_lowercase: boolean
  require_digit: boolean
  require_special: boolean
  expiry_days: number
  history_count: number
}

interface LockoutPolicy {
  temp_lock_threshold: number
  temp_lock_minutes: number
  permanent_lock_threshold: number
}

interface SessionPolicy {
  access_token_expire_minutes: number
  refresh_token_expire_days: number
  max_sessions_per_user: number
  excluded_user_ids: string[]
  excluded_roles: string[]
}

interface OrgSecuritySettings {
  mfa_policy: MfaPolicy
  password_policy: PasswordPolicy
  lockout_policy: LockoutPolicy
  session_policy: SessionPolicy
}

const DEFAULT_SETTINGS: OrgSecuritySettings = {
  mfa_policy: { mode: 'optional', excluded_user_ids: [] },
  password_policy: { min_length: 8, require_uppercase: false, require_lowercase: false, require_digit: false, require_special: false, expiry_days: 0, history_count: 0 },
  lockout_policy: { temp_lock_threshold: 5, temp_lock_minutes: 15, permanent_lock_threshold: 10 },
  session_policy: { access_token_expire_minutes: 30, refresh_token_expire_days: 7, max_sessions_per_user: 5, excluded_user_ids: [], excluded_roles: [] },
}

export function SecuritySettings() {
  const [settings, setSettings] = useState<OrgSecuritySettings>(DEFAULT_SETTINGS)
  const [loading, setLoading] = useState(true)
  const { toasts, addToast, dismissToast } = useToast()

  useEffect(() => {
    const controller = new AbortController()
    const fetchSettings = async () => {
      try {
        const res = await apiClient.get('/org/security-settings', { signal: controller.signal })
        setSettings({
          mfa_policy: res.data?.mfa_policy ?? DEFAULT_SETTINGS.mfa_policy,
          password_policy: res.data?.password_policy ?? DEFAULT_SETTINGS.password_policy,
          lockout_policy: res.data?.lockout_policy ?? DEFAULT_SETTINGS.lockout_policy,
          session_policy: res.data?.session_policy ?? DEFAULT_SETTINGS.session_policy,
        })
      } catch (err) {
        if (!controller.signal.aborted) {
          addToast('error', 'Failed to load security settings')
        }
      } finally {
        setLoading(false)
      }
    }
    fetchSettings()
    return () => controller.abort()
  }, []) // eslint-disable-line react-hooks/exhaustive-deps

  if (loading) {
    return (
      <div className="flex items-center justify-center py-12">
        <p className="text-sm text-gray-500">Loading security settings…</p>
      </div>
    )
  }

  return (
    <div>
      <h1 className="text-2xl font-semibold text-gray-900 mb-6">Security Settings</h1>
      <ToastContainer toasts={toasts} onDismiss={dismissToast} />

      <div className="space-y-2">
        <Collapsible label="🔐 MFA Enforcement" defaultOpen className="border rounded-lg">
          <MfaEnforcementSection
            policy={settings.mfa_policy}
            onSaved={(p) => setSettings((prev) => ({ ...prev, mfa_policy: p }))}
          />
        </Collapsible>

        <Collapsible label="🔑 Password Policy" className="border rounded-lg">
          <PasswordPolicySection
            policy={settings.password_policy}
            onSaved={(p) => setSettings((prev) => ({ ...prev, password_policy: p }))}
          />
        </Collapsible>

        <Collapsible label="🚫 Account Lockout" className="border rounded-lg">
          <LockoutPolicySection
            policy={settings.lockout_policy}
            onSaved={(p) => setSettings((prev) => ({ ...prev, lockout_policy: p }))}
          />
        </Collapsible>

        <Collapsible label="👥 Roles & Permissions" className="border rounded-lg">
          <RolesPermissionsSection />
        </Collapsible>

        <Collapsible label="⏱ Session Management" className="border rounded-lg">
          <SessionPolicySection
            policy={settings.session_policy}
            onSaved={(p) => setSettings((prev) => ({ ...prev, session_policy: p }))}
          />
        </Collapsible>

        <Collapsible label="📋 Audit Log" className="border rounded-lg">
          <SecurityAuditLogSection />
        </Collapsible>
      </div>
    </div>
  )
}
