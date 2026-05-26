/**
 * Fleet Portal reminders page — per-vehicle WOF/COF/service-due config.
 *
 * Implements: B2B Fleet Portal — Requirements 10.1–10.8.
 */
import { useEffect, useState } from 'react'

import { fleetClient } from '../api/client'
import { listReminders, listVehicles } from '../api/endpoints'
import type { ReminderPreference, VehicleListItem, LeadTimeDays, ReminderChannel, ReminderRecipient } from '../api/types'
import { useFleetSession } from '../contexts/FleetSessionContext'

export default function RemindersPage() {
  const { user } = useFleetSession()
  const smsConfigured = user?.sms_provider_configured ?? false
  const [reminders, setReminders] = useState<ReminderPreference[]>([])
  const [vehicles, setVehicles] = useState<VehicleListItem[]>([])
  const [loading, setLoading] = useState(true)
  const [saving, setSaving] = useState<string | null>(null)
  const [expandedVehicle, setExpandedVehicle] = useState<string | null>(null)
  const [smsMsg, setSmsMsg] = useState<{ type: 'ok' | 'err'; text: string } | null>(null)

  const fetchData = async () => {
    try {
      const [r, v] = await Promise.all([listReminders(0, 200), listVehicles(0, 100)])
      setReminders(r.items ?? [])
      setVehicles(v.items ?? [])
    } catch {} finally { setLoading(false) }
  }

  useEffect(() => { fetchData() }, [])

  const updateReminder = async (
    vehicleId: string,
    type: string,
    updates: Partial<{ enabled: boolean; lead_time_days: LeadTimeDays; channels: ReminderChannel[]; recipients: ReminderRecipient[] }>,
    current: ReminderPreference | undefined,
  ) => {
    const key = `${vehicleId}-${type}`
    setSaving(key)
    try {
      await fleetClient.put(`/reminders/${vehicleId}/${type}`, {
        enabled: updates.enabled ?? current?.enabled ?? false,
        lead_time_days: updates.lead_time_days ?? current?.lead_time_days ?? 14,
        channels: updates.channels ?? current?.channels ?? ['email'],
        recipients: updates.recipients ?? current?.recipients ?? ['fleet_admin'],
        service_interval_km: current?.service_interval_km ?? null,
        service_interval_months: current?.service_interval_months ?? null,
      })
      await fetchData()
    } catch {} finally { setSaving(null) }
  }

  const sendAdHocSms = async (vehicleId: string, type: string) => {
    setSmsMsg(null)
    try {
      await fleetClient.post('/reminders/send-sms', {
        customer_vehicle_id: vehicleId,
        reminder_type: type,
      })
      setSmsMsg({ type: 'ok', text: 'SMS reminder sent successfully.' })
    } catch (err: unknown) {
      setSmsMsg({ type: 'err', text: (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail ?? 'Failed to send SMS.' })
    }
  }

  if (loading) return <div className="p-4 text-sm text-gray-500">Loading…</div>

  if ((vehicles ?? []).length === 0) {
    return (
      <div className="space-y-4">
        <h1 className="text-xl font-semibold">Reminders</h1>
        <div className="rounded-lg border border-dashed border-gray-300 p-8 text-center dark:border-gray-700">
          <p className="text-sm text-gray-500">Add vehicles to your fleet to configure WOF, COF, and service-due reminders.</p>
        </div>
      </div>
    )
  }

  const types = ['wof_expiry_reminder', 'cof_expiry_reminder', 'service_due_reminder'] as const
  const typeLabels: Record<string, string> = { wof_expiry_reminder: 'WOF Expiry', cof_expiry_reminder: 'COF Expiry', service_due_reminder: 'Service Due' }

  return (
    <div className="space-y-4">
      <h1 className="text-xl font-semibold">Reminders</h1>
      <p className="text-sm text-gray-500">Configure reminder notifications for each vehicle. Tap a vehicle to expand settings.</p>

      {smsMsg && <p className={`text-xs ${smsMsg.type === 'ok' ? 'text-green-600' : 'text-red-600'}`}>{smsMsg.text}</p>}

      <div className="space-y-3">
        {(vehicles ?? []).map(v => {
          const vehicleReminders = (reminders ?? []).filter(r => r.customer_vehicle_id === v.customer_vehicle_id)
          const isExpanded = expandedVehicle === v.customer_vehicle_id

          return (
            <div key={v.customer_vehicle_id} className="rounded-lg border border-gray-200 bg-white dark:border-gray-800 dark:bg-gray-950">
              {/* Vehicle header with toggle summary */}
              <button
                onClick={() => setExpandedVehicle(isExpanded ? null : v.customer_vehicle_id)}
                className="w-full flex items-center justify-between px-4 py-3 text-left min-h-[44px]"
              >
                <div>
                  <span className="text-sm font-medium">{v.rego}</span>
                  <span className="ml-2 text-xs text-gray-500">{[v.make, v.model].filter(Boolean).join(' ')}</span>
                </div>
                <div className="flex items-center gap-2">
                  {types.map(t => {
                    const pref = vehicleReminders.find(r => r.reminder_type === t)
                    return (
                      <span key={t} className={`h-2 w-2 rounded-full ${pref?.enabled ? 'bg-green-500' : 'bg-gray-300 dark:bg-gray-600'}`} title={`${typeLabels[t]}: ${pref?.enabled ? 'On' : 'Off'}`} />
                    )
                  })}
                  <span className="text-xs text-gray-400">{isExpanded ? '▲' : '▼'}</span>
                </div>
              </button>

              {/* Expanded config */}
              {isExpanded && (
                <div className="border-t border-gray-200 px-4 py-3 space-y-4 dark:border-gray-800">
                  {types.map(t => {
                    const pref = vehicleReminders.find(r => r.reminder_type === t)
                    const isOn = pref?.enabled ?? false
                    const key = `${v.customer_vehicle_id}-${t}`

                    return (
                      <div key={t} className="space-y-2">
                        <div className="flex items-center justify-between">
                          <span className="text-sm font-medium">{typeLabels[t]}</span>
                          <button
                            onClick={() => updateReminder(v.customer_vehicle_id, t, { enabled: !isOn }, pref)}
                            disabled={saving === key}
                            className={`relative inline-flex h-6 w-11 items-center rounded-full transition-colors ${isOn ? 'bg-indigo-600' : 'bg-gray-300 dark:bg-gray-700'}`}
                            aria-label={`Toggle ${typeLabels[t]}`}
                          >
                            <span className={`inline-block h-4 w-4 transform rounded-full bg-white transition-transform ${isOn ? 'translate-x-6' : 'translate-x-1'}`} />
                          </button>
                        </div>

                        {isOn && (
                          <div className="ml-4 grid grid-cols-1 gap-2 sm:grid-cols-3 text-xs">
                            {/* Lead time */}
                            <div>
                              <label className="text-gray-500 block mb-1">Lead Time</label>
                              <select
                                value={pref?.lead_time_days ?? 14}
                                onChange={e => updateReminder(v.customer_vehicle_id, t, { lead_time_days: parseInt(e.target.value) as LeadTimeDays }, pref)}
                                className="w-full rounded border border-gray-300 px-2 py-1 text-xs min-h-[36px] dark:border-gray-700 dark:bg-gray-900 dark:text-white"
                              >
                                <option value={7}>7 days</option>
                                <option value={14}>14 days</option>
                                <option value={30}>30 days</option>
                              </select>
                            </div>

                            {/* Channels */}
                            <div>
                              <label className="text-gray-500 block mb-1">Channels</label>
                              <div className="flex gap-2">
                                <label className="flex items-center gap-1">
                                  <input type="checkbox" checked={(pref?.channels ?? ['email']).includes('email')}
                                    onChange={e => {
                                      const channels = [...(pref?.channels ?? ['email'])]
                                      if (e.target.checked && !channels.includes('email')) channels.push('email')
                                      else if (!e.target.checked) channels.splice(channels.indexOf('email'), 1)
                                      updateReminder(v.customer_vehicle_id, t, { channels: channels as ReminderChannel[] }, pref)
                                    }} />
                                  Email
                                </label>
                                <label className={`flex items-center gap-1 ${!smsConfigured ? 'opacity-40' : ''}`}>
                                  <input type="checkbox" disabled={!smsConfigured}
                                    checked={(pref?.channels ?? []).includes('sms')}
                                    onChange={e => {
                                      const channels = [...(pref?.channels ?? ['email'])]
                                      if (e.target.checked && !channels.includes('sms')) channels.push('sms')
                                      else if (!e.target.checked) channels.splice(channels.indexOf('sms'), 1)
                                      updateReminder(v.customer_vehicle_id, t, { channels: channels as ReminderChannel[] }, pref)
                                    }} />
                                  SMS
                                </label>
                              </div>
                            </div>

                            {/* Recipients */}
                            <div>
                              <label className="text-gray-500 block mb-1">Recipients</label>
                              <div className="flex gap-2">
                                <label className="flex items-center gap-1">
                                  <input type="checkbox" checked={(pref?.recipients ?? ['fleet_admin']).includes('fleet_admin')}
                                    onChange={e => {
                                      const recipients = [...(pref?.recipients ?? ['fleet_admin'])]
                                      if (e.target.checked && !recipients.includes('fleet_admin')) recipients.push('fleet_admin')
                                      else if (!e.target.checked) recipients.splice(recipients.indexOf('fleet_admin'), 1)
                                      updateReminder(v.customer_vehicle_id, t, { recipients: recipients as ReminderRecipient[] }, pref)
                                    }} />
                                  Admin
                                </label>
                                <label className="flex items-center gap-1">
                                  <input type="checkbox" checked={(pref?.recipients ?? []).includes('assigned_drivers')}
                                    onChange={e => {
                                      const recipients = [...(pref?.recipients ?? ['fleet_admin'])]
                                      if (e.target.checked && !recipients.includes('assigned_drivers')) recipients.push('assigned_drivers')
                                      else if (!e.target.checked) recipients.splice(recipients.indexOf('assigned_drivers'), 1)
                                      updateReminder(v.customer_vehicle_id, t, { recipients: recipients as ReminderRecipient[] }, pref)
                                    }} />
                                  Drivers
                                </label>
                              </div>
                            </div>
                          </div>
                        )}

                        {/* Ad-hoc SMS button (Req 10.7) */}
                        {isOn && smsConfigured && (
                          <div className="ml-4">
                            <button
                              onClick={() => sendAdHocSms(v.customer_vehicle_id, t)}
                              className="text-xs text-indigo-600 hover:underline min-h-[36px]"
                            >
                              Send SMS Now
                            </button>
                          </div>
                        )}
                      </div>
                    )
                  })}
                </div>
              )}
            </div>
          )
        })}
      </div>

      {!smsConfigured && (
        <p className="text-xs text-gray-400 italic">SMS reminders are disabled — no SMS provider configured for this organisation.</p>
      )}
    </div>
  )
}
