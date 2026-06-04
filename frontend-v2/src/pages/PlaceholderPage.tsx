/**
 * PlaceholderPage — temporary route target for the Task 4 router skeleton.
 *
 * The real pages are ported in later phases (Dashboard → Task 16, auth pages
 * → Tasks 13/14, portal → Tasks 57/58, kiosk → Task 60, etc.). Each lazy
 * route in App.tsx points here for now so the router compiles and renders a
 * recognisable shell while those tasks fill in the actual screens.
 *
 * TODO(Tasks 13-72): replace each placeholder route with its ported page.
 */
export default function PlaceholderPage({ title }: { title?: string }) {
  return (
    <div className="mx-auto flex max-w-xl flex-col items-start gap-2 rounded-card border border-border bg-card p-pad shadow-card">
      <span className="mono text-xs uppercase tracking-wide text-muted-2">frontend-v2</span>
      <h1 className="text-xl font-semibold text-text">{title ?? 'Coming soon'}</h1>
      <p className="text-sm text-muted">
        This screen is part of the OraInvoice redesign and will be ported in a
        later task. The router skeleton is wired up and routing correctly.
      </p>
    </div>
  )
}
