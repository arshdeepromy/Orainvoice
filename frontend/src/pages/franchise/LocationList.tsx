/**
 * Location list page for multi-location management.
 * Supports add, edit, deactivate. RBAC-scoped for Location_Manager.
 *
 * Validates: Requirements 2.1, 2.2, 2.6, 2.7, 2.8
 */
import React, { useCallback, useEffect, useState } from 'react';
import apiClient from '@/api/client';
import { useAuth } from '@/contexts/AuthContext';
import { useModuleGuard } from '@/hooks/useModuleGuard';
import { useFlag } from '@/contexts/FeatureFlagContext';
import { useTerm } from '@/contexts/TerminologyContext';
import { ToastContainer } from '@/components/ui/Toast';
import { filterByUserLocations } from '@/utils/franchiseUtils';

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
  const { user } = useAuth();
  const { isAllowed, isLoading: guardLoading, toasts, dismissToast } = useModuleGuard('franchise');
  const franchiseEnabled = useFlag('franchise');
  const locationLabel = useTerm('location', 'Location');

  const [locations, setLocations] = useState<LocationData[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [showForm, setShowForm] = useState(false);
  const [editingId, setEditingId] = useState<string | null>(null);
  const [form, setForm] = useState<LocationForm>({ ...EMPTY_FORM });

  const fetchLocations = useCallback(async () => {
    try {
      setLoading(true);
      const res = await apiClient.get('/api/v2/locations');
      const raw: LocationData[] = res.data;
      const role: string = user?.role ?? '';
      const locs: string[] = (user as any)?.assigned_locations ?? [];
      const scoped = filterByUserLocations(raw, locs, role, 'id') as LocationData[];
      setLocations(scoped);
    } catch {
      setError('Failed to load locations');
    } finally {
      setLoading(false);
    }
  // eslint-disable-next-line react-hooks/exhaustive-deps
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
      setEditingId(null);
      await fetchLocations();
    } catch (err: any) {
      setError(err?.response?.data?.detail || 'Failed to create location');
    }
  };

  const handleEdit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!editingId) return;
    try {
      await apiClient.put(`/api/v2/locations/${editingId}`, {
        name: form.name,
        address: form.address || null,
        phone: form.phone || null,
        email: form.email || null,
        invoice_prefix: form.invoice_prefix || null,
        has_own_inventory: form.has_own_inventory,
      });
      setForm({ ...EMPTY_FORM });
      setShowForm(false);
      setEditingId(null);
      await fetchLocations();
    } catch (err: any) {
      setError(err?.response?.data?.detail || 'Failed to update location');
    }
  };

  const handleDeactivate = async (locationId: string) => {
    try {
      await apiClient.put(`/api/v2/locations/${locationId}`, { is_active: false });
      await fetchLocations();
    } catch (err: any) {
      setError(err?.response?.data?.detail || 'Failed to deactivate location');
    }
  };

  const startEdit = (loc: LocationData) => {
    setEditingId(loc.id);
    setForm({
      name: loc.name,
      address: loc.address ?? '',
      phone: loc.phone ?? '',
      email: loc.email ?? '',
      invoice_prefix: loc.invoice_prefix ?? '',
      has_own_inventory: loc.has_own_inventory,
    });
    setShowForm(true);
  };

  if (guardLoading || loading) {
    return <p role="status" aria-label="Loading locations">Loading locations…</p>;
  }

  if (!isAllowed || !franchiseEnabled) return null;

  return (
    <section aria-label="Location Management">
      <ToastContainer toasts={toasts} onDismiss={dismissToast} />
      <h2>{locationLabel}s</h2>
      {error && (
        <div role="alert" className="error-banner">
          {error}
          <button onClick={() => setError(null)} aria-label="Dismiss error">×</button>
        </div>
      )}

      <table role="grid" aria-label="Locations list">
        <thead>
          <tr><th>Name</th><th>Address</th><th>Phone</th><th>Status</th><th>Inventory</th><th>Actions</th></tr>
        </thead>
        <tbody>
          {locations.map((loc) => (
            <tr key={loc.id} data-testid={`location-row-${loc.name}`}>
              <td><a href={`/franchise/locations/${loc.id}`}>{loc.name}</a></td>
              <td>{loc.address || '—'}</td>
              <td>{loc.phone || '—'}</td>
              <td>{loc.is_active ? 'Active' : 'Inactive'}</td>
              <td>{loc.has_own_inventory ? 'Yes' : 'No'}</td>
              <td>
                <button
                  onClick={() => startEdit(loc)}
                  aria-label={`Edit ${loc.name}`}
                  style={{ minWidth: 44, minHeight: 44 }}
                >
                  Edit
                </button>
                {loc.is_active && (
                  <button
                    onClick={() => handleDeactivate(loc.id)}
                    aria-label={`Deactivate ${loc.name}`}
                    style={{ minWidth: 44, minHeight: 44 }}
                  >
                    Deactivate
                  </button>
                )}
              </td>
            </tr>
          ))}
          {locations.length === 0 && (
            <tr><td colSpan={6}>No locations configured</td></tr>
          )}
        </tbody>
      </table>

      {!showForm ? (
        <button onClick={() => { setEditingId(null); setForm({ ...EMPTY_FORM }); setShowForm(true); }} aria-label="Add location" style={{ minWidth: 44, minHeight: 44 }}>
          Add {locationLabel}
        </button>
      ) : (
        <form onSubmit={editingId ? handleEdit : handleCreate} aria-label={editingId ? 'Edit location form' : 'Create location form'}>
          <div>
            <label htmlFor="loc-name">{locationLabel} Name</label>
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
            <input id="loc-phone" type="tel" value={form.phone}
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
          <button type="submit" aria-label={editingId ? 'Update location' : 'Save location'} style={{ minWidth: 44, minHeight: 44 }}>
            {editingId ? 'Update' : 'Save'} {locationLabel}
          </button>
          <button type="button" onClick={() => { setShowForm(false); setEditingId(null); }} aria-label="Cancel" style={{ minWidth: 44, minHeight: 44 }}>Cancel</button>
        </form>
      )}
    </section>
  );
}
