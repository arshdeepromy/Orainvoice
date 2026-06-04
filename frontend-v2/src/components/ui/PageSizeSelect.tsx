/**
 * PageSizeSelect — rows-per-page selector (Task 23 port of
 * frontend/src/components/ui/PageSizeSelect).
 *
 * PUBLIC API + the [10, 25, 50] option set are copied VERBATIM from the
 * original. Styling is remapped to the prototype's control language from
 * OraInvoice_Handoff/app/ds.css (ctl radii, border, card bg, muted label
 * text) to sit alongside the design-system table/pagination footer.
 */
const PAGE_SIZE_OPTIONS = [10, 25, 50]

interface PageSizeSelectProps {
  value: number
  onChange: (size: number) => void
}

export function PageSizeSelect({ value, onChange }: PageSizeSelectProps) {
  return (
    <div className="flex items-center gap-2 text-[12.5px] text-muted">
      <label htmlFor="page-size-select">Show</label>
      <select
        id="page-size-select"
        value={value}
        onChange={(e) => onChange(Number(e.target.value))}
        className="mono rounded-ctl border border-border bg-card px-2 py-1 text-[12.5px] text-text
          focus:outline-none focus:border-accent focus:shadow-[0_0_0_3px_var(--accent-soft)]"
      >
        {PAGE_SIZE_OPTIONS.map((opt) => (
          <option key={opt} value={opt}>{opt}</option>
        ))}
      </select>
      <span>per page</span>
    </div>
  )
}

export default PageSizeSelect
