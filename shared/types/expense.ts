export interface Expense {
  id: string
  description: string
  amount: number
  category: string | null
  date: string
  receipt_url: string | null
  created_at: string
}
