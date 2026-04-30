import { useParams } from 'react-router-dom'
import { Page, List, ListItem, Block, BlockTitle, Preloader } from 'konsta/react'
import { KonstaNavbar } from '@/components/konsta/KonstaNavbar'
import { useApiDetail } from '@/hooks/useApiDetail'

interface AssetDetail {
  id: string
  name: string
  category: string | null
  value: number
  current_value: number | null
  depreciation_rate: number | null
  depreciation_method: string | null
  purchase_date: string | null
  useful_life_years: number | null
  status: string | null
  location: string | null
  serial_number: string | null
  maintenance_log: MaintenanceEntry[]
}

interface MaintenanceEntry {
  id: string
  date: string
  description: string
  cost: number | null
}

function formatNZD(value: number | null | undefined): string {
  return `NZD${Number(value ?? 0).toLocaleString('en-NZ', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`
}

function formatDate(dateStr: string | null): string {
  if (!dateStr) return 'N/A'
  try { return new Date(dateStr).toLocaleDateString('en-NZ', { day: 'numeric', month: 'short', year: 'numeric' }) }
  catch { return dateStr ?? '' }
}

/**
 * Asset detail — depreciation schedule and maintenance log.
 * Requirements: 43.2, 43.3
 */
export default function AssetDetailScreen() {
  const { id } = useParams<{ id: string }>()

  const { data, isLoading, error } = useApiDetail<AssetDetail>({
    endpoint: `/api/v1/assets/${id}`,
  })

  if (isLoading) {
    return (<Page data-testid="asset-detail-page"><KonstaNavbar title="Asset" showBack /><div className="flex flex-1 items-center justify-center p-8"><Preloader /></div></Page>)
  }

  if (error || !data) {
    return (<Page data-testid="asset-detail-page"><KonstaNavbar title="Asset" showBack /><Block><p className="text-center text-red-600 dark:text-red-400">{error ?? 'Asset not found'}</p></Block></Page>)
  }

  const maintenanceLog: MaintenanceEntry[] = data.maintenance_log ?? []

  return (
    <Page data-testid="asset-detail-page">
      <KonstaNavbar title={data.name ?? 'Asset'} showBack />

      <div className="flex flex-col pb-24">
        <BlockTitle>Details</BlockTitle>
        <List strongIos outlineIos dividersIos>
          <ListItem title="Category" after={data.category ?? 'General'} />
          <ListItem title="Purchase Value" after={formatNZD(data.value)} />
          <ListItem title="Current Value" after={formatNZD(data.current_value ?? data.value)} />
          {data.depreciation_rate != null && <ListItem title="Depreciation Rate" after={`${data.depreciation_rate}%`} />}
          {data.depreciation_method && <ListItem title="Method" after={<span className="capitalize">{data.depreciation_method}</span>} />}
          {data.purchase_date && <ListItem title="Purchase Date" after={formatDate(data.purchase_date)} />}
          {data.useful_life_years != null && <ListItem title="Useful Life" after={`${data.useful_life_years} years`} />}
          {data.serial_number && <ListItem title="Serial Number" after={data.serial_number} />}
          {data.location && <ListItem title="Location" after={data.location} />}
        </List>

        <BlockTitle>Maintenance Log ({maintenanceLog.length})</BlockTitle>
        {maintenanceLog.length === 0 ? (
          <Block><p className="text-sm text-gray-500 dark:text-gray-400">No maintenance records</p></Block>
        ) : (
          <List strongIos outlineIos dividersIos data-testid="maintenance-log">
            {maintenanceLog.map((entry) => (
              <ListItem key={entry.id}
                title={entry.description}
                subtitle={<span className="text-xs text-gray-500 dark:text-gray-400">{formatDate(entry.date)}</span>}
                after={entry.cost != null ? <span className="font-medium">{formatNZD(entry.cost)}</span> : undefined}
              />
            ))}
          </List>
        )}
      </div>
    </Page>
  )
}
