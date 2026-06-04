/**
 * Location detail page for viewing and editing a single location.
 *
 * **Validates: Requirement 8 — Extended RBAC / Multi-Location, Task 43.12**
 */
import React, { useCallback, useEffect, useState } from 'react';
import apiClient from '@/api/client';
import { Button } from '@/components/ui';

interface LocationData {
  id: string; org_id: string; name: string; address: string | null;
  phone: string | null; email: string | null; invoice_prefix: string | null;
  has_own_inventory: boolean; is_active: boolean;
  created_at: string; updated_at: string;
}

interface Props {
  locationId: string;
}

const inputClass =
  'min-h-[44px] w-full rounded-ctl border border-border bg-card px-3 py-2 text-sm text-text outline-none focus:border-accent focus:ring-1 focus:ring-accent';
const labelClass = 'mb-1 block text-sm font-medium text-text';

export default function LocationDetail({ locationId }: Props) {
  const [location, setLocation] = useState<LocationData | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [editing, setEditing] = useState(false);
  const [form, setForm] = useState({
    name: '', address: '', phone: '', email: '',
    invoice_prefix: '', has_own_inventory: false, is_active: true,
  });

  const fetchLocation = useCallback(async (controller?: AbortController) => {
    try {
      setLoading(true);
      const res = await apiClient.get(`/api/v2/locations/${locationId}`, { signal: controller?.signal });
      setLocation(res.data);
      setForm({
        name: res.data.name,
        address: res.data.address || '',
        phone: res.data.phone || '',
        email: res.data.email || '',
        invoice_prefix: res.data.invoice_prefix || '',
        has_own_inventory: res.data.has_own_inventory,
        is_active: res.data.is_active,
      });
    } catch {
      if (!controller?.signal.aborted) {
        setError('Failed to load location');
      }
    } finally {
      setLoading(false);
    }
  }, [locationId]);

  useEffect(() => {
    const controller = new AbortController();
    fetchLocation(controller);
    return () => controller.abort();
  }, [fetchLocation]);

  const handleSave = async (e: React.FormEvent) => {
    e.preventDefault();
    try {
      const res = await apiClient.put(`/api/v2/locations/${locationId}`, {
        name: form.name,
        address: form.address || null,
        phone: form.phone || null,
        email: form.email || null,
        invoice_prefix: form.invoice_prefix || null,
        has_own_inventory: form.has_own_inventory,
        is_active: form.is_active,
      });
      setLocation(res.data);
      setEditing(false);
    } catch (err: any) {
      setError(err?.response?.data?.detail || 'Failed to update location');
    }
  };

  if (loading) {
    return <p role="status" aria-label="Loading location" className="py-12 text-center text-sm text-muted">Loading location…</p>;
  }

  if (!location) {
    return <div role="alert" className="px-4 py-6 text-sm text-muted">Location not found</div>;
  }

  return (
    <section aria-label="Location Detail" className="space-y-4 px-4 py-6 sm:px-6 lg:px-8">
      <h2 className="text-2xl font-semibold text-text">{location.name}</h2>
      {error && (
        <div role="alert" className="flex items-center justify-between rounded-ctl bg-danger-soft px-4 py-3 text-sm text-danger">
          {error}
          <button onClick={() => setError(null)} aria-label="Dismiss error" className="ml-2 text-danger">×</button>
        </div>
      )}

      {!editing ? (
        <div data-testid="location-detail" className="space-y-4">
          <dl className="overflow-hidden rounded-card border border-border bg-card shadow-card">
            <div className="flex items-center justify-between border-b border-border px-4 py-3">
              <dt className="text-sm text-muted">Address</dt><dd data-testid="detail-address" className="text-sm text-text">{location.address || '—'}</dd>
            </div>
            <div className="flex items-center justify-between border-b border-border px-4 py-3">
              <dt className="text-sm text-muted">Phone</dt><dd data-testid="detail-phone" className="mono text-sm text-text">{location.phone || '—'}</dd>
            </div>
            <div className="flex items-center justify-between border-b border-border px-4 py-3">
              <dt className="text-sm text-muted">Email</dt><dd data-testid="detail-email" className="text-sm text-text">{location.email || '—'}</dd>
            </div>
            <div className="flex items-center justify-between border-b border-border px-4 py-3">
              <dt className="text-sm text-muted">Invoice Prefix</dt><dd className="mono text-sm text-text">{location.invoice_prefix || '—'}</dd>
            </div>
            <div className="flex items-center justify-between border-b border-border px-4 py-3">
              <dt className="text-sm text-muted">Own Inventory</dt><dd className="text-sm text-text">{location.has_own_inventory ? 'Yes' : 'No'}</dd>
            </div>
            <div className="flex items-center justify-between px-4 py-3">
              <dt className="text-sm text-muted">Status</dt><dd data-testid="detail-status" className="text-sm text-text">{location.is_active ? 'Active' : 'Inactive'}</dd>
            </div>
          </dl>
          <Button onClick={() => setEditing(true)} aria-label="Edit location">Edit</Button>
        </div>
      ) : (
        <form onSubmit={handleSave} aria-label="Edit location form" className="space-y-3 rounded-card border border-border bg-card p-4 shadow-card">
          <div>
            <label htmlFor="edit-name" className={labelClass}>Name</label>
            <input id="edit-name" type="text" value={form.name}
              onChange={(e) => setForm({ ...form, name: e.target.value })} required className={inputClass} />
          </div>
          <div>
            <label htmlFor="edit-address" className={labelClass}>Address</label>
            <input id="edit-address" type="text" value={form.address}
              onChange={(e) => setForm({ ...form, address: e.target.value })} className={inputClass} />
          </div>
          <div>
            <label htmlFor="edit-phone" className={labelClass}>Phone</label>
            <input id="edit-phone" type="tel" value={form.phone}
              onChange={(e) => setForm({ ...form, phone: e.target.value })} className={inputClass} />
          </div>
          <div>
            <label htmlFor="edit-email" className={labelClass}>Email</label>
            <input id="edit-email" type="email" value={form.email}
              onChange={(e) => setForm({ ...form, email: e.target.value })} className={inputClass} />
          </div>
          <div>
            <label className="flex items-center gap-2 text-sm text-text">
              <input type="checkbox" checked={form.has_own_inventory}
                onChange={(e) => setForm({ ...form, has_own_inventory: e.target.checked })} />
              Has Own Inventory
            </label>
          </div>
          <div>
            <label className="flex items-center gap-2 text-sm text-text">
              <input type="checkbox" checked={form.is_active}
                onChange={(e) => setForm({ ...form, is_active: e.target.checked })} />
              Active
            </label>
          </div>
          <div className="flex gap-2">
            <Button type="submit" aria-label="Save changes">Save</Button>
            <Button type="button" variant="ghost" onClick={() => setEditing(false)} aria-label="Cancel edit">Cancel</Button>
          </div>
        </form>
      )}
    </section>
  );
}
