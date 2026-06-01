/**
 * PpsrIcon — sidebar icon for the PPSR Check module.
 *
 * Heroicons-style outline SVG. Evokes a clipboard / checklist (the PPSR
 * search produces a security-interest report) layered with a small vehicle
 * silhouette (the search is keyed by rego). Mirrors the inline SVG pattern
 * used for the other nav-item icons in `frontend/src/layouts/OrgLayout.tsx`
 * (e.g. `VehiclesIcon`, `CustomersIcon`).
 */
export default function PpsrIcon() {
  return (
    <svg className="h-5 w-5" fill="none" viewBox="0 0 24 24" stroke="currentColor" aria-hidden="true">
      {/* Clipboard body */}
      <path
        strokeLinecap="round"
        strokeLinejoin="round"
        strokeWidth={2}
        d="M9 5H7a2 2 0 00-2 2v12a2 2 0 002 2h10a2 2 0 002-2V7a2 2 0 00-2-2h-2"
      />
      {/* Clipboard clip */}
      <path
        strokeLinecap="round"
        strokeLinejoin="round"
        strokeWidth={2}
        d="M9 5a2 2 0 012-2h2a2 2 0 012 2v1a1 1 0 01-1 1h-4a1 1 0 01-1-1V5z"
      />
      {/* Checkmark — PPSR clear/match indicator */}
      <path
        strokeLinecap="round"
        strokeLinejoin="round"
        strokeWidth={2}
        d="M9 13l2 2 4-4"
      />
    </svg>
  )
}
