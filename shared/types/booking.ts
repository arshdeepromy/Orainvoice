export interface Booking {
  id: string
  customer_id: string
  customer_name: string
  date: string
  start_time: string
  duration_minutes: number
  service_type: string | null
  notes: string | null
  status: 'scheduled' | 'confirmed' | 'completed' | 'cancelled'
}
