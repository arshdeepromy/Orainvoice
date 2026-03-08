/**
 * Stock transfers page for creating and managing inter-location transfers.
 * Includes transfer creation form, history list, RBAC scoping, and context integration.
 *
 * Validates: Requirements 2.1, 2.4, 2.5, 2.6, 2.7, 2.8
 */
import React, { useCallback, useEffect, useState } from 'react';
import apiClient from '@/api/client';
import { useAuth } from '@/contexts/AuthContext';
import { useModuleGuard } from '@/hooks/useModuleGuard';
import { useFlag } from '@/contexts/FeatureFlagContext';
import { useTerm } from '@/contexts/TerminologyContext';
import { ToastContainer } from '@/components/ui/Toast';

interface LocationData {
  id: string; name: string; is_active: boolean;
}

interface StockTransferData {
  id: string; org_id: string; from_location_id: string; to_location_id: string;
  from_location_name?: string; to_location_name?: string;
  product_id: string; product_name?: string; quantity: string; status: string;
  notes?: string; requested_by: string | null; approved_by: string | null;
  created_at: string; completed_at: string | null;
}

interface TransferForm {
  from_location_id: string; to_location_id: string;
  product_id: string; quantity: string; notes: string;
}

const EMPTY_FORM: TransferForm = {
  from_location_id: '', to_location_id: '', product_id: '', quantity: '', notes: '',
};

const STATUS_COLORS: Record<string, string> = {
  pending: '#f59e0b', in_transit: '#3b82f6', received: '#10b981',
  cancelled: '#ef4444', approved: '#3b82f6', executed: '#10b981', rejected: '#ef4444',
};

export default function StockTransfers() {
  const { user } = useAuth();
  const { isAllowed, isLoading: guardLoading, toasts, dismissToast } = useModuleGuard('franchise');
  const franchiseEnabled = useFlag('franchise');
  const locationLabel = useTerm('location', 'Location');
  const transferLabel = useTerm('transfer', 'Transfer');

  const [transfers, setTransfers] = useState<StockTransferData[]>([]);
  const [locations, setLocations] = useState<LocationData[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [showForm, setShowForm] = useState(false);
  const [form, setForm] = useState<TransferForm>({ ...EMPTY_FORM });
  const [statusFilter, setStatusFilter] = useState('');

  const fetchLocations = useCallback(async () => {
    try {
      const res = await apiClient.get('/api/v2/locations');
      setLocations(res.data);
    } catch {
      // Non-critical — form will fall back to ID inputs
    }
  }, []);

  const fetchTransfers = useCallback(async () => {
    try {
      setLoading(true);
      const params = statusFilter ? `?status=${statusFilter}` : '';
      const res = await apiClient.get(`/api/v2/stock-transfers${params}`);
      const raw: StockTransferData[] = res.data;
      // RBAC: Location_Manager sees only transfers involving their locations
      const role: string = user?.role ?? '';
      const locs: string[] = (user as any)?.assigned_locations ?? [];
      const scoped = role === 'location_manager'
        ? raw.filter((t) => {
            const locSet = new Set(locs);
            return locSet.has(t.from_location_id) || locSet.has(t.to_location_id);
          })
        : raw;
      setTransfers(scoped);
    } catch {
      setError('Failed to load stock transfers');
    } finally {
      setLoading(false);
    }
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [statusFilter]);

  useEffect(() => { fetchLocations(); fetchTransfers(); }, [fetchLocations, fetchTransfers]);

  const handleCreate = async (e: React.FormEvent) => {
    e.preventDefault();
    if (form.from_location_id === form.to_location_id) {
      setError('Source and destination must be different');
      return;
    }
    try {
      await apiClient.post('/api/v2/stock-transfers', {
        from_location_id: form.from_location_id,
        to_location_id: form.to_location_id,
        product_id: form.product_id,
        quantity: parseFloat(form.quantity),
        notes: form.notes || null,
      });
      setForm({ ...EMPTY_FORM });
      setShowForm(false);
      await fetchTransfers();
    } catch (err: any) {
      setError(err?.response?.data?.detail || 'Failed to create transfer');
    }
  };

  const handleApprove = async (transferId: string) => {
    try {
      await apiClient.put(`/api/v2/stock-transfers/${transferId}/approve`);
      await fetchTransfers();
    } catch (err: any) {
      setError(err?.response?.data?.detail || 'Failed to approve transfer');
    }
  };

  const handleExecute = async (transferId: string) => {
    try {
      await apiClient.put(`/api/v2/stock-transfers/${transferId}/execute`);
      await fetchTransfers();
    } catch (err: any) {
      setError(err?.response?.data?.detail || 'Failed to execute transfer');
    }
  };

  const statusBadge = (status: string) => {
    const displayStatus = status.replace('_', ' ');
    return (
      <span data-testid={`status-${status}`}
        style={{ color: STATUS_COLORS[status] || '#6b7280', fontWeight: 600 }}>
        {displayStatus.charAt(0).toUpperCase() + displayStatus.slice(1)}
      </span>
    );
  };

  const getLocationName = (id: string) => {
    const loc = locations.find((l) => l.id === id);
    return loc ? loc.name : id.slice(0, 8);
  };

  if (guardLoading || loading) {
    return <p role="status" aria-label="Loading transfers">Loading stock transfers…</p>;
  }

  if (!isAllowed || !franchiseEnabled) return null;

  return (
    <section aria-label="Stock Transfers">
      <ToastContainer toasts={toasts} onDismiss={dismissToast} />
      <h2>Stock {transferLabel}s</h2>
      {error && (
        <div role="alert" className="error-banner">
          {error}
          <button onClick={() => setError(null)} aria-label="Dismiss error">×</button>
        </div>
      )}

      <div>
        <label htmlFor="status-filter">Filter by status: </label>
        <select id="status-filter" value={statusFilter}
          onChange={(e) => setStatusFilter(e.target.value)} aria-label="Filter by status">
          <option value="">All</option>
          <option value="pending">Pending</option>
          <option value="in_transit">In Transit</option>
          <option value="received">Received</option>
          <option value="cancelled">Cancelled</option>
          <option value="approved">Approved</option>
          <option value="executed">Executed</option>
        </select>
      </div>

      <table role="grid" aria-label="Stock transfers list">
        <thead>
          <tr>
            <th>From</th><th>To</th><th>Product</th>
            <th>Quantity</th><th>Status</th><th>Date</th><th>Notes</th><th>Actions</th>
          </tr>
        </thead>
        <tbody>
          {transfers.map((t) => (
            <tr key={t.id} data-testid={`transfer-row-${t.id}`}>
              <td>{t.from_location_name || getLocationName(t.from_location_id)}</td>
              <td>{t.to_location_name || getLocationName(t.to_location_id)}</td>
              <td>{t.product_name || t.product_id.slice(0, 8)}</td>
              <td>{t.quantity}</td>
              <td>{statusBadge(t.status)}</td>
              <td>{new Date(t.created_at).toLocaleDateString()}</td>
              <td>{t.notes || '—'}</td>
              <td>
                {t.status === 'pending' && (
                  <button onClick={() => handleApprove(t.id)} aria-label="Approve transfer"
                    style={{ minWidth: 44, minHeight: 44 }}>
                    Approve
                  </button>
                )}
                {t.status === 'approved' && (
                  <button onClick={() => handleExecute(t.id)} aria-label="Execute transfer"
                    style={{ minWidth: 44, minHeight: 44 }}>
                    Execute
                  </button>
                )}
              </td>
            </tr>
          ))}
          {transfers.length === 0 && (
            <tr><td colSpan={8}>No stock transfers found</td></tr>
          )}
        </tbody>
      </table>

      {!showForm ? (
        <button onClick={() => setShowForm(true)} aria-label="Request transfer"
          style={{ minWidth: 44, minHeight: 44 }}>
          Request {transferLabel}
        </button>
      ) : (
        <form onSubmit={handleCreate} aria-label="Create transfer form">
          <div>
            <label htmlFor="tf-from">Source {locationLabel}</label>
            {locations.length > 0 ? (
              <select id="tf-from" value={form.from_location_id}
                onChange={(e) => setForm({ ...form, from_location_id: e.target.value })} required
                aria-label={`Source ${locationLabel}`}>
                <option value="">Select source</option>
                {locations.filter((l) => l.is_active).map((l) => (
                  <option key={l.id} value={l.id}>{l.name}</option>
                ))}
              </select>
            ) : (
              <input id="tf-from" type="text" value={form.from_location_id}
                onChange={(e) => setForm({ ...form, from_location_id: e.target.value })} required />
            )}
          </div>
          <div>
            <label htmlFor="tf-to">Destination {locationLabel}</label>
            {locations.length > 0 ? (
              <select id="tf-to" value={form.to_location_id}
                onChange={(e) => setForm({ ...form, to_location_id: e.target.value })} required
                aria-label={`Destination ${locationLabel}`}>
                <option value="">Select destination</option>
                {locations.filter((l) => l.is_active).map((l) => (
                  <option key={l.id} value={l.id}>{l.name}</option>
                ))}
              </select>
            ) : (
              <input id="tf-to" type="text" value={form.to_location_id}
                onChange={(e) => setForm({ ...form, to_location_id: e.target.value })} required />
            )}
          </div>
          <div>
            <label htmlFor="tf-product">Product ID</label>
            <input id="tf-product" type="text" value={form.product_id}
              onChange={(e) => setForm({ ...form, product_id: e.target.value })} required />
          </div>
          <div>
            <label htmlFor="tf-qty">Quantity</label>
            <input id="tf-qty" type="number" step="0.001" min="0.001" inputMode="numeric" value={form.quantity}
              onChange={(e) => setForm({ ...form, quantity: e.target.value })} required />
          </div>
          <div>
            <label htmlFor="tf-notes">{transferLabel} Notes</label>
            <textarea id="tf-notes" value={form.notes}
              onChange={(e) => setForm({ ...form, notes: e.target.value })}
              aria-label={`${transferLabel} notes`} />
          </div>
          <button type="submit" aria-label="Submit transfer" style={{ minWidth: 44, minHeight: 44 }}>Submit</button>
          <button type="button" onClick={() => setShowForm(false)} aria-label="Cancel transfer" style={{ minWidth: 44, minHeight: 44 }}>Cancel</button>
        </form>
      )}
    </section>
  );
}
