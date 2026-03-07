/**
 * Asset list page with trade-specific terminology.
 *
 * Displays assets (vehicles, devices, properties, etc.) based on the
 * organisation's trade category. Uses the terminology context to show
 * trade-appropriate labels.
 *
 * **Validates: Extended Asset Tracking — Task 45.10**
 */
import React, { useCallback, useEffect, useState } from 'react';
import apiClient from '@/api/client';

/** Trade-family → asset label mapping */
const ASSET_LABELS: Record<string, string> = {
  'automotive-transport': 'Vehicle',
  'it-technology': 'Device',
  'building-construction': 'Property',
  'landscaping-outdoor': 'Property',
  'cleaning-facilities': 'Property',
  'electrical-mechanical': 'Equipment',
  'plumbing-gas': 'Equipment',
  'food-hospitality': 'Equipment',
  'retail': 'Equipment',
  'health-wellness': 'Device',
};

export function getAssetLabel(tradeFamily?: string): string {
  if (!tradeFamily) return 'Asset';
  return ASSET_LABELS[tradeFamily] || 'Asset';
}

interface AssetData {
  id: string;
  org_id: string;
  customer_id: string | null;
  asset_type: string;
  identifier: string | null;
  make: string | null;
  model: string | null;
  year: number | null;
  serial_number: string | null;
  is_active: boolean;
  created_at: string;
  updated_at: string;
}

interface AssetForm {
  asset_type: string;
  identifier: string;
  make: string;
  model: string;
  year: string;
  serial_number: string;
}

const EMPTY_FORM: AssetForm = {
  asset_type: 'vehicle', identifier: '', make: '', model: '',
  year: '', serial_number: '',
};

interface AssetListProps {
  tradeFamily?: string;
}

export default function AssetList({ tradeFamily }: AssetListProps = {}) {
  const [assets, setAssets] = useState<AssetData[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [showForm, setShowForm] = useState(false);
  const [form, setForm] = useState<AssetForm>({ ...EMPTY_FORM });

  const label = getAssetLabel(tradeFamily);

  const fetchAssets = useCallback(async () => {
    try {
      setLoading(true);
      const res = await apiClient.get('/api/v2/assets');
      setAssets(res.data);
    } catch {
      setError(`Failed to load ${label.toLowerCase()}s`);
    } finally {
      setLoading(false);
    }
  }, [label]);

  useEffect(() => { fetchAssets(); }, [fetchAssets]);

  const handleCreate = async (e: React.FormEvent) => {
    e.preventDefault();
    try {
      await apiClient.post('/api/v2/assets', {
        asset_type: form.asset_type,
        identifier: form.identifier || null,
        make: form.make || null,
        model: form.model || null,
        year: form.year ? parseInt(form.year, 10) : null,
        serial_number: form.serial_number || null,
      });
      setForm({ ...EMPTY_FORM });
      setShowForm(false);
      await fetchAssets();
    } catch (err: any) {
      setError(err?.response?.data?.detail || `Failed to create ${label.toLowerCase()}`);
    }
  };

  if (loading) {
    return <p role="status" aria-label={`Loading ${label.toLowerCase()}s`}>Loading {label.toLowerCase()}s…</p>;
  }

  return (
    <section aria-label={`${label} Management`}>
      <h2>{label}s</h2>
      {error && (
        <div role="alert" className="error-banner">
          {error}
          <button onClick={() => setError(null)} aria-label="Dismiss error">×</button>
        </div>
      )}

      <table role="grid" aria-label={`${label}s list`}>
        <thead>
          <tr>
            <th>Identifier</th>
            <th>Make</th>
            <th>Model</th>
            <th>Year</th>
            <th>Type</th>
            <th>Status</th>
          </tr>
        </thead>
        <tbody>
          {assets.map((a) => (
            <tr key={a.id}>
              <td>{a.identifier || '—'}</td>
              <td>{a.make || '—'}</td>
              <td>{a.model || '—'}</td>
              <td>{a.year || '—'}</td>
              <td>{a.asset_type}</td>
              <td>{a.is_active ? 'Active' : 'Inactive'}</td>
            </tr>
          ))}
          {assets.length === 0 && (
            <tr><td colSpan={6}>No {label.toLowerCase()}s found</td></tr>
          )}
        </tbody>
      </table>

      <button onClick={() => setShowForm(!showForm)} aria-label={`Add ${label.toLowerCase()}`}>
        {showForm ? 'Cancel' : `Add ${label}`}
      </button>

      {showForm && (
        <form onSubmit={handleCreate} aria-label={`Create ${label.toLowerCase()}`}>
          <label>
            Identifier
            <input value={form.identifier} onChange={(e) => setForm({ ...form, identifier: e.target.value })} />
          </label>
          <label>
            Make
            <input value={form.make} onChange={(e) => setForm({ ...form, make: e.target.value })} />
          </label>
          <label>
            Model
            <input value={form.model} onChange={(e) => setForm({ ...form, model: e.target.value })} />
          </label>
          <label>
            Year
            <input type="number" value={form.year} onChange={(e) => setForm({ ...form, year: e.target.value })} />
          </label>
          <label>
            Serial Number
            <input value={form.serial_number} onChange={(e) => setForm({ ...form, serial_number: e.target.value })} />
          </label>
          <button type="submit">Create {label}</button>
        </form>
      )}
    </section>
  );
}
