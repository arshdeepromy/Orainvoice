/**
 * Stock transfers page for creating and managing inter-location transfers.
 * Includes transfer creation form, history list, RBAC scoping, and context integration.
 *
 * Validates: Requirements 2.1, 2.4, 2.5, 2.6, 2.7, 2.8
 */
import React, { useCallback, useEffect, useRef, useState } from 'react';
import { useNavigate } from 'react-router-dom';
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
  received_quantity?: string | null; discrepancy_quantity?: string | null;
  notes?: string; requested_by: string | null; approved_by: string | null;
  created_at: string; completed_at: string | null;
}

interface ProductSearchResult {
  id: string;
  name: string;
  sku: string | null;
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
  partially_received: '#f97316', cancelled: '#ef4444', approved: '#3b82f6',
  executed: '#10b981', rejected: '#ef4444',
};

export default function StockTransfers() {
  const { user } = useAuth();
  const navigate = useNavigate();
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

  // Product search state
  const [productQuery, setProductQuery] = useState('');
  const [productResults, setProductResults] = useState<ProductSearchResult[]>([]);
  const [productSearching, setProductSearching] = useState(false);
  const [showProductDropdown, setShowProductDropdown] = useState(false);
  const [selectedProductLabel, setSelectedProductLabel] = useState('');
  const productContainerRef = useRef<HTMLDivElement>(null);
  const productDebounceRef = useRef<ReturnType<typeof setTimeout>>(undefined);

  // Receive dialog state for partial transfer support
  const [receiveDialogTransfer, setReceiveDialogTransfer] = useState<StockTransferData | null>(null);
  const [receiveQty, setReceiveQty] = useState('');

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

  // Click outside to close product dropdown
  useEffect(() => {
    const handleClickOutside = (e: MouseEvent) => {
      if (productContainerRef.current && !productContainerRef.current.contains(e.target as Node)) {
        setShowProductDropdown(false);
      }
    };
    document.addEventListener('mousedown', handleClickOutside);
    return () => document.removeEventListener('mousedown', handleClickOutside);
  }, []);

  // Debounced product search
  const searchProducts = useCallback(async (term: string) => {
    if (term.length < 2) {
      setProductResults([]);
      return;
    }
    setProductSearching(true);
    try {
      const res = await apiClient.get<{ products: ProductSearchResult[]; total: number }>(
        '/api/v2/products',
        { params: { search: term, page_size: 20, is_active: true } },
      );
      setProductResults(res.data?.products ?? []);
    } catch {
      setProductResults([]);
    } finally {
      setProductSearching(false);
    }
  }, []);

  useEffect(() => {
    if (productQuery.length < 2) {
      setProductResults([]);
      setShowProductDropdown(false);
      return;
    }
    setShowProductDropdown(true);
    if (productDebounceRef.current) clearTimeout(productDebounceRef.current);
    productDebounceRef.current = setTimeout(() => searchProducts(productQuery), 300);
    return () => {
      if (productDebounceRef.current) clearTimeout(productDebounceRef.current);
    };
  }, [productQuery, searchProducts]);

  const handleSelectProduct = (product: ProductSearchResult) => {
    setForm((prev) => ({ ...prev, product_id: product.id }));
    const label = product.sku ? `${product.name} (${product.sku})` : product.name;
    setSelectedProductLabel(label);
    setProductQuery('');
    setProductResults([]);
    setShowProductDropdown(false);
  };

  const handleClearProduct = () => {
    setForm((prev) => ({ ...prev, product_id: '' }));
    setSelectedProductLabel('');
    setProductQuery('');
    setProductResults([]);
  };

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
      setSelectedProductLabel('');
      setProductQuery('');
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

  const handleReject = async (transferId: string) => {
    try {
      await apiClient.put(`/api/v2/stock-transfers/${transferId}/reject`);
      await fetchTransfers();
    } catch (err: any) {
      setError(err?.response?.data?.detail || 'Failed to reject transfer');
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

  const handleReceive = async (transferId: string) => {
    // Find the transfer to get its quantity for the receive dialog
    const t = transfers.find((tr) => tr.id === transferId);
    if (t) {
      setReceiveQty(t.quantity);
      setReceiveDialogTransfer(t);
    }
  };

  const handleReceiveSubmit = async () => {
    if (!receiveDialogTransfer) return;
    const qty = parseFloat(receiveQty);
    if (isNaN(qty) || qty <= 0) {
      setError('Received quantity must be greater than zero');
      return;
    }
    const transferQty = parseFloat(receiveDialogTransfer.quantity);
    if (qty > transferQty) {
      setError('Received quantity cannot exceed the transfer quantity');
      return;
    }
    try {
      await apiClient.put(`/api/v2/stock-transfers/${receiveDialogTransfer.id}/receive`, {
        received_quantity: qty,
      });
      setReceiveDialogTransfer(null);
      setReceiveQty('');
      await fetchTransfers();
    } catch (err: any) {
      setError(err?.response?.data?.detail || 'Failed to receive transfer');
    }
  };

  const handleReceiveCancel = () => {
    setReceiveDialogTransfer(null);
    setReceiveQty('');
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

  const isUserAtDestination = (toLocationId: string): boolean => {
    const locs: string[] = (user as any)?.assigned_locations ?? [];
    return locs.includes(toLocationId);
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
          <option value="partially_received">Partially Received</option>
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
            <tr key={t.id} data-testid={`transfer-row-${t.id}`}
              onClick={() => navigate(`/stock-transfers/${t.id}`)}
              style={{ cursor: 'pointer' }}
              role="link"
              aria-label={`View transfer from ${t.from_location_name || t.from_location_id.slice(0, 8)} to ${t.to_location_name || t.to_location_id.slice(0, 8)}`}>
              <td>{t.from_location_name || getLocationName(t.from_location_id)}</td>
              <td>{t.to_location_name || getLocationName(t.to_location_id)}</td>
              <td>{t.product_name || t.product_id.slice(0, 8)}</td>
              <td>{t.quantity}</td>
              <td>{statusBadge(t.status)}</td>
              <td>{new Date(t.created_at).toLocaleDateString()}</td>
              <td>{t.notes || '—'}</td>
              <td onClick={(e) => e.stopPropagation()}>
                {t.status === 'pending' && (
                  <>
                    <button onClick={() => handleApprove(t.id)} aria-label="Approve transfer"
                      style={{ minWidth: 44, minHeight: 44 }}>
                      Approve
                    </button>
                    <button onClick={() => handleReject(t.id)} aria-label="Reject transfer"
                      style={{ minWidth: 44, minHeight: 44, marginLeft: 4 }}>
                      Reject
                    </button>
                  </>
                )}
                {t.status === 'approved' && (
                  <button onClick={() => handleExecute(t.id)} aria-label="Execute transfer"
                    style={{ minWidth: 44, minHeight: 44 }}>
                    Execute
                  </button>
                )}
                {t.status === 'executed' && isUserAtDestination(t.to_location_id) && (
                  <button onClick={() => handleReceive(t.id)} aria-label="Receive transfer"
                    style={{ minWidth: 44, minHeight: 44 }}>
                    Receive
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
          <div ref={productContainerRef} style={{ position: 'relative' }}>
            <label htmlFor="tf-product">Product</label>
            {form.product_id && selectedProductLabel ? (
              <div style={{ display: 'flex', alignItems: 'center', gap: 8, padding: '6px 8px', border: '1px solid #d1d5db', borderRadius: 6, background: '#f9fafb' }}>
                <span style={{ flex: 1, fontWeight: 500 }}>{selectedProductLabel}</span>
                <button type="button" onClick={handleClearProduct}
                  aria-label="Change product"
                  style={{ minWidth: 44, minHeight: 44, background: 'none', border: 'none', cursor: 'pointer', color: '#9ca3af' }}>
                  ✕
                </button>
              </div>
            ) : (
              <>
                <input id="tf-product" type="text" value={productQuery}
                  onChange={(e) => setProductQuery(e.target.value)}
                  onFocus={() => productQuery.length >= 2 && setShowProductDropdown(true)}
                  placeholder="Search by name or SKU…"
                  autoComplete="off"
                  aria-label="Search products"
                  required={!form.product_id} />
                {/* Hidden input to hold the actual product_id for form validation */}
                <input type="hidden" value={form.product_id} required />
                {showProductDropdown && productQuery.length >= 2 && (
                  <div style={{ position: 'absolute', top: '100%', left: 0, right: 0, zIndex: 30, marginTop: 4, maxHeight: 240, overflowY: 'auto', borderRadius: 6, border: '1px solid #e5e7eb', background: '#fff', boxShadow: '0 4px 6px -1px rgba(0,0,0,0.1)' }}>
                    {productSearching && (
                      <div style={{ padding: '12px 16px', color: '#6b7280', fontSize: 14 }}>Searching…</div>
                    )}
                    {!productSearching && productResults.length > 0 && (
                      productResults.map((p) => (
                        <button key={p.id} type="button"
                          onClick={() => handleSelectProduct(p)}
                          style={{ display: 'block', width: '100%', textAlign: 'left', padding: '10px 16px', border: 'none', borderBottom: '1px solid #f3f4f6', background: 'none', cursor: 'pointer', minHeight: 44 }}
                          onMouseOver={(e) => { (e.currentTarget as HTMLButtonElement).style.background = '#f9fafb'; }}
                          onMouseOut={(e) => { (e.currentTarget as HTMLButtonElement).style.background = 'none'; }}
                          aria-label={`Select ${p.name}`}>
                          <span style={{ fontWeight: 500, color: '#111827' }}>{p.name}</span>
                          {p.sku && (
                            <span style={{ marginLeft: 8, fontSize: 13, color: '#6b7280' }}>SKU: {p.sku}</span>
                          )}
                        </button>
                      ))
                    )}
                    {!productSearching && productResults.length === 0 && (
                      <div style={{ padding: '12px 16px', color: '#6b7280', fontSize: 14 }}>No products found</div>
                    )}
                  </div>
                )}
              </>
            )}
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
          <button type="button" onClick={() => { setShowForm(false); setSelectedProductLabel(''); setProductQuery(''); setForm({ ...EMPTY_FORM }); }} aria-label="Cancel transfer" style={{ minWidth: 44, minHeight: 44 }}>Cancel</button>
        </form>
      )}

      {/* Receive dialog for partial transfer support */}
      {receiveDialogTransfer && (
        <div
          role="dialog"
          aria-label="Receive transfer"
          aria-modal="true"
          style={{
            position: 'fixed', inset: 0, display: 'flex', alignItems: 'center',
            justifyContent: 'center', background: 'rgba(0,0,0,0.4)', zIndex: 50,
          }}
        >
          <div style={{
            background: '#fff', borderRadius: 8, padding: 24, minWidth: 340,
            maxWidth: 420, boxShadow: '0 8px 30px rgba(0,0,0,0.12)',
          }}>
            <h3 style={{ margin: '0 0 16px 0' }}>Receive Transfer</h3>
            <p style={{ margin: '0 0 8px 0', color: '#374151' }}>
              Transfer quantity: <strong>{receiveDialogTransfer.quantity}</strong>
            </p>
            <div style={{ marginBottom: 16 }}>
              <label htmlFor="receive-qty" style={{ display: 'block', marginBottom: 4, fontWeight: 500 }}>
                Received Quantity
              </label>
              <input
                id="receive-qty"
                type="number"
                step="0.001"
                min="0.001"
                max={receiveDialogTransfer.quantity}
                value={receiveQty}
                onChange={(e) => setReceiveQty(e.target.value)}
                aria-label="Received quantity"
                style={{ width: '100%', padding: '8px 12px', border: '1px solid #d1d5db', borderRadius: 6 }}
                autoFocus
              />
              {receiveQty && parseFloat(receiveQty) < parseFloat(receiveDialogTransfer.quantity) && (
                <p style={{ margin: '8px 0 0 0', fontSize: 13, color: '#f97316' }}>
                  Discrepancy: {(parseFloat(receiveDialogTransfer.quantity) - parseFloat(receiveQty)).toFixed(3)} — transfer will be marked as partially received.
                </p>
              )}
            </div>
            <div style={{ display: 'flex', gap: 8, justifyContent: 'flex-end' }}>
              <button
                type="button"
                onClick={handleReceiveCancel}
                aria-label="Cancel receive"
                style={{ minWidth: 44, minHeight: 44 }}
              >
                Cancel
              </button>
              <button
                type="button"
                onClick={handleReceiveSubmit}
                aria-label="Confirm receive"
                style={{ minWidth: 44, minHeight: 44, fontWeight: 600 }}
              >
                Confirm Receive
              </button>
            </div>
          </div>
        </div>
      )}
    </section>
  );
}
