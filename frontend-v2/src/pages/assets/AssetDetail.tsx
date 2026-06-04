/**
 * Asset detail page with service history and trade-specific terminology.
 *
 * Shows full asset details, custom fields, and service history
 * (linked invoices, jobs, quotes). Supports Carjam lookup for
 * automotive trades.
 *
 * **Validates: Extended Asset Tracking — Task 45.10**
 */
import React, { useCallback, useEffect, useState } from 'react';
import apiClient from '@/api/client';
import { getAssetLabel } from './AssetList';

interface AssetData {
  id: string;
  org_id: string;
  customer_id: string | null;
  asset_type: string;
  identifier: string | null;
  make: string | null;
  model: string | null;
  year: number | null;
  description: string | null;
  serial_number: string | null;
  location: string | null;
  custom_fields: Record<string, unknown>;
  carjam_data: Record<string, unknown> | null;
  is_active: boolean;
  created_at: string;
  updated_at: string;
}

interface ServiceHistoryEntry {
  reference_type: string;
  reference_id: string;
  reference_number: string | null;
  description: string | null;
  date: string | null;
  status: string | null;
}

interface AssetDetailProps {
  assetId: string;
  tradeFamily?: string;
}

export default function AssetDetail({ assetId, tradeFamily }: AssetDetailProps) {
  const [asset, setAsset] = useState<AssetData | null>(null);
  const [history, setHistory] = useState<ServiceHistoryEntry[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [carjamLoading, setCarjamLoading] = useState(false);

  const label = getAssetLabel(tradeFamily);
  const isAutomotive = tradeFamily === 'automotive-transport';

  const fetchAsset = useCallback(async () => {
    try {
      setLoading(true);
      const [assetRes, historyRes] = await Promise.all([
        apiClient.get(`/api/v2/assets/${assetId}`),
        apiClient.get(`/api/v2/assets/${assetId}/history`),
      ]);
      setAsset(assetRes.data);
      setHistory(historyRes.data.entries || []);
    } catch {
      setError(`Failed to load ${label.toLowerCase()}`);
    } finally {
      setLoading(false);
    }
  }, [assetId, label]);

  useEffect(() => { fetchAsset(); }, [fetchAsset]);

  const handleCarjamLookup = async () => {
    try {
      setCarjamLoading(true);
      await apiClient.post(`/api/v2/assets/${assetId}/carjam`);
      await fetchAsset();
    } catch (err) {
      setError((err as { response?: { data?: { detail?: string } } })?.response?.data?.detail || 'Carjam lookup failed');
    } finally {
      setCarjamLoading(false);
    }
  };

  if (loading) {
    return (
      <p role="status" aria-label={`Loading ${label.toLowerCase()}`} className="px-4 py-8 text-sm text-muted">
        Loading {label.toLowerCase()}…
      </p>
    );
  }

  if (!asset) {
    return <p role="alert" className="px-4 py-8 text-sm text-danger">{label} not found</p>;
  }

  return (
    <section aria-label={`${label} Detail`} className="px-4 py-6 sm:px-6 lg:px-8 space-y-6">
      <h2 className="text-2xl font-semibold text-text">{label}: <span className="mono">{asset.identifier || asset.make || 'Unknown'}</span></h2>
      {error && (
        <div role="alert" className="flex items-center justify-between rounded-ctl border border-danger/40 bg-danger-soft px-4 py-3 text-sm text-danger">
          {error}
          <button onClick={() => setError(null)} aria-label="Dismiss error" className="ml-3 text-danger hover:brightness-90">×</button>
        </div>
      )}

      <dl aria-label={`${label} information`} className="grid grid-cols-1 gap-x-6 gap-y-3 rounded-card border border-border bg-card p-6 shadow-card sm:grid-cols-2">
        <div className="flex justify-between border-b border-border pb-2"><dt className="text-sm text-muted">Type</dt><dd className="text-sm font-medium text-text">{asset.asset_type}</dd></div>
        <div className="flex justify-between border-b border-border pb-2"><dt className="text-sm text-muted">Identifier</dt><dd className="mono text-sm font-medium text-text">{asset.identifier || '—'}</dd></div>
        <div className="flex justify-between border-b border-border pb-2"><dt className="text-sm text-muted">Make</dt><dd className="text-sm font-medium text-text">{asset.make || '—'}</dd></div>
        <div className="flex justify-between border-b border-border pb-2"><dt className="text-sm text-muted">Model</dt><dd className="text-sm font-medium text-text">{asset.model || '—'}</dd></div>
        {asset.year && <div className="flex justify-between border-b border-border pb-2"><dt className="text-sm text-muted">Year</dt><dd className="mono text-sm font-medium text-text">{asset.year}</dd></div>}
        {asset.serial_number && <div className="flex justify-between border-b border-border pb-2"><dt className="text-sm text-muted">Serial Number</dt><dd className="mono text-sm font-medium text-text">{asset.serial_number}</dd></div>}
        {asset.description && <div className="flex justify-between border-b border-border pb-2"><dt className="text-sm text-muted">Description</dt><dd className="text-sm font-medium text-text">{asset.description}</dd></div>}
        {asset.location && <div className="flex justify-between border-b border-border pb-2"><dt className="text-sm text-muted">Location</dt><dd className="text-sm font-medium text-text">{asset.location}</dd></div>}
        <div className="flex justify-between border-b border-border pb-2"><dt className="text-sm text-muted">Status</dt><dd className="text-sm font-medium text-text">{asset.is_active ? 'Active' : 'Inactive'}</dd></div>
      </dl>

      {/* Custom fields */}
      {Object.keys(asset.custom_fields).length > 0 && (
        <section aria-label="Custom fields" className="rounded-card border border-border bg-card p-6 shadow-card">
          <h3 className="mb-3 text-base font-semibold text-text">Custom Fields</h3>
          <dl className="grid grid-cols-1 gap-x-6 gap-y-3 sm:grid-cols-2">
            {Object.entries(asset.custom_fields).map(([key, value]) => (
              <React.Fragment key={key}>
                <div className="flex justify-between border-b border-border pb-2">
                  <dt className="text-sm text-muted">{key}</dt>
                  <dd className="text-sm font-medium text-text">{String(value)}</dd>
                </div>
              </React.Fragment>
            ))}
          </dl>
        </section>
      )}

      {/* Carjam lookup — automotive only */}
      {isAutomotive && (
        <section aria-label="Carjam data" className="rounded-card border border-border bg-card p-6 shadow-card">
          <h3 className="mb-3 text-base font-semibold text-text">Carjam Data</h3>
          {asset.carjam_data ? (
            <pre className="mono overflow-x-auto rounded-ctl border border-border bg-canvas p-3 text-xs text-text">{JSON.stringify(asset.carjam_data, null, 2)}</pre>
          ) : (
            <p className="text-sm text-muted">No Carjam data available</p>
          )}
          <button
            onClick={handleCarjamLookup}
            disabled={carjamLoading}
            aria-label="Lookup Carjam data"
            className="mt-3 inline-flex h-10 items-center rounded-ctl bg-accent px-4 text-sm font-semibold text-white shadow-card hover:bg-accent-press focus:outline-none focus-visible:ring-2 focus-visible:ring-accent disabled:opacity-60"
          >
            {carjamLoading ? 'Looking up…' : 'Carjam Lookup'}
          </button>
        </section>
      )}

      {/* Service history */}
      <section aria-label="Service history" className="rounded-card border border-border bg-card shadow-card">
        <h3 className="border-b border-border px-6 py-4 text-base font-semibold text-text">Service History</h3>
        {history.length === 0 ? (
          <p className="px-6 py-6 text-sm text-muted">No service history</p>
        ) : (
          <div className="overflow-x-auto">
            <table role="grid" aria-label="Service history entries" className="min-w-full">
              <thead>
                <tr>
                  <th className="mono border-b border-border px-4 py-3 text-left text-[10.5px] font-medium uppercase tracking-[0.08em] text-muted-2">Type</th>
                  <th className="mono border-b border-border px-4 py-3 text-left text-[10.5px] font-medium uppercase tracking-[0.08em] text-muted-2">Reference</th>
                  <th className="mono border-b border-border px-4 py-3 text-left text-[10.5px] font-medium uppercase tracking-[0.08em] text-muted-2">Description</th>
                  <th className="mono border-b border-border px-4 py-3 text-left text-[10.5px] font-medium uppercase tracking-[0.08em] text-muted-2">Status</th>
                  <th className="mono border-b border-border px-4 py-3 text-left text-[10.5px] font-medium uppercase tracking-[0.08em] text-muted-2">Date</th>
                </tr>
              </thead>
              <tbody>
                {history.map((entry) => (
                  <tr key={`${entry.reference_type}-${entry.reference_id}`} className="border-b border-border last:border-b-0 hover:bg-canvas">
                    <td className="px-4 py-3 text-sm text-text">{entry.reference_type}</td>
                    <td className="mono px-4 py-3 text-sm text-text">{entry.reference_number || '—'}</td>
                    <td className="px-4 py-3 text-sm text-muted">{entry.description || '—'}</td>
                    <td className="px-4 py-3 text-sm text-muted">{entry.status || '—'}</td>
                    <td className="mono px-4 py-3 text-sm text-muted">{entry.date ? new Date(entry.date).toLocaleDateString() : '—'}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </section>
    </section>
  );
}
