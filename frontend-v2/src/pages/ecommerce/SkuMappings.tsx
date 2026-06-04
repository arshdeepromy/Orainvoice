/**
 * SKU Mappings page — map external SKUs to internal products.
 *
 * Validates: Requirement — Ecommerce Module, Task 39.14
 */

import { useCallback, useEffect, useState } from 'react'
import apiClient from '@/api/client'
import { Button } from '@/components/ui'

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

const headerCell =
  'mono border-b border-border px-4 py-3 text-left text-[10.5px] font-medium uppercase tracking-[0.08em] text-muted-2'
const inputClass =
  'min-h-[44px] w-full rounded-ctl border border-border bg-card px-3 py-2 text-sm text-text outline-none focus:border-accent focus:ring-1 focus:ring-accent'
const labelClass = 'mb-1 block text-sm font-medium text-text'

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
      setMappings(res.data?.mappings ?? [])
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
    return <div role="status" aria-label="Loading SKU mappings" className="py-12 text-center text-sm text-muted">Loading…</div>
  }

  return (
    <div className="space-y-4 px-4 py-6 sm:px-6 lg:px-8">
      <h1 className="text-2xl font-semibold text-text">SKU Mappings</h1>
      {error && <div role="alert" className="rounded-ctl bg-danger-soft px-4 py-3 text-sm text-danger">{error}</div>}

      <Button variant={showForm ? 'ghost' : 'primary'} onClick={() => setShowForm(!showForm)}>
        {showForm ? 'Cancel' : 'Add Mapping'}
      </Button>

      {showForm && (
        <form onSubmit={handleCreate} aria-label="Create SKU mapping" className="max-w-lg space-y-3 rounded-card border border-border bg-card p-4 shadow-card">
          <div>
            <label htmlFor="external_sku" className={labelClass}>External SKU</label>
            <input
              id="external_sku"
              required
              value={form.external_sku}
              onChange={(e) => setForm({ ...form, external_sku: e.target.value })}
              className={inputClass}
            />
          </div>
          <div>
            <label htmlFor="internal_product_id" className={labelClass}>Internal Product ID</label>
            <input
              id="internal_product_id"
              value={form.internal_product_id}
              onChange={(e) => setForm({ ...form, internal_product_id: e.target.value })}
              className={inputClass}
            />
          </div>
          <div>
            <label htmlFor="platform" className={labelClass}>Platform</label>
            <select
              id="platform"
              value={form.platform}
              onChange={(e) => setForm({ ...form, platform: e.target.value })}
              className={inputClass}
            >
              <option value="woocommerce">WooCommerce</option>
              <option value="shopify">Shopify</option>
              <option value="other">Other</option>
            </select>
          </div>
          <Button type="submit">Save Mapping</Button>
        </form>
      )}

      {mappings.length === 0 ? (
        <p className="text-sm text-muted">No SKU mappings configured</p>
      ) : (
        <div className="overflow-x-auto overflow-hidden rounded-card border border-border bg-card shadow-card">
          <table role="grid" aria-label="SKU mappings list" className="w-full text-sm">
            <thead>
              <tr>
                <th className={headerCell}>External SKU</th>
                <th className={headerCell}>Product ID</th>
                <th className={headerCell}>Platform</th>
                <th className={headerCell}>Created</th>
                <th className={headerCell}>Actions</th>
              </tr>
            </thead>
            <tbody>
              {mappings.map((m) => (
                <tr key={m.id} className="border-b border-border last:border-b-0 hover:bg-canvas">
                  <td className="mono px-4 py-3 text-text">{m.external_sku}</td>
                  <td className="mono px-4 py-3 text-text">{m.internal_product_id ?? 'Unmapped'}</td>
                  <td className="px-4 py-3 text-text">{m.platform}</td>
                  <td className="mono px-4 py-3 text-text">{new Date(m.created_at).toLocaleDateString()}</td>
                  <td className="px-4 py-3">
                    <Button variant="ghost" size="sm" onClick={() => handleDelete(m.id)}>Delete</Button>
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
