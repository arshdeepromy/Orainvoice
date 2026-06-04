/**
 * StaffPicker — Task 27 port of frontend/src/components/StaffPicker.tsx.
 *
 * Reusable dropdown that fetches active staff (GET /api/v2/staff) and renders a
 * select for assigning staff to jobs. Logic copied VERBATIM (cancelled-guard
 * fetch, loading/error states). Styling remapped onto the design tokens.
 *
 * _Requirements: 3.4_
 */

import { useEffect, useState } from 'react'
import apiClient from '@/api/client'

interface StaffOption {
  id: string
  name: string
}

interface StaffPickerProps {
  value: string | null
  onChange: (staffId: string) => void
  disabled?: boolean
}

export default function StaffPicker({ value, onChange, disabled = false }: StaffPickerProps) {
  const [staffOptions, setStaffOptions] = useState<StaffOption[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    let cancelled = false

    async function fetchStaff() {
      setLoading(true)
      setError(null)
      try {
        const res = await apiClient.get('/staff', {
          baseURL: '/api/v2',
          params: { is_active: true, page_size: 200 },
        })
        if (!cancelled) {
          const data = res.data as { staff: Array<{ id: string; name: string }> }
          setStaffOptions(
            (data.staff ?? []).map((s) => ({ id: s.id, name: s.name })),
          )
        }
      } catch {
        if (!cancelled) {
          setError('Failed to load staff members')
        }
      } finally {
        if (!cancelled) {
          setLoading(false)
        }
      }
    }

    fetchStaff()
    return () => { cancelled = true }
  }, [])

  const selectId = 'staff-picker'
  const errorId = `${selectId}-error`

  return (
    <div className="flex flex-col gap-[7px]">
      <label htmlFor={selectId} className="text-[12.5px] font-medium text-text">
        Assigned To
      </label>
      <select
        id={selectId}
        value={value ?? ''}
        onChange={(e) => onChange(e.target.value)}
        disabled={disabled || loading}
        className={`h-[42px] w-full appearance-none rounded-ctl border bg-card px-[13px] text-[13.5px] text-text shadow-sm transition-[border-color,box-shadow] duration-150
          bg-[url('data:image/svg+xml;charset=utf-8,%3Csvg%20xmlns%3D%22http%3A%2F%2Fwww.w3.org%2F2000%2Fsvg%22%20fill%3D%22none%22%20viewBox%3D%220%200%2024%2024%22%20stroke%3D%22%23687283%22%3E%3Cpath%20stroke-linecap%3D%22round%22%20stroke-linejoin%3D%22round%22%20stroke-width%3D%222%22%20d%3D%22M19%209l-7%207-7-7%22%2F%3E%3C%2Fsvg%3E')]
          bg-[length:20px_20px] bg-[right_8px_center] bg-no-repeat pr-10
          focus:outline-none focus:shadow-[0_0_0_3px_var(--accent-soft)]
          ${error ? 'border-danger focus:border-danger' : 'border-border focus:border-accent'}
          ${disabled ? 'cursor-not-allowed opacity-50' : ''}`}
        aria-invalid={error ? 'true' : undefined}
        aria-describedby={error ? errorId : undefined}
      >
        {loading ? (
          <option value="">Loading staff…</option>
        ) : (
          <>
            <option value="" disabled>
              Select a staff member
            </option>
            {staffOptions.map((s) => (
              <option key={s.id} value={s.id}>
                {s.name}
              </option>
            ))}
          </>
        )}
      </select>
      {error && (
        <p id={errorId} className="text-[12.5px] text-danger" role="alert">
          {error}
        </p>
      )}
    </div>
  )
}
