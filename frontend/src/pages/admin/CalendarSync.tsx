import { useState, useEffect } from 'react'
import apiClient from '@/api/client'
import { Button } from '@/components/ui/Button'
import { Badge } from '@/components/ui/Badge'
import { Spinner } from '@/components/ui/Spinner'

interface PublicHoliday {
  id: string
  country_code: string
  holiday_date: string
  name: string
  local_name: string | null
  year: number
  is_fixed: boolean
  synced_at: string | null
}

const COUNTRIES = [
  { code: 'NZ', label: 'New Zealand', flag: '🇳🇿' },
  { code: 'AU', label: 'Australia', flag: '🇦🇺' },
]

export default function CalendarSync() {
  const currentYear = new Date().getFullYear()
  const nextYear = currentYear + 1
  const [holidays, setHolidays] = useState<PublicHoliday[]>([])
  const [loading, setLoading] = useState(true)
  const [syncing, setSyncing] = useState<string | null>(null)
  const [selectedCountry, setSelectedCountry] = useState<string>('NZ')
  const [selectedYear, setSelectedYear] = useState<number>(currentYear)
  const [error, setError] = useState('')
  const [successMsg, setSuccessMsg] = useState('')

  const fetchHolidays = async () => {
    setLoading(true)
    try {
      const res = await apiClient.get<PublicHoliday[]>('/admin/calendar/holidays', {
        params: { country_code: selectedCountry, year: selectedYear },
      })
      setHolidays(res.data)
    } catch {
      setError('Failed to load holidays.')
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => { fetchHolidays() }, [selectedCountry, selectedYear])

  const handleSync = async (countryCode: string) => {
    setSyncing(countryCode)
    setError('')
    setSuccessMsg('')
    try {
      // Sync both current year and next year for 12-month coverage
      const [r1, r2] = await Promise.all([
        apiClient.post<{ synced: number }>('/admin/calendar/holidays/sync', null, {
          params: { country_code: countryCode, year: currentYear },
        }),
        apiClient.post<{ synced: number }>('/admin/calendar/holidays/sync', null, {
          params: { country_code: countryCode, year: nextYear },
        }),
      ])
      const total = r1.data.synced + r2.data.synced
      setSuccessMsg(`Synced ${total} holidays for ${countryCode} (${currentYear}–${nextYear})`)
      if (countryCode === selectedCountry) fetchHolidays()
    } catch {
      setError(`Failed to sync holidays for ${countryCode}.`)
    } finally {
      setSyncing(null)
    }
  }

  const lastSynced = holidays.length > 0 && holidays[0].synced_at
    ? new Date(holidays[0].synced_at).toLocaleString('en-NZ')
    : null

  const countryInfo = COUNTRIES.find((c) => c.code === selectedCountry)

  return (
    <div className="space-y-6">
      <p className="text-sm text-gray-600">
        Sync public holiday calendars for supported countries. Holidays are fetched from the free
        Nager.Date API and stored in the database for use across the platform (e.g. booking calendar overlays).
      </p>

      {/* Auto-sync status banner */}
      <div className="flex items-center gap-3 rounded-lg border border-green-200 bg-green-50 px-4 py-3">
        <div className="flex h-8 w-8 items-center justify-center rounded-full bg-green-100">
          <span className="text-green-600 text-sm">↻</span>
        </div>
        <div className="flex-1">
          <p className="text-sm font-medium text-green-800">Auto-sync is active</p>
          <p className="text-xs text-green-600">
            Holidays for NZ and AU are automatically synced every 6 months (current year + next year).
            The sync runs on server startup and then every 6 months.
          </p>
        </div>
        <Badge variant="success">ON</Badge>
      </div>

      {error && (
        <div className="rounded-md border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700" role="alert">{error}</div>
      )}
      {successMsg && (
        <div className="rounded-md border border-green-200 bg-green-50 px-4 py-3 text-sm text-green-700" role="alert">{successMsg}</div>
      )}

      {/* Country sync cards */}
      <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
        {COUNTRIES.map((c) => (
          <div key={c.code} className="rounded-lg border border-gray-200 bg-white p-5">
            <div className="flex items-center justify-between">
              <div className="flex items-center gap-2">
                <span className="text-2xl">{c.flag}</span>
                <div>
                  <p className="font-medium text-gray-900">{c.label}</p>
                  <p className="text-xs text-gray-500">Public Holidays {currentYear}–{nextYear}</p>
                </div>
              </div>
              <Button
                size="sm"
                onClick={() => handleSync(c.code)}
                loading={syncing === c.code}
                disabled={syncing !== null}
              >
                Sync Now
              </Button>
            </div>
          </div>
        ))}
      </div>

      {/* Holiday list */}
      <div>
        <div className="flex items-center justify-between mb-3">
          <h3 className="text-lg font-medium text-gray-900">
            {countryInfo?.flag} {countryInfo?.label} — {selectedYear}
          </h3>
          <div className="flex items-center gap-3">
            <div className="flex gap-1">
              {[currentYear, nextYear].map((y) => (
                <button
                  key={y}
                  onClick={() => setSelectedYear(y)}
                  className={`px-3 py-1 text-xs rounded-md ${
                    selectedYear === y ? 'bg-blue-600 text-white' : 'bg-gray-100 text-gray-600 hover:bg-gray-200'
                  }`}
                >
                  {y}
                </button>
              ))}
            </div>
            <div className="flex gap-1">
              {COUNTRIES.map((c) => (
                <button
                  key={c.code}
                  onClick={() => setSelectedCountry(c.code)}
                  className={`px-3 py-1 text-xs rounded-md ${
                    selectedCountry === c.code ? 'bg-blue-600 text-white' : 'bg-gray-100 text-gray-600 hover:bg-gray-200'
                  }`}
                >
                  {c.flag} {c.code}
                </button>
              ))}
            </div>
          </div>
        </div>

        {lastSynced && (
          <p className="text-xs text-gray-500 mb-3">Last synced: {lastSynced}</p>
        )}

        {loading ? (
          <Spinner label="Loading holidays" />
        ) : holidays.length === 0 ? (
          <div className="rounded-lg border border-gray-200 bg-gray-50 p-8 text-center">
            <p className="text-sm text-gray-500">No holidays synced for {selectedYear} yet. Click "Sync Now" above to fetch holidays.</p>
          </div>
        ) : (
          <div className="rounded-lg border border-gray-200 overflow-hidden">
            <table className="min-w-full divide-y divide-gray-200">
              <thead className="bg-gray-50">
                <tr>
                  <th className="px-4 py-3 text-left text-xs font-medium uppercase tracking-wider text-gray-500">Date</th>
                  <th className="px-4 py-3 text-left text-xs font-medium uppercase tracking-wider text-gray-500">Holiday</th>
                  <th className="px-4 py-3 text-left text-xs font-medium uppercase tracking-wider text-gray-500">Local Name</th>
                  <th className="px-4 py-3 text-center text-xs font-medium uppercase tracking-wider text-gray-500">Fixed</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-gray-100 bg-white">
                {holidays.map((h) => {
                  const d = new Date(h.holiday_date + 'T00:00:00')
                  const isPast = d < new Date(new Date().toDateString())
                  return (
                    <tr key={h.id} className={isPast ? 'opacity-50' : ''}>
                      <td className="px-4 py-2 text-sm text-gray-900 whitespace-nowrap">
                        {d.toLocaleDateString('en-NZ', { weekday: 'short', day: 'numeric', month: 'short', year: 'numeric' })}
                      </td>
                      <td className="px-4 py-2 text-sm text-gray-900">{h.name}</td>
                      <td className="px-4 py-2 text-sm text-gray-500">{h.local_name || '—'}</td>
                      <td className="px-4 py-2 text-center">
                        {h.is_fixed ? <Badge variant="info">Fixed</Badge> : <Badge variant="neutral">Variable</Badge>}
                      </td>
                    </tr>
                  )
                })}
              </tbody>
            </table>
          </div>
        )}
      </div>
    </div>
  )
}
