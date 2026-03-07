/**
 * Staff list page with paginated table, role filter, active/inactive filter,
 * and create button.
 *
 * Validates: Requirement — Staff Module
 */

import { useEffect, useState, useCallback } from 'react'
import apiClient from '@/api/client'

interface StaffMember {
  id: string
  org_id: string
  name: string
  email: string | null
  phone: string | null
  role_type: string
  hourly_rate: string | null
  is_active: boolean
  created_at: string
}

const ROLE_OPTIONS = [
  { value: '', label: 'All Roles' },
  { value: 'employee', label: 'Employee' },
  { value: 'contractor', label: 'Contractor' },
]

const ACTIVE_OPTIONS = [
  { value: '', label: 'All Status' },
  { value: 'true', label: 'Active' },
  { value: 'false', label: 'Inactive' },
]

export default function StaffList() {
  const [staff, setStaff] = useState<StaffMember[]>([])
  const [total, setTotal] = useState(0)
  const [loading, setLoading] = useState(true)
  const [page, setPage] = useState(1)
  const [roleFilter, setRoleFilter] = useState('')
  const [activeFilter, setActiveFilter] = useState('')
  const pageSize = 20

  const fetchStaff = useCallback(async () => {
    setLoading(true)
    try {
      const params = new URLSearchParams({
        page: String(page),
        page_size: String(pageSize),
      })
      if (roleFilter) params.set('role_type', roleFilter)
      if (activeFilter) params.set('is_active', activeFilter)

      const res = await apiClient.get(`/api/v2/staff?${params}`)
      setStaff(res.data.staff)
      setTotal(res.data.total)
    } catch {
      setStaff([])
    } finally {
      setLoading(false)
    }
  }, [page, roleFilter, activeFilter])

  useEffect(() => { fetchStaff() }, [fetchStaff])

  const totalPages = Math.ceil(total / pageSize)

  if (loading) {
    return <div role="status" aria-label="Loading staff">Loading staff…</div>
  }

  return (
    <div>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
        <h1>Staff</h1>
        <a href="/staff/new" role="link" aria-label="Add staff member">
          <button>+ Add Staff</button>
        </a>
      </div>

      {/* Filters */}
      <div style={{ display: 'flex', gap: '1rem', marginBottom: '1rem' }}>
        <div>
          <label htmlFor="role-filter">Role</label>
          <select
            id="role-filter"
            value={roleFilter}
            onChange={e => { setRoleFilter(e.target.value); setPage(1) }}
          >
            {ROLE_OPTIONS.map(opt => (
              <option key={opt.value} value={opt.value}>{opt.label}</option>
            ))}
          </select>
        </div>
        <div>
          <label htmlFor="active-filter">Status</label>
          <select
            id="active-filter"
            value={activeFilter}
            onChange={e => { setActiveFilter(e.target.value); setPage(1) }}
          >
            {ACTIVE_OPTIONS.map(opt => (
              <option key={opt.value} value={opt.value}>{opt.label}</option>
            ))}
          </select>
        </div>
      </div>

      {/* Staff table */}
      {staff.length === 0 ? (
        <p>No staff members found. Add your first staff member to get started.</p>
      ) : (
        <>
          <table role="grid" aria-label="Staff list">
            <thead>
              <tr>
                <th>Name</th>
                <th>Email</th>
                <th>Phone</th>
                <th>Role</th>
                <th>Hourly Rate</th>
                <th>Status</th>
                <th>Actions</th>
              </tr>
            </thead>
            <tbody>
              {staff.map(member => (
                <tr key={member.id} role="row">
                  <td><a href={`/staff/${member.id}`}>{member.name}</a></td>
                  <td>{member.email || '—'}</td>
                  <td>{member.phone || '—'}</td>
                  <td>{member.role_type}</td>
                  <td>{member.hourly_rate ? `$${Number(member.hourly_rate).toFixed(2)}/hr` : '—'}</td>
                  <td>{member.is_active ? 'Active' : 'Inactive'}</td>
                  <td><a href={`/staff/${member.id}`}>View</a></td>
                </tr>
              ))}
            </tbody>
          </table>

          {totalPages > 1 && (
            <nav aria-label="Pagination">
              <button disabled={page <= 1} onClick={() => setPage(p => p - 1)}>Previous</button>
              <span>Page {page} of {totalPages}</span>
              <button disabled={page >= totalPages} onClick={() => setPage(p => p + 1)}>Next</button>
            </nav>
          )}
        </>
      )}
    </div>
  )
}
