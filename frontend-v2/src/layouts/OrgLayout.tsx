import { useState, useCallback, useEffect } from 'react'
import { Outlet } from 'react-router-dom'
import Sidebar from '@/components/shell/Sidebar'
import TopBar from '@/components/shell/TopBar'
import { usePaymentMethodEnforcement } from '@/hooks/usePaymentMethodEnforcement'
import { BlockingPaymentModal } from '@/components/billing/BlockingPaymentModal'
import { ExpiringPaymentWarningModal } from '@/components/billing/ExpiringPaymentWarningModal'

/**
 * OrgLayout — the authenticated org app shell (sidebar + top bar + content).
 *
 * Structure mirrors the prototype's `.app` shell in
 * OraInvoice_Handoff/app/shell.js and the `.app` / `.sidebar` / `.main` /
 * `.topbar` / `.content` rules in OraInvoice_Handoff/app/ds.css:
 *
 *   .app   → 100vh flex row, overflow hidden        (root <div>)
 *     ├── <Sidebar>  264px ink rail, flex column     (left region)
 *     └── .main      flex-1 column, overflow hidden  (right region)
 *           ├── <TopBar>            64px header       (fixed top)
 *           └── <main class=content> flex-1, scrolls  (independent scroll)
 *                 └── <Outlet />   ported page provides its own `.page`
 *                                  padding / max-width wrapper
 *
 * The whole viewport is locked to 100vh with overflow hidden; only the content
 * region scrolls, so the sidebar and top bar stay pinned (design.md: "100vh;
 * overflow hidden; main content scrolls independently").
 *
 * Responsive drawer (Task 9): at ≤860px the docked sidebar becomes a fixed
 * off-canvas drawer that slides in over the content with a scrim behind it. The
 * structural mechanics (sidebar transform, scrim fade, content scroll-lock)
 * live in src/styles/shell.css, keyed off the root `data-nav-open` flag + the
 * scoped marker classes applied here (`app-shell` / `shell-sidebar` /
 * `shell-scrim` / `shell-main`). Per-element collapse (hamburger, in-drawer
 * close button, search→icon, branch chip hidden, "New"→icon-only) is done with
 * inline `max-mobile:` Tailwind variants in TopBar/Sidebar (a custom variant
 * defined in tokens.css = `@media (max-width: 860px)`). Escape closes the
 * drawer (handler below); clicking the scrim or any nav item also closes it.
 */
export default function OrgLayout() {
  // Mobile off-canvas drawer state. Docked (always visible) >860px; at ≤860px
  // this drives the slide-in transform + scrim via shell.css (`data-nav-open`).
  const [sidebarOpen, setSidebarOpen] = useState(false)

  const openSidebar = useCallback(() => setSidebarOpen(true), [])
  const closeSidebar = useCallback(() => setSidebarOpen(false), [])

  // Payment method enforcement — blocking/warning modals for org_admin
  const {
    showBlockingModal, showWarningModal, expiringMethod,
    dismissWarning, refetchStatus,
  } = usePaymentMethodEnforcement()

  // Escape closes the drawer when it's open (a11y: the drawer is a transient
  // overlay, so Esc should dismiss it like a dialog). Only bound while open so
  // we don't intercept Escape for other handlers when the drawer is docked.
  useEffect(() => {
    if (!sidebarOpen) return
    const onKeyDown = (e: KeyboardEvent) => {
      if (e.key === 'Escape') closeSidebar()
    }
    document.addEventListener('keydown', onKeyDown)
    return () => document.removeEventListener('keydown', onKeyDown)
  }, [sidebarOpen, closeSidebar])

  return (
    <>
      <BlockingPaymentModal open={showBlockingModal} onSuccess={refetchStatus} />
      <ExpiringPaymentWarningModal
        open={showWarningModal && !showBlockingModal}
        expiringMethod={expiringMethod}
        onDismiss={dismissWarning}
      />
      <div
        className="app-shell flex h-screen overflow-hidden bg-canvas text-text"
        data-nav-open={sidebarOpen}
      >
        <Sidebar open={sidebarOpen} onClose={closeSidebar} />

        {/* Scrim overlay — only rendered as a visible layer at ≤860px when the
            drawer is open (shell.css drives display/opacity off `data-nav-open`).
            Clicking it dismisses the drawer. `aria-hidden` since it's a purely
            decorative dismiss surface; the in-drawer close button + Escape give
            keyboard users a way out. */}
        <div
          className="shell-scrim"
          aria-hidden="true"
          onClick={closeSidebar}
        />

        {/* Main column: fixed top bar + independently scrolling content. */}
        <div className="shell-main flex min-w-0 flex-1 flex-col overflow-hidden">
          <TopBar onOpenSidebar={openSidebar} />
          <main className="flex-1 overflow-y-auto">
            {/* Ported pages supply their own `.page` (padding + max-width)
                wrapper, matching the prototype where `.content` is flush and
                `.page` handles padding/centering. */}
            <Outlet />
          </main>
        </div>
      </div>
    </>
  )
}
