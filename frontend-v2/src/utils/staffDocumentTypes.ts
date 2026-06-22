/**
 * Shared staff-document type catalogue used by BOTH the Staff → Documents tab
 * and the public onboarding form, so the "document type + detail" inputs behave
 * identically on both surfaces.
 *
 * Each type optionally declares a `detail` field:
 *   - `options` present  → render a <select> of those options. When `allowOther`
 *     is true an "Other" choice reveals a free-text input.
 *   - `options` absent   → render a free-text input (e.g. certifications).
 *
 * The resolved human-readable detail string is stored in the compliance
 * document's `description` column.
 */

export interface DocDetailOption {
  value: string
  label: string
}

export interface DocDetailConfig {
  /** Label shown above the detail field. */
  label: string
  /** Fixed options → renders a select. Omit for a free-text field. */
  options?: DocDetailOption[]
  /** When true, the select includes an "Other" option with a free-text box. */
  allowOther?: boolean
  /** Placeholder for the free-text input. */
  placeholder?: string
  /** When true, the detail is required to submit. */
  required?: boolean
}

export interface DocTypeConfig {
  value: string
  label: string
  detail?: DocDetailConfig
}

export const STAFF_DOC_TYPES: DocTypeConfig[] = [
  {
    value: 'working_rights',
    label: 'Working rights',
    detail: {
      label: 'What proves the right to work?',
      required: true,
      allowOther: true,
      options: [
        { value: 'nz_au_citizen_passport', label: 'Passport — NZ/Australian citizen' },
        { value: 'citizenship_certificate', label: 'Citizenship certificate' },
        { value: 'nz_birth_certificate', label: 'NZ birth certificate' },
        { value: 'residence_visa', label: 'Residence visa' },
        { value: 'work_visa', label: 'Work visa' },
      ],
    },
  },
  {
    value: 'identity',
    label: 'Identity',
    detail: {
      label: 'ID type',
      required: true,
      allowOther: true,
      options: [
        { value: 'passport', label: 'Passport' },
        { value: 'drivers_licence', label: "Driver's licence" },
        { value: 'national_id', label: 'National ID card' },
        { value: 'kiwi_access_card', label: 'Kiwi Access card' },
      ],
    },
  },
  {
    value: 'visa',
    label: 'Visa / Work permit',
    detail: {
      label: 'Visa type',
      required: true,
      allowOther: true,
      options: [
        { value: 'work_visa', label: 'Work visa' },
        { value: 'student_visa', label: 'Student visa' },
        { value: 'resident_visa', label: 'Resident visa' },
        { value: 'visitor_visa', label: 'Visitor visa' },
      ],
    },
  },
  {
    value: 'certification',
    label: 'Certification / Licence',
    detail: {
      label: 'Certification type',
      required: true,
      placeholder: 'e.g. First Aid, Electrical Practising Licence, Forklift (F endorsement)',
    },
  },
  {
    value: 'qualification',
    label: 'Qualification',
    detail: {
      label: 'Qualification',
      placeholder: 'e.g. NZ Certificate in Automotive Engineering (Level 4)',
    },
  },
  {
    value: 'contract',
    label: 'Contract / Agreement',
    detail: { label: 'Details (optional)', placeholder: 'e.g. Employment agreement, NDA' },
  },
  {
    value: 'staff_document',
    label: 'Other',
    detail: { label: 'Description (optional)', placeholder: 'Briefly describe this document' },
  },
]

const BY_VALUE: Record<string, DocTypeConfig> = Object.fromEntries(
  STAFF_DOC_TYPES.map((t) => [t.value, t]),
)

export function docTypeConfig(value: string | null | undefined): DocTypeConfig | undefined {
  return value ? BY_VALUE[value] : undefined
}

/** Human label for a document_type slug (falls back to title-casing). */
export function documentTypeLabel(type: string): string {
  if (type === 'employment_agreement') return 'Employment agreement'
  return (
    BY_VALUE[type]?.label ??
    type.replace(/_/g, ' ').replace(/\b\w/g, (c) => c.toUpperCase())
  )
}

/** Map a detail option value back to its human label for a given type. */
export function detailOptionLabel(typeValue: string, optionValue: string): string {
  const opt = docTypeConfig(typeValue)?.detail?.options?.find((o) => o.value === optionValue)
  return opt?.label ?? optionValue
}
