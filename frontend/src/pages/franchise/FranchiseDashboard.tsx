/**
 * Franchise dashboard with aggregate metrics across linked organisations.
 *
 * **Validates: Requirement 8 — Extended RBAC / Multi-Location, Task 43.14**
 */
import { useCallback, useEffect, useState } from 'react';
import apiClient from '@/api/client';

interface LocationMetric {
  location_id: string; location_name: string;
  revenue: string; outstanding: string; invoice_count: number;
}

interface HeadOfficeData {
  total_revenue: string; total_outstanding: string;
  location_metrics: LocationMetric[];
}

interface FranchiseMetrics {
  total_organisations: number; total_revenue: string;
  total_outstanding: string; total_locations: number;
}

export default function FranchiseDashboard() {
  const [headOffice, setHeadOffice] = useState<HeadOfficeData | null>(null);
  const [franchise, setFranchise] = useState<FranchiseMetrics | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [view, setView] = useState<'head-office' | 'franchise'>('head-office');

  const fetchData = useCallback(async () => {
    try {
      setLoading(true);
      if (view === 'head-office') {
        const res = await apiClient.get('/api/v2/franchise/head-office');
        setHeadOffice(res.data);
      } else {
        const res = await apiClient.get('/api/v2/franchise/dashboard');
        setFranchise(res.data);
      }
    } catch {
      setError(`Failed to load ${view} dashboard`);
    } finally {
      setLoading(false);
    }
  }, [view]);

  useEffect(() => { fetchData(); }, [fetchData]);

  if (loading) {
    return <p role="status" aria-label="Loading dashboard">Loading dashboard…</p>;
  }

  return (
    <section aria-label="Franchise Dashboard">
      <h2>Franchise Dashboard</h2>
      {error && (
        <div role="alert" className="error-banner">
          {error}
          <button onClick={() => setError(null)} aria-label="Dismiss error">×</button>
        </div>
      )}

      <div role="tablist" aria-label="Dashboard views">
        <button role="tab" aria-selected={view === 'head-office'}
          onClick={() => setView('head-office')} aria-label="Head office view">
          Head Office
        </button>
        <button role="tab" aria-selected={view === 'franchise'}
          onClick={() => setView('franchise')} aria-label="Franchise view">
          Franchise Overview
        </button>
      </div>

      {view === 'head-office' && headOffice && (
        <div data-testid="head-office-view">
          <div className="metrics-grid" data-testid="aggregate-metrics">
            <div data-testid="total-revenue">
              <h4>Total Revenue</h4>
              <p>${parseFloat(headOffice.total_revenue).toLocaleString()}</p>
            </div>
            <div data-testid="total-outstanding">
              <h4>Outstanding</h4>
              <p>${parseFloat(headOffice.total_outstanding).toLocaleString()}</p>
            </div>
          </div>

          <h3>Per-Location Comparison</h3>
          <table role="grid" aria-label="Location comparison">
            <thead>
              <tr><th>Location</th><th>Revenue</th><th>Outstanding</th></tr>
            </thead>
            <tbody>
              {headOffice.location_metrics.map((m) => (
                <tr key={m.location_id} data-testid={`loc-metric-${m.location_name}`}>
                  <td>{m.location_name}</td>
                  <td>${parseFloat(m.revenue).toLocaleString()}</td>
                  <td>${parseFloat(m.outstanding).toLocaleString()}</td>
                </tr>
              ))}
              {headOffice.location_metrics.length === 0 && (
                <tr><td colSpan={3}>No location data available</td></tr>
              )}
            </tbody>
          </table>
        </div>
      )}

      {view === 'franchise' && franchise && (
        <div data-testid="franchise-view">
          <div className="metrics-grid" data-testid="franchise-metrics">
            <div data-testid="franchise-orgs">
              <h4>Organisations</h4>
              <p>{franchise.total_organisations}</p>
            </div>
            <div data-testid="franchise-revenue">
              <h4>Total Revenue</h4>
              <p>${parseFloat(franchise.total_revenue).toLocaleString()}</p>
            </div>
            <div data-testid="franchise-outstanding">
              <h4>Outstanding</h4>
              <p>${parseFloat(franchise.total_outstanding).toLocaleString()}</p>
            </div>
            <div data-testid="franchise-locations">
              <h4>Total Locations</h4>
              <p>{franchise.total_locations}</p>
            </div>
          </div>
        </div>
      )}
    </section>
  );
}
