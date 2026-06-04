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
import { Button } from '@/components/ui';

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

const STATUS_TONES: Record<string, string> = {
  pending: 'text-warn',
  in_transit: 'text-accent',
  received: 'text-ok',
  partially_received: 'text-warn',
  cancelled: 'text-danger',
  approved: 'text-accent',
  executed: 'text-ok',
  rejected: 'text-danger',
};

const ACTION_LABELS: Record<string, string> = {
  created: 'Transfer Created',
  approved: 'Transfer Approved',
  rejected: 'Transfer Rejected',
  executed: 'Transfer Executed',
  received: 'Transfer Received',
  partially_received: 'Partially Received',
};

const ACTION_DOT_COLORS: Record<string, string> = {
  created: '#687283',
  approved: 'var(--accent)',
  rejected: 'var(--danger)',
  executed: 'var(--ok)',
  received: 'var(--purple)',
  partially_received: 'var(--warn)',
};

const ACTION_TEXT_TONES: Record<string, string> = {
  created: 'text-muted',
  approved: 'text-accent',
  rejected: 'text-danger',
  executed: 'text-ok',
  received: 'text-purple',
  partially_received: 'text-warn',
};

const inputClass =
  'min-h-[44px] w-full rounded-ctl border border-border bg-card px-3 py-2 text-sm text-text outline-none focus:border-accent focus:ring-1 focus:ring-accent';
const labelClass = 'mb-1 block text-sm font-medium text-text';

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
        className={`text-[1.1em] font-semibold ${STATUS_TONES[status] || 'text-muted'}`}
      >
        {displayStatus.charAt(0).toUpperCase() + displayStatus.slice(1)}
      </span>
    );
  };

  if (loading) {
    return <p role="status" aria-label="Loading transfer" className="py-12 text-center text-sm text-muted">Loading transfer details…</p>;
  }

  if (!transfer) {
    return (
      <section aria-label="Transfer Detail" className="space-y-4 px-4 py-6 sm:px-6 lg:px-8">
        <div role="alert" className="text-sm text-muted">Transfer not found</div>
        <Button
          variant="ghost"
          onClick={() => navigate('/stock-transfers')}
          aria-label="Back to transfers"
        >
          ← Back to Transfers
        </Button>
      </section>
    );
  }

  return (
    <section aria-label="Transfer Detail" className="space-y-4 px-4 py-6 sm:px-6 lg:px-8">
      <div className="flex items-center gap-3">
        <Button
          variant="ghost"
          iconOnly
          onClick={() => navigate('/stock-transfers')}
          aria-label="Back to transfers"
        >
          ←
        </Button>
        <h2 className="text-2xl font-semibold text-text">Transfer Detail</h2>
      </div>

      {error && (
        <div role="alert" className="flex items-center justify-between rounded-ctl bg-danger-soft px-4 py-3 text-sm text-danger">
          {error}
          <button onClick={() => setError(null)} aria-label="Dismiss error" className="ml-2 text-danger">×</button>
        </div>
      )}

      <div data-testid="transfer-detail" className="overflow-hidden rounded-card border border-border bg-card shadow-card">
        <dl className="grid grid-cols-[auto_1fr] gap-x-4 gap-y-2 p-4">
          <dt className="font-semibold text-text">Status</dt>
          <dd data-testid="detail-status">{statusBadge(transfer.status)}</dd>

          <dt className="font-semibold text-text">Source Location</dt>
          <dd data-testid="detail-from" className="text-text">
            {transfer.from_location_name || getLocationName(transfer.from_location_id)}
          </dd>

          <dt className="font-semibold text-text">Destination Location</dt>
          <dd data-testid="detail-to" className="text-text">
            {transfer.to_location_name || getLocationName(transfer.to_location_id)}
          </dd>

          <dt className="font-semibold text-text">Product</dt>
          <dd data-testid="detail-product" className="text-text">
            {transfer.product_name || transfer.product_id.slice(0, 8)}
          </dd>

          <dt className="font-semibold text-text">Quantity</dt>
          <dd data-testid="detail-quantity" className="mono text-text">{transfer.quantity}</dd>

          {transfer.received_quantity != null && (
            <>
              <dt className="font-semibold text-text">Received Quantity</dt>
              <dd data-testid="detail-received-quantity" className="mono text-text">{transfer.received_quantity}</dd>
            </>
          )}

          {transfer.discrepancy_quantity != null && parseFloat(String(transfer.discrepancy_quantity)) > 0 && (
            <>
              <dt className="font-semibold text-warn">Discrepancy</dt>
              <dd data-testid="detail-discrepancy" className="mono text-warn">
                {transfer.discrepancy_quantity}
              </dd>
            </>
          )}

          <dt className="font-semibold text-text">Notes</dt>
          <dd data-testid="detail-notes" className="text-text">{transfer.notes || '—'}</dd>

          <dt className="font-semibold text-text">Requested By</dt>
          <dd data-testid="detail-requested-by" className="mono text-text">
            {transfer.requested_by ? transfer.requested_by.slice(0, 8) : '—'}
          </dd>

          <dt className="font-semibold text-text">Approved By</dt>
          <dd data-testid="detail-approved-by" className="mono text-text">
            {transfer.approved_by ? transfer.approved_by.slice(0, 8) : '—'}
          </dd>

          <dt className="font-semibold text-text">Created</dt>
          <dd data-testid="detail-created" className="mono text-text">{formatDate(transfer.created_at)}</dd>

          <dt className="font-semibold text-text">Completed</dt>
          <dd data-testid="detail-completed" className="mono text-text">{formatDate(transfer.completed_at)}</dd>
        </dl>
      </div>

      {/* Status-appropriate action buttons */}
      <div className="flex gap-2" data-testid="transfer-actions">
        {transfer.status === 'pending' && (
          <>
            <Button
              onClick={() => handleAction('approve')}
              disabled={actionLoading}
              aria-label="Approve transfer"
            >
              Approve
            </Button>
            <Button
              variant="ghost"
              onClick={() => handleAction('reject')}
              disabled={actionLoading}
              aria-label="Reject transfer"
            >
              Reject
            </Button>
          </>
        )}
        {transfer.status === 'approved' && (
          <Button
            onClick={() => handleAction('execute')}
            disabled={actionLoading}
            aria-label="Execute transfer"
          >
            Execute
          </Button>
        )}
        {transfer.status === 'executed' && isUserAtDestination(transfer.to_location_id) && (
          <Button
            onClick={() => handleAction('receive')}
            disabled={actionLoading}
            aria-label="Receive transfer"
          >
            Receive
          </Button>
        )}
      </div>

      {/* Audit Trail Timeline */}
      <div data-testid="audit-trail">
        <h3 className="mb-4 text-[1.1em] font-semibold text-text">Audit Trail</h3>
        {(auditTrail ?? []).length === 0 ? (
          <p className="text-sm text-muted">No audit trail entries yet.</p>
        ) : (
          <ol
            className="relative m-0 list-none p-0"
            aria-label="Transfer audit trail"
          >
            {(auditTrail ?? []).map((entry, idx) => {
              const isLast = idx === auditTrail.length - 1;
              const dotColor = ACTION_DOT_COLORS[entry.action] ?? '#687283';
              const textTone = ACTION_TEXT_TONES[entry.action] ?? 'text-muted';
              return (
                <li
                  key={entry.id}
                  data-testid={`audit-entry-${entry.action}`}
                  className="relative flex gap-3"
                  style={{ paddingBottom: isLast ? 0 : 16 }}
                >
                  {/* Timeline dot and connector line */}
                  <div className="flex min-w-[20px] flex-col items-center">
                    <div
                      className="mt-1 h-3 w-3 flex-shrink-0 rounded-full"
                      style={{ backgroundColor: dotColor }}
                      aria-hidden="true"
                    />
                    {!isLast && (
                      <div
                        className="mt-1 w-0.5 flex-1 bg-border"
                        aria-hidden="true"
                      />
                    )}
                  </div>
                  {/* Content */}
                  <div className="flex-1 pb-1">
                    <div className={`font-semibold ${textTone}`}>
                      {ACTION_LABELS[entry.action] ?? entry.action}
                    </div>
                    <div className="text-[0.85em] text-muted">
                      {formatDate(entry.created_at)}
                      {entry.performed_by && (
                        <span> · by {entry.performed_by.slice(0, 8)}</span>
                      )}
                    </div>
                    {entry.notes && (
                      <div className="mt-1 text-[0.9em] text-text">
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
          className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 px-4"
        >
          <div className="w-full max-w-[420px] min-w-[340px] rounded-card bg-card p-6 shadow-pop">
            <h3 className="mb-4 text-lg font-semibold text-text">Receive Transfer</h3>
            <p className="mb-2 text-sm text-text">
              Transfer quantity: <strong>{transfer.quantity}</strong>
            </p>
            <div className="mb-4">
              <label htmlFor="detail-receive-qty" className={labelClass}>
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
                className={inputClass}
                autoFocus
              />
              {receiveQty && parseFloat(receiveQty) < parseFloat(transfer.quantity) && (
                <p className="mt-2 text-[13px] text-warn">
                  Discrepancy: {(parseFloat(transfer.quantity) - parseFloat(receiveQty)).toFixed(3)} — transfer will be marked as partially received.
                </p>
              )}
            </div>
            <div className="flex justify-end gap-2">
              <Button
                type="button"
                variant="ghost"
                onClick={() => { setShowReceiveDialog(false); setReceiveQty(''); }}
                disabled={actionLoading}
                aria-label="Cancel receive"
              >
                Cancel
              </Button>
              <Button
                type="button"
                onClick={handleReceiveSubmit}
                disabled={actionLoading}
                aria-label="Confirm receive"
              >
                {actionLoading ? 'Receiving…' : 'Confirm Receive'}
              </Button>
            </div>
          </div>
        </div>
      )}
    </section>
  );
}
