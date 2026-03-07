/**
 * Location list page for multi-location management.
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

interface LocationForm {
  name: string; address: string; phone: string; email: string;
  invoice_prefix: string; has_own_inventory: boolean;
}

const EMPTY_FORM: LocationForm = {
  name: '', address: '', phone: '', email: '',
  invoice_prefix: '', has_own_inventory: false,
};

export default function LocationList() {
  const [locations, setLocations] = useState<LocationData[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [showForm, setShowForm] = useState(false);
  const [form, setForm] = useState<LocationForm>({ ...EMPTY_FORM });

  const fetchLocations = useCallback(async () => {
    try {
      setLoading(true);
      const res = await apiClient.get('/api/v2/locations');
      setLocations(res.data);
    } catch {
      setError('Failed to load locations');
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { fetchLocations(); }, [fetchLocations]);

  const handleCreate = async (e: React.FormEvent) => {
    e.preventDefault();
    try {
      await apiClient.post('/api/v2/locations', {
        name: form.name,
        address: form.address || null,
        phone: form.phone || null,
        email: form.email || null,
        invoice_prefix: form.invoice_prefix || null,
        has_own_inventory: form.has_own_inventory,
      });
      setForm({ ...EMPTY_FORM });
      setShowForm(false);
      await fetchLocations();
    } catch (err: any) {
      setError(err?.response?.data?.detail || 'Failed to create location');
    }
  };

  if (loading) {
    return <p role="status" aria-label="Loading locations">Loading locations…</p>;
  }

  return (
    <section aria-label="Location Management">
      <h2>Locations</h2>
      {error && (
        <div role="alert" className="error-banner">
          {error}
          <button onClick={() => setError(null)} aria-label="Dismiss error">×</button>
        </div>
      )}

      <table role="grid" aria-label="Locations list">
        <thead>
          <tr><th>Name</th><th>Address</th><th>Phone</th><th>Status</th><th>Inventory</th></tr>
        </thead>
        <tbody>
          {locations.map((loc) => (
            <tr key={loc.id} data-testid={`location-row-${loc.name}`}>
              <td><a href={`/franchise/locations/${loc.id}`}>{loc.name}</a></td>
              <td>{loc.address || '—'}</td>
              <td>{loc.phone || '—'}</td>
              <td>{loc.is_active ? 'Active' : 'Inactive'}</td>
              <td>{loc.has_own_inventory ? 'Yes' : 'No'}</td>
            </tr>
          ))}
          {locations.length === 0 && (
            <tr><td colSpan={5}>No locations configured</td></tr>
          )}
        </tbody>
      </table>

      {!showForm ? (
        <button onClick={() => setShowForm(true)} aria-label="Add location">Add Location</button>
      ) : (
        <form onSubmit={handleCreate} aria-label="Create location form">
          <div>
            <label htmlFor="loc-name">Location Name</label>
            <input id="loc-name" type="text" value={form.name}
              onChange={(e) => setForm({ ...form, name: e.target.value })} required />
          </div>
          <div>
            <label htmlFor="loc-address">Address</label>
            <input id="loc-address" type="text" value={form.address}
              onChange={(e) => setForm({ ...form, address: e.target.value })} />
          </div>
          <div>
            <label htmlFor="loc-phone">Phone</label>
            <input id="loc-phone" type="text" value={form.phone}
              onChange={(e) => setForm({ ...form, phone: e.target.value })} />
          </div>
          <div>
            <label htmlFor="loc-email">Email</label>
            <input id="loc-email" type="email" value={form.email}
              onChange={(e) => setForm({ ...form, email: e.target.value })} />
          </div>
          <div>
            <label htmlFor="loc-prefix">Invoice Prefix</label>
            <input id="loc-prefix" type="text" maxLength={20} value={form.invoice_prefix}
              onChange={(e) => setForm({ ...form, invoice_prefix: e.target.value })} />
          </div>
          <div>
            <label>
              <input type="checkbox" checked={form.has_own_inventory}
                onChange={(e) => setForm({ ...form, has_own_inventory: e.target.checked })} />
              Has Own Inventory
            </label>
          </div>
          <button type="submit" aria-label="Save location">Save Location</button>
          <button type="button" onClick={() => setShowForm(false)} aria-label="Cancel">Cancel</button>
        </form>
      )}
    </section>
  );
}
