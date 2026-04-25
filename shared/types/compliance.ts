export type ComplianceStatus = 'valid' | 'expiring_soon' | 'expired'

export interface ComplianceDocument {
  id: string
  name: string
  document_type: string
  description: string | null
  expiry_date: string | null
  status: ComplianceStatus
  file_url: string | null
  uploaded_at: string
}
