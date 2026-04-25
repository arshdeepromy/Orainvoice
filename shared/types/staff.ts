import type { UserRole } from './auth'

export interface StaffMember {
  id: string
  first_name: string
  last_name: string | null
  email: string | null
  phone: string | null
  role: UserRole
  is_active: boolean
  branches: string[]
}
