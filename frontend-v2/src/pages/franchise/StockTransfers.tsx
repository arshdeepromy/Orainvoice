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
import { ToastContainer, Button } from '@/components/ui';

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

const STATUS_TONES: Record<string, string> = {
  pending: 'text-warn', in_transit: 'text-accent', received: 'text-ok',
  partially_received: 'text-warn', cancelled: 'text-danger', approved: 'text-accent',
  executed: 'text-ok', rejected: 'text-danger',
};

const headerCell =
  'mono border-b border-border px-4 py-3 text-left text-[10.5px] font-medium uppercase tracking-[0.08em] text-muted-2';
const inputClass =
  'min-h-[44px] w-full rounded-ctl border border-border bg-card px-3 py-2 text-sm text-text outline-none focus:border-accent focus:ring-1 focus:ring-accent';
const labelClass = 'mb-1 block text-sm font-medium text-text';

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
      setLocations(res.data ?? []);
    } catch {
      // Non-critical — form will fall back to ID inputs
    }
  }, []);

  const fetchTransfers = useCallback(async () => {
    try {
      setLoading(true);
      const params = statusFilter ? `?status=${statusFilter}` : '';
      const res = await apiClient.get(`/api/v2/stock-transfers${params}`);
      const raw: StockTransferData[] = res.data ?? [];
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
        className={`font-semibold ${STATUS_TONES[status] || 'text-muted'}`}>
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
    return <p role="status" aria-label="Loading transfers" className="py-12 text-center text-sm text-muted">Loading stock transfers…</p>;
  }

  if (!isAllowed || !franchiseEnabled) return null;

  return (
    <section aria-label="Stock Transfers" className="space-y-4 px-4 py-6 sm:px-6 lg:px-8">
      <ToastContainer toasts={toasts} onDismiss={dismissToast} />
      <h2 className="text-2xl font-semibold text-text">Stock {transferLabel}s</h2>
      {error && (
        <div role="alert" className="flex items-center justify-between rounded-ctl bg-danger-soft px-4 py-3 text-sm text-danger">
          {error}
          <button onClick={() => setError(null)} aria-label="Dismiss error" className="ml-2 text-danger">×</button>
        </div>
      )}

      <div className="flex flex-wrap items-center gap-2">
        <label htmlFor="status-filter" className="text-sm text-muted">Filter by status: </label>
        <select id="status-filter" value={statusFilter}
          onChange={(e) => setStatusFilter(e.target.value)} aria-label="Filter by status"
          className="min-h-[44px] rounded-ctl border border-border bg-card px-3 py-2 text-sm text-text outline-none focus:border-accent focus:ring-1 focus:ring-accent">
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

      <div className="overflow-x-auto overflow-hidden rounded-card border border-border bg-card shadow-card">
        <table role="grid" aria-label="Stock transfers list" className="w-full text-sm">
          <thead>
            <tr>
              <th className={headerCell}>From</th>
              <th className={headerCell}>To</th>
              <th className={headerCell}>Product</th>
              <th className={headerCell}>Quantity</th>
              <th className={headerCell}>Status</th>
              <th className={headerCell}>Date</th>
              <th className={headerCell}>Notes</th>
              <th className={headerCell}>Actions</th>
            </tr>
          </thead>
          <tbody>
            {transfers.map((t) => (
              <tr key={t.id} data-testid={`transfer-row-${t.id}`}
                onClick={() => navigate(`/stock-transfers/${t.id}`)}
                className="cursor-pointer border-b border-border last:border-b-0 hover:bg-canvas"
                role="link"
                aria-label={`View transfer from ${t.from_location_name || t.from_location_id.slice(0, 8)} to ${t.to_location_name || t.to_location_id.slice(0, 8)}`}>
                <td className="px-4 py-3 text-text">{t.from_location_name || getLocationName(t.from_location_id)}</td>
                <td className="px-4 py-3 text-text">{t.to_location_name || getLocationName(t.to_location_id)}</td>
                <td className="px-4 py-3 text-text">{t.product_name || t.product_id.slice(0, 8)}</td>
                <td className="mono px-4 py-3 text-text">{t.quantity}</td>
                <td className="px-4 py-3">{statusBadge(t.status)}</td>
                <td className="mono px-4 py-3 text-text">{new Date(t.created_at).toLocaleDateString()}</td>
                <td className="px-4 py-3 text-text">{t.notes || '—'}</td>
                <td className="px-4 py-3" onClick={(e) => e.stopPropagation()}>
                  <div className="flex flex-wrap gap-2">
                    {t.status === 'pending' && (
                      <>
                        <Button size="sm" variant="ghost" onClick={() => handleApprove(t.id)} aria-label="Approve transfer">
                          Approve
                        </Button>
                        <Button size="sm" variant="ghost" onClick={() => handleReject(t.id)} aria-label="Reject transfer">
                          Reject
                        </Button>
                      </>
                    )}
                    {t.status === 'approved' && (
                      <Button size="sm" variant="ghost" onClick={() => handleExecute(t.id)} aria-label="Execute transfer">
                        Execute
                      </Button>
                    )}
                    {t.status === 'executed' && isUserAtDestination(t.to_location_id) && (
                      <Button size="sm" variant="ghost" onClick={() => handleReceive(t.id)} aria-label="Receive transfer">
                        Receive
                      </Button>
                    )}
                  </div>
                </td>
              </tr>
            ))}
            {transfers.length === 0 && (
              <tr><td colSpan={8} className="px-4 py-3 text-sm text-muted">No stock transfers found</td></tr>
            )}
          </tbody>
        </table>
      </div>

      {!showForm ? (
        <Button onClick={() => setShowForm(true)} aria-label="Request transfer">
          Request {transferLabel}
        </Button>
      ) : (
        <form onSubmit={handleCreate} aria-label="Create transfer form" className="space-y-3 rounded-card border border-border bg-card p-4 shadow-card">
          <div>
            <label htmlFor="tf-from" className={labelClass}>Source {locationLabel}</label>
            {locations.length > 0 ? (
              <select id="tf-from" value={form.from_location_id}
                onChange={(e) => setForm({ ...form, from_location_id: e.target.value })} required
                aria-label={`Source ${locationLabel}`} className={inputClass}>
                <option value="">Select source</option>
                {locations.filter((l) => l.is_active).map((l) => (
                  <option key={l.id} value={l.id}>{l.name}</option>
                ))}
              </select>
            ) : (
              <input id="tf-from" type="text" value={form.from_location_id}
                onChange={(e) => setForm({ ...form, from_location_id: e.target.value })} required className={inputClass} />
            )}
          </div>
          <div>
            <label htmlFor="tf-to" className={labelClass}>Destination {locationLabel}</label>
            {locations.length > 0 ? (
              <select id="tf-to" value={form.to_location_id}
                onChange={(e) => setForm({ ...form, to_location_id: e.target.value })} required
                aria-label={`Destination ${locationLabel}`} className={inputClass}>
                <option value="">Select destination</option>
                {locations.filter((l) => l.is_active).map((l) => (
                  <option key={l.id} value={l.id}>{l.name}</option>
                ))}
              </select>
            ) : (
              <input id="tf-to" type="text" value={form.to_location_id}
                onChange={(e) => setForm({ ...form, to_location_id: e.target.value })} required className={inputClass} />
            )}
          </div>
          <div ref={productContainerRef} className="relative">
            <label htmlFor="tf-product" className={labelClass}>Product</label>
            {form.product_id && selectedProductLabel ? (
              <div className="flex items-center gap-2 rounded-ctl border border-border bg-canvas px-2 py-1.5">
                <span className="flex-1 font-medium text-text">{selectedProductLabel}</span>
                <button type="button" onClick={handleClearProduct}
                  aria-label="Change product"
                  className="flex min-h-[44px] min-w-[44px] items-center justify-center text-muted-2 hover:text-text">
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
                  required={!form.product_id}
                  className={inputClass} />
                {/* Hidden input to hold the actual product_id for form validation */}
                <input type="hidden" value={form.product_id} required />
                {showProductDropdown && productQuery.length >= 2 && (
                  <div className="absolute left-0 right-0 top-full z-30 mt-1 max-h-60 overflow-y-auto rounded-ctl border border-border bg-card shadow-pop">
                    {productSearching && (
                      <div className="px-4 py-3 text-sm text-muted">Searching…</div>
                    )}
                    {!productSearching && productResults.length > 0 && (
                      productResults.map((p) => (
                        <button key={p.id} type="button"
                          onClick={() => handleSelectProduct(p)}
                          className="block min-h-[44px] w-full border-b border-border px-4 py-2.5 text-left last:border-b-0 hover:bg-canvas"
                          aria-label={`Select ${p.name}`}>
                          <span className="font-medium text-text">{p.name}</span>
                          {p.sku && (
                            <span className="mono ml-2 text-[13px] text-muted">SKU: {p.sku}</span>
                          )}
                        </button>
                      ))
                    )}
                    {!productSearching && productResults.length === 0 && (
                      <div className="px-4 py-3 text-sm text-muted">No products found</div>
                    )}
                  </div>
                )}
              </>
            )}
          </div>
          <div>
            <label htmlFor="tf-qty" className={labelClass}>Quantity</label>
            <input id="tf-qty" type="number" step="0.001" min="0.001" inputMode="numeric" value={form.quantity}
              onChange={(e) => setForm({ ...form, quantity: e.target.value })} required className={inputClass} />
          </div>
          <div>
            <label htmlFor="tf-notes" className={labelClass}>{transferLabel} Notes</label>
            <textarea id="tf-notes" value={form.notes}
              onChange={(e) => setForm({ ...form, notes: e.target.value })}
              aria-label={`${transferLabel} notes`} className={inputClass} />
          </div>
          <div className="flex gap-2">
            <Button type="submit" aria-label="Submit transfer">Submit</Button>
            <Button type="button" variant="ghost" onClick={() => { setShowForm(false); setSelectedProductLabel(''); setProductQuery(''); setForm({ ...EMPTY_FORM }); }} aria-label="Cancel transfer">Cancel</Button>
          </div>
        </form>
      )}

      {/* Receive dialog for partial transfer support */}
      {receiveDialogTransfer && (
        <div
          role="dialog"
          aria-label="Receive transfer"
          aria-modal="true"
          className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 px-4"
        >
          <div className="w-full max-w-[420px] min-w-[340px] rounded-card bg-card p-6 shadow-pop">
            <h3 className="mb-4 text-lg font-semibold text-text">Receive Transfer</h3>
            <p className="mb-2 text-sm text-text">
              Transfer quantity: <strong>{receiveDialogTransfer.quantity}</strong>
            </p>
            <div className="mb-4">
              <label htmlFor="receive-qty" className={labelClass}>
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
                className={inputClass}
                autoFocus
              />
              {receiveQty && parseFloat(receiveQty) < parseFloat(receiveDialogTransfer.quantity) && (
                <p className="mt-2 text-[13px] text-warn">
                  Discrepancy: {(parseFloat(receiveDialogTransfer.quantity) - parseFloat(receiveQty)).toFixed(3)} — transfer will be marked as partially received.
                </p>
              )}
            </div>
            <div className="flex justify-end gap-2">
              <Button
                type="button"
                variant="ghost"
                onClick={handleReceiveCancel}
                aria-label="Cancel receive"
              >
                Cancel
              </Button>
              <Button
                type="button"
                onClick={handleReceiveSubmit}
                aria-label="Confirm receive"
              >
                Confirm Receive
              </Button>
            </div>
          </div>
        </div>
      )}
    </section>
  );
}
