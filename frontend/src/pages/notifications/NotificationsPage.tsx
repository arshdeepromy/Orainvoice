import { Tabs } from '../../components/ui'
import NotificationPreferences from './NotificationPreferences'
import TemplateEditor from './TemplateEditor'
import NotificationLog from './NotificationLog'
import OverdueRules from './OverdueRules'
import Reminders from './Reminders'

/**
 * Notification settings page with tabbed navigation for preferences, templates,
 * delivery log, overdue rules, and reminders.
 *
 * Requirements: 34.1-34.3, 35.1-35.3, 36.3-36.6, 38.1-38.4, 83.1-83.4
 */
export default function NotificationsPage() {
  const tabs = [
    { id: 'preferences', label: 'Preferences', content: <NotificationPreferences /> },
    { id: 'templates', label: 'Templates', content: <TemplateEditor /> },
    { id: 'log', label: 'Delivery Log', content: <NotificationLog /> },
    { id: 'reminders', label: 'Reminders', content: <Reminders /> },
    { id: 'overdue-rules', label: 'Overdue Rules', content: <OverdueRules /> },
  ]

  return (
    <div className="px-4 py-6 sm:px-6 lg:px-8">
      <h1 className="text-2xl font-semibold text-gray-900 mb-4">Notifications</h1>
      <Tabs tabs={tabs} defaultTab="preferences" />
    </div>
  )
}

