import { Outlet } from 'react-router-dom'

/**
 * PortalLayout — customer portal shell (branded header + footer).
 *
 * PLACEHOLDER (Task 4 router skeleton). Renders only an <Outlet />.
 *
 * TODO(Task 56): replace with the real PortalLayout — branded header,
 *   summary cards, tabbed content, "Powered by OraInvoice" footer.
 *   Reference: OraInvoice_Handoff/app/Portal.html
 */
export default function PortalLayout() {
  return (
    <div className="min-h-screen bg-canvas text-text">
      {/* TODO(Task 56): branded header + footer */}
      <Outlet />
    </div>
  )
}
