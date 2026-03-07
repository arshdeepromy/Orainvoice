/**
 * Currency settings page for managing enabled currencies and exchange rates.
 *
 * Features: list enabled currencies, enable new currency, view/set exchange rates,
 * refresh rates from provider.
 *
 * **Validates: Requirement — MultiCurrency Module, Task 40.12**
 */

import React, { useCallback, useEffect, useState } from 'react';
import apiClient from '@/api/client';

interface OrgCurrency {
  id: string;
  org_id: string;
  currency_code: string;
  is_base: boolean;
  enabled: boolean;
}

interface ExchangeRate {
  id: string;
  base_currency: string;
  target_currency: string;
  rate: string;
  source: string;
  effective_date: string;
  created_at: string;
}

interface EnableCurrencyForm {
  currency_code: string;
  is_base: boolean;
}

interface ManualRateForm {
  base_currency: string;
  target_currency: string;
  rate: string;
  effective_date: string;
}

const EMPTY_ENABLE_FORM: EnableCurrencyForm = { currency_code: '', is_base: false };
const EMPTY_RATE_FORM: ManualRateForm = {
  base_currency: '',
  target_currency: '',
  rate: '',
  effective_date: new Date().toISOString().split('T')[0],
};

export default function CurrencySettings() {
  const [currencies, setCurrencies] = useState<OrgCurrency[]>([]);
  const [rates, setRates] = useState<ExchangeRate[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [showEnableForm, setShowEnableForm] = useState(false);
  const [showRateForm, setShowRateForm] = useState(false);
  const [enableForm, setEnableForm] = useState<EnableCurrencyForm>({ ...EMPTY_ENABLE_FORM });
  const [rateForm, setRateForm] = useState<ManualRateForm>({ ...EMPTY_RATE_FORM });
  const [refreshing, setRefreshing] = useState(false);

  const fetchData = useCallback(async () => {
    try {
      setLoading(true);
      const [currRes, rateRes] = await Promise.all([
        apiClient.get('/api/v2/currencies'),
        apiClient.get('/api/v2/currencies/rates'),
      ]);
      setCurrencies(currRes.data);
      setRates(rateRes.data);
    } catch {
      setError('Failed to load currency settings');
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { fetchData(); }, [fetchData]);

  const handleEnable = async (e: React.FormEvent) => {
    e.preventDefault();
    try {
      await apiClient.post('/api/v2/currencies/enable', {
        currency_code: enableForm.currency_code.toUpperCase(),
        is_base: enableForm.is_base,
      });
      setEnableForm({ ...EMPTY_ENABLE_FORM });
      setShowEnableForm(false);
      await fetchData();
    } catch (err: any) {
      setError(err?.response?.data?.detail || 'Failed to enable currency');
    }
  };

  const handleSetRate = async (e: React.FormEvent) => {
    e.preventDefault();
    try {
      await apiClient.post('/api/v2/currencies/rates', {
        base_currency: rateForm.base_currency.toUpperCase(),
        target_currency: rateForm.target_currency.toUpperCase(),
        rate: parseFloat(rateForm.rate),
        effective_date: rateForm.effective_date,
      });
      setRateForm({ ...EMPTY_RATE_FORM });
      setShowRateForm(false);
      await fetchData();
    } catch (err: any) {
      setError(err?.response?.data?.detail || 'Failed to set exchange rate');
    }
  };

  const handleRefresh = async () => {
    setRefreshing(true);
    try {
      const baseCurrency = currencies.find((c) => c.is_base)?.currency_code || 'NZD';
      await apiClient.post(`/api/v2/currencies/rates/refresh?base_currency=${baseCurrency}`);
      await fetchData();
    } catch (err: any) {
      setError(err?.response?.data?.detail || 'Failed to refresh rates');
    } finally {
      setRefreshing(false);
    }
  };

  if (loading) {
    return <p role="status" aria-label="Loading currency settings">Loading currency settings…</p>;
  }

  return (
    <section aria-label="Currency Settings">
      <h2>Currency Settings</h2>
      {error && (
        <div role="alert" className="error-banner">
          {error}
          <button onClick={() => setError(null)} aria-label="Dismiss error">×</button>
        </div>
      )}

      {/* Enabled currencies */}
      <h3>Enabled Currencies</h3>
      <table role="grid" aria-label="Enabled currencies list">
        <thead>
          <tr>
            <th>Currency</th>
            <th>Base</th>
            <th>Status</th>
          </tr>
        </thead>
        <tbody>
          {currencies.map((c) => (
            <tr key={c.id} data-testid={`currency-row-${c.currency_code}`}>
              <td>{c.currency_code}</td>
              <td>{c.is_base ? '✓ Base' : ''}</td>
              <td>{c.enabled ? 'Enabled' : 'Disabled'}</td>
            </tr>
          ))}
          {currencies.length === 0 && (
            <tr><td colSpan={3}>No currencies enabled</td></tr>
          )}
        </tbody>
      </table>

      {!showEnableForm ? (
        <button onClick={() => setShowEnableForm(true)} aria-label="Enable currency">
          Enable Currency
        </button>
      ) : (
        <form onSubmit={handleEnable} aria-label="Enable currency form">
          <div>
            <label htmlFor="currency-code">Currency Code</label>
            <input
              id="currency-code"
              type="text"
              maxLength={3}
              value={enableForm.currency_code}
              onChange={(e) => setEnableForm({ ...enableForm, currency_code: e.target.value })}
              placeholder="USD"
              required
            />
          </div>
          <div>
            <label>
              <input
                type="checkbox"
                checked={enableForm.is_base}
                onChange={(e) => setEnableForm({ ...enableForm, is_base: e.target.checked })}
              />
              Set as base currency
            </label>
          </div>
          <button type="submit" aria-label="Save currency">Save</button>
          <button type="button" onClick={() => setShowEnableForm(false)} aria-label="Cancel enable">Cancel</button>
        </form>
      )}

      {/* Exchange rates */}
      <h3>Exchange Rates</h3>
      <button
        onClick={handleRefresh}
        disabled={refreshing}
        aria-label="Refresh rates from provider"
      >
        {refreshing ? 'Refreshing…' : 'Refresh from Provider'}
      </button>

      <table role="grid" aria-label="Exchange rates list">
        <thead>
          <tr>
            <th>Base</th>
            <th>Target</th>
            <th>Rate</th>
            <th>Source</th>
            <th>Date</th>
          </tr>
        </thead>
        <tbody>
          {rates.map((r) => (
            <tr key={r.id} data-testid={`rate-row-${r.base_currency}-${r.target_currency}`}>
              <td>{r.base_currency}</td>
              <td>{r.target_currency}</td>
              <td>{r.rate}</td>
              <td>{r.source}</td>
              <td>{r.effective_date}</td>
            </tr>
          ))}
          {rates.length === 0 && (
            <tr><td colSpan={5}>No exchange rates configured</td></tr>
          )}
        </tbody>
      </table>

      {!showRateForm ? (
        <button onClick={() => setShowRateForm(true)} aria-label="Add manual rate">
          Add Manual Rate
        </button>
      ) : (
        <form onSubmit={handleSetRate} aria-label="Set exchange rate form">
          <div>
            <label htmlFor="rate-base">Base Currency</label>
            <input
              id="rate-base"
              type="text"
              maxLength={3}
              value={rateForm.base_currency}
              onChange={(e) => setRateForm({ ...rateForm, base_currency: e.target.value })}
              placeholder="NZD"
              required
            />
          </div>
          <div>
            <label htmlFor="rate-target">Target Currency</label>
            <input
              id="rate-target"
              type="text"
              maxLength={3}
              value={rateForm.target_currency}
              onChange={(e) => setRateForm({ ...rateForm, target_currency: e.target.value })}
              placeholder="USD"
              required
            />
          </div>
          <div>
            <label htmlFor="rate-value">Rate</label>
            <input
              id="rate-value"
              type="number"
              step="0.00000001"
              min="0.00000001"
              value={rateForm.rate}
              onChange={(e) => setRateForm({ ...rateForm, rate: e.target.value })}
              required
            />
          </div>
          <div>
            <label htmlFor="rate-date">Effective Date</label>
            <input
              id="rate-date"
              type="date"
              value={rateForm.effective_date}
              onChange={(e) => setRateForm({ ...rateForm, effective_date: e.target.value })}
              required
            />
          </div>
          <button type="submit" aria-label="Save rate">Save Rate</button>
          <button type="button" onClick={() => setShowRateForm(false)} aria-label="Cancel rate">Cancel</button>
        </form>
      )}
    </section>
  );
}
