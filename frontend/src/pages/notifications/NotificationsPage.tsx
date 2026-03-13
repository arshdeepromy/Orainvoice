import { Tabs } from '../../components/ui'
import { useModules } from '../../contexts/ModuleContext'
import NotificationPreferences from './NotificationPreferences'
import TemplateEditor from './TemplateEditor'
import NotificationLog from './NotificationLog'
import OverdueRules from './OverdueRules'
import WofRegoReminders from './WofRegoReminders'

/**
 * Notification settings page with tabbed navigation for preferences, templates,
 * delivery log, overdue rules, and WOF/rego reminders.
 *
 * Requirements: 34.1-34.3, 35.1-35.3, 36.3-36.6, 38.1-38.4, 39.1-39.4, 83.1-83.4
 */
export default function NotificationsPage() {
  const { isEnabled } = useModules()
  const vehiclesEnabled = isEnabled('vehicles')

  const tabs = [
    { id: 'preferences', label: 'Preferences', content: <NotificationPreferences /> },
    { id: 'templates', label: 'Templates', content: <TemplateEditor /> },
    { id: 'log', label: 'Delivery Log', content: <NotificationLog /> },
    { id: 'overdue-rules', label: 'Overdue Rules', content: <OverdueRules /> },
    ...(vehiclesEnabled
      ? [{ id: 'wof-rego', label: 'WOF / Rego Reminders', content: <WofRegoReminders /> }]
      : []),
  ]

  return (
    <div className="mx-auto max-w-7xl px-4 py-6 sm:px-6 lg:px-8">
      <h1 className="text-2xl font-semibold text-gray-900 mb-4">Notifications</h1>
      <Tabs tabs={tabs} defaultTab="preferences" />
    </div>
  )
}

