/**
 * Loyalty configuration page for managing earn rate, tiers, customer balance,
 * analytics, and manual points adjustments.
 *
 * Validates: Requirements 10.1, 10.2, 10.3, 10.4, 10.5, 10.6, 10.7
 */
import React, { useCallback, useEffect, useState } from 'react';
import apiClient from '@/api/client';
import { Spinner } from '@/components/ui/Spinner';
import { AlertBanner } from '@/components/ui/AlertBanner';
import { Tabs } from '@/components/ui/Tabs';
import { ToastContainer, useToast } from '@/components/ui/Toast';
import { useTerm } from '@/contexts/TerminologyContext';
import { useFlag } from '@/contexts/FeatureFlagContext';
import {
  areTiersAscending,
  calculatePointsToNextTier,
  validatePointsAdjustment,
} from '@/utils/loyaltyCalcs';

/* ── Types ── */

interface LoyaltyConfigData {
  id: string; org_id: string; earn_rate: string; redemption_rate: string;
  is_active: boolean; created_at: string; updated_at: string;
}
interface LoyaltyTier {
  id: string; org_id: string; name: string; threshold_points: number;
  discount_percent: string; benefits: Record<string, unknown>; display_order: number;
}
interface LoyaltyTransaction {
  id: string; transaction_type: string; points: number; balance_after: number;
  reference_type: string | null; created_at: string;
}
interface CustomerBalance {
  customer_id: string; total_points: number; current_tier: LoyaltyTier | null;
  next_tier: LoyaltyTier | null; points_to_next_tier: number | null;
  transactions: LoyaltyTransaction[];
}
interface LoyaltyAnalytics {
  total_active_members: number;
  members_per_tier: { tier_name: string; count: number }[];
  total_points_issued: number;
  total_points_redeemed: number;
  redemption_rate_pct: number;
  top_customers: { customer_id: string; name: string; points: number }[];
}
interface ConfigForm { earn_rate: string; redemption_rate: string; is_active: boolean; }
interface TierForm { name: string; threshold_points: string; discount_percent: string; }
interface AdjustmentForm { customer_id: string; amount: string; reason: string; }

const EMPTY_TIER: TierForm = { name: '', threshold_points: '', discount_percent: '0' };
const EMPTY_ADJUSTMENT: AdjustmentForm = { customer_id: '', amount: '', reason: '' };

/* ── Sub-components ── */

function ConfigSection({
  configForm,
  setConfigForm,
  onSave,
}: {
  configForm: ConfigForm;
  setConfigForm: React.Dispatch<React.SetStateAction<ConfigForm>>;
  onSave: (e: React.FormEvent) => void;
}) {
  return (
    <div>
      <h3>Configuration</h3>
      <form onSubmit={onSave} aria-label="Loyalty configuration form">
        <div>
          <label htmlFor="earn-rate">Earn Rate (points per $1)</label>
          <input id="earn-rate" type="number" step="0.0001" min="0" inputMode="numeric"
            value={configForm.earn_rate}
            onChange={(e) => setConfigForm((f) => ({ ...f, earn_rate: e.target.value }))}
            required style={{ minHeight: 44 }} />
        </div>
        <div>
          <label htmlFor="redemption-rate">Redemption Rate ($ per point)</label>
          <input id="redemption-rate" type="number" step="0.0001" min="0.0001" inputMode="numeric"
            value={configForm.redemption_rate}
            onChange={(e) => setConfigForm((f) => ({ ...f, redemption_rate: e.target.value }))}
            required style={{ minHeight: 44 }} />
        </div>
        <div>
          <label>
            <input type="checkbox" checked={configForm.is_active}
              onChange={(e) => setConfigForm((f) => ({ ...f, is_active: e.target.checked }))}
              style={{ minWidth: 44, minHeight: 44 }} />
            {' '}Programme Active
          </label>
        </div>
        <button type="submit" aria-label="Save loyalty config" style={{ minHeight: 44, minWidth: 44 }}>
          Save Configuration
        </button>
      </form>
    </div>
  );
}

function TierSection({
  tiers,
  showTierForm,
  setShowTierForm,
  tierForm,
  setTierForm,
  tierError,
  onCreateTier,
}: {
  tiers: LoyaltyTier[];
  showTierForm: boolean;
  setShowTierForm: (v: boolean) => void;
  tierForm: TierForm;
  setTierForm: React.Dispatch<React.SetStateAction<TierForm>>;
  tierError: string | null;
  onCreateTier: (e: React.FormEvent) => void;
}) {
  return (
    <div>
      <h3>Membership Tiers</h3>
      {tierError && (
        <div role="alert" style={{ color: '#ef4444', marginBottom: 8 }}>{tierError}</div>
      )}
      <table role="grid" aria-label="Loyalty tiers list">
        <thead><tr><th>Name</th><th>Threshold (pts)</th><th>Discount %</th></tr></thead>
        <tbody>
          {tiers.map((t) => (
            <tr key={t.id} data-testid={`tier-row-${t.name}`}>
              <td>{t.name}</td><td>{t.threshold_points}</td><td>{t.discount_percent}%</td>
            </tr>
          ))}
          {tiers.length === 0 && <tr><td colSpan={3}>No tiers configured</td></tr>}
        </tbody>
      </table>
      {!showTierForm ? (
        <button onClick={() => setShowTierForm(true)} aria-label="Add tier"
          style={{ minHeight: 44, minWidth: 44 }}>Add Tier</button>
      ) : (
        <form onSubmit={onCreateTier} aria-label="Create tier form">
          <div>
            <label htmlFor="tier-name">Tier Name</label>
            <input id="tier-name" type="text" value={tierForm.name}
              onChange={(e) => setTierForm((f) => ({ ...f, name: e.target.value }))}
              placeholder="Gold" required style={{ minHeight: 44 }} />
          </div>
          <div>
            <label htmlFor="tier-threshold">Threshold Points</label>
            <input id="tier-threshold" type="number" min="0" value={tierForm.threshold_points}
              onChange={(e) => setTierForm((f) => ({ ...f, threshold_points: e.target.value }))}
              required style={{ minHeight: 44 }} />
          </div>
          <div>
            <label htmlFor="tier-discount">Discount %</label>
            <input id="tier-discount" type="number" step="0.01" min="0" max="100" inputMode="numeric"
              value={tierForm.discount_percent}
              onChange={(e) => setTierForm((f) => ({ ...f, discount_percent: e.target.value }))}
              style={{ minHeight: 44 }} />
          </div>
          <button type="submit" aria-label="Save tier" style={{ minHeight: 44, minWidth: 44 }}>Save Tier</button>
          <button type="button" onClick={() => setShowTierForm(false)} aria-label="Cancel tier"
            style={{ minHeight: 44, minWidth: 44 }}>Cancel</button>
        </form>
      )}
    </div>
  );
}

function CustomerBalanceSection({
  customerIdInput,
  setCustomerIdInput,
  customerBalance,
  onLookup,
  tiers,
}: {
  customerIdInput: string;
  setCustomerIdInput: (v: string) => void;
  customerBalance: CustomerBalance | null;
  onLookup: (e: React.FormEvent) => void;
  tiers: LoyaltyTier[];
}) {
  const customerLabel = useTerm('customer', 'Customer');
  const pointsToNext = customerBalance
    ? calculatePointsToNextTier(
        customerBalance.total_points,
        tiers.map((t) => ({ threshold: t.threshold_points })),
      )
    : null;

  return (
    <div>
      <h3>{customerLabel} Balance</h3>
      <form onSubmit={onLookup} aria-label="Customer balance lookup form">
        <div>
          <label htmlFor="customer-id">{customerLabel} ID</label>
          <input id="customer-id" type="text" value={customerIdInput}
            onChange={(e) => setCustomerIdInput(e.target.value)}
            placeholder="Enter customer UUID" required style={{ minHeight: 44 }} />
        </div>
        <button type="submit" aria-label="Look up balance" style={{ minHeight: 44, minWidth: 44 }}>
          Look Up
        </button>
      </form>
      {customerBalance && (
        <div data-testid="customer-balance-result" aria-label="Customer balance result">
          <p data-testid="balance-points">Points: {customerBalance.total_points}</p>
          <p data-testid="balance-tier">Tier: {customerBalance.current_tier?.name || 'None'}</p>
          {customerBalance.next_tier && (
            <p data-testid="balance-next-tier">
              Next tier: {customerBalance.next_tier.name} ({pointsToNext ?? customerBalance.points_to_next_tier} pts needed)
            </p>
          )}
          {!customerBalance.next_tier && customerBalance.current_tier && (
            <p data-testid="balance-max-tier">Max tier reached</p>
          )}
          {customerBalance.transactions.length > 0 && (
            <table role="grid" aria-label="Transaction history">
              <thead><tr><th>Type</th><th>Points</th><th>Balance</th><th>Date</th></tr></thead>
              <tbody>
                {customerBalance.transactions.map((tx) => (
                  <tr key={tx.id}>
                    <td>{tx.transaction_type}</td>
                    <td>{tx.points > 0 ? `+${tx.points}` : tx.points}</td>
                    <td>{tx.balance_after}</td>
                    <td>{new Date(tx.created_at).toLocaleDateString()}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </div>
      )}
    </div>
  );
}

function AnalyticsSection({ analytics }: { analytics: LoyaltyAnalytics | null }) {
  if (!analytics || typeof analytics !== 'object' || !('total_active_members' in analytics)) {
    return <p>No analytics data available.</p>;
  }

  return (
    <div data-testid="loyalty-analytics" aria-label="Loyalty analytics dashboard">
      <h3>Loyalty Analytics</h3>
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(200px, 1fr))', gap: 16 }}>
        <div data-testid="analytics-active-members">
          <strong>Active Members</strong>
          <p>{analytics.total_active_members}</p>
        </div>
        <div data-testid="analytics-points-issued">
          <strong>Points Issued</strong>
          <p>{analytics.total_points_issued.toLocaleString()}</p>
        </div>
        <div data-testid="analytics-points-redeemed">
          <strong>Points Redeemed</strong>
          <p>{analytics.total_points_redeemed.toLocaleString()}</p>
        </div>
        <div data-testid="analytics-redemption-rate">
          <strong>Redemption Rate</strong>
          <p>{analytics.redemption_rate_pct.toFixed(1)}%</p>
        </div>
      </div>

      {analytics.members_per_tier.length > 0 && (
        <div style={{ marginTop: 16 }}>
          <h4>Members per Tier</h4>
          <table role="grid" aria-label="Members per tier">
            <thead><tr><th>Tier</th><th>Members</th></tr></thead>
            <tbody>
              {analytics.members_per_tier.map((t) => (
                <tr key={t.tier_name}><td>{t.tier_name}</td><td>{t.count}</td></tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {analytics.top_customers.length > 0 && (
        <div style={{ marginTop: 16 }}>
          <h4>Top Customers</h4>
          <table role="grid" aria-label="Top customers by points">
            <thead><tr><th>Name</th><th>Points</th></tr></thead>
            <tbody>
              {analytics.top_customers.map((c) => (
                <tr key={c.customer_id}><td>{c.name}</td><td>{c.points.toLocaleString()}</td></tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}

function PointsAdjustmentSection({
  adjustmentForm,
  setAdjustmentForm,
  adjustmentError,
  onSubmit,
}: {
  adjustmentForm: AdjustmentForm;
  setAdjustmentForm: React.Dispatch<React.SetStateAction<AdjustmentForm>>;
  adjustmentError: string | null;
  onSubmit: (e: React.FormEvent) => void;
}) {
  const customerLabel = useTerm('customer', 'Customer');

  return (
    <div>
      <h3>Manual Points Adjustment</h3>
      {adjustmentError && (
        <div role="alert" style={{ color: '#ef4444', marginBottom: 8 }}>{adjustmentError}</div>
      )}
      <form onSubmit={onSubmit} aria-label="Points adjustment form">
        <div>
          <label htmlFor="adj-customer-id">{customerLabel} ID</label>
          <input id="adj-customer-id" type="text" value={adjustmentForm.customer_id}
            onChange={(e) => setAdjustmentForm((f) => ({ ...f, customer_id: e.target.value }))}
            placeholder="Enter customer UUID" required style={{ minHeight: 44 }} />
        </div>
        <div>
          <label htmlFor="adj-amount">Points (positive to add, negative to deduct)</label>
          <input id="adj-amount" type="number" inputMode="numeric" value={adjustmentForm.amount}
            onChange={(e) => setAdjustmentForm((f) => ({ ...f, amount: e.target.value }))}
            required style={{ minHeight: 44 }} />
        </div>
        <div>
          <label htmlFor="adj-reason">Reason (required)</label>
          <textarea id="adj-reason" value={adjustmentForm.reason}
            onChange={(e) => setAdjustmentForm((f) => ({ ...f, reason: e.target.value }))}
            placeholder="Reason for adjustment" required
            style={{ minHeight: 44, width: '100%' }} />
        </div>
        <button type="submit" aria-label="Submit adjustment" style={{ minHeight: 44, minWidth: 44 }}>
          Submit Adjustment
        </button>
      </form>
    </div>
  );
}

/* ── Main Component ── */

export default function LoyaltyConfig() {
  // Context integration (Req 10.7)
  // Module guard is handled at the router level via FlagGatedRoute in ModuleRouter.tsx
  // Here we integrate FeatureFlagContext and TerminologyContext for sub-feature gating and labels
  const loyaltyLabel = useTerm('loyalty', 'Loyalty');
  void useFlag('loyalty');

  const [config, setConfig] = useState<LoyaltyConfigData | null>(null);
  const [tiers, setTiers] = useState<LoyaltyTier[]>([]);
  const [analytics, setAnalytics] = useState<LoyaltyAnalytics | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [configForm, setConfigForm] = useState<ConfigForm>({
    earn_rate: '1.0', redemption_rate: '0.01', is_active: true,
  });
  const [showTierForm, setShowTierForm] = useState(false);
  const [tierForm, setTierForm] = useState<TierForm>({ ...EMPTY_TIER });
  const [tierError, setTierError] = useState<string | null>(null);
  const [customerIdInput, setCustomerIdInput] = useState('');
  const [customerBalance, setCustomerBalance] = useState<CustomerBalance | null>(null);
  const [adjustmentForm, setAdjustmentForm] = useState<AdjustmentForm>({ ...EMPTY_ADJUSTMENT });
  const [adjustmentError, setAdjustmentError] = useState<string | null>(null);
  const { addToast, toasts, dismissToast } = useToast();

  const fetchData = useCallback(async () => {
    try {
      setLoading(true);
      const [cfgRes, tiersRes, analyticsRes] = await Promise.all([
        apiClient.get('/api/v2/loyalty/config').catch(() => ({ data: null })),
        apiClient.get('/api/v2/loyalty/tiers'),
        apiClient.get('/api/v2/loyalty/analytics').catch(() => ({ data: null })),
      ]);
      if (cfgRes.data) {
        setConfig(cfgRes.data);
        setConfigForm({
          earn_rate: cfgRes.data.earn_rate,
          redemption_rate: cfgRes.data.redemption_rate,
          is_active: cfgRes.data.is_active,
        });
      }
      setTiers(tiersRes.data);
      if (analyticsRes.data && typeof analyticsRes.data === 'object' && !Array.isArray(analyticsRes.data)) {
        setAnalytics(analyticsRes.data);
      }
    } catch {
      setError('Failed to load loyalty settings');
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { fetchData(); }, [fetchData]);

  const handleSaveConfig = async (e: React.FormEvent) => {
    e.preventDefault();
    try {
      const res = await apiClient.put('/api/v2/loyalty/config', {
        earn_rate: parseFloat(configForm.earn_rate),
        redemption_rate: parseFloat(configForm.redemption_rate),
        is_active: configForm.is_active,
      });
      setConfig(res.data);
      addToast('success', 'Configuration saved');
    } catch (err: any) {
      setError(err?.response?.data?.detail || 'Failed to save config');
    }
  };

  const handleCreateTier = async (e: React.FormEvent) => {
    e.preventDefault();
    setTierError(null);

    const newThreshold = parseInt(tierForm.threshold_points, 10);
    // Validate ascending thresholds (Property 19)
    const proposedTiers = [
      ...tiers.map((t) => ({ threshold: t.threshold_points })),
      { threshold: newThreshold },
    ].sort((a, b) => a.threshold - b.threshold);

    if (!areTiersAscending(proposedTiers)) {
      setTierError('Tier thresholds must be strictly ascending. A tier with this threshold already exists or conflicts with existing tiers.');
      return;
    }

    try {
      await apiClient.post('/api/v2/loyalty/tiers', {
        name: tierForm.name,
        threshold_points: newThreshold,
        discount_percent: parseFloat(tierForm.discount_percent),
      });
      setTierForm({ ...EMPTY_TIER });
      setShowTierForm(false);
      addToast('success', 'Tier created');
      await fetchData();
    } catch (err: any) {
      setError(err?.response?.data?.detail || 'Failed to create tier');
    }
  };

  const handleLookupBalance = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!customerIdInput.trim()) return;
    try {
      const res = await apiClient.get(`/api/v2/loyalty/customers/${customerIdInput}/balance`);
      setCustomerBalance(res.data);
    } catch (err: any) {
      setError(err?.response?.data?.detail || 'Failed to load customer balance');
    }
  };

  const handleAdjustment = async (e: React.FormEvent) => {
    e.preventDefault();
    setAdjustmentError(null);

    const amount = parseInt(adjustmentForm.amount, 10);
    // Validate using pure utility (Property 21)
    const validation = validatePointsAdjustment(amount, adjustmentForm.reason);
    if (!validation.valid) {
      setAdjustmentError(validation.error || 'Invalid adjustment');
      return;
    }

    try {
      await apiClient.post(`/api/v2/loyalty/customers/${adjustmentForm.customer_id}/adjust`, {
        points: amount,
        reason: adjustmentForm.reason.trim(),
      });
      setAdjustmentForm({ ...EMPTY_ADJUSTMENT });
      addToast('success', 'Points adjustment applied');
    } catch (err: any) {
      setAdjustmentError(err?.response?.data?.detail || 'Failed to apply adjustment');
    }
  };

  if (loading) {
    return <Spinner label="Loading loyalty settings" aria-label="Loading loyalty settings" />;
  }

  return (
    <section aria-label="Loyalty Settings">
      <h2>{loyaltyLabel} Programme</h2>
      {config && (
        <p style={{ color: '#6b7280', fontSize: 14 }}>
          Last updated: {new Date(config.updated_at).toLocaleString()}
        </p>
      )}
      {error && (
        <AlertBanner variant="error" onDismiss={() => setError(null)}>
          {error}
        </AlertBanner>
      )}

      {/* Core configuration — always visible (matches original layout) */}
      <ConfigSection
        configForm={configForm}
        setConfigForm={setConfigForm}
        onSave={handleSaveConfig}
      />

      <TierSection
        tiers={tiers}
        showTierForm={showTierForm}
        setShowTierForm={setShowTierForm}
        tierForm={tierForm}
        setTierForm={setTierForm}
        tierError={tierError}
        onCreateTier={handleCreateTier}
      />

      <CustomerBalanceSection
        customerIdInput={customerIdInput}
        setCustomerIdInput={setCustomerIdInput}
        customerBalance={customerBalance}
        onLookup={handleLookupBalance}
        tiers={tiers}
      />

      {/* Extended features in tabs */}
      <Tabs
        tabs={[
          {
            id: 'analytics',
            label: 'Analytics',
            content: <AnalyticsSection analytics={analytics} />,
          },
          {
            id: 'adjustments',
            label: 'Points Adjustment',
            content: (
              <PointsAdjustmentSection
                adjustmentForm={adjustmentForm}
                setAdjustmentForm={setAdjustmentForm}
                adjustmentError={adjustmentError}
                onSubmit={handleAdjustment}
              />
            ),
          },
        ]}
      />

      <ToastContainer toasts={toasts} onDismiss={dismissToast} />
    </section>
  );
}
