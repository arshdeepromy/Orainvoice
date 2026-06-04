import { useMemo } from 'react'
import { useNavigate } from 'react-router-dom'
import { Menu, MenuButton, MenuItem, MenuItems } from '@headlessui/react'
import { useAuth } from '@/contexts/AuthContext'
import { useTenant } from '@/contexts/TenantContext'

/**
 * OrgSwitcher — sidebar-footer organisation chip + menu (Task 10).
 *
 * Mounted in the Sidebar's `.sb-foot` region (Task 7). Matches the prototype's
 * `.org-switch` row from OraInvoice_Handoff/app/ds.css + shell.js (gradient
 * rounded avatar with initials, org name + plan/seats line, double chevron),
 * upgraded to a real Headless UI Menu whose actions mirror what the production
 * app actually does for organisation context.
 *
 * ── Behaviour cross-checked against the real app ──
 * The production app does NOT let a normal user switch between multiple orgs:
 * every user belongs to exactly one org (a single `org_id` baked into the JWT —
 * see frontend/src/contexts/AuthContext.tsx) and there is no "my organisations"
 * list endpoint. So this is deliberately an org-identity + actions menu, NOT a
 * fabricated org-switcher. The actions replicate the real org-context surfaces:
 *
 *   - Organisation settings → /settings        (org_admin / global_admin only —
 *                                                /settings is adminOnly in the
 *                                                real OrgLayout nav)
 *   - Billing               → /settings?tab=billing (adminOnly — the Billing tab
 *                                                of the real Settings page, the
 *                                                same target as the real
 *                                                ExpiringPaymentWarningModal's
 *                                                "Update payment" action)
 *   - View all organisations → /admin/organisations (global_admin only — the
 *                                                real admin org list)
 *   - Back to Admin          → clears sessionStorage('admin_view_as_org') and
 *                                                returns to /admin/organisations.
 *                                                This is the real global-admin
 *                                                "View as Org" impersonation exit
 *                                                (frontend/src/layouts/OrgLayout
 *                                                .tsx `handleBackToAdmin`); only
 *                                                shown to a global_admin who is
 *                                                currently impersonating an org.
 *
 * Sign-out is intentionally NOT duplicated here — it lives in the TopBar avatar
 * menu (Task 8), matching the real app where logout is a user-menu action.
 *
 * ── Data sourcing ──
 * Org name + avatar initials come from `useTenant().settings.branding.name`
 * (the real `/org/settings` response). When a global_admin is impersonating an
 * org, the impersonated org's name (sessionStorage `admin_view_as_org`) takes
 * precedence — mirroring the real "Viewing as organisation" banner.
 *
 * The plan/seats line ("PRO · 12 SEATS") has no source in the real
 * TenantContext (it isn't part of `/org/settings`); the prototype shows it
 * presentationally, so it falls back to the prototype string for now.
 *
 * TenantContext is currently a SHIM returning `settings: null` (Task 15 drops in
 * the real `/org/settings` fetch), so until then the org name falls back to the
 * prototype's "Kerikeri Motors". The public surface used here
 * (useTenant → settings.branding.name, useAuth → user.role) is identical to the
 * real contexts, so the Task 15 drop-in needs no changes to this component.
 *
 * TODO(Task 15): once the real TenantContext + subscription/plan data are wired,
 *   bind the org name to `settings.branding.name` (already read here) and source
 *   the plan + seat count from the real org subscription (e.g. the billing /
 *   plan endpoint) instead of the presentational fallback.
 */

/* ── Prototype fallbacks (OraInvoice_Handoff/app/shell.js `.org-switch`) ── */
const FALLBACK_ORG_NAME = 'Kerikeri Motors'
const FALLBACK_PLAN = 'PRO · 12 SEATS'

/* ── SVG path data (24×24 viewBox, stroke-based), reused from the shell icons ── */
const ICON = {
  /** Double chevron (up + down) — exact prototype `.org-switch .chev` path. */
  chevron: 'M8 9l4-4 4 4M8 15l4 4 4-4',
  settings:
    'M10.3 4.3c.4-1.8 2.9-1.8 3.3 0a1.7 1.7 0 002.6 1.1c1.5-.9 3.3.8 2.4 2.4a1.7 1.7 0 001 2.5c1.8.5 1.8 3 0 3.4a1.7 1.7 0 00-1 2.6c.9 1.5-.8 3.3-2.4 2.4a1.7 1.7 0 00-2.6 1c-.4 1.8-2.9 1.8-3.3 0a1.7 1.7 0 00-2.6-1c-1.5.9-3.3-.8-2.4-2.4a1.7 1.7 0 00-1-2.6c-1.8-.4-1.8-3 0-3.4a1.7 1.7 0 001-2.5C4.7 6.2 6.5 4.5 8 5.4a1.7 1.7 0 002.5-1zM15 12a3 3 0 11-6 0 3 3 0 016 0z',
  billing:
    'M3 10h18M7 15h1m4 0h1m-7 4h12a3 3 0 003-3V8a3 3 0 00-3-3H6a3 3 0 00-3 3v8a3 3 0 003 3z',
  orgs: 'M5 3h14a2 2 0 012 2v4a2 2 0 01-2 2H5a2 2 0 01-2-2V5a2 2 0 012-2zm0 10h14a2 2 0 012 2v4a2 2 0 01-2 2H5a2 2 0 01-2-2v-4a2 2 0 012-2zm3-6h.01M8 17h.01',
  back: 'M11 17l-5-5m0 0l5-5m-5 5h12',
} as const

/** Stroke SVG glyph at the given pixel size. */
function Glyph({ d, size = 16, strokeWidth = 1.9 }: { d: string; size?: number; strokeWidth?: number }) {
  return (
    <svg
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth={strokeWidth}
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
      style={{ width: size, height: size }}
      className="flex-shrink-0"
    >
      <path d={d} />
    </svg>
  )
}

/** Org avatar initials (e.g. "Kerikeri Motors" → "KM", "Acme" → "AC"). */
function getOrgInitials(name: string): string {
  const parts = name.trim().split(/\s+/).filter(Boolean)
  if (parts.length === 0) return 'OR'
  if (parts.length === 1) return parts[0].slice(0, 2).toUpperCase()
  return (parts[0].charAt(0) + parts[parts.length - 1].charAt(0)).toUpperCase()
}

export default function OrgSwitcher() {
  const navigate = useNavigate()
  const { user } = useAuth()
  const { settings } = useTenant()

  const userRole = user?.role
  const isAdmin = userRole === 'org_admin' || userRole === 'global_admin'
  const isGlobalAdmin = userRole === 'global_admin'

  /**
   * Global-admin "View as Org" impersonation — read the same sessionStorage key
   * the real OrgLayout uses. When set, the impersonated org's name is shown and
   * the "Back to Admin" exit is offered (mirroring the real banner + handler).
   */
  const viewAsOrg = useMemo(() => {
    try {
      const raw = sessionStorage.getItem('admin_view_as_org')
      return raw ? (JSON.parse(raw) as { id: string; name: string }) : null
    } catch {
      return null
    }
  }, [])

  // Org name: impersonated org (global_admin) → real branding name → prototype.
  const orgName = viewAsOrg?.name || settings?.branding?.name || FALLBACK_ORG_NAME
  // Plan/seats has no real source yet (see header TODO) — presentational fallback.
  const planLine = FALLBACK_PLAN
  const initials = getOrgInitials(orgName)

  const handleBackToAdmin = () => {
    // Mirrors OrgLayout.handleBackToAdmin — exit impersonation, return to admin.
    sessionStorage.removeItem('admin_view_as_org')
    navigate('/admin/organisations')
  }

  return (
    <Menu as="div" className="relative">
      {/* Trigger — full-width `.org-switch` row on the ink palette. */}
      <MenuButton
        className="flex w-full items-center gap-[10px] rounded-ctl px-[10px] py-2 text-left transition-colors hover:bg-sb-hover focus:outline-none focus-visible:ring-2 focus-visible:ring-accent-fg focus-visible:ring-offset-2 focus-visible:ring-offset-sb-bg"
        aria-label={`Organisation: ${orgName}. Open organisation menu`}
      >
        {/* Gradient avatar (accent → purple) with initials. */}
        <div className="grid h-[30px] w-[30px] flex-shrink-0 place-items-center rounded-lg bg-gradient-to-br from-accent to-purple text-[13px] font-bold text-white">
          {initials}
        </div>
        <div className="min-w-0 leading-tight">
          <div className="truncate text-[13px] font-semibold text-white">{orgName}</div>
          <div className="mono text-[10.5px] uppercase text-sb-muted">{planLine}</div>
        </div>
        <span className="ml-auto flex-shrink-0 text-sb-muted">
          <Glyph d={ICON.chevron} size={16} strokeWidth={2} />
        </span>
      </MenuButton>

      {/* Dropdown — light card popover opening upward (chip is pinned bottom-left).
          Headless UI `anchor="top start"` positions it above the trigger, start-
          aligned, so it never overflows the bottom of the ink sidebar. */}
      <MenuItems
        anchor={{ to: 'top start', gap: 8 }}
        className="z-50 w-60 rounded-card border border-border bg-card shadow-pop focus:outline-none"
      >
        {/* Header — org identity (matches the trigger; light-card styled). */}
        <div className="border-b border-border px-4 py-3">
          <p className="truncate text-[13px] font-semibold text-text">{orgName}</p>
          <p className="mono truncate text-[11px] uppercase text-muted">{planLine}</p>
        </div>

        <div className="p-1.5">
          {isAdmin && (
            <MenuItem>
              <button
                type="button"
                onClick={() => navigate('/settings')}
                className="flex w-full items-center gap-3 rounded-chip px-3 py-2 text-left text-[13px] text-text transition-colors data-[focus]:bg-canvas"
              >
                <span className="text-muted-2">
                  <Glyph d={ICON.settings} size={16} />
                </span>
                Organisation settings
              </button>
            </MenuItem>
          )}

          {isAdmin && (
            <MenuItem>
              <button
                type="button"
                onClick={() => navigate('/settings?tab=billing')}
                className="flex w-full items-center gap-3 rounded-chip px-3 py-2 text-left text-[13px] text-text transition-colors data-[focus]:bg-canvas"
              >
                <span className="text-muted-2">
                  <Glyph d={ICON.billing} size={16} />
                </span>
                Billing
              </button>
            </MenuItem>
          )}

          {isGlobalAdmin && (
            <MenuItem>
              <button
                type="button"
                onClick={() => navigate('/admin/organisations')}
                className="flex w-full items-center gap-3 rounded-chip px-3 py-2 text-left text-[13px] text-text transition-colors data-[focus]:bg-canvas"
              >
                <span className="text-muted-2">
                  <Glyph d={ICON.orgs} size={16} />
                </span>
                View all organisations
              </button>
            </MenuItem>
          )}

          {isGlobalAdmin && viewAsOrg && (
            <MenuItem>
              <button
                type="button"
                onClick={handleBackToAdmin}
                className="flex w-full items-center gap-3 rounded-chip px-3 py-2 text-left text-[13px] text-accent transition-colors data-[focus]:bg-accent-soft"
              >
                <span>
                  <Glyph d={ICON.back} size={16} />
                </span>
                Back to Admin
              </button>
            </MenuItem>
          )}
        </div>
      </MenuItems>
    </Menu>
  )
}
