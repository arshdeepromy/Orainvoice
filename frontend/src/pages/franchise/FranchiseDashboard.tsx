/**
 * Franchise dashboard with aggregate metrics, per-location performance
 * comparison charts, RBAC-scoped data, and per-location filtering.
 *
 * Validates: Requirements 2.1, 2.3, 2.6, 2.7, 2.8
 */
import { useCallback, useEffect, useMemo, useState } from 'react';
import apiClient from '@/api/client';
import { useAuth } from '@/contexts/AuthContext';
import { useModuleGuard } from '@/hooks/useModuleGuard';
import { useFlag } from '@/contexts/FeatureFlagContext';
import { useTerm } from '@/contexts/TerminologyContext';
import { ToastContainer } from '@/components/ui/Toast';
import { filterByUserLocations } from '@/utils/franchiseUtils';

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
  const { user } = useAuth();
  const { isAllowed, isLoading: guardLoading, toasts, dismissToast } = useModuleGuard('franchise');
  const franchiseEnabled = useFlag('franchise');
  const locationLabel = useTerm('location', 'Location');
  const revenueLabel = useTerm('revenue', 'Revenue');

  const [headOffice, setHeadOffice] = useState<HeadOfficeData | null>(null);
  const [franchise, setFranchise] = useState<FranchiseMetrics | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [view, setView] = useState<'head-office' | 'franchise'>('head-office');
  const [locationFilter, setLocationFilter] = useState<string>('all');

  // RBAC
  const userRole: string = user?.role ?? '';
  const assignedLocs = (user as any)?.assigned_locations;
  const userLocations: string[] = useMemo(
    () => assignedLocs ?? [],
    [assignedLocs],
  );

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

  // Apply RBAC scoping and per-location filter to metrics
  const filteredMetrics = (() => {
    if (!headOffice) return [];
    let metrics = filterByUserLocations(headOffice.location_metrics, userLocations, userRole, 'location_id');
    if (locationFilter !== 'all') {
      metrics = metrics.filter((m) => m.location_id === locationFilter);
    }
    return metrics;
  })();

  // Compute max revenue for simple bar chart scaling
  const maxRevenue = Math.max(...filteredMetrics.map((m) => parseFloat(m.revenue) || 0), 1);

  if (guardLoading || loading) {
    return <p role="status" aria-label="Loading dashboard">Loading dashboard…</p>;
  }

  if (!isAllowed || !franchiseEnabled) return null;

  return (
    <section aria-label="Franchise Dashboard">
      <ToastContainer toasts={toasts} onDismiss={dismissToast} />
      <h2>Franchise Dashboard</h2>
      {error && (
        <div role="alert" className="error-banner">
          {error}
          <button onClick={() => setError(null)} aria-label="Dismiss error">×</button>
        </div>
      )}

      <div role="tablist" aria-label="Dashboard views">
        <button role="tab" aria-selected={view === 'head-office'}
          onClick={() => setView('head-office')} aria-label="Head office view"
          style={{ minWidth: 44, minHeight: 44 }}>
          Head Office
        </button>
        <button role="tab" aria-selected={view === 'franchise'}
          onClick={() => setView('franchise')} aria-label="Franchise view"
          style={{ minWidth: 44, minHeight: 44 }}>
          Franchise Overview
        </button>
      </div>

      {view === 'head-office' && headOffice && (
        <div data-testid="head-office-view">
          <div className="metrics-grid responsive-grid" data-testid="aggregate-metrics">
            <div data-testid="total-revenue">
              <h4>{revenueLabel}</h4>
              <p>${parseFloat(headOffice.total_revenue).toLocaleString()}</p>
            </div>
            <div data-testid="total-outstanding">
              <h4>Outstanding</h4>
              <p>${parseFloat(headOffice.total_outstanding).toLocaleString()}</p>
            </div>
          </div>

          {/* Per-location filter for Org_Admin */}
          <div style={{ margin: '1rem 0' }}>
            <label htmlFor="location-filter">Filter by {locationLabel}: </label>
            <select
              id="location-filter"
              value={locationFilter}
              onChange={(e) => setLocationFilter(e.target.value)}
              aria-label={`Filter by ${locationLabel}`}
            >
              <option value="all">All {locationLabel}s</option>
              {headOffice.location_metrics.map((m) => (
                <option key={m.location_id} value={m.location_id}>{m.location_name}</option>
              ))}
            </select>
          </div>

          <h3>Per-{locationLabel} Performance Comparison</h3>

          {/* Simple bar chart for per-location revenue comparison */}
          <div data-testid="performance-chart" aria-label="Per-location performance chart" role="img" style={{ marginBottom: '1rem' }}>
            {filteredMetrics.map((m) => {
              const pct = (parseFloat(m.revenue) / maxRevenue) * 100;
              return (
                <div key={m.location_id} data-testid={`chart-bar-${m.location_name}`} style={{ display: 'flex', alignItems: 'center', marginBottom: 4 }}>
                  <span style={{ width: 120, fontSize: 14 }}>{m.location_name}</span>
                  <div
                    style={{
                      height: 24,
                      width: `${pct}%`,
                      maxWidth: '60%',
                      backgroundColor: '#3b82f6',
                      borderRadius: 4,
                      minWidth: 4,
                    }}
                    aria-label={`${m.location_name}: $${parseFloat(m.revenue).toLocaleString()}`}
                  />
                  <span style={{ marginLeft: 8, fontSize: 14 }}>${parseFloat(m.revenue).toLocaleString()}</span>
                </div>
              );
            })}
            {filteredMetrics.length === 0 && <p>No location data available</p>}
          </div>

          <table role="grid" aria-label="Location comparison">
            <thead>
              <tr><th>{locationLabel}</th><th>{revenueLabel}</th><th>Outstanding</th><th>Invoices</th></tr>
            </thead>
            <tbody>
              {filteredMetrics.map((m) => (
                <tr key={m.location_id} data-testid={`loc-metric-${m.location_name}`}>
                  <td>{m.location_name}</td>
                  <td>${parseFloat(m.revenue).toLocaleString()}</td>
                  <td>${parseFloat(m.outstanding).toLocaleString()}</td>
                  <td>{m.invoice_count}</td>
                </tr>
              ))}
              {filteredMetrics.length === 0 && (
                <tr><td colSpan={4}>No location data available</td></tr>
              )}
            </tbody>
          </table>
        </div>
      )}

      {view === 'franchise' && franchise && (
        <div data-testid="franchise-view">
          <div className="metrics-grid responsive-grid" data-testid="franchise-metrics">
            <div data-testid="franchise-orgs">
              <h4>Organisations</h4>
              <p>{franchise.total_organisations}</p>
            </div>
            <div data-testid="franchise-revenue">
              <h4>{revenueLabel}</h4>
              <p>${parseFloat(franchise.total_revenue).toLocaleString()}</p>
            </div>
            <div data-testid="franchise-outstanding">
              <h4>Outstanding</h4>
              <p>${parseFloat(franchise.total_outstanding).toLocaleString()}</p>
            </div>
            <div data-testid="franchise-locations">
              <h4>Total {locationLabel}s</h4>
              <p>{franchise.total_locations}</p>
            </div>
          </div>
        </div>
      )}
    </section>
  );
}
