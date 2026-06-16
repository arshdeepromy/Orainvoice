/**
 * BackupLayout — shared shell + sub-navigation for the Cloud Backup area.
 *
 * The Cloud Backup & Restore feature (Global-Admin only, mounted under
 * /admin/backup/*) is six distinct pages: an Overview dashboard, Destinations &
 * Schedule settings, backup History, the Restore wizard, Recovery Keys, and
 * restore Rehearsals. Each page is reached from a single "Cloud Backup" entry in
 * the Admin Console sidebar (AdminLayout); this layout renders the consistent
 * horizontal sub-navigation that lets an operator move between the six pages,
 * with the active page's content rendered via <Outlet/>.
 *
 * Mounted as a parent route in App.tsx:
 *   <Route path="backup" element={<BackupLayout/>}>
 *     <Route index            element={<BackupDashboard/>} />
 *     <Route path="settings"  element={<BackupSettings/>}  />
 *     ...
 *   </Route>
 *
 * Requirements: 1.4 (the backup navigation surface is exposed only inside the
 * global-admin Admin Console, which is itself behind RequireGlobalAdmin).
 */
import { NavLink, Outlet } from 'react-router-dom'

interface BackupTab {
  to: string
  label: string
  /** `end` makes the Overview tab active only on the exact index path. */
  end?: boolean
}

const BACKUP_TABS: BackupTab[] = [
  { to: '/admin/backup', label: 'Overview', end: true },
  { to: '/admin/backup/settings', label: 'Destinations & Schedule' },
  { to: '/admin/backup/history', label: 'History' },
  { to: '/admin/backup/restore', label: 'Restore' },
  { to: '/admin/backup/keys', label: 'Recovery Keys' },
  { to: '/admin/backup/rehearsals', label: 'Rehearsals' },
  { to: '/admin/backup/guide', label: 'Setup Guide' },
]

export function BackupLayout() {
  return (
    <div className="flex flex-col gap-5">
      <div>
        <h1 className="text-2xl font-semibold text-text">Cloud Backup &amp; Restore</h1>
        <p className="mt-1 text-[13px] text-muted">
          Platform-wide disaster recovery: encrypted offsite backups, restore, and recovery keys.
        </p>
      </div>

      <nav
        className="-mb-px flex flex-wrap gap-1 border-b border-border"
        role="navigation"
        aria-label="Cloud Backup sections"
      >
        {BACKUP_TABS.map((tab) => (
          <NavLink
            key={tab.to}
            to={tab.to}
            end={tab.end}
            className={({ isActive }) =>
              `min-h-[44px] inline-flex items-center border-b-2 px-3 text-sm font-medium transition-colors ${
                isActive
                  ? 'border-accent text-accent'
                  : 'border-transparent text-muted hover:text-text hover:border-border-strong'
              }`
            }
          >
            {tab.label}
          </NavLink>
        ))}
      </nav>

      <Outlet />
    </div>
  )
}
