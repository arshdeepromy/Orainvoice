/**
 * Location detail page for viewing and editing a single location.
 *
 * **Validates: Requirement 8 — Extended RBAC / Multi-Location, Task 43.12**
 */
import React, { useCallback, useEffect, useState } from 'react';
import apiClient from '@/api/client';

interface LocationData {
  id: string; org_id: string; name: string; address: string | null;
  phone: string | null; email: string | null; invoice_prefix: string | null;
  has_own_inventory: boolean; is_active: boolean;
  created_at: string; updated_at: string;
}

interface Props {
  locationId: string;
}

export default function LocationDetail({ locationId }: Props) {
  const [location, setLocation] = useState<LocationData | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [editing, setEditing] = useState(false);
  const [form, setForm] = useState({
    name: '', address: '', phone: '', email: '',
    invoice_prefix: '', has_own_inventory: false, is_active: true,
  });

  const fetchLocation = useCallback(async () => {
    try {
      setLoading(true);
      const res = await apiClient.get(`/api/v2/locations/${locationId}`);
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
      setError('Failed to load location');
    } finally {
      setLoading(false);
    }
  }, [locationId]);

  useEffect(() => { fetchLocation(); }, [fetchLocation]);

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
    return <p role="status" aria-label="Loading location">Loading location…</p>;
  }

  if (!location) {
    return <div role="alert">Location not found</div>;
  }

  return (
    <section aria-label="Location Detail">
      <h2>{location.name}</h2>
      {error && (
        <div role="alert" className="error-banner">
          {error}
          <button onClick={() => setError(null)} aria-label="Dismiss error">×</button>
        </div>
      )}

      {!editing ? (
        <div data-testid="location-detail">
          <dl>
            <dt>Address</dt><dd data-testid="detail-address">{location.address || '—'}</dd>
            <dt>Phone</dt><dd data-testid="detail-phone">{location.phone || '—'}</dd>
            <dt>Email</dt><dd data-testid="detail-email">{location.email || '—'}</dd>
            <dt>Invoice Prefix</dt><dd>{location.invoice_prefix || '—'}</dd>
            <dt>Own Inventory</dt><dd>{location.has_own_inventory ? 'Yes' : 'No'}</dd>
            <dt>Status</dt><dd data-testid="detail-status">{location.is_active ? 'Active' : 'Inactive'}</dd>
          </dl>
          <button onClick={() => setEditing(true)} aria-label="Edit location">Edit</button>
        </div>
      ) : (
        <form onSubmit={handleSave} aria-label="Edit location form">
          <div>
            <label htmlFor="edit-name">Name</label>
            <input id="edit-name" type="text" value={form.name}
              onChange={(e) => setForm({ ...form, name: e.target.value })} required />
          </div>
          <div>
            <label htmlFor="edit-address">Address</label>
            <input id="edit-address" type="text" value={form.address}
              onChange={(e) => setForm({ ...form, address: e.target.value })} />
          </div>
          <div>
            <label htmlFor="edit-phone">Phone</label>
            <input id="edit-phone" type="tel" value={form.phone}
              onChange={(e) => setForm({ ...form, phone: e.target.value })} />
          </div>
          <div>
            <label htmlFor="edit-email">Email</label>
            <input id="edit-email" type="email" value={form.email}
              onChange={(e) => setForm({ ...form, email: e.target.value })} />
          </div>
          <div>
            <label>
              <input type="checkbox" checked={form.has_own_inventory}
                onChange={(e) => setForm({ ...form, has_own_inventory: e.target.checked })} />
              Has Own Inventory
            </label>
          </div>
          <div>
            <label>
              <input type="checkbox" checked={form.is_active}
                onChange={(e) => setForm({ ...form, is_active: e.target.checked })} />
              Active
            </label>
          </div>
          <button type="submit" aria-label="Save changes">Save</button>
          <button type="button" onClick={() => setEditing(false)} aria-label="Cancel edit">Cancel</button>
        </form>
      )}
    </section>
  );
}
