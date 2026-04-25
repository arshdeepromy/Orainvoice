export type JobStatus = 'pending' | 'in_progress' | 'completed' | 'cancelled'

export interface Job {
  id: string
  title: string
  description: string | null
  status: JobStatus
  customer_id: string
  customer_name: string
  assigned_staff_id: string | null
  assigned_staff_name: string | null
  created_at: string
  updated_at: string
}

export interface JobCard {
  id: string
  job_card_number: string
  customer_id: string
  customer_name: string
  vehicle_id: string | null
  vehicle_registration: string | null
  status: JobStatus
  description: string | null
  created_at: string
}

export interface TimeEntry {
  id: string
  job_id: string
  staff_id: string
  staff_name: string
  clock_in: string
  clock_out: string | null
  duration_minutes: number | null
  notes: string | null
}
