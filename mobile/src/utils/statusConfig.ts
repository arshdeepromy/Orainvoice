/**
 * Centralised status colour map for invoice and job statuses.
 *
 * Each entry provides:
 *  - label:  human-readable uppercase label
 *  - color:  Tailwind text colour class
 *  - bg:     Tailwind background colour class
 */

export interface StatusConfigEntry {
  label: string
  color: string
  bg: string
}

export const STATUS_CONFIG: Record<string, StatusConfigEntry> = {
  draft:              { label: 'DRAFT',              color: 'text-gray-500',    bg: 'bg-gray-100' },
  issued:             { label: 'ISSUED',             color: 'text-blue-600',    bg: 'bg-blue-100' },
  partially_paid:     { label: 'PARTIALLY PAID',     color: 'text-amber-600',   bg: 'bg-amber-100' },
  paid:               { label: 'PAID',               color: 'text-emerald-600', bg: 'bg-emerald-100' },
  overdue:            { label: 'OVERDUE',            color: 'text-red-600',     bg: 'bg-red-100' },
  voided:             { label: 'VOIDED',             color: 'text-gray-400',    bg: 'bg-gray-50' },
  refunded:           { label: 'REFUNDED',           color: 'text-orange-600',  bg: 'bg-orange-100' },
  partially_refunded: { label: 'PARTIALLY REFUNDED', color: 'text-orange-600',  bg: 'bg-orange-100' },
}
