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
}

export interface QuoteLineItem {
  id: string
  description: string
  quantity: number
  unit_price: number
  tax_rate: number
  amount: number
}
