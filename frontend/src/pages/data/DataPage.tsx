import { Tabs } from '../../components/ui'
import DataImport from './DataImport'
import DataExport from './DataExport'
import JsonBulkImport from './JsonBulkImport'

/**
 * Data management page with tabbed navigation for import, JSON bulk import, and export.
 * Import: CSV upload, field mapping, validation preview, error report download.
 * JSON Import: Bulk upload customers/vehicles via JSON file with sample template download.
 * Export: Customer, vehicle, and invoice CSV export buttons.
 *
 * Requirements: 69.1-69.5, 78.2, 78.3
 */
export default function DataPage() {
  const tabs = [
    { id: 'import', label: 'CSV Import', content: <DataImport /> },
    { id: 'json-import', label: 'JSON Import', content: <JsonBulkImport /> },
    { id: 'export', label: 'Export', content: <DataExport /> },
  ]

  return (
    <div className="px-4 py-6 sm:px-6 lg:px-8">
      <h1 className="text-2xl font-semibold text-gray-900 mb-4">Data Management</h1>
      <Tabs tabs={tabs} defaultTab="import" />
    </div>
  )
}
