/**
 * Location list page for multi-location management.
 * Supports add, edit, deactivate. RBAC-scoped for Location_Manager.
 *
 * Validates: Requirements 2.1, 2.2, 2.6, 2.7, 2.8
 */
import React, { useCallback, useEffect, useState } from 'react';
import { Link } from 'react-router-dom';
import apiClient from '@/api/client';
import { useAuth } from '@/contexts/AuthContext';
import { useModuleGuard } from '@/hooks/useModuleGuard';
import { useFlag } from '@/contexts/FeatureFlagContext';
import { useTerm } from '@/contexts/TerminologyContext';
import { ToastContainer, Button } from '@/components/ui';
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

const headerCell =
  'mono border-b border-border px-4 py-3 text-left text-[10.5px] font-medium uppercase tracking-[0.08em] text-muted-2';
const inputClass =
  'min-h-[44px] w-full rounded-ctl border border-border bg-card px-3 py-2 text-sm text-text outline-none focus:border-accent focus:ring-1 focus:ring-accent';
const labelClass = 'mb-1 block text-sm font-medium text-text';

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
      const raw: LocationData[] = res.data ?? [];
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
    return <p role="status" aria-label="Loading locations" className="py-12 text-center text-sm text-muted">Loading locations…</p>;
  }

  if (!isAllowed || !franchiseEnabled) return null;

  return (
    <section aria-label="Location Management" className="space-y-4 px-4 py-6 sm:px-6 lg:px-8">
      <ToastContainer toasts={toasts} onDismiss={dismissToast} />
      <h2 className="text-2xl font-semibold text-text">{locationLabel}s</h2>
      {error && (
        <div role="alert" className="flex items-center justify-between rounded-ctl bg-danger-soft px-4 py-3 text-sm text-danger">
          {error}
          <button onClick={() => setError(null)} aria-label="Dismiss error" className="ml-2 text-danger">×</button>
        </div>
      )}

      <div className="overflow-x-auto overflow-hidden rounded-card border border-border bg-card shadow-card">
        <table role="grid" aria-label="Locations list" className="w-full text-sm">
          <thead>
            <tr>
              <th className={headerCell}>Name</th>
              <th className={headerCell}>Address</th>
              <th className={headerCell}>Phone</th>
              <th className={headerCell}>Status</th>
              <th className={headerCell}>Inventory</th>
              <th className={headerCell}>Actions</th>
            </tr>
          </thead>
          <tbody>
            {locations.map((loc) => (
              <tr key={loc.id} data-testid={`location-row-${loc.name}`} className="border-b border-border last:border-b-0 hover:bg-canvas">
                <td className="px-4 py-3"><Link to={`/locations/${loc.id}`} className="text-accent hover:underline">{loc.name}</Link></td>
                <td className="px-4 py-3 text-text">{loc.address || '—'}</td>
                <td className="mono px-4 py-3 text-text">{loc.phone || '—'}</td>
                <td className="px-4 py-3 text-text">{loc.is_active ? 'Active' : 'Inactive'}</td>
                <td className="px-4 py-3 text-text">{loc.has_own_inventory ? 'Yes' : 'No'}</td>
                <td className="px-4 py-3">
                  <div className="flex gap-2">
                    <Button
                      size="sm"
                      variant="ghost"
                      onClick={() => startEdit(loc)}
                      aria-label={`Edit ${loc.name}`}
                    >
                      Edit
                    </Button>
                    {loc.is_active && (
                      <Button
                        size="sm"
                        variant="ghost"
                        onClick={() => handleDeactivate(loc.id)}
                        aria-label={`Deactivate ${loc.name}`}
                      >
                        Deactivate
                      </Button>
                    )}
                  </div>
                </td>
              </tr>
            ))}
            {locations.length === 0 && (
              <tr><td colSpan={6} className="px-4 py-3 text-sm text-muted">No locations configured</td></tr>
            )}
          </tbody>
        </table>
      </div>

      {!showForm ? (
        <Button onClick={() => { setEditingId(null); setForm({ ...EMPTY_FORM }); setShowForm(true); }} aria-label="Add location">
          Add {locationLabel}
        </Button>
      ) : (
        <form onSubmit={editingId ? handleEdit : handleCreate} aria-label={editingId ? 'Edit location form' : 'Create location form'} className="space-y-3 rounded-card border border-border bg-card p-4 shadow-card">
          <div>
            <label htmlFor="loc-name" className={labelClass}>{locationLabel} Name</label>
            <input id="loc-name" type="text" value={form.name}
              onChange={(e) => setForm({ ...form, name: e.target.value })} required className={inputClass} />
          </div>
          <div>
            <label htmlFor="loc-address" className={labelClass}>Address</label>
            <input id="loc-address" type="text" value={form.address}
              onChange={(e) => setForm({ ...form, address: e.target.value })} className={inputClass} />
          </div>
          <div>
            <label htmlFor="loc-phone" className={labelClass}>Phone</label>
            <input id="loc-phone" type="tel" value={form.phone}
              onChange={(e) => setForm({ ...form, phone: e.target.value })} className={inputClass} />
          </div>
          <div>
            <label htmlFor="loc-email" className={labelClass}>Email</label>
            <input id="loc-email" type="email" value={form.email}
              onChange={(e) => setForm({ ...form, email: e.target.value })} className={inputClass} />
          </div>
          <div>
            <label htmlFor="loc-prefix" className={labelClass}>Invoice Prefix</label>
            <input id="loc-prefix" type="text" maxLength={20} value={form.invoice_prefix}
              onChange={(e) => setForm({ ...form, invoice_prefix: e.target.value })} className={inputClass} />
          </div>
          <div>
            <label className="flex items-center gap-2 text-sm text-text">
              <input type="checkbox" checked={form.has_own_inventory}
                onChange={(e) => setForm({ ...form, has_own_inventory: e.target.checked })} />
              Has Own Inventory
            </label>
          </div>
          <div className="flex gap-2">
            <Button type="submit" aria-label={editingId ? 'Update location' : 'Save location'}>
              {editingId ? 'Update' : 'Save'} {locationLabel}
            </Button>
            <Button type="button" variant="ghost" onClick={() => { setShowForm(false); setEditingId(null); }} aria-label="Cancel">Cancel</Button>
          </div>
        </form>
      )}
    </section>
  );
}
