import { useNavigate } from 'react-router-dom'
import { Menu, MenuButton, MenuItem, MenuItems } from '@headlessui/react'
import { useAuth } from '@/contexts/AuthContext'
import { useModules } from '@/contexts/ModuleContext'
import { useFeatureFlags } from '@/contexts/FeatureFlagContext'
import { useBranch } from '@/contexts/BranchContext'

/**
 * TopBar — 64px application header (top region of OrgLayout's main column).
 *
 * Real implementation (Task 8). Matches the prototype's `.topbar` row from
 * OraInvoice_Handoff/app/ds.css and the topbar markup in
 * OraInvoice_Handoff/app/shell.js (search field with ⌘K hint, branch chip,
 * notifications icon button with badge, "New" primary button, avatar), while
 * wiring the authoritative actions copied from the existing app's header
 * (frontend/src/layouts/OrgLayout.tsx) so functionality matches per FR-1.
 *
 * Layout (prototype `.topbar`: 64px tall, card bg, bottom border, gap 14px):
 *   [hamburger] [search ⌘K] [spacer] [branch chip] [notifications] [New ▾] [avatar]
 *   - search grows to max 440px, then a flex spacer pushes the right cluster out.
 *
 * Behaviours ported from the real OrgLayout header:
 *   - New ▾        → Headless UI Menu of quick actions (New Booking / Job Card /
 *                    Quote / Invoice / Customer), module/flag-gated exactly like
 *                    the real `visibleQuickActions`. Items navigate (with the
 *                    same optional router state) via useNavigate.
 *   - Branch chip  → reads/sets the selected branch via useBranch (which
 *                    persists `localStorage('selected_branch_id')` → the
 *                    api/client.ts X-Branch-Id header), the same flow as the
 *                    real BranchSelector. Gated on the branch_management module;
 *                    a branch-locked user (branch_admin) gets a static chip.
 *   - Notifications→ links to the notifications inbox (the real bell's "View all"
 *                    destination). Badge structure rendered per prototype; the
 *                    real unread count source is wired in a later task (see below).
 *   - Avatar       → Headless UI Menu (Profile / Settings / Setup Guide / Sign
 *                    out) mirroring the real user menu, including the admin-only
 *                    gates and the navigation targets.
 *   - Search ⌘K    → cmd/ctrl+K (or clicking the field) opens the real command
 *                    palette (GlobalSearchBar, mounted in OrgLayout). Visual
 *                    matches the prototype's `.search` + `⌘K` kbd hint.
 *
 * Gating contexts (useAuth / useModules / useFeatureFlags / useBranch) are
 * imported from the real `@/contexts/...` paths. Those context files are
 * currently lightweight SHIMS (see each contexts/*.tsx) so this compiles today;
 * Task 15 drops in the verbatim real contexts + mounts the providers in
 * App.tsx, at which point the TopBar starts acting on real session / module /
 * flag / branch state with no changes needed here.
 *
 * TODO(Task 9): responsive collapse at ≤860px — reveal the hamburger (already
 *   wired below), collapse the search to an icon (hide its label + kbd), hide
 *   the branch chip, and make "New" icon-only. Driven purely by responsive
 *   `display`/width rules; no restructuring of this component required.
 * The unread badge is sourced for real: OrgLayout supplies `notificationCount`
 * from the /notifications/inbox/unread-count poll (useUnreadNotificationCount).
 * TODO(Task 52, notifications): mount the full InboxBellDropdown panel so
 *   clicking the bell opens the inbox, once the notifications pages are ported.
 */
export interface TopBarProps {
  /**
   * Open the mobile off-canvas drawer (≤860px). Wired here to the hamburger
   * button so Task 9 only needs to add the responsive `display` rules, not
   * restructure the toggle wiring.
   */
  onOpenSidebar: () => void
  /**
   * Unread-notification count for the bell badge, supplied by OrgLayout from
   * the /notifications/inbox/unread-count poll. When omitted, a presentation
   * dot is shown to match the prototype. When provided, a numeric badge renders
   * (and 0 hides it).
   */
  notificationCount?: number
}

/* ── SVG path data (24×24 viewBox, stroke-based), from shell.js / OrgLayout ── */
const ICON = {
  hamburger: 'M4 6h16M4 12h16M4 18h16',
  search: 'M21 21l-5-5m2-5a7 7 0 11-14 0 7 7 0 0114 0z',
  bell: 'M15 17h5l-1.4-1.4A2 2 0 0118 14.2V11a6 6 0 00-4-5.7V5a2 2 0 10-4 0v.3C7.7 6.2 6 8.4 6 11v3.2c0 .5-.2 1-.6 1.4L4 17h5m6 0v1a3 3 0 11-6 0v-1',
  plus: 'M12 5v14M5 12h14',
  chevronDown: 'M19 9l-7 7-7-7',
  pin: 'M8 9l4-4 4 4M8 15l4 4 4-4',
  // Quick-action icons (reused from shell.js ICON map).
  booking: 'M8 7V3m8 4V3m-9 8h10M5 21h14a2 2 0 002-2V7a2 2 0 00-2-2H5a2 2 0 00-2 2v12a2 2 0 002 2z',
  job: 'M11 5H6a2 2 0 00-2 2v11a2 2 0 002 2h11a2 2 0 002-2v-5m-1.4-9.4a2 2 0 112.8 2.8L11.8 15H9v-2.8l8.6-8.6z',
  quote: 'M9 5H7a2 2 0 00-2 2v12a2 2 0 002 2h10a2 2 0 002-2V7a2 2 0 00-2-2h-2M9 5a2 2 0 002 2h2a2 2 0 002-2M9 5a2 2 0 012-2h2a2 2 0 012 2',
  inv: 'M9 12h6m-6 4h6m2 5H7a2 2 0 01-2-2V5a2 2 0 012-2h7l5 5v11a2 2 0 01-2 2z',
  cust: 'M16 7a4 4 0 11-8 0 4 4 0 018 0zM12 14a7 7 0 00-7 7h14a7 7 0 00-7-7z',
  // User-menu icons.
  profile: 'M16 7a4 4 0 11-8 0 4 4 0 018 0zM12 14a7 7 0 00-7 7h14a7 7 0 00-7-7z',
  settings: 'M10.3 4.3c.4-1.8 2.9-1.8 3.3 0a1.7 1.7 0 002.6 1.1c1.5-.9 3.3.8 2.4 2.4a1.7 1.7 0 001 2.5c1.8.5 1.8 3 0 3.4a1.7 1.7 0 00-1 2.6c.9 1.5-.8 3.3-2.4 2.4a1.7 1.7 0 00-2.6 1c-.4 1.8-2.9 1.8-3.3 0a1.7 1.7 0 00-2.6-1c-1.5.9-3.3-.8-2.4-2.4a1.7 1.7 0 00-1-2.6c-1.8-.4-1.8-3 0-3.4a1.7 1.7 0 001-2.5C4.7 6.2 6.5 4.5 8 5.4a1.7 1.7 0 002.5-1zM15 12a3 3 0 11-6 0 3 3 0 016 0z',
  setupGuide: 'M9 5H7a2 2 0 00-2 2v12a2 2 0 002 2h10a2 2 0 002-2V7a2 2 0 00-2-2h-2M9 5a2 2 0 002 2h2a2 2 0 002-2M9 5a2 2 0 012-2h2a2 2 0 012 2m-6 9l2 2 4-4',
  signOut: 'M17 16l4-4m0 0l-4-4m4 4H7m6 4v1a3 3 0 01-3 3H6a3 3 0 01-3-3V7a3 3 0 013-3h4a3 3 0 013 3v1',
} as const

/* ── Quick actions — copied verbatim from frontend/src/layouts/OrgLayout.tsx ── */
interface QuickAction {
  label: string
  path: string
  /** SVG path `d` (replaces the original emoji icons with design-system glyphs). */
  icon: string
  module?: string
  flagKey?: string
  state?: Record<string, unknown>
}

const QUICK_ACTIONS: QuickAction[] = [
  { label: 'New Booking', path: '/bookings', icon: ICON.booking, module: 'bookings', flagKey: 'bookings', state: { openNew: true } },
  { label: 'New Job Card', path: '/job-cards/new', icon: ICON.job, module: 'jobs', flagKey: 'jobs' },
  { label: 'New Quote', path: '/quotes/new', icon: ICON.quote, module: 'quotes', flagKey: 'quotes' },
  { label: 'New Invoice', path: '/invoices/new', icon: ICON.inv },
  { label: 'New Customer', path: '/customers/new', icon: ICON.cust },
]

/** Stroke SVG glyph at the given pixel size. */
function Glyph({ d, size = 17, strokeWidth = 2 }: { d: string; size?: number; strokeWidth?: number }) {
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

/** Avatar initials from the user's display name (e.g. "Ada Reign" → "AR"). */
function getInitials(name?: string | null): string {
  if (!name) return 'U'
  const parts = name.trim().split(/\s+/).filter(Boolean)
  if (parts.length === 0) return 'U'
  if (parts.length === 1) return parts[0].charAt(0).toUpperCase()
  return (parts[0].charAt(0) + parts[parts.length - 1].charAt(0)).toUpperCase()
}

/** Short branch code shown in mono after the branch name (e.g. 'br-01' → 'BR-01'). */
function branchCode(id: string): string {
  return id.toUpperCase()
}

export default function TopBar({ onOpenSidebar, notificationCount }: TopBarProps) {
  const navigate = useNavigate()
  const { user, logout } = useAuth()
  const { isEnabled } = useModules()
  const { flags } = useFeatureFlags()
  const { selectedBranchId, branches, selectBranch, isBranchLocked } = useBranch()

  const userRole = user?.role
  const isAdmin = userRole === 'org_admin' || userRole === 'global_admin'
  const branchModuleEnabled = isEnabled('branch_management')

  /* ── Open the global command palette (GlobalSearchBar) ──
     GlobalSearchBar is mounted in OrgLayout and owns the ⌘K / Ctrl+K shortcut.
     Clicking the search field dispatches the same shortcut to open it — the
     established trigger pattern from the original app's OrgLayout. */
  const openSearch = () => {
    document.dispatchEvent(new KeyboardEvent('keydown', { key: 'k', ctrlKey: true }))
  }

  /* ── Quick-action visibility — copied verbatim from OrgLayout.visibleQuickActions.
     Module enablement is sufficient; items without a module fall back to a flag. */
  const visibleQuickActions = QUICK_ACTIONS.filter((action) => {
    if (action.module) return isEnabled(action.module)
    if (action.flagKey && !flags[action.flagKey]) return false
    return true
  })

  const selectedBranch = selectedBranchId
    ? branches.find((b) => b.id === selectedBranchId) ?? null
    : null

  const handleSignOut = async () => {
    // Clear the session first (POST /auth/logout + reset auth state). Without
    // this the user stays authenticated, so the GuestOnly guard on /login
    // immediately bounces them back to the dashboard.
    await logout()
    navigate('/login', { replace: true })
  }

  return (
    <header className="flex h-16 flex-shrink-0 items-center gap-[14px] border-b border-border bg-card px-pad">
      {/* Hamburger — toggles the mobile drawer. Hidden when the rail is docked
          (>860px); shown only at ≤860px where the sidebar is an off-canvas
          drawer. Kept mounted + wired at all widths so the toggle just works. */}
      <button
        type="button"
        onClick={onOpenSidebar}
        aria-label="Open navigation menu"
        className="hidden h-10 w-10 flex-shrink-0 place-items-center rounded-ctl border border-border bg-card text-muted transition-colors hover:border-border-strong hover:bg-canvas hover:text-text max-mobile:grid"
      >
        <Glyph d={ICON.hamburger} size={19} />
      </button>

      {/* Search field (⌘K). Matches prototype `.search`: grows to 440px, canvas
          bg, border, search icon + label + ⌘K kbd hint. Rendered as a button for
          keyboard accessibility (focus via ⌘K / Tab). At ≤860px it collapses to
          an icon-only 40px square (label + kbd hidden, centered glyph), matching
          the prototype's mobile `.search`; the aria-label keeps it accessible. */}
      <button
        type="button"
        onClick={openSearch}
        aria-label="Search customers, invoices, jobs"
        aria-keyshortcuts="Meta+K Control+K"
        className="flex h-10 max-w-[440px] flex-1 items-center gap-[10px] rounded-ctl border border-border bg-canvas px-3 text-left text-muted-2 transition-colors hover:border-border-strong focus:border-accent focus:outline-none max-mobile:max-w-10 max-mobile:flex-none max-mobile:justify-center max-mobile:gap-0 max-mobile:px-0"
      >
        <Glyph d={ICON.search} size={17} />
        <span className="text-[13.5px] max-mobile:hidden">Search customers, invoices, jobs…</span>
        <kbd className="mono ml-auto rounded-md border border-border bg-card px-1.5 py-0.5 text-[11px] text-muted max-mobile:hidden">
          ⌘K
        </kbd>
      </button>

      {/* Spacer — pushes the right cluster to the far edge (prototype `.spacer`). */}
      <div className="flex-1" />

      {/* Branch chip — reflects/sets the selected branch (→ X-Branch-Id).
          Shown only when the branch_management module is enabled, matching the
          real header. A branch-locked user (branch_admin) gets a static chip.
          Hidden at ≤860px (prototype `.branch { display:none }`) to make room
          on small screens. */}
      {branchModuleEnabled && isBranchLocked && (
        <span className="inline-flex h-9 items-center gap-[7px] rounded-[20px] border border-border bg-card px-3 text-[12.5px] font-medium text-text max-mobile:hidden">
          <span className="h-[7px] w-[7px] rounded-full bg-ok" aria-hidden="true" />
          My Branch
        </span>
      )}

      {branchModuleEnabled && !isBranchLocked && branches.length > 0 && (
        <Menu as="div" className="relative max-mobile:hidden">
          <MenuButton
            className="inline-flex h-9 items-center gap-[7px] rounded-[20px] border border-border bg-card px-3 text-[12.5px] font-medium text-text transition-colors hover:border-border-strong"
            aria-label="Select branch"
          >
            <span className="h-[7px] w-[7px] rounded-full bg-ok" aria-hidden="true" />
            {selectedBranch ? (
              <>
                <span className="max-w-[140px] truncate">{selectedBranch.name}</span>
                <span className="mono text-muted">· {branchCode(selectedBranch.id)}</span>
              </>
            ) : (
              <span>All Branches</span>
            )}
            <Glyph d={ICON.chevronDown} size={13} />
          </MenuButton>
          <MenuItems
            anchor="bottom end"
            className="z-50 mt-2 w-56 rounded-card border border-border bg-card p-1.5 shadow-pop focus:outline-none"
          >
            <MenuItem>
              <button
                type="button"
                onClick={() => selectBranch(null)}
                className={`flex w-full items-center gap-2 rounded-chip px-3 py-2 text-left text-[13px] transition-colors data-[focus]:bg-canvas ${
                  selectedBranchId === null ? 'font-semibold text-accent' : 'text-text'
                }`}
              >
                <span className="h-[7px] w-[7px] rounded-full bg-muted-2" aria-hidden="true" />
                All Branches
              </button>
            </MenuItem>
            {branches.map((branch) => (
              <MenuItem key={branch.id}>
                <button
                  type="button"
                  onClick={() => selectBranch(branch.id)}
                  className={`flex w-full items-center gap-2 rounded-chip px-3 py-2 text-left text-[13px] transition-colors data-[focus]:bg-canvas ${
                    selectedBranchId === branch.id ? 'font-semibold text-accent' : 'text-text'
                  }`}
                >
                  <span className="h-[7px] w-[7px] rounded-full bg-ok" aria-hidden="true" />
                  <span className="truncate">{branch.name}</span>
                  <span className="mono ml-auto text-muted">{branchCode(branch.id)}</span>
                </button>
              </MenuItem>
            ))}
          </MenuItems>
        </Menu>
      )}

      {/* Notifications — links to the inbox (the real bell's "View all" target).
          Badge matches prototype `.icon-btn .bdg`; count source TODO(Task 52). */}
      <button
        type="button"
        onClick={() => navigate('/notifications/inbox')}
        aria-label={
          notificationCount && notificationCount > 0
            ? `Notifications, ${notificationCount} unread`
            : 'Notifications'
        }
        className="relative grid h-10 w-10 flex-shrink-0 place-items-center rounded-ctl border border-border bg-card text-muted transition-colors hover:border-border-strong hover:bg-canvas hover:text-text"
      >
        <Glyph d={ICON.bell} size={19} />
        {notificationCount === undefined ? (
          // Presentation dot (prototype always shows the badge dot).
          <span
            className="absolute right-2 top-[7px] h-[7px] w-[7px] rounded-full border-2 border-card bg-danger"
            aria-hidden="true"
          />
        ) : notificationCount > 0 ? (
          <span
            className="mono absolute -right-1 -top-1 inline-flex h-5 min-w-[20px] items-center justify-center rounded-full border-2 border-card bg-danger px-1 text-[10px] font-bold leading-none text-white"
            aria-hidden="true"
          >
            {notificationCount > 99 ? '99+' : notificationCount}
          </span>
        ) : null}
      </button>

      {/* "New" primary button — Headless UI Menu of quick actions, gated exactly
          like the real header. Hidden entirely if every action is gated out. At
          ≤860px it collapses to an icon-only button (label + chevron hidden,
          plus glyph kept); the aria-label="Create new" keeps it accessible. */}
      {visibleQuickActions.length > 0 && (
        <Menu as="div" className="relative flex-shrink-0">
          <MenuButton
            className="inline-flex h-10 items-center gap-2 rounded-ctl bg-accent px-4 text-[13.5px] font-semibold text-white shadow-[0_1px_2px_rgba(16,24,40,0.18),inset_0_1px_0_rgba(255,255,255,0.14)] transition-colors hover:bg-accent-press focus:outline-none max-mobile:w-10 max-mobile:justify-center max-mobile:gap-0 max-mobile:px-0"
            aria-label="Create new"
          >
            <Glyph d={ICON.plus} size={17} strokeWidth={2.2} />
            <span className="max-mobile:hidden">New</span>
            <span className="inline-flex max-mobile:hidden">
              <Glyph d={ICON.chevronDown} size={14} />
            </span>
          </MenuButton>
          <MenuItems
            anchor="bottom end"
            className="z-50 mt-2 w-56 rounded-card border border-border bg-card p-1.5 shadow-pop focus:outline-none"
          >
            {visibleQuickActions.map((action) => (
              <MenuItem key={action.path + action.label}>
                <button
                  type="button"
                  onClick={() => navigate(action.path, action.state ? { state: action.state } : undefined)}
                  className="flex w-full items-center gap-3 rounded-chip px-3 py-2 text-left text-[13px] text-text transition-colors data-[focus]:bg-canvas"
                >
                  <span className="grid h-7 w-7 flex-shrink-0 place-items-center rounded-md bg-canvas text-muted">
                    <Glyph d={action.icon} size={15} strokeWidth={1.9} />
                  </span>
                  <span>{action.label}</span>
                </button>
              </MenuItem>
            ))}
          </MenuItems>
        </Menu>
      )}

      {/* Avatar — Headless UI Menu (Profile / Settings / Setup Guide / Sign out),
          mirroring the real user menu incl. its admin-only gates + targets. */}
      <Menu as="div" className="relative flex-shrink-0">
        <MenuButton
          className="grid h-10 w-10 place-items-center rounded-full bg-ink text-[14px] font-semibold text-white focus:outline-none focus-visible:ring-2 focus-visible:ring-accent focus-visible:ring-offset-2"
          aria-label="Account menu"
        >
          {getInitials(user?.name)}
        </MenuButton>
        <MenuItems
          anchor="bottom end"
          className="z-50 mt-2 w-56 rounded-card border border-border bg-card shadow-pop focus:outline-none"
        >
          {/* Header — name + email (matches the real user-menu header). */}
          <div className="border-b border-border px-4 py-3">
            <p className="truncate text-[13px] font-semibold text-text">{user?.name ?? 'User'}</p>
            <p className="truncate text-[12px] text-muted">{user?.email}</p>
          </div>
          <div className="p-1.5">
            <MenuItem>
              <button
                type="button"
                onClick={() => navigate('/settings?tab=profile')}
                className="flex w-full items-center gap-3 rounded-chip px-3 py-2 text-left text-[13px] text-text transition-colors data-[focus]:bg-canvas"
              >
                <span className="text-muted-2"><Glyph d={ICON.profile} size={16} strokeWidth={1.9} /></span>
                Profile
              </button>
            </MenuItem>
            {isAdmin && (
              <MenuItem>
                <button
                  type="button"
                  onClick={() => navigate('/settings')}
                  className="flex w-full items-center gap-3 rounded-chip px-3 py-2 text-left text-[13px] text-text transition-colors data-[focus]:bg-canvas"
                >
                  <span className="text-muted-2"><Glyph d={ICON.settings} size={16} strokeWidth={1.9} /></span>
                  Settings
                </button>
              </MenuItem>
            )}
            {isAdmin && (
              <MenuItem>
                <button
                  type="button"
                  onClick={() => navigate('/setup-guide?rerun=true')}
                  className="flex w-full items-center gap-3 rounded-chip px-3 py-2 text-left text-[13px] text-text transition-colors data-[focus]:bg-canvas"
                >
                  <span className="text-muted-2"><Glyph d={ICON.setupGuide} size={16} strokeWidth={1.9} /></span>
                  Setup Guide
                </button>
              </MenuItem>
            )}
            <MenuItem>
              <button
                type="button"
                onClick={handleSignOut}
                className="flex w-full items-center gap-3 rounded-chip px-3 py-2 text-left text-[13px] text-danger transition-colors data-[focus]:bg-danger-soft"
              >
                <span><Glyph d={ICON.signOut} size={16} strokeWidth={1.9} /></span>
                Sign out
              </button>
            </MenuItem>
          </div>
        </MenuItems>
      </Menu>
    </header>
  )
}
