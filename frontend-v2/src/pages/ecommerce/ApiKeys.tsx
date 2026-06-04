/**
 * API Keys management page — create, list, revoke API credentials.
 *
 * Validates: Requirement — Ecommerce Module, Task 39.15
 */

import { useCallback, useEffect, useState } from 'react'
import apiClient from '@/api/client'
import { Button } from '@/components/ui'

interface ApiCredential {
  id: string
  name: string
  scopes: string[]
  rate_limit_per_minute: number
  is_active: boolean
  last_used_at: string | null
  created_at: string
}

const headerCell =
  'mono border-b border-border px-4 py-3 text-left text-[10.5px] font-medium uppercase tracking-[0.08em] text-muted-2'
const inputClass =
  'min-h-[44px] w-full rounded-ctl border border-border bg-card px-3 py-2 text-sm text-text outline-none focus:border-accent focus:ring-1 focus:ring-accent'
const labelClass = 'mb-1 block text-sm font-medium text-text'

export default function ApiKeys() {
  const [credentials, setCredentials] = useState<ApiCredential[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [showForm, setShowForm] = useState(false)
  const [newKeyName, setNewKeyName] = useState('')
  const [createdKey, setCreatedKey] = useState<string | null>(null)

  const fetchCredentials = useCallback(async () => {
    try {
      const res = await apiClient.get('/api/v2/ecommerce/api-keys')
      setCredentials(res.data?.credentials ?? [])
    } catch {
      setError('Failed to load API credentials')
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    fetchCredentials()
  }, [fetchCredentials])

  const handleCreate = async (e: React.FormEvent) => {
    e.preventDefault()
    setError(null)
    setCreatedKey(null)
    try {
      const res = await apiClient.post('/api/v2/ecommerce/api-keys', {
        name: newKeyName,
        scopes: ['read', 'write'],
      })
      setCreatedKey(res.data?.api_key ?? '')
      setShowForm(false)
      setNewKeyName('')
      fetchCredentials()
    } catch (err: any) {
      setError(err?.response?.data?.detail ?? 'Failed to create API key')
    }
  }

  const handleRevoke = async (id: string) => {
    try {
      await apiClient.delete(`/api/v2/ecommerce/api-keys/${id}`)
      fetchCredentials()
    } catch {
      setError('Failed to revoke API key')
    }
  }

  if (loading) {
    return <div role="status" aria-label="Loading API keys" className="py-12 text-center text-sm text-muted">Loading…</div>
  }

  return (
    <div className="space-y-4 px-4 py-6 sm:px-6 lg:px-8">
      <h1 className="text-2xl font-semibold text-text">API Keys</h1>
      {error && <div role="alert" className="rounded-ctl bg-danger-soft px-4 py-3 text-sm text-danger">{error}</div>}

      {createdKey && (
        <div role="alert" data-testid="new-key-display" className="space-y-2 rounded-ctl bg-ok-soft px-4 py-3 text-sm text-ok">
          <strong>New API Key (copy now — it won't be shown again):</strong>
          <code className="mono block break-all rounded-ctl bg-card px-3 py-2 text-text">{createdKey}</code>
        </div>
      )}

      <Button variant={showForm ? 'ghost' : 'primary'} onClick={() => setShowForm(!showForm)}>
        {showForm ? 'Cancel' : 'Create API Key'}
      </Button>

      {showForm && (
        <form onSubmit={handleCreate} aria-label="Create API key" className="max-w-lg space-y-3 rounded-card border border-border bg-card p-4 shadow-card">
          <div>
            <label htmlFor="key_name" className={labelClass}>Key Name</label>
            <input
              id="key_name"
              required
              value={newKeyName}
              onChange={(e) => setNewKeyName(e.target.value)}
              className={inputClass}
            />
          </div>
          <Button type="submit">Generate Key</Button>
        </form>
      )}

      {credentials.length === 0 ? (
        <p className="text-sm text-muted">No API keys configured</p>
      ) : (
        <div className="overflow-x-auto overflow-hidden rounded-card border border-border bg-card shadow-card">
          <table role="grid" aria-label="API credentials list" className="w-full text-sm">
            <thead>
              <tr>
                <th className={headerCell}>Name</th>
                <th className={headerCell}>Scopes</th>
                <th className={headerCell}>Rate Limit</th>
                <th className={headerCell}>Active</th>
                <th className={headerCell}>Last Used</th>
                <th className={headerCell}>Created</th>
                <th className={headerCell}>Actions</th>
              </tr>
            </thead>
            <tbody>
              {credentials.map((c) => (
                <tr key={c.id} className="border-b border-border last:border-b-0 hover:bg-canvas">
                  <td className="px-4 py-3 text-text">{c.name}</td>
                  <td className="px-4 py-3 text-text">{(c.scopes ?? []).join(', ')}</td>
                  <td className="mono px-4 py-3 text-text">{c.rate_limit_per_minute}/min</td>
                  <td className="px-4 py-3 text-text">{c.is_active ? 'Yes' : 'No'}</td>
                  <td className="mono px-4 py-3 text-text">{c.last_used_at ? new Date(c.last_used_at).toLocaleString() : 'Never'}</td>
                  <td className="mono px-4 py-3 text-text">{new Date(c.created_at).toLocaleDateString()}</td>
                  <td className="px-4 py-3">
                    {c.is_active && (
                      <Button variant="ghost" size="sm" onClick={() => handleRevoke(c.id)}>Revoke</Button>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  )
}
