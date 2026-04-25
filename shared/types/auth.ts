export type UserRole = 'owner' | 'admin' | 'manager' | 'salesperson' | 'technician' | 'kiosk' | 'global_admin' | 'org_admin' | 'branch_admin'

export interface AuthUser {
  id: string
  email: string
  first_name: string
  last_name: string | null
  role: UserRole
  org_id: string
  org_name: string
  is_active: boolean
}

export interface LoginCredentials {
  email: string
  password: string
  remember_me?: boolean
}

export interface LoginResponse {
  access_token: string
  token_type: string
  mfa_required?: boolean
  mfa_methods?: MfaMethod[]
}

export type MfaMethod = 'totp' | 'sms' | 'backup_codes'

export interface MfaVerifyRequest {
  method: MfaMethod
  code: string
}
