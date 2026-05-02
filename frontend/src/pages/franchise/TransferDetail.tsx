/**
 * Transfer detail page for viewing a single stock transfer with status-appropriate actions
 * and an audit trail timeline.
 *
 * Validates: Requirements 34.1, 34.2, 34.3, 53.1, 53.2, 53.3
 */
import { useCallback, useEffect, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import apiClient from '@/api/client';
import { useAuth } from '@/contexts/AuthContext';

interface LocationData {
  id: string;
  name: string;
  is_active: boolean;
}

interface StockTransferData {
  id: string;
  org_id: string;
  from_location_id: string;
  to_location_id: string;
  from_location_name?: string;
  to_location_name?: string;
  product_id: string;
  product_name?: string;
  quantity: string;
  received_quantity?: string | null;
  discrepancy_quantity?: string | null;
  status: string;
  notes?: string;
  requested_by: string | null;
  approved_by: string | null;
  created_at: string;
  completed_at: string | null;
}

interface TransferActionData {
  id: string;
  transfer_id: string;
  action: string;
  performed_by: string | null;
  notes: string | null;
  created_at: string;
}

interface Props {
  transferId: string;
}

const STATUS_COLORS: Record<string, string> = {
  pending: '#f59e0b',
  in_transit: '#3b82f6',
  received: '#10b981',
  partially_received: '#f97316',
  cancelled: '#ef4444',
  approved: '#3b82f6',
  executed: '#10b981',
  rejected: '#ef4444',
};

const ACTION_LABELS: Record<string, string> = {
  created: 'Transfer Created',
  approved: 'Transfer Approved',
  rejected: 'Transfer Rejected',
  executed: 'Transfer Executed',
  received: 'Transfer Received',
  partially_received: 'Partially Received',
};

const ACTION_COLORS: Record<string, string> = {
  created: '#6b7280',
  approved: '#3b82f6',
  rejected: '#ef4444',
  executed: '#10b981',
  received: '#8b5cf6',
  partially_received: '#f97316',
};

export default function TransferDetail({ transferId }: Props) {
  const { user } = useAuth();
  const navigate = useNavigate();
  const [transfer, setTransfer] = useState<StockTransferData | null>(null);
  const [locations, setLocations] = useState<LocationData[]>([]);
  const [auditTrail, setAuditTrail] = useState<TransferActionData[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [actionLoading, setActionLoading] = useState(false);

  // Receive dialog state for partial transfer support
  const [showReceiveDialog, setShowReceiveDialog] = useState(false);
  const [receiveQty, setReceiveQty] = useState('');

  const fetchTransfer = useCallback(async (controller?: AbortController) => {
    try {
      setLoading(true);
      const [transfersRes, locationsRes, actionsRes] = await Promise.all([
        apiClient.get('/api/v2/stock-transfers', { signal: controller?.signal }),
        apiClient.get('/api/v2/locations', { signal: controller?.signal }),
        apiClient.get(`/api/v2/stock-transfers/${transferId}/actions`, { signal: controller?.signal }),
      ]);
      const allTransfers: StockTransferData[] = transfersRes.data ?? [];
      const found = allTransfers.find((t) => t.id === transferId) ?? null;
      setTransfer(found);
      setLocations(locationsRes.data ?? []);
      setAuditTrail(actionsRes.data ?? []);
    } catch (err: any) {
      if (!controller?.signal.aborted) {
        setError('Failed to load transfer details');
      }
    } finally {
      setLoading(false);
    }
  }, [transferId]);

  useEffect(() => {
    const controller = new AbortController();
    fetchTransfer(controller);
    return () => controller.abort();
  }, [fetchTransfer]);

  const getLocationName = (id: string) => {
    const loc = locations.find((l) => l.id === id);
    return loc ? loc.name : id.slice(0, 8);
  };

  const isUserAtDestination = (toLocationId: string): boolean => {
    const locs: string[] = (user as any)?.assigned_locations ?? [];
    return locs.includes(toLocationId);
  };

  const handleAction = async (action: string) => {
    if (!transfer) return;
    if (action === 'receive') {
      // Open receive dialog instead of immediate action
      setReceiveQty(transfer.quantity);
      setShowReceiveDialog(true);
      return;
    }
    setActionLoading(true);
    setError(null);
    try {
      await apiClient.put(`/api/v2/stock-transfers/${transfer.id}/${action}`);
      await fetchTransfer();
    } catch (err: any) {
      setError(err?.response?.data?.detail ?? `Failed to ${action} transfer`);
    } finally {
      setActionLoading(false);
    }
  };

  const handleReceiveSubmit = async () => {
    if (!transfer) return;
    const qty = parseFloat(receiveQty);
    if (isNaN(qty) || qty <= 0) {
      setError('Received quantity must be greater than zero');
      return;
    }
    const transferQty = parseFloat(transfer.quantity);
    if (qty > transferQty) {
      setError('Received quantity cannot exceed the transfer quantity');
      return;
    }
    setActionLoading(true);
    setError(null);
    try {
      await apiClient.put(`/api/v2/stock-transfers/${transfer.id}/receive`, {
        received_quantity: qty,
      });
      setShowReceiveDialog(false);
      setReceiveQty('');
      await fetchTransfer();
    } catch (err: any) {
      setError(err?.response?.data?.detail ?? 'Failed to receive transfer');
    } finally {
      setActionLoading(false);
    }
  };

  const formatDate = (dateStr: string | null | undefined) => {
    if (!dateStr) return '—';
    try {
      return new Date(dateStr).toLocaleString();
    } catch {
      return dateStr;
    }
  };

  const statusBadge = (status: string) => {
    const displayStatus = status.replace('_', ' ');
    return (
      <span
        data-testid={`status-${status}`}
        style={{
          color: STATUS_COLORS[status] || '#6b7280',
          fontWeight: 600,
          fontSize: '1.1em',
        }}
      >
        {displayStatus.charAt(0).toUpperCase() + displayStatus.slice(1)}
      </span>
    );
  };

  if (loading) {
    return <p role="status" aria-label="Loading transfer">Loading transfer details…</p>;
  }

  if (!transfer) {
    return (
      <section aria-label="Transfer Detail">
        <div role="alert">Transfer not found</div>
        <button
          onClick={() => navigate('/stock-transfers')}
          aria-label="Back to transfers"
          style={{ minWidth: 44, minHeight: 44, marginTop: 16 }}
        >
          ← Back to Transfers
        </button>
      </section>
    );
  }

  return (
    <section aria-label="Transfer Detail">
      <div style={{ display: 'flex', alignItems: 'center', gap: 12, marginBottom: 16 }}>
        <button
          onClick={() => navigate('/stock-transfers')}
          aria-label="Back to transfers"
          style={{ minWidth: 44, minHeight: 44, background: 'none', border: '1px solid #d1d5db', borderRadius: 6, cursor: 'pointer' }}
        >
          ←
        </button>
        <h2 style={{ margin: 0 }}>Transfer Detail</h2>
      </div>

      {error && (
        <div role="alert" className="error-banner" style={{ marginBottom: 16 }}>
          {error}
          <button onClick={() => setError(null)} aria-label="Dismiss error">×</button>
        </div>
      )}

      <div data-testid="transfer-detail">
        <dl style={{ display: 'grid', gridTemplateColumns: 'auto 1fr', gap: '8px 16px' }}>
          <dt style={{ fontWeight: 600 }}>Status</dt>
          <dd data-testid="detail-status">{statusBadge(transfer.status)}</dd>

          <dt style={{ fontWeight: 600 }}>Source Location</dt>
          <dd data-testid="detail-from">
            {transfer.from_location_name || getLocationName(transfer.from_location_id)}
          </dd>

          <dt style={{ fontWeight: 600 }}>Destination Location</dt>
          <dd data-testid="detail-to">
            {transfer.to_location_name || getLocationName(transfer.to_location_id)}
          </dd>

          <dt style={{ fontWeight: 600 }}>Product</dt>
          <dd data-testid="detail-product">
            {transfer.product_name || transfer.product_id.slice(0, 8)}
          </dd>

          <dt style={{ fontWeight: 600 }}>Quantity</dt>
          <dd data-testid="detail-quantity">{transfer.quantity}</dd>

          {transfer.received_quantity != null && (
            <>
              <dt style={{ fontWeight: 600 }}>Received Quantity</dt>
              <dd data-testid="detail-received-quantity">{transfer.received_quantity}</dd>
            </>
          )}

          {transfer.discrepancy_quantity != null && parseFloat(String(transfer.discrepancy_quantity)) > 0 && (
            <>
              <dt style={{ fontWeight: 600, color: '#f97316' }}>Discrepancy</dt>
              <dd data-testid="detail-discrepancy" style={{ color: '#f97316' }}>
                {transfer.discrepancy_quantity}
              </dd>
            </>
          )}

          <dt style={{ fontWeight: 600 }}>Notes</dt>
          <dd data-testid="detail-notes">{transfer.notes || '—'}</dd>

          <dt style={{ fontWeight: 600 }}>Requested By</dt>
          <dd data-testid="detail-requested-by">
            {transfer.requested_by ? transfer.requested_by.slice(0, 8) : '—'}
          </dd>

          <dt style={{ fontWeight: 600 }}>Approved By</dt>
          <dd data-testid="detail-approved-by">
            {transfer.approved_by ? transfer.approved_by.slice(0, 8) : '—'}
          </dd>

          <dt style={{ fontWeight: 600 }}>Created</dt>
          <dd data-testid="detail-created">{formatDate(transfer.created_at)}</dd>

          <dt style={{ fontWeight: 600 }}>Completed</dt>
          <dd data-testid="detail-completed">{formatDate(transfer.completed_at)}</dd>
        </dl>
      </div>

      {/* Status-appropriate action buttons */}
      <div style={{ marginTop: 24, display: 'flex', gap: 8 }} data-testid="transfer-actions">
        {transfer.status === 'pending' && (
          <>
            <button
              onClick={() => handleAction('approve')}
              disabled={actionLoading}
              aria-label="Approve transfer"
              style={{ minWidth: 44, minHeight: 44 }}
            >
              Approve
            </button>
            <button
              onClick={() => handleAction('reject')}
              disabled={actionLoading}
              aria-label="Reject transfer"
              style={{ minWidth: 44, minHeight: 44 }}
            >
              Reject
            </button>
          </>
        )}
        {transfer.status === 'approved' && (
          <button
            onClick={() => handleAction('execute')}
            disabled={actionLoading}
            aria-label="Execute transfer"
            style={{ minWidth: 44, minHeight: 44 }}
          >
            Execute
          </button>
        )}
        {transfer.status === 'executed' && isUserAtDestination(transfer.to_location_id) && (
          <button
            onClick={() => handleAction('receive')}
            disabled={actionLoading}
            aria-label="Receive transfer"
            style={{ minWidth: 44, minHeight: 44 }}
          >
            Receive
          </button>
        )}
      </div>

      {/* Audit Trail Timeline */}
      <div style={{ marginTop: 32 }} data-testid="audit-trail">
        <h3 style={{ margin: '0 0 16px 0', fontSize: '1.1em' }}>Audit Trail</h3>
        {(auditTrail ?? []).length === 0 ? (
          <p style={{ color: '#6b7280' }}>No audit trail entries yet.</p>
        ) : (
          <ol
            style={{ listStyle: 'none', padding: 0, margin: 0, position: 'relative' }}
            aria-label="Transfer audit trail"
          >
            {(auditTrail ?? []).map((entry, idx) => {
              const isLast = idx === auditTrail.length - 1;
              const color = ACTION_COLORS[entry.action] ?? '#6b7280';
              return (
                <li
                  key={entry.id}
                  data-testid={`audit-entry-${entry.action}`}
                  style={{
                    display: 'flex',
                    gap: 12,
                    paddingBottom: isLast ? 0 : 16,
                    position: 'relative',
                  }}
                >
                  {/* Timeline dot and connector line */}
                  <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'center', minWidth: 20 }}>
                    <div
                      style={{
                        width: 12,
                        height: 12,
                        borderRadius: '50%',
                        backgroundColor: color,
                        flexShrink: 0,
                        marginTop: 4,
                      }}
                      aria-hidden="true"
                    />
                    {!isLast && (
                      <div
                        style={{
                          width: 2,
                          flex: 1,
                          backgroundColor: '#d1d5db',
                          marginTop: 4,
                        }}
                        aria-hidden="true"
                      />
                    )}
                  </div>
                  {/* Content */}
                  <div style={{ flex: 1, paddingBottom: 4 }}>
                    <div style={{ fontWeight: 600, color }}>
                      {ACTION_LABELS[entry.action] ?? entry.action}
                    </div>
                    <div style={{ fontSize: '0.85em', color: '#6b7280' }}>
                      {formatDate(entry.created_at)}
                      {entry.performed_by && (
                        <span> · by {entry.performed_by.slice(0, 8)}</span>
                      )}
                    </div>
                    {entry.notes && (
                      <div style={{ fontSize: '0.9em', marginTop: 4, color: '#374151' }}>
                        {entry.notes}
                      </div>
                    )}
                  </div>
                </li>
              );
            })}
          </ol>
        )}
      </div>

      {/* Receive dialog for partial transfer support */}
      {showReceiveDialog && transfer && (
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
              Transfer quantity: <strong>{transfer.quantity}</strong>
            </p>
            <div style={{ marginBottom: 16 }}>
              <label htmlFor="detail-receive-qty" style={{ display: 'block', marginBottom: 4, fontWeight: 500 }}>
                Received Quantity
              </label>
              <input
                id="detail-receive-qty"
                type="number"
                step="0.001"
                min="0.001"
                max={transfer.quantity}
                value={receiveQty}
                onChange={(e) => setReceiveQty(e.target.value)}
                aria-label="Received quantity"
                style={{ width: '100%', padding: '8px 12px', border: '1px solid #d1d5db', borderRadius: 6 }}
                autoFocus
              />
              {receiveQty && parseFloat(receiveQty) < parseFloat(transfer.quantity) && (
                <p style={{ margin: '8px 0 0 0', fontSize: 13, color: '#f97316' }}>
                  Discrepancy: {(parseFloat(transfer.quantity) - parseFloat(receiveQty)).toFixed(3)} — transfer will be marked as partially received.
                </p>
              )}
            </div>
            <div style={{ display: 'flex', gap: 8, justifyContent: 'flex-end' }}>
              <button
                type="button"
                onClick={() => { setShowReceiveDialog(false); setReceiveQty(''); }}
                disabled={actionLoading}
                aria-label="Cancel receive"
                style={{ minWidth: 44, minHeight: 44 }}
              >
                Cancel
              </button>
              <button
                type="button"
                onClick={handleReceiveSubmit}
                disabled={actionLoading}
                aria-label="Confirm receive"
                style={{ minWidth: 44, minHeight: 44, fontWeight: 600 }}
              >
                {actionLoading ? 'Receiving…' : 'Confirm Receive'}
              </button>
            </div>
          </div>
        </div>
      )}
    </section>
  );
}
