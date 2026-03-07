import { useState } from 'react'
import { OrgSettings } from './OrgSettings'
import { BranchManagement } from './BranchManagement'
import { UserManagement } from './UserManagement'
import { Billing } from './Billing'

type SettingsSection = 'organisation' | 'branches' | 'users' | 'billing'

const NAV_ITEMS: { id: SettingsSection; label: string; icon: string }[] = [
  { id: 'organisation', label: 'Organisation', icon: '⚙' },
  { id: 'branches', label: 'Branches', icon: '🏢' },
  { id: 'users', label: 'Users', icon: '👥' },
  { id: 'billing', label: 'Billing', icon: '💳' },
]

const SECTION_COMPONENTS: Record<SettingsSection, React.FC> = {
  organisation: OrgSettings,
  branches: BranchManagement,
  users: UserManagement,
  billing: Billing,
}

export function Settings() {
  const [active, setActive] = useState<SettingsSection>('organisation')
  const ActiveComponent = SECTION_COMPONENTS[active]

  return (
    <div className="flex flex-col md:flex-row gap-6 min-h-[calc(100vh-8rem)]">
      {/* Sidebar nav */}
      <nav
        aria-label="Settings navigation"
        className="md:w-56 flex-shrink-0 border-b md:border-b-0 md:border-r border-gray-200"
      >
        <ul className="flex md:flex-col gap-1 p-2 overflow-x-auto md:overflow-x-visible">
          {NAV_ITEMS.map((item) => (
            <li key={item.id}>
              <button
                onClick={() => setActive(item.id)}
                aria-current={active === item.id ? 'page' : undefined}
                className={`w-full flex items-center gap-2 rounded-md px-3 py-2 text-sm font-medium transition-colors whitespace-nowrap
                  ${active === item.id
                    ? 'bg-blue-50 text-blue-700'
                    : 'text-gray-600 hover:bg-gray-100 hover:text-gray-900'
                  }`}
              >
                <span aria-hidden="true">{item.icon}</span>
                {item.label}
              </button>
            </li>
          ))}
        </ul>
      </nav>

      {/* Content area */}
      <main className="flex-1 min-w-0 p-2 md:p-0">
        <ActiveComponent />
      </main>
    </div>
  )
}
