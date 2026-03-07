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
    } catch (err: any) {
      setError(err?.response?.data?.detail || 'Carjam lookup failed');
    } finally {
      setCarjamLoading(false);
    }
  };

  if (loading) {
    return <p role="status" aria-label={`Loading ${label.toLowerCase()}`}>Loading {label.toLowerCase()}…</p>;
  }

  if (!asset) {
    return <p role="alert">{label} not found</p>;
  }

  return (
    <section aria-label={`${label} Detail`}>
      <h2>{label}: {asset.identifier || asset.make || 'Unknown'}</h2>
      {error && (
        <div role="alert" className="error-banner">
          {error}
          <button onClick={() => setError(null)} aria-label="Dismiss error">×</button>
        </div>
      )}

      <dl aria-label={`${label} information`}>
        <dt>Type</dt><dd>{asset.asset_type}</dd>
        <dt>Identifier</dt><dd>{asset.identifier || '—'}</dd>
        <dt>Make</dt><dd>{asset.make || '—'}</dd>
        <dt>Model</dt><dd>{asset.model || '—'}</dd>
        {asset.year && <><dt>Year</dt><dd>{asset.year}</dd></>}
        {asset.serial_number && <><dt>Serial Number</dt><dd>{asset.serial_number}</dd></>}
        {asset.description && <><dt>Description</dt><dd>{asset.description}</dd></>}
        {asset.location && <><dt>Location</dt><dd>{asset.location}</dd></>}
        <dt>Status</dt><dd>{asset.is_active ? 'Active' : 'Inactive'}</dd>
      </dl>

      {/* Custom fields */}
      {Object.keys(asset.custom_fields).length > 0 && (
        <section aria-label="Custom fields">
          <h3>Custom Fields</h3>
          <dl>
            {Object.entries(asset.custom_fields).map(([key, value]) => (
              <React.Fragment key={key}>
                <dt>{key}</dt>
                <dd>{String(value)}</dd>
              </React.Fragment>
            ))}
          </dl>
        </section>
      )}

      {/* Carjam lookup — automotive only */}
      {isAutomotive && (
        <section aria-label="Carjam data">
          <h3>Carjam Data</h3>
          {asset.carjam_data ? (
            <pre>{JSON.stringify(asset.carjam_data, null, 2)}</pre>
          ) : (
            <p>No Carjam data available</p>
          )}
          <button
            onClick={handleCarjamLookup}
            disabled={carjamLoading}
            aria-label="Lookup Carjam data"
          >
            {carjamLoading ? 'Looking up…' : 'Carjam Lookup'}
          </button>
        </section>
      )}

      {/* Service history */}
      <section aria-label="Service history">
        <h3>Service History</h3>
        {history.length === 0 ? (
          <p>No service history</p>
        ) : (
          <table role="grid" aria-label="Service history entries">
            <thead>
              <tr>
                <th>Type</th>
                <th>Reference</th>
                <th>Description</th>
                <th>Status</th>
                <th>Date</th>
              </tr>
            </thead>
            <tbody>
              {history.map((entry) => (
                <tr key={`${entry.reference_type}-${entry.reference_id}`}>
                  <td>{entry.reference_type}</td>
                  <td>{entry.reference_number || '—'}</td>
                  <td>{entry.description || '—'}</td>
                  <td>{entry.status || '—'}</td>
                  <td>{entry.date ? new Date(entry.date).toLocaleDateString() : '—'}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </section>
    </section>
  );
}
