export type AccountType = 'asset' | 'liability' | 'equity' | 'revenue' | 'expense'

export interface Account {
  id: string
  code: string
  name: string
  type: AccountType
  balance: number
  parent_id: string | null
}

export interface JournalEntry {
  id: string
  date: string
  description: string
  reference: string | null
  lines: JournalEntryLine[]
  created_at: string
}

export interface JournalEntryLine {
  id: string
  account_id: string
  account_name: string
  debit: number
  credit: number
}

export interface BankAccount {
  id: string
  name: string
  institution: string | null
  account_number: string | null
  balance: number
  currency: string
}

export interface BankTransaction {
  id: string
  bank_account_id: string
  date: string
  description: string
  amount: number
  is_reconciled: boolean
}

export interface GstPeriod {
  id: string
  start_date: string
  end_date: string
  status: 'open' | 'filed' | 'paid'
  gst_collected: number
  gst_paid: number
  net_gst: number
}
