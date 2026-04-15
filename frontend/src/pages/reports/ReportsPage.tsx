import { Tabs } from '../../components/ui'
import { useModules } from '../../contexts/ModuleContext'
import RevenueSummary from './RevenueSummary'
import InvoiceStatus from './InvoiceStatus'
import OutstandingInvoices from './OutstandingInvoices'
import TopServices from './TopServices'
import GstReturnSummary from './GstReturnSummary'
import CustomerStatement from './CustomerStatement'
import CarjamUsage from './CarjamUsage'
import SmsUsage from './SmsUsage'
import StorageUsage from './StorageUsage'
import FleetReport from './FleetReport'

/**
 * Reports page with tabbed navigation for all org-level reports.
 * Each tab includes date range filters, charts, and PDF/CSV export.
 *
 * Requirements: 45.1-45.7, 66.4
 */
export default function ReportsPage() {
  const { isEnabled } = useModules()
  const showVehicles = isEnabled('vehicles')

  const tabs = [
    { id: 'revenue', label: 'Revenue', content: <RevenueSummary /> },
    { id: 'invoice-status', label: 'Invoice Status', content: <InvoiceStatus /> },
    { id: 'outstanding', label: 'Outstanding', content: <OutstandingInvoices /> },
    { id: 'top-services', label: 'Top Services', content: <TopServices /> },
    { id: 'gst-return', label: 'GST Return', content: <GstReturnSummary /> },
    { id: 'customer-statement', label: 'Customer Statement', content: <CustomerStatement /> },
    ...(showVehicles ? [{ id: 'carjam-usage', label: 'Carjam Usage', content: <CarjamUsage /> }] : []),
    { id: 'sms-usage', label: 'SMS Usage', content: <SmsUsage /> },
    { id: 'storage', label: 'Storage', content: <StorageUsage /> },
    ...(showVehicles ? [{ id: 'fleet', label: 'Fleet', content: <FleetReport /> }] : []),
  ]

  return (
    <div className="px-4 py-6 sm:px-6 lg:px-8">
      <h1 className="text-2xl font-semibold text-gray-900 mb-4 no-print">Reports</h1>
      <Tabs tabs={tabs} defaultTab="revenue" />
    </div>
  )
}
