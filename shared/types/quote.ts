export interface Quote {
  id: string
  quote_number: string
  customer_id: string
  customer_name: string
  status: 'draft' | 'sent' | 'accepted' | 'declined' | 'expired'
  subtotal: number
  tax_amount: number
  discount_amount: number
  total: number
  valid_until: string
  created_at: string
  line_items: QuoteLineItem[]
  customer_portal_token?: string | null
  customer_enable_portal?: boolean
}

export interface QuoteLineItem {
  id: string
  description: string
  quantity: number
  unit_price: number
  tax_rate: number
  amount: number
}
