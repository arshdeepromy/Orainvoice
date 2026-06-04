/**
 * Shared types for POS module components.
 */

export interface POSProduct {
  id: string
  name: string
  sku: string | null
  barcode: string | null
  category_id: string | null
  category_name: string | null
  sale_price: number
  cost_price: number
  stock_quantity: number
  unit_of_measure: string
  images: string[]
  is_active: boolean
}

export interface POSCategory {
  id: string
  name: string
}

export interface POSLineItem {
  id: string
  product: POSProduct
  quantity: number
  unitPrice: number
  discountPercent: number
  discountAmount: number
}

export interface POSOrder {
  lineItems: POSLineItem[]
  orderDiscountPercent: number
  orderDiscountAmount: number
  customerId: string | null
  tableId: string | null
}

export type PaymentMethod = 'cash' | 'card' | 'split'

export interface PaymentInfo {
  method: PaymentMethod
  cashTendered?: number
  changeGiven?: number
  cardAmount?: number
  splitCash?: number
  splitCard?: number
}

export interface OfflineTransaction {
  offlineId: string
  timestamp: string
  userId: string
  lineItems: {
    productId: string
    productName: string
    quantity: number
    unitPrice: number
    discountPercent: number
    discountAmount: number
  }[]
  paymentMethod: string
  subtotal: number
  taxAmount: number
  discountAmount: number
  tipAmount: number
  total: number
  cashTendered?: number
  changeGiven?: number
  customerId?: string
  tableId?: string
  syncStatus: 'pending' | 'synced' | 'failed'
  syncError?: string
}

export interface SyncReport {
  successes: { offlineId: string; transactionId: string }[]
  conflicts: { offlineId: string; reason: string }[]
  errors: { offlineId: string; error: string }[]
}
