export interface Vehicle {
  id: string
  registration: string
  make: string | null
  model: string | null
  year: number | null
  vin: string | null
  colour: string | null
  owner_id: string
  owner_name: string
}
