import { useState, useEffect } from 'react'
import { useSearchParams } from 'react-router-dom'
import { OrgSettings } from './OrgSettings'
import { BranchManagement } from './BranchManagement'
import { UserManagement } from './UserManagement'
import { Billing } from './Billing'
import { AccountingIntegrations } from './AccountingIntegrations'
import CurrencySettings from './CurrencySettings'
import { LanguageSwitcher } from './LanguageSwitcher'
import PrinterSettings from './PrinterSettings'
import { WebhookManagement } from './WebhookManagement'
import { ModuleConfiguration } from './ModuleConfiguration'
import NotificationsPage from '../notifications/NotificationsPage'
import { Profile } from './Profile'

type SettingsSection =
  | 'profile'
  | 'organisation'
  | 'branches'
  | 'users'
  | 'billing'
  | 'accounting'
  | 'currency'
  | 'language'
  | 'printer'
  | 'webhooks'
  | 'modules'
  | 'notifications'

const NAV_ITEMS: { id: SettingsSection; label: string; icon: string }[] = [
  { id: 'profile', label: 'Profile', icon: '👤' },
  { id: 'organisation', label: 'Organisation', icon: '⚙' },
  { id: 'branches', label: 'Branches', icon: '🏢' },
  { id: 'users', label: 'Users', icon: '👥' },
  { id: 'billing', label: 'Billing', icon: '💳' },
  { id: 'accounting', label: 'Accounting', icon: '📒' },
  { id: 'currency', label: 'Currency', icon: '💱' },
  { id: 'language', label: 'Language', icon: '🌐' },
  { id: 'printer', label: 'Printer', icon: '🖨' },
  { id: 'webhooks', label: 'Webhooks', icon: '🔗' },
  { id: 'modules', label: 'Modules', icon: '🧩' },
  { id: 'notifications', label: 'Notifications', icon: '🔔' },
]

const SECTION_COMPONENTS: Record<SettingsSection, React.FC> = {
  profile: Profile,
  organisation: OrgSettings,
  branches: BranchManagement,
  users: UserManagement,
  billing: Billing,
  accounting: AccountingIntegrations,
  currency: CurrencySettings,
  language: LanguageSwitcher,
  printer: PrinterSettings,
  webhooks: WebhookManagement,
  modules: ModuleConfiguration,
  notifications: NotificationsPage,
}

export function Settings() {
  const [searchParams, setSearchParams] = useSearchParams()
  const tabParam = searchParams.get('tab')
  const initialTab = NAV_ITEMS.some(i => i.id === tabParam) ? (tabParam as SettingsSection) : 'organisation'
  const [active, setActive] = useState<SettingsSection>(initialTab)

  useEffect(() => {
    setSearchParams({ tab: active }, { replace: true })
  }, [active])
  const ActiveComponent = SECTION_COMPONENTS[active]

  return (
    <div className="flex flex-col md:flex-row gap-6 h-full">
      {/* Sidebar nav */}
      <nav
        aria-label="Settings navigation"
        className="md:w-56 flex-shrink-0 border-b md:border-b-0 md:border-r border-gray-200 md:sticky md:top-0 md:self-start"
      >
        <ul className="flex md:flex-col gap-1 p-2 overflow-x-auto md:overflow-x-visible md:overflow-y-auto md:max-h-[calc(100vh-10rem)]">
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
