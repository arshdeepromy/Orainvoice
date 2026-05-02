export interface Invoice {
  id: string
  invoice_number: string
  customer_id: string
  customer_name: string
  status: 'draft' | 'sent' | 'paid' | 'overdue' | 'cancelled'
  subtotal: number
  tax_amount: number
  discount_amount: number
  total: number
  amount_paid: number
  amount_due: number
  due_date: string
  created_at: string
  line_items: InvoiceLineItem[]
  customer_portal_token?: string | null
  customer_enable_portal?: boolean
}

export interface InvoiceLineItem {
  id: string
  description: string
  quantity: number
  unit_price: number
  tax_rate: number
  amount: number
}

export interface InvoiceCreate {
  customer_id: string
  due_date: string
  line_items: InvoiceLineItemCreate[]
  discount_amount?: number
  notes?: string
}

export interface InvoiceLineItemCreate {
  description: string
  quantity: number
  unit_price: number
  tax_rate: number
}
