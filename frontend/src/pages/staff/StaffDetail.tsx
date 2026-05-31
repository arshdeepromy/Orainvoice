/**
 * Staff Detail — tabbed shell (Phase 1, task E2).
 *
 * Module-gated by `staff_management`. When the module is disabled this
 * component falls back to the legacy single-form view at
 * `./_legacy/StaffDetail.legacy.tsx`. When enabled it renders a tab strip
 * (Overview / Roster / Documents) backed by `useTabHash` so the active
 * tab survives refresh + browser back/forward, with `<Suspense>` wrapping
 * lazy-loaded tab components so the staff list page doesn't pull the
 * calendar bundle.
 *
 * The discard-changes guard is a confirm() in the tab change handler.
 * Per the design, dirty-state tracking lives inside OverviewTab (which
 * registers a callback on this shell). For now the shell exposes the
 * hook but has no dirty source — the guard becomes effective once E3
 * wires its dirty flag in.
 */

import { Suspense, lazy, useCallback, useRef } from 'react'
import { useTabHash } from '@/hooks/useTabHash'
import { useModules } from '@/contexts/ModuleContext'
import LegacyStaffDetail from './_legacy/StaffDetail.legacy'

const OverviewTab = lazy(() => import('./tabs/OverviewTab'))
const RosterTab = lazy(() => import('./tabs/RosterTab'))
const PayslipsTab = lazy(() => import('./tabs/PayslipsTab'))
const DocumentsTab = lazy(() => import('./tabs/DocumentsTab'))

type TabId = 'overview' | 'roster' | 'payslips' | 'documents'

const TABS: { id: TabId; label: string }[] = [
  { id: 'overview', label: 'Overview' },
  { id: 'roster', label: 'Roster' },
  { id: 'payslips', label: 'Payslips' },
  { id: 'documents', label: 'Documents' },
]
const TAB_IDS: TabId[] = TABS.map((t) => t.id)

interface Props {
  staffId: string
}

export default function StaffDetail({ staffId }: Props) {
  const { isEnabled } = useModules()
  const moduleEnabled = isEnabled('staff_management')

  // Dirty-state ref — OverviewTab (E3) sets this so the discard-changes
  // guard fires before we navigate away from a tab with unsaved changes.
  const isDirtyRef = useRef<() => boolean>(() => false)
  const registerDirtyCheck = useCallback((checker: () => boolean) => {
    isDirtyRef.current = checker
  }, [])

  const [activeTab, setActiveTab] = useTabHash<TabId>('overview', TAB_IDS)

  const handleTabChange = useCallback(
    (next: TabId) => {
      if (next === activeTab) return
      const dirty = isDirtyRef.current?.() ?? false
      if (dirty) {
        const proceed = window.confirm(
          'You have unsaved changes on this tab. Discard them?'
        )
        if (!proceed) return
      }
      // The next tab is taking over — clear the dirty checker so we don't
      // pop the prompt again with a stale closure.
      isDirtyRef.current = () => false
      setActiveTab(next)
    },
    [activeTab, setActiveTab]
  )

  if (!moduleEnabled) {
    return <LegacyStaffDetail staffId={staffId} />
  }

  return (
    <div className="h-full flex flex-col" data-testid="staff-detail-tabbed">
      <div className="bg-white border-b border-gray-200">
        <div className="px-6 pt-4 flex gap-1" role="tablist">
          {TABS.map((tab) => {
            const isActive = activeTab === tab.id
            return (
              <button
                key={tab.id}
                role="tab"
                aria-selected={isActive}
                aria-controls={`staff-tab-panel-${tab.id}`}
                id={`staff-tab-${tab.id}`}
                className={`px-4 py-2 min-h-[44px] text-sm font-medium border-b-2 transition-colors ${
                  isActive
                    ? 'border-blue-600 text-blue-600'
                    : 'border-transparent text-gray-600 hover:text-gray-900'
                }`}
                onClick={() => handleTabChange(tab.id)}
              >
                {tab.label}
              </button>
            )
          })}
        </div>
      </div>

      <div
        role="tabpanel"
        id={`staff-tab-panel-${activeTab}`}
        aria-labelledby={`staff-tab-${activeTab}`}
        className="flex-1 min-h-0 overflow-auto"
      >
        <Suspense fallback={<div className="p-6 text-gray-500">Loading...</div>}>
          {activeTab === 'overview' && (
            <OverviewTab staffId={staffId} onDirtyChange={registerDirtyCheck} />
          )}
          {activeTab === 'roster' && <RosterTab staffId={staffId} />}
          {activeTab === 'payslips' && <PayslipsTab staffId={staffId} />}
          {activeTab === 'documents' && <DocumentsTab staffId={staffId} />}
        </Suspense>
      </div>
    </div>
  )
}
