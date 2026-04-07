import { useState, useEffect } from 'react'
import { useParams, useNavigate, Navigate } from 'react-router-dom'
import { useModules } from '@/contexts/ModuleContext'
import { Button } from '@/components/ui/Button'
import { Input } from '@/components/ui/Input'
import { Select } from '@/components/ui/Select'
import { ToastContainer, useToast } from '@/components/ui/Toast'
import apiClient from '@/api/client'

/* ── Types ── */

interface OperatingHoursEntry {
  open: string
  close: string
}

interface BranchSettingsData {
  address: string | null
  phone: string | null
  email: string | null
  logo_url: string | null
  operating_hours: Record<string, OperatingHoursEntry>
  timezone: string
}

const DAYS_OF_WEEK = [
  'monday', 'tuesday', 'wednesday', 'thursday', 'friday', 'saturday', 'sunday',
] as const

const DAY_LABELS: Record<string, string> = {
  monday: 'Monday', tuesday: 'Tuesday', wednesday: 'Wednesday',
  thursday: 'Thursday', friday: 'Friday', saturday: 'Saturday', sunday: 'Sunday',
}

/** Common IANA timezones relevant to NZ/AU/global users */
const TIMEZONE_OPTIONS = [
  { value: '', label: 'Select timezone' },
  { value: 'Pacific/Auckland', label: 'Pacific/Auckland (NZST)' },
  { value: 'Pacific/Chatham', label: 'Pacific/Chatham' },
  { value: 'Australia/Sydney', label: 'Australia/Sydney (AEST)' },
  { value: 'Australia/Melbourne', label: 'Australia/Melbourne (AEST)' },
  { value: 'Australia/Brisbane', label: 'Australia/Brisbane (AEST)' },
  { value: 'Australia/Perth', label: 'Australia/Perth (AWST)' },
  { value: 'Australia/Adelaide', label: 'Australia/Adelaide (ACST)' },
  { value: 'Australia/Darwin', label: 'Australia/Darwin (ACST)' },
  { value: 'Australia/Hobart', label: 'Australia/Hobart (AEST)' },
  { value: 'Pacific/Fiji', label: 'Pacific/Fiji' },
  { value: 'Pacific/Tongatapu', label: 'Pacific/Tongatapu' },
  { value: 'Pacific/Apia', label: 'Pacific/Apia' },
  { value: 'Asia/Singapore', label: 'Asia/Singapore (SGT)' },
  { value: 'Asia/Tokyo', label: 'Asia/Tokyo (JST)' },
  { value: 'Asia/Shanghai', label: 'Asia/Shanghai (CST)' },
  { value: 'Asia/Kolkata', label: 'Asia/Kolkata (IST)' },
  { value: 'Asia/Dubai', label: 'Asia/Dubai (GST)' },
  { value: 'Europe/London', label: 'Europe/London (GMT/BST)' },
  { value: 'Europe/Paris', label: 'Europe/Paris (CET)' },
  { value: 'Europe/Berlin', label: 'Europe/Berlin (CET)' },
  { value: 'America/New_York', label: 'America/New_York (EST)' },
  { value: 'America/Chicago', label: 'America/Chicago (CST)' },
  { value: 'America/Denver', label: 'America/Denver (MST)' },
  { value: 'America/Los_Angeles', label: 'America/Los_Angeles (PST)' },
  { value: 'UTC', label: 'UTC' },
]

const EMPTY_HOURS: Record<string, OperatingHoursEntry> = {}

/**
 * Per-branch settings form — address, phone, email, logo, operating hours, timezone.
 *
 * Requirements: 3.1, 3.2, 3.3, 3.4, 3.5
 */
export default function BranchSettings() {
  const { isEnabled } = useModules()
  if (!isEnabled('branch_management')) return <Navigate to="/dashboard" replace />

  const { id: branchId } = useParams<{ id: string }>()
  const navigate = useNavigate()
  const { toasts, addToast, dismissToast } = useToast()

  const [loading, setLoading] = useState(true)
  const [saving, setSaving] = useState(false)
  const [branchName, setBranchName] = useState('')

  /* Form fields */
  const [address, setAddress] = useState('')
  const [phone, setPhone] = useState('')
  const [email, setEmail] = useState('')
  const [logoUrl, setLogoUrl] = useState('')
  const [timezone, setTimezone] = useState('Pacific/Auckland')
  const [operatingHours, setOperatingHours] = useState<Record<string, OperatingHoursEntry>>(EMPTY_HOURS)
  const [enabledDays, setEnabledDays] = useState<Record<string, boolean>>({})
  const [uploading, setUploading] = useState(false)

  useEffect(() => {
    if (!branchId) return
    const controller = new AbortController()

    const fetchSettings = async () => {
      setLoading(true)
      try {
        const res = await apiClient.get<BranchSettingsData>(
          `/org/branches/${branchId}/settings`,
          { signal: controller.signal },
        )
        const data = res.data
        setAddress(data?.address ?? '')
        setPhone(data?.phone ?? '')
        setEmail(data?.email ?? '')
        setLogoUrl(data?.logo_url ?? '')
        setTimezone(data?.timezone ?? 'Pacific/Auckland')

        const hours = data?.operating_hours ?? {}
        setOperatingHours(hours)
        const enabled: Record<string, boolean> = {}
        for (const day of DAYS_OF_WEEK) {
          enabled[day] = !!hours[day]
        }
        setEnabledDays(enabled)

        // Also fetch branch name for the heading
        try {
          const branchRes = await apiClient.get(`/org/branches`, { signal: controller.signal })
          const branches = Array.isArray(branchRes.data)
            ? branchRes.data
            : (branchRes.data?.branches ?? [])
          const branch = branches.find((b: { id: string; name: string }) => b.id === branchId)
          if (branch) setBranchName(branch.name)
        } catch { /* ignore */ }
      } catch (err: unknown) {
        if (!(err as { name?: string })?.name?.includes('Cancel')) {
          addToast('error', 'Failed to load branch settings')
        }
      } finally {
        setLoading(false)
      }
    }

    fetchSettings()
    return () => controller.abort()
  }, [branchId]) // eslint-disable-line react-hooks/exhaustive-deps

  const toggleDay = (day: string) => {
    setEnabledDays((prev) => {
      const next = { ...prev, [day]: !prev[day] }
      if (!next[day]) {
        setOperatingHours((h) => {
          const copy = { ...h }
          delete copy[day]
          return copy
        })
      } else {
        setOperatingHours((h) => ({
          ...h,
          [day]: h[day] ?? { open: '08:00', close: '17:00' },
        }))
      }
      return next
    })
  }

  const updateHours = (day: string, field: 'open' | 'close', value: string) => {
    setOperatingHours((prev) => ({
      ...prev,
      [day]: { ...(prev[day] ?? { open: '08:00', close: '17:00' }), [field]: value },
    }))
  }

  const handleLogoUpload = async (file: File) => {
    setUploading(true)
    try {
      const fd = new FormData()
      fd.append('file', file)
      const res = await apiClient.post('/api/v2/uploads/logos', fd, {
        headers: { 'Content-Type': 'multipart/form-data' },
      })
      setLogoUrl(res.data?.url ?? res.data?.file_key ?? '')
      addToast('success', 'Logo uploaded')
    } catch {
      addToast('error', 'Failed to upload logo')
    } finally {
      setUploading(false)
    }
  }

  const handleSave = async () => {
    if (!branchId) return
    if (!timezone) {
      addToast('error', 'Please select a valid timezone')
      return
    }
    setSaving(true)
    try {
      await apiClient.put(`/org/branches/${branchId}/settings`, {
        address: address || null,
        phone: phone || null,
        email: email || null,
        logo_url: logoUrl || null,
        timezone,
        operating_hours: operatingHours,
      })
      addToast('success', 'Branch settings saved')
    } catch (err: unknown) {
      const detail = (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail
      addToast('error', detail || 'Failed to save settings')
    } finally {
      setSaving(false)
    }
  }

  if (loading) {
    return <p className="text-gray-500 px-4 py-6">Loading branch settings…</p>
  }

  return (
    <div className="px-4 py-6 sm:px-6 lg:px-8 max-w-3xl">
      <div className="flex items-center gap-3 mb-6">
        <button
          onClick={() => navigate('/settings/branches')}
          className="text-gray-400 hover:text-gray-600"
          aria-label="Back to branches"
        >
          <svg className="w-5 h-5" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
            <path strokeLinecap="round" strokeLinejoin="round" d="M15.75 19.5L8.25 12l7.5-7.5" />
          </svg>
        </button>
        <h1 className="text-2xl font-semibold text-gray-900">
          {branchName ? `${branchName} — Settings` : 'Branch Settings'}
        </h1>
      </div>

      <ToastContainer toasts={toasts} onDismiss={dismissToast} />

      <div className="space-y-6">
        {/* Contact Details */}
        <section className="rounded-lg border border-gray-200 p-5 space-y-4">
          <h2 className="text-lg font-medium text-gray-900">Contact Details</h2>
          <Input label="Address" value={address} onChange={(e) => setAddress(e.target.value)} />
          <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
            <Input label="Phone" value={phone} onChange={(e) => setPhone(e.target.value)} type="tel" />
            <Input label="Email" value={email} onChange={(e) => setEmail(e.target.value)} type="email" />
          </div>
        </section>

        {/* Logo */}
        <section className="rounded-lg border border-gray-200 p-5 space-y-4">
          <h2 className="text-lg font-medium text-gray-900">Branch Logo</h2>
          <p className="text-sm text-gray-500">
            This logo will appear on invoices generated for this branch instead of the organisation logo.
          </p>
          {logoUrl && (
            <div className="flex items-center gap-4">
              <img src={logoUrl} alt="Branch logo" className="h-16 w-auto rounded border border-gray-200" />
              <button
                onClick={() => setLogoUrl('')}
                className="text-sm text-red-500 hover:text-red-700"
              >
                Remove
              </button>
            </div>
          )}
          <div>
            <label className="inline-flex items-center gap-2 rounded-md border border-gray-300 bg-white px-4 py-2 text-sm text-gray-700 hover:bg-gray-50 cursor-pointer">
              <svg className="h-4 w-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                <path strokeLinecap="round" strokeLinejoin="round" d="M4 16v1a3 3 0 003 3h10a3 3 0 003-3v-1m-4-8l-4-4m0 0L8 8m4-4v12" />
              </svg>
              {uploading ? 'Uploading…' : 'Upload Logo'}
              <input
                type="file"
                accept="image/*"
                className="hidden"
                onChange={(e) => {
                  if (e.target.files?.[0]) handleLogoUpload(e.target.files[0])
                }}
              />
            </label>
          </div>
        </section>

        {/* Timezone */}
        <section className="rounded-lg border border-gray-200 p-5 space-y-4">
          <h2 className="text-lg font-medium text-gray-900">Timezone</h2>
          <Select
            label="Branch Timezone"
            options={TIMEZONE_OPTIONS}
            value={timezone}
            onChange={(e) => setTimezone(e.target.value)}
          />
        </section>

        {/* Operating Hours */}
        <section className="rounded-lg border border-gray-200 p-5 space-y-4">
          <h2 className="text-lg font-medium text-gray-900">Operating Hours</h2>
          <p className="text-sm text-gray-500">
            Set the hours this branch is open. Bookings will be validated against these hours.
          </p>
          <div className="space-y-3">
            {DAYS_OF_WEEK.map((day) => (
              <div key={day} className="flex items-center gap-4">
                <label className="flex items-center gap-2 w-32 cursor-pointer">
                  <input
                    type="checkbox"
                    checked={!!enabledDays[day]}
                    onChange={() => toggleDay(day)}
                    className="h-4 w-4 rounded border-gray-300 text-blue-600 focus:ring-blue-500"
                  />
                  <span className="text-sm text-gray-700">{DAY_LABELS[day]}</span>
                </label>
                {enabledDays[day] && (
                  <div className="flex items-center gap-2">
                    <input
                      type="time"
                      value={operatingHours[day]?.open ?? '08:00'}
                      onChange={(e) => updateHours(day, 'open', e.target.value)}
                      className="rounded-md border border-gray-300 px-2 py-1.5 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
                      aria-label={`${DAY_LABELS[day]} opening time`}
                    />
                    <span className="text-sm text-gray-500">to</span>
                    <input
                      type="time"
                      value={operatingHours[day]?.close ?? '17:00'}
                      onChange={(e) => updateHours(day, 'close', e.target.value)}
                      className="rounded-md border border-gray-300 px-2 py-1.5 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
                      aria-label={`${DAY_LABELS[day]} closing time`}
                    />
                  </div>
                )}
                {!enabledDays[day] && (
                  <span className="text-sm text-gray-400">Closed</span>
                )}
              </div>
            ))}
          </div>
        </section>

        {/* Save */}
        <div className="flex justify-end gap-2 pt-2">
          <Button variant="secondary" onClick={() => navigate('/settings/branches')}>Cancel</Button>
          <Button onClick={handleSave} loading={saving}>Save Settings</Button>
        </div>
      </div>
    </div>
  )
}
