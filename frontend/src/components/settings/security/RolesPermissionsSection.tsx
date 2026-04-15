import { useState, useEffect, useCallback } from 'react'
import { Button } from '@/components/ui/Button'
import { Input } from '@/components/ui/Input'
import { Modal } from '@/components/ui/Modal'
import { ConfirmDialog } from '@/components/ui/ConfirmDialog'
import { useToast, ToastContainer } from '@/components/ui/Toast'
import apiClient from '@/api/client'

interface RoleResponse {
  id: string
  org_id: string
  name: string
  slug: string
  description: string | null
  permissions: string[]
  is_system: boolean
  user_count: number
  created_at: string
}

interface PermissionItem {
  key: string
  label: string
}

interface PermissionGroup {
  module_slug: string
  module_name: string
  permissions: PermissionItem[]
}

/** Expand wildcard permissions into concrete permission keys using available permission groups */
function expandPermissions(rolePerms: string[], groups: PermissionGroup[]): Set<string> {
  const expanded = new Set<string>()
  const allKeys = (groups ?? []).flatMap((g) => (g.permissions ?? []).map((p) => p.key))

  for (const pattern of rolePerms ?? []) {
    if (pattern === '*') {
      allKeys.forEach((k) => expanded.add(k))
    } else if (pattern.endsWith('.*')) {
      const prefix = pattern.slice(0, -2)
      allKeys.filter((k) => k.startsWith(prefix + '.')).forEach((k) => expanded.add(k))
    } else {
      expanded.add(pattern)
    }
  }
  return expanded
}

export function RolesPermissionsSection() {
  const [roles, setRoles] = useState<RoleResponse[]>([])
  const [permissionGroups, setPermissionGroups] = useState<PermissionGroup[]>([])
  const [loading, setLoading] = useState(true)
  const [modalOpen, setModalOpen] = useState(false)
  const [viewMode, setViewMode] = useState(false)
  const [editingRole, setEditingRole] = useState<RoleResponse | null>(null)
  const [roleName, setRoleName] = useState('')
  const [roleDesc, setRoleDesc] = useState('')
  const [selectedPerms, setSelectedPerms] = useState<Set<string>>(new Set())
  const [modalSaving, setModalSaving] = useState(false)
  const [deleteTarget, setDeleteTarget] = useState<RoleResponse | null>(null)
  const [deleting, setDeleting] = useState(false)
  const { toasts, addToast, dismissToast } = useToast()

  const fetchData = useCallback(async () => {
    try {
      const [rolesRes, permsRes] = await Promise.all([
        apiClient.get('/org/roles'),
        apiClient.get('/org/permissions'),
      ])
      setRoles(rolesRes.data?.roles ?? rolesRes.data ?? [])
      setPermissionGroups(permsRes.data?.groups ?? permsRes.data ?? [])
    } catch {
      addToast('error', 'Failed to load roles')
    } finally {
      setLoading(false)
    }
  }, []) // eslint-disable-line react-hooks/exhaustive-deps

  useEffect(() => {
    const controller = new AbortController()
    const load = async () => {
      try {
        const [rolesRes, permsRes] = await Promise.all([
          apiClient.get('/org/roles', { signal: controller.signal }),
          apiClient.get('/org/permissions', { signal: controller.signal }),
        ])
        setRoles(rolesRes.data?.roles ?? rolesRes.data ?? [])
        setPermissionGroups(permsRes.data?.groups ?? permsRes.data ?? [])
      } catch (err) {
        if (!controller.signal.aborted) addToast('error', 'Failed to load roles')
      } finally {
        setLoading(false)
      }
    }
    load()
    return () => controller.abort()
  }, []) // eslint-disable-line react-hooks/exhaustive-deps

  const openCreate = () => {
    setEditingRole(null)
    setViewMode(false)
    setRoleName('')
    setRoleDesc('')
    setSelectedPerms(new Set())
    setModalOpen(true)
  }

  const openView = (role: RoleResponse) => {
    setEditingRole(role)
    setViewMode(true)
    setRoleName(role.name)
    setRoleDesc(role.description ?? '')
    setSelectedPerms(expandPermissions(role.permissions, permissionGroups))
    setModalOpen(true)
  }

  const openEdit = (role: RoleResponse) => {
    setEditingRole(role)
    setViewMode(false)
    setRoleName(role.name)
    setRoleDesc(role.description ?? '')
    setSelectedPerms(new Set(role.permissions ?? []))
    setModalOpen(true)
  }

  const togglePerm = (key: string) => {
    if (viewMode) return
    setSelectedPerms((prev) => {
      const next = new Set(prev)
      if (next.has(key)) next.delete(key)
      else next.add(key)
      return next
    })
  }

  const toggleModule = (group: PermissionGroup) => {
    if (viewMode) return
    const keys = (group.permissions ?? []).map((p) => p.key)
    const allSelected = keys.every((k) => selectedPerms.has(k))
    setSelectedPerms((prev) => {
      const next = new Set(prev)
      keys.forEach((k) => (allSelected ? next.delete(k) : next.add(k)))
      return next
    })
  }

  const saveRole = async () => {
    if (!roleName.trim()) {
      addToast('error', 'Role name is required')
      return
    }
    setModalSaving(true)
    try {
      const perms = Array.from(selectedPerms)
      if (editingRole) {
        await apiClient.put(`/org/roles/${editingRole.id}`, {
          name: roleName,
          description: roleDesc || null,
          permissions: perms,
        })
        addToast('success', 'Role updated')
      } else {
        await apiClient.post('/org/roles', {
          name: roleName,
          description: roleDesc || null,
          permissions: perms,
        })
        addToast('success', 'Role created')
      }
      setModalOpen(false)
      await fetchData()
    } catch (err: unknown) {
      const detail = (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail
      addToast('error', detail ?? 'Failed to save role')
    } finally {
      setModalSaving(false)
    }
  }

  const confirmDelete = async () => {
    if (!deleteTarget) return
    setDeleting(true)
    try {
      await apiClient.delete(`/org/roles/${deleteTarget.id}`)
      addToast('success', 'Role deleted')
      setDeleteTarget(null)
      await fetchData()
    } catch (err: unknown) {
      const detail = (err as { response?: { data?: { detail?: string; message?: string } } })?.response?.data
      addToast('error', detail?.detail ?? detail?.message ?? 'Failed to delete role')
    } finally {
      setDeleting(false)
    }
  }

  /** Count how many concrete permissions a role has (expanding wildcards) */
  const countPermissions = (role: RoleResponse): number => {
    return expandPermissions(role.permissions, permissionGroups).size
  }

  if (loading) return <p className="text-sm text-gray-500">Loading roles…</p>

  return (
    <div className="space-y-4">
      <ToastContainer toasts={toasts} onDismiss={dismissToast} />

      <div className="flex items-center justify-between">
        <p className="text-sm text-gray-600">Manage built-in and custom roles for your organisation.</p>
        <Button size="sm" onClick={openCreate}>Create Role</Button>
      </div>

      <div className="border rounded-lg divide-y divide-gray-200">
        {(roles ?? []).map((role) => (
          <div key={role.id} className="flex items-center justify-between px-4 py-3">
            <div>
              <span className="text-sm font-medium text-gray-900">{role.name}</span>
              {role.is_system && <span className="ml-2 text-xs text-gray-400">Built-in</span>}
              <p className="text-xs text-gray-500">
                {countPermissions(role)} permissions · {role.user_count ?? 0} users
              </p>
              {role.is_system && (role.permissions ?? []).some((p) => p.includes('*')) && (
                <div className="flex flex-wrap gap-1 mt-1">
                  {(role.permissions ?? []).slice(0, 6).map((p) => (
                    <span key={p} className="inline-block rounded bg-gray-100 px-1.5 py-0.5 text-[10px] font-mono text-gray-500">
                      {p}
                    </span>
                  ))}
                  {(role.permissions ?? []).length > 6 && (
                    <span className="text-[10px] text-gray-400">+{(role.permissions ?? []).length - 6} more</span>
                  )}
                </div>
              )}
            </div>
            <div className="flex gap-2">
              {role.is_system ? (
                <Button size="sm" variant="secondary" onClick={() => openView(role)}>View</Button>
              ) : (
                <>
                  <Button size="sm" variant="secondary" onClick={() => openEdit(role)}>Edit</Button>
                  <Button size="sm" variant="danger" onClick={() => setDeleteTarget(role)}>Delete</Button>
                </>
              )}
            </div>
          </div>
        ))}
        {(roles ?? []).length === 0 && (
          <p className="px-4 py-6 text-sm text-gray-500 text-center">No roles found.</p>
        )}
      </div>

      {/* Create/Edit/View Modal */}
      <Modal
        open={modalOpen}
        onClose={() => setModalOpen(false)}
        title={viewMode ? `${editingRole?.name ?? 'Role'} — Permissions` : editingRole ? 'Edit Role' : 'Create Role'}
        className="max-w-2xl"
      >
        <div className="space-y-4">
          {!viewMode && (
            <>
              <Input label="Role Name" value={roleName} onChange={(e) => setRoleName(e.target.value)} required />
              <div className="flex flex-col gap-1">
                <label className="text-sm font-medium text-gray-700">Description</label>
                <textarea
                  rows={2}
                  value={roleDesc}
                  onChange={(e) => setRoleDesc(e.target.value)}
                  className="rounded-md border border-gray-300 px-3 py-2 text-sm text-gray-900 focus:outline-none focus:ring-2 focus:ring-blue-500"
                />
              </div>
            </>
          )}

          {viewMode && editingRole?.is_system && (
            <div className="rounded-md bg-blue-50 border border-blue-200 px-4 py-2 text-sm text-blue-800">
              This is a built-in role. Its permissions are defined at the system level.
              {(editingRole.permissions ?? []).some((p) => p.includes('*')) && (
                <span className="block mt-1 text-xs text-blue-600">
                  Wildcard patterns (e.g. <code className="bg-blue-100 px-1 rounded">invoices.*</code>) grant all actions for that module.
                </span>
              )}
            </div>
          )}

          {/* Raw permission patterns for built-in roles */}
          {viewMode && editingRole?.is_system && (
            <div>
              <p className="text-sm font-medium text-gray-700 mb-2">Permission Patterns</p>
              <div className="flex flex-wrap gap-1.5">
                {(editingRole.permissions ?? []).map((p) => (
                  <span key={p} className="inline-flex items-center rounded-md bg-gray-100 px-2 py-1 text-xs font-mono text-gray-700">
                    {p}
                  </span>
                ))}
              </div>
            </div>
          )}

          <div>
            <p className="text-sm font-medium text-gray-700 mb-2">
              {viewMode ? 'Effective Permissions (expanded)' : 'Permissions'}
            </p>
            <div className="space-y-3 max-h-64 overflow-y-auto border rounded-md p-3">
              {(permissionGroups ?? []).map((group) => {
                const keys = (group.permissions ?? []).map((p) => p.key)
                const allChecked = keys.length > 0 && keys.every((k) => selectedPerms.has(k))
                const someChecked = keys.some((k) => selectedPerms.has(k))
                const hasAnyInGroup = keys.some((k) => selectedPerms.has(k))

                if (viewMode && !hasAnyInGroup) return null

                return (
                  <div key={group.module_slug}>
                    <label className={`flex items-center gap-2 ${viewMode ? '' : 'cursor-pointer'}`}>
                      <input
                        type="checkbox"
                        checked={allChecked}
                        ref={(el) => { if (el) el.indeterminate = someChecked && !allChecked }}
                        onChange={() => toggleModule(group)}
                        disabled={viewMode}
                        className="rounded"
                      />
                      <span className="text-sm font-medium text-gray-800">{group.module_name}</span>
                    </label>
                    <div className="ml-6 mt-1 flex flex-wrap gap-x-4 gap-y-1">
                      {(group.permissions ?? []).map((perm) => (
                        <label key={perm.key} className={`flex items-center gap-1.5 ${viewMode ? '' : 'cursor-pointer'}`}>
                          <input
                            type="checkbox"
                            checked={selectedPerms.has(perm.key)}
                            onChange={() => togglePerm(perm.key)}
                            disabled={viewMode}
                            className="rounded"
                          />
                          <span className="text-xs text-gray-600">{perm.label}</span>
                        </label>
                      ))}
                    </div>
                  </div>
                )
              })}
              {(permissionGroups ?? []).length === 0 && (
                <p className="text-sm text-gray-500">No permissions available.</p>
              )}
            </div>
          </div>

          <div className="flex justify-end gap-3 pt-2">
            <Button variant="secondary" size="sm" onClick={() => setModalOpen(false)}>
              {viewMode ? 'Close' : 'Cancel'}
            </Button>
            {!viewMode && (
              <Button size="sm" onClick={saveRole} loading={modalSaving}>
                {editingRole ? 'Update Role' : 'Create Role'}
              </Button>
            )}
          </div>
        </div>
      </Modal>

      {/* Delete Confirmation */}
      <ConfirmDialog
        open={!!deleteTarget}
        title="Delete Role"
        message={
          deleteTarget && (deleteTarget.user_count ?? 0) > 0
            ? `This role is assigned to ${deleteTarget.user_count} user(s). Are you sure you want to delete "${deleteTarget.name}"?`
            : `Are you sure you want to delete "${deleteTarget?.name ?? ''}"?`
        }
        confirmLabel="Delete"
        variant="danger"
        loading={deleting}
        onConfirm={confirmDelete}
        onCancel={() => setDeleteTarget(null)}
      />
    </div>
  )
}
