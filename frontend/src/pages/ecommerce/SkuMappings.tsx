/**
 * SKU Mappings page — map external SKUs to internal products.
 *
 * Validates: Requirement — Ecommerce Module, Task 39.14
 */

import { useCallback, useEffect, useState } from 'react'
import apiClient from '@/api/client'

interface SkuMapping {
  id: string
  external_sku: string
  internal_product_id: string | null
  platform: string
  created_at: string
}

interface NewMapping {
  external_sku: string
  internal_product_id: string
  platform: string
}

export default function SkuMappings() {
  const [mappings, setMappings] = useState<SkuMapping[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [showForm, setShowForm] = useState(false)
  const [form, setForm] = useState<NewMapping>({
    external_sku: '',
    internal_product_id: '',
    platform: 'woocommerce',
  })

  const fetchMappings = useCallback(async () => {
    try {
      const res = await apiClient.get('/api/v2/ecommerce/sku-mappings')
      setMappings(res.data.mappings)
    } catch {
      setError('Failed to load SKU mappings')
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    fetchMappings()
  }, [fetchMappings])

  const handleCreate = async (e: React.FormEvent) => {
    e.preventDefault()
    setError(null)
    try {
      await apiClient.post('/api/v2/ecommerce/sku-mappings', {
        external_sku: form.external_sku,
        internal_product_id: form.internal_product_id || null,
        platform: form.platform,
      })
      setShowForm(false)
      setForm({ external_sku: '', internal_product_id: '', platform: 'woocommerce' })
      fetchMappings()
    } catch (err: any) {
      setError(err?.response?.data?.detail ?? 'Failed to create mapping')
    }
  }

  const handleDelete = async (id: string) => {
    try {
      await apiClient.delete(`/api/v2/ecommerce/sku-mappings/${id}`)
      fetchMappings()
    } catch {
      setError('Failed to delete mapping')
    }
  }

  if (loading) {
    return <div role="status" aria-label="Loading SKU mappings">Loading…</div>
  }

  return (
    <div>
      <h1>SKU Mappings</h1>
      {error && <div role="alert">{error}</div>}

      <button onClick={() => setShowForm(!showForm)}>
        {showForm ? 'Cancel' : 'Add Mapping'}
      </button>

      {showForm && (
        <form onSubmit={handleCreate} aria-label="Create SKU mapping">
          <div>
            <label htmlFor="external_sku">External SKU</label>
            <input
              id="external_sku"
              required
              value={form.external_sku}
              onChange={(e) => setForm({ ...form, external_sku: e.target.value })}
            />
          </div>
          <div>
            <label htmlFor="internal_product_id">Internal Product ID</label>
            <input
              id="internal_product_id"
              value={form.internal_product_id}
              onChange={(e) => setForm({ ...form, internal_product_id: e.target.value })}
            />
          </div>
          <div>
            <label htmlFor="platform">Platform</label>
            <select
              id="platform"
              value={form.platform}
              onChange={(e) => setForm({ ...form, platform: e.target.value })}
            >
              <option value="woocommerce">WooCommerce</option>
              <option value="shopify">Shopify</option>
              <option value="other">Other</option>
            </select>
          </div>
          <button type="submit">Save Mapping</button>
        </form>
      )}

      {mappings.length === 0 ? (
        <p>No SKU mappings configured</p>
      ) : (
        <table role="grid" aria-label="SKU mappings list">
          <thead>
            <tr>
              <th>External SKU</th>
              <th>Product ID</th>
              <th>Platform</th>
              <th>Created</th>
              <th>Actions</th>
            </tr>
          </thead>
          <tbody>
            {mappings.map((m) => (
              <tr key={m.id}>
                <td>{m.external_sku}</td>
                <td>{m.internal_product_id ?? 'Unmapped'}</td>
                <td>{m.platform}</td>
                <td>{new Date(m.created_at).toLocaleDateString()}</td>
                <td>
                  <button onClick={() => handleDelete(m.id)}>Delete</button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </div>
  )
}
