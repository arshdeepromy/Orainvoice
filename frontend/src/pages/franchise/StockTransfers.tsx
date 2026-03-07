/**
 * Stock transfers page for requesting and approving inter-location transfers.
 *
 * **Validates: Requirement 8 — Extended RBAC / Multi-Location, Task 43.13**
 */
import React, { useCallback, useEffect, useState } from 'react';
import apiClient from '@/api/client';

interface StockTransferData {
  id: string; org_id: string; from_location_id: string; to_location_id: string;
  product_id: string; quantity: string; status: string;
  requested_by: string | null; approved_by: string | null;
  created_at: string; completed_at: string | null;
}

interface TransferForm {
  from_location_id: string; to_location_id: string;
  product_id: string; quantity: string;
}

const EMPTY_FORM: TransferForm = {
  from_location_id: '', to_location_id: '', product_id: '', quantity: '',
};

export default function StockTransfers() {
  const [transfers, setTransfers] = useState<StockTransferData[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [showForm, setShowForm] = useState(false);
  const [form, setForm] = useState<TransferForm>({ ...EMPTY_FORM });
  const [statusFilter, setStatusFilter] = useState('');

  const fetchTransfers = useCallback(async () => {
    try {
      setLoading(true);
      const params = statusFilter ? `?status=${statusFilter}` : '';
      const res = await apiClient.get(`/api/v2/stock-transfers${params}`);
      setTransfers(res.data);
    } catch {
      setError('Failed to load stock transfers');
    } finally {
      setLoading(false);
    }
  }, [statusFilter]);

  useEffect(() => { fetchTransfers(); }, [fetchTransfers]);

  const handleCreate = async (e: React.FormEvent) => {
    e.preventDefault();
    try {
      await apiClient.post('/api/v2/stock-transfers', {
        from_location_id: form.from_location_id,
        to_location_id: form.to_location_id,
        product_id: form.product_id,
        quantity: parseFloat(form.quantity),
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
    const colors: Record<string, string> = {
      pending: '#f59e0b', approved: '#3b82f6', executed: '#10b981', rejected: '#ef4444',
    };
    return (
      <span data-testid={`status-${status}`}
        style={{ color: colors[status] || '#6b7280', fontWeight: 600 }}>
        {status.charAt(0).toUpperCase() + status.slice(1)}
      </span>
    );
  };

  if (loading) {
    return <p role="status" aria-label="Loading transfers">Loading stock transfers…</p>;
  }

  return (
    <section aria-label="Stock Transfers">
      <h2>Stock Transfers</h2>
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
          <option value="approved">Approved</option>
          <option value="executed">Executed</option>
          <option value="rejected">Rejected</option>
        </select>
      </div>

      <table role="grid" aria-label="Stock transfers list">
        <thead>
          <tr>
            <th>From</th><th>To</th><th>Product</th>
            <th>Quantity</th><th>Status</th><th>Actions</th>
          </tr>
        </thead>
        <tbody>
          {transfers.map((t) => (
            <tr key={t.id} data-testid={`transfer-row-${t.id}`}>
              <td>{t.from_location_id.slice(0, 8)}</td>
              <td>{t.to_location_id.slice(0, 8)}</td>
              <td>{t.product_id.slice(0, 8)}</td>
              <td>{t.quantity}</td>
              <td>{statusBadge(t.status)}</td>
              <td>
                {t.status === 'pending' && (
                  <button onClick={() => handleApprove(t.id)} aria-label="Approve transfer">
                    Approve
                  </button>
                )}
                {t.status === 'approved' && (
                  <button onClick={() => handleExecute(t.id)} aria-label="Execute transfer">
                    Execute
                  </button>
                )}
              </td>
            </tr>
          ))}
          {transfers.length === 0 && (
            <tr><td colSpan={6}>No stock transfers found</td></tr>
          )}
        </tbody>
      </table>

      {!showForm ? (
        <button onClick={() => setShowForm(true)} aria-label="Request transfer">
          Request Transfer
        </button>
      ) : (
        <form onSubmit={handleCreate} aria-label="Create transfer form">
          <div>
            <label htmlFor="tf-from">From Location ID</label>
            <input id="tf-from" type="text" value={form.from_location_id}
              onChange={(e) => setForm({ ...form, from_location_id: e.target.value })} required />
          </div>
          <div>
            <label htmlFor="tf-to">To Location ID</label>
            <input id="tf-to" type="text" value={form.to_location_id}
              onChange={(e) => setForm({ ...form, to_location_id: e.target.value })} required />
          </div>
          <div>
            <label htmlFor="tf-product">Product ID</label>
            <input id="tf-product" type="text" value={form.product_id}
              onChange={(e) => setForm({ ...form, product_id: e.target.value })} required />
          </div>
          <div>
            <label htmlFor="tf-qty">Quantity</label>
            <input id="tf-qty" type="number" step="0.001" min="0.001" value={form.quantity}
              onChange={(e) => setForm({ ...form, quantity: e.target.value })} required />
          </div>
          <button type="submit" aria-label="Submit transfer">Submit</button>
          <button type="button" onClick={() => setShowForm(false)} aria-label="Cancel transfer">Cancel</button>
        </form>
      )}
    </section>
  );
}
