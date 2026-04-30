export interface Customer {
  id: string
  first_name: string
  last_name: string | null
  email: string | null
  phone: string | null
  company: string | null
  address: string | null
}

export interface CustomerCreate {
  first_name: string
  last_name?: string
  email?: string
  phone?: string
  mobile_phone?: string
  work_phone?: string
  company?: string
  address?: string
}
