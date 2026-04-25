export type ReportType =
  | 'revenue'
  | 'job'
  | 'fleet'
  | 'inventory'
  | 'customer_statement'
  | 'outstanding_invoices'
  | 'profit_and_loss'
  | 'balance_sheet'
  | 'aged_receivables'

export interface ReportDefinition {
  type: ReportType
  name: string
  description: string
  moduleSlug: string | null
  tradeFamily: string | null
}

export interface ReportData {
  type: ReportType
  title: string
  date_range: { start: string; end: string }
  summary: Record<string, number>
  rows: Record<string, unknown>[]
}
