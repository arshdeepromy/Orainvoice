/**
 * API Keys management page — create, list, revoke API credentials.
 *
 * Validates: Requirement — Ecommerce Module, Task 39.15
 */

import { useCallback, useEffect, useState } from 'react'
import apiClient from '@/api/client'

interface ApiCredential {
  id: string
  name: string
  scopes: string[]
  rate_limit_per_minute: number
  is_active: boolean
  last_used_at: string | null
  created_at: string
}

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
    return <div role="status" aria-label="Loading API keys">Loading…</div>
  }

  return (
    <div>
      <h1>API Keys</h1>
      {error && <div role="alert">{error}</div>}

      {createdKey && (
        <div role="alert" data-testid="new-key-display">
          <strong>New API Key (copy now — it won't be shown again):</strong>
          <code>{createdKey}</code>
        </div>
      )}

      <button onClick={() => setShowForm(!showForm)}>
        {showForm ? 'Cancel' : 'Create API Key'}
      </button>

      {showForm && (
        <form onSubmit={handleCreate} aria-label="Create API key">
          <div>
            <label htmlFor="key_name">Key Name</label>
            <input
              id="key_name"
              required
              value={newKeyName}
              onChange={(e) => setNewKeyName(e.target.value)}
            />
          </div>
          <button type="submit">Generate Key</button>
        </form>
      )}

      {credentials.length === 0 ? (
        <p>No API keys configured</p>
      ) : (
        <table role="grid" aria-label="API credentials list">
          <thead>
            <tr>
              <th>Name</th>
              <th>Scopes</th>
              <th>Rate Limit</th>
              <th>Active</th>
              <th>Last Used</th>
              <th>Created</th>
              <th>Actions</th>
            </tr>
          </thead>
          <tbody>
            {credentials.map((c) => (
              <tr key={c.id}>
                <td>{c.name}</td>
                <td>{c.scopes.join(', ')}</td>
                <td>{c.rate_limit_per_minute}/min</td>
                <td>{c.is_active ? 'Yes' : 'No'}</td>
                <td>{c.last_used_at ? new Date(c.last_used_at).toLocaleString() : 'Never'}</td>
                <td>{new Date(c.created_at).toLocaleDateString()}</td>
                <td>
                  {c.is_active && (
                    <button onClick={() => handleRevoke(c.id)}>Revoke</button>
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </div>
  )
}
