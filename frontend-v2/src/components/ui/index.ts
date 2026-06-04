/**
 * UI primitives barrel (Task 11).
 *
 * Shared building blocks for the ported pages, each matching the prototype's
 * `ds.css` component classes (OraInvoice_Handoff/app/ds.css) and the variant
 * gallery in OraInvoice_Handoff/app/Components.html:
 *
 *   Button       → `.btn` (primary / ghost / quiet / danger, sm size, icon-only)
 *   IconButton   → `.icon-btn` (40px square topbar icon button, badge dot)
 *   Card         → `.card` / `.card-head` / `.card-body`
 *   Badge        → `.badge` status pills (paid / sent / overdue / draft + tones)
 *   cx           → tiny dependency-free className merge helper
 */
export { default as Button, buttonClasses } from './Button'
export type { ButtonProps, ButtonVariant, ButtonSize } from './Button'

export { default as IconButton } from './IconButton'
export type { IconButtonProps } from './IconButton'

export { default as Card, CardHead, CardBody } from './Card'
export type { CardProps, CardHeadProps, CardBodyProps } from './Card'

export { default as Badge, statusToBadgeVariant } from './Badge'
export type { BadgeProps, BadgeVariant } from './Badge'

export { default as DataTable } from './DataTable'
export type { Column } from './DataTable'

/* Pagination + PageSizeSelect + Tabs — ported for the customer pages (Task 23). */
export { default as Pagination } from './Pagination'
export { default as PageSizeSelect } from './PageSizeSelect'
export { default as Tabs } from './Tabs'

export { Spinner } from './Spinner'

/* PrintButton — ported for the reports pages (Task 46). */
export { PrintButton } from './PrintButton'

export { Modal } from './Modal'

export { ConfirmDialog } from './ConfirmDialog'

/* Form + feedback primitives ported for the auth pages (Task 13). */
export { Input } from './Input'
export { AlertBanner } from './AlertBanner'

/* Select + PhoneInput — ported for the invoice form + customer modal (Task 20). */
export { Select } from './Select'
export {
  PhoneInput,
  COUNTRY_CODES,
  getCountryCodeFromName,
  getDialCodeForCountry,
} from './PhoneInput'
export type { CountryCode } from './PhoneInput'

/* FormField + Toast — ported for the invoice/quote modals (Tasks 19, 22). */
export { FormField } from './FormField'
export { useToast, ToastContainer } from './Toast'
export type { ToastMessage } from './Toast'
export { CountrySelect, resolveCountryCode, COUNTRIES } from './CountrySelect'
export type { Country } from './CountrySelect'

export { cx } from './cx'
export type { ClassValue } from './cx'
