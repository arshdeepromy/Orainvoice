/**
 * Loyalty configuration page for managing earn rate, tiers, and customer balance.
 *
 * **Validates: Requirement 38 — Loyalty Module, Task 41.10**
 */
import React, { useCallback, useEffect, useState } from 'react';
import apiClient from '@/api/client';

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
interface ConfigForm { earn_rate: string; redemption_rate: string; is_active: boolean; }
interface TierForm { name: string; threshold_points: string; discount_percent: string; }

const EMPTY_TIER: TierForm = { name: '', threshold_points: '', discount_percent: '0' };

export default function LoyaltyConfig() {
  const [config, setConfig] = useState<LoyaltyConfigData | null>(null);
  const [tiers, setTiers] = useState<LoyaltyTier[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [configForm, setConfigForm] = useState<ConfigForm>({
    earn_rate: '1.0', redemption_rate: '0.01', is_active: true,
  });
  const [showTierForm, setShowTierForm] = useState(false);
  const [tierForm, setTierForm] = useState<TierForm>({ ...EMPTY_TIER });
  const [customerIdInput, setCustomerIdInput] = useState('');
  const [customerBalance, setCustomerBalance] = useState<CustomerBalance | null>(null);

  const fetchData = useCallback(async () => {
    try {
      setLoading(true);
      const [cfgRes, tiersRes] = await Promise.all([
        apiClient.get('/api/v2/loyalty/config').catch(() => ({ data: null })),
        apiClient.get('/api/v2/loyalty/tiers'),
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
    } catch (err: any) {
      setError(err?.response?.data?.detail || 'Failed to save config');
    }
  };

  const handleCreateTier = async (e: React.FormEvent) => {
    e.preventDefault();
    try {
      await apiClient.post('/api/v2/loyalty/tiers', {
        name: tierForm.name,
        threshold_points: parseInt(tierForm.threshold_points, 10),
        discount_percent: parseFloat(tierForm.discount_percent),
      });
      setTierForm({ ...EMPTY_TIER });
      setShowTierForm(false);
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

  if (loading) {
    return <p role="status" aria-label="Loading loyalty settings">Loading loyalty settings…</p>;
  }

  return (
    <section aria-label="Loyalty Settings">
      <h2>Loyalty Programme</h2>
      {error && (
        <div role="alert" className="error-banner">
          {error}
          <button onClick={() => setError(null)} aria-label="Dismiss error">×</button>
        </div>
      )}

      <h3>Configuration</h3>
      <form onSubmit={handleSaveConfig} aria-label="Loyalty configuration form">
        <div>
          <label htmlFor="earn-rate">Earn Rate (points per $1)</label>
          <input id="earn-rate" type="number" step="0.0001" min="0"
            value={configForm.earn_rate}
            onChange={(e) => setConfigForm({ ...configForm, earn_rate: e.target.value })} required />
        </div>
        <div>
          <label htmlFor="redemption-rate">Redemption Rate ($ per point)</label>
          <input id="redemption-rate" type="number" step="0.0001" min="0.0001"
            value={configForm.redemption_rate}
            onChange={(e) => setConfigForm({ ...configForm, redemption_rate: e.target.value })} required />
        </div>
        <div>
          <label><input type="checkbox" checked={configForm.is_active}
            onChange={(e) => setConfigForm({ ...configForm, is_active: e.target.checked })} /> Programme Active</label>
        </div>
        <button type="submit" aria-label="Save loyalty config">Save Configuration</button>
      </form>

      <h3>Membership Tiers</h3>
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
        <button onClick={() => setShowTierForm(true)} aria-label="Add tier">Add Tier</button>
      ) : (
        <form onSubmit={handleCreateTier} aria-label="Create tier form">
          <div><label htmlFor="tier-name">Tier Name</label>
            <input id="tier-name" type="text" value={tierForm.name}
              onChange={(e) => setTierForm({ ...tierForm, name: e.target.value })} placeholder="Gold" required /></div>
          <div><label htmlFor="tier-threshold">Threshold Points</label>
            <input id="tier-threshold" type="number" min="0" value={tierForm.threshold_points}
              onChange={(e) => setTierForm({ ...tierForm, threshold_points: e.target.value })} required /></div>
          <div><label htmlFor="tier-discount">Discount %</label>
            <input id="tier-discount" type="number" step="0.01" min="0" max="100" value={tierForm.discount_percent}
              onChange={(e) => setTierForm({ ...tierForm, discount_percent: e.target.value })} /></div>
          <button type="submit" aria-label="Save tier">Save Tier</button>
          <button type="button" onClick={() => setShowTierForm(false)} aria-label="Cancel tier">Cancel</button>
        </form>
      )}

      <h3>Customer Balance</h3>
      <form onSubmit={handleLookupBalance} aria-label="Customer balance lookup form">
        <div><label htmlFor="customer-id">Customer ID</label>
          <input id="customer-id" type="text" value={customerIdInput}
            onChange={(e) => setCustomerIdInput(e.target.value)} placeholder="Enter customer UUID" required /></div>
        <button type="submit" aria-label="Look up balance">Look Up</button>
      </form>
      {customerBalance && (
        <div data-testid="customer-balance-result" aria-label="Customer balance result">
          <p data-testid="balance-points">Points: {customerBalance.total_points}</p>
          <p data-testid="balance-tier">Tier: {customerBalance.current_tier?.name || 'None'}</p>
          {customerBalance.next_tier && (
            <p data-testid="balance-next-tier">
              Next tier: {customerBalance.next_tier.name} ({customerBalance.points_to_next_tier} pts needed)
            </p>
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
    </section>
  );
}
