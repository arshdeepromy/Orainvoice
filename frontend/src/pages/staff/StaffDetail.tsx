/**
 * Staff detail page with form for editing staff member details
 * and a weekly availability schedule editor (hours grid).
 *
 * Validates: Requirement — Staff Module
 */

import React, { useEffect, useState, useCallback } from 'react'
import apiClient from '@/api/client'

interface StaffMemberDetail {
  id: string
  org_id: string
  user_id: string | null
  name: string
  email: string | null
  phone: string | null
  role_type: string
  hourly_rate: string | null
  overtime_rate: string | null
  is_active: boolean
  availability_schedule: Record<string, { start: string; end: string }>
  skills: string[]
  location_assignments: Array<{ id: string; location_id: string; assigned_at: string }>
  created_at: string
  updated_at: string
}

const DAYS = ['monday', 'tuesday', 'wednesday', 'thursday', 'friday', 'saturday', 'sunday']
const DAY_LABELS: Record<string, string> = {
  monday: 'Mon', tuesday: 'Tue', wednesday: 'Wed',
  thursday: 'Thu', friday: 'Fri', saturday: 'Sat', sunday: 'Sun',
}

interface Props {
  staffId: string
}

export default function StaffDetail({ staffId }: Props) {
  const [staff, setStaff] = useState<StaffMemberDetail | null>(null)
  const [loading, setLoading] = useState(true)
  const [saving, setSaving] = useState(false)

  // Form state
  const [name, setName] = useState('')
  const [email, setEmail] = useState('')
  const [phone, setPhone] = useState('')
  const [roleType, setRoleType] = useState('employee')
  const [hourlyRate, setHourlyRate] = useState('')
  const [overtimeRate, setOvertimeRate] = useState('')
  const [isActive, setIsActive] = useState(true)
  const [skills, setSkills] = useState('')
  const [schedule, setSchedule] = useState<Record<string, { start: string; end: string }>>({})

  const fetchStaff = useCallback(async () => {
    setLoading(true)
    try {
      const res = await apiClient.get(`/api/v2/staff/${staffId}`)
      const data: StaffMemberDetail = res.data
      setStaff(data)
      setName(data.name)
      setEmail(data.email || '')
      setPhone(data.phone || '')
      setRoleType(data.role_type)
      setHourlyRate(data.hourly_rate || '')
      setOvertimeRate(data.overtime_rate || '')
      setIsActive(data.is_active)
      setSkills((data.skills || []).join(', '))
      setSchedule(data.availability_schedule || {})
    } catch {
      setStaff(null)
    } finally {
      setLoading(false)
    }
  }, [staffId])

  useEffect(() => { fetchStaff() }, [fetchStaff])

  const handleSave = async (e: React.FormEvent) => {
    e.preventDefault()
    setSaving(true)
    try {
      await apiClient.put(`/api/v2/staff/${staffId}`, {
        name,
        email: email || null,
        phone: phone || null,
        role_type: roleType,
        hourly_rate: hourlyRate ? parseFloat(hourlyRate) : null,
        overtime_rate: overtimeRate ? parseFloat(overtimeRate) : null,
        is_active: isActive,
        skills: skills ? skills.split(',').map(s => s.trim()).filter(Boolean) : [],
        availability_schedule: schedule,
      })
      fetchStaff()
    } catch {
      // Save failed
    } finally {
      setSaving(false)
    }
  }

  const handleScheduleChange = (day: string, field: 'start' | 'end', value: string) => {
    setSchedule(prev => ({
      ...prev,
      [day]: { ...prev[day], [field]: value },
    }))
  }

  const toggleDay = (day: string) => {
    setSchedule(prev => {
      if (prev[day]) {
        const next = { ...prev }
        delete next[day]
        return next
      }
      return { ...prev, [day]: { start: '09:00', end: '17:00' } }
    })
  }

  if (loading) {
    return <div role="status" aria-label="Loading staff member">Loading staff member…</div>
  }

  if (!staff) {
    return <p>Staff member not found.</p>
  }

  return (
    <div>
      <h1>{staff.name}</h1>
      <span data-testid="staff-status">{isActive ? 'Active' : 'Inactive'}</span>

      <form onSubmit={handleSave} aria-label="Edit staff member">
        <div style={{ display: 'grid', gap: '0.5rem', marginBottom: '1rem' }}>
          <div>
            <label htmlFor="staff-name">Name</label>
            <input id="staff-name" type="text" required value={name}
              onChange={e => setName(e.target.value)} />
          </div>
          <div>
            <label htmlFor="staff-email">Email</label>
            <input id="staff-email" type="email" value={email}
              onChange={e => setEmail(e.target.value)} />
          </div>
          <div>
            <label htmlFor="staff-phone">Phone</label>
            <input id="staff-phone" type="tel" value={phone}
              onChange={e => setPhone(e.target.value)} />
          </div>
          <div>
            <label htmlFor="staff-role">Role</label>
            <select id="staff-role" value={roleType}
              onChange={e => setRoleType(e.target.value)}>
              <option value="employee">Employee</option>
              <option value="contractor">Contractor</option>
            </select>
          </div>
          <div>
            <label htmlFor="staff-hourly-rate">Hourly Rate</label>
            <input id="staff-hourly-rate" type="number" step="0.01" value={hourlyRate}
              onChange={e => setHourlyRate(e.target.value)} />
          </div>
          <div>
            <label htmlFor="staff-overtime-rate">Overtime Rate</label>
            <input id="staff-overtime-rate" type="number" step="0.01" value={overtimeRate}
              onChange={e => setOvertimeRate(e.target.value)} />
          </div>
          <div>
            <label htmlFor="staff-skills">Skills (comma-separated)</label>
            <input id="staff-skills" type="text" value={skills}
              onChange={e => setSkills(e.target.value)} />
          </div>
          <div>
            <label htmlFor="staff-active">
              <input id="staff-active" type="checkbox" checked={isActive}
                onChange={e => setIsActive(e.target.checked)} />
              Active
            </label>
          </div>
        </div>

        {/* Availability Schedule Editor */}
        <fieldset>
          <legend>Weekly Availability Schedule</legend>
          <table role="grid" aria-label="Availability schedule">
            <thead>
              <tr>
                <th>Day</th>
                <th>Enabled</th>
                <th>Start</th>
                <th>End</th>
              </tr>
            </thead>
            <tbody>
              {DAYS.map(day => (
                <tr key={day} role="row">
                  <td>{DAY_LABELS[day]}</td>
                  <td>
                    <input
                      type="checkbox"
                      checked={!!schedule[day]}
                      onChange={() => toggleDay(day)}
                      aria-label={`Enable ${DAY_LABELS[day]}`}
                    />
                  </td>
                  <td>
                    <input
                      type="time"
                      value={schedule[day]?.start || '09:00'}
                      disabled={!schedule[day]}
                      onChange={e => handleScheduleChange(day, 'start', e.target.value)}
                      aria-label={`${DAY_LABELS[day]} start time`}
                    />
                  </td>
                  <td>
                    <input
                      type="time"
                      value={schedule[day]?.end || '17:00'}
                      disabled={!schedule[day]}
                      onChange={e => handleScheduleChange(day, 'end', e.target.value)}
                      aria-label={`${DAY_LABELS[day]} end time`}
                    />
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </fieldset>

        <div style={{ marginTop: '1rem', display: 'flex', gap: '0.5rem' }}>
          <button type="submit" disabled={saving}>
            {saving ? 'Saving…' : 'Save Changes'}
          </button>
          <a href="/staff"><button type="button">Back to List</button></a>
        </div>
      </form>
    </div>
  )
}
