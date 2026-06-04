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
import { ToastContainer } from '@/components/ui';
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

const tabBase =
  'min-h-[44px] min-w-[44px] rounded-ctl px-4 py-2 text-sm font-medium transition-colors';
const metricCard = 'rounded-card border border-border bg-card p-4 shadow-card';
const headerCell =
  'mono border-b border-border px-4 py-3 text-left text-[10.5px] font-medium uppercase tracking-[0.08em] text-muted-2';

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

  const fetchData = useCallback(async (controller?: AbortController) => {
    try {
      setLoading(true);
      if (view === 'head-office') {
        const res = await apiClient.get('/api/v2/franchise/head-office', { signal: controller?.signal });
        setHeadOffice(res.data);
      } else {
        const res = await apiClient.get('/api/v2/franchise/dashboard', { signal: controller?.signal });
        setFranchise(res.data);
      }
    } catch {
      if (!controller?.signal.aborted) {
        setError(`Failed to load ${view} dashboard`);
      }
    } finally {
      setLoading(false);
    }
  }, [view]);

  useEffect(() => {
    const controller = new AbortController();
    fetchData(controller);
    return () => controller.abort();
  }, [fetchData]);

  // Apply RBAC scoping and per-location filter to metrics
  const filteredMetrics = (() => {
    if (!headOffice) return [];
    let metrics = filterByUserLocations(headOffice.location_metrics ?? [], userLocations, userRole, 'location_id');
    if (locationFilter !== 'all') {
      metrics = metrics.filter((m) => m.location_id === locationFilter);
    }
    return metrics;
  })();

  // Compute max revenue for simple bar chart scaling
  const maxRevenue = Math.max(...filteredMetrics.map((m) => parseFloat(m.revenue) || 0), 1);

  if (guardLoading || loading) {
    return <p role="status" aria-label="Loading dashboard" className="py-12 text-center text-sm text-muted">Loading dashboard…</p>;
  }

  if (!isAllowed || !franchiseEnabled) return null;

  return (
    <section aria-label="Franchise Dashboard" className="space-y-5 px-4 py-6 sm:px-6 lg:px-8">
      <ToastContainer toasts={toasts} onDismiss={dismissToast} />
      <h2 className="text-2xl font-semibold text-text">Franchise Dashboard</h2>
      {error && (
        <div role="alert" className="flex items-center justify-between rounded-ctl bg-danger-soft px-4 py-3 text-sm text-danger">
          {error}
          <button onClick={() => setError(null)} aria-label="Dismiss error" className="ml-2 text-danger">×</button>
        </div>
      )}

      <div role="tablist" aria-label="Dashboard views" className="flex gap-2 border-b border-border pb-2">
        <button role="tab" aria-selected={view === 'head-office'}
          onClick={() => setView('head-office')} aria-label="Head office view"
          className={`${tabBase} ${view === 'head-office' ? 'bg-accent text-white' : 'text-muted hover:bg-canvas hover:text-text'}`}>
          Head Office
        </button>
        <button role="tab" aria-selected={view === 'franchise'}
          onClick={() => setView('franchise')} aria-label="Franchise view"
          className={`${tabBase} ${view === 'franchise' ? 'bg-accent text-white' : 'text-muted hover:bg-canvas hover:text-text'}`}>
          Franchise Overview
        </button>
      </div>

      {view === 'head-office' && headOffice && (
        <div data-testid="head-office-view" className="space-y-5">
          <div className="grid grid-cols-1 gap-4 sm:grid-cols-2" data-testid="aggregate-metrics">
            <div data-testid="total-revenue" className={metricCard}>
              <h4 className="text-xs font-medium uppercase tracking-wide text-muted-2">{revenueLabel}</h4>
              <p className="mono mt-1 text-2xl font-semibold text-text">${(parseFloat(headOffice.total_revenue) || 0).toLocaleString()}</p>
            </div>
            <div data-testid="total-outstanding" className={metricCard}>
              <h4 className="text-xs font-medium uppercase tracking-wide text-muted-2">Outstanding</h4>
              <p className="mono mt-1 text-2xl font-semibold text-text">${(parseFloat(headOffice.total_outstanding) || 0).toLocaleString()}</p>
            </div>
          </div>

          {/* Per-location filter for Org_Admin */}
          <div className="flex flex-wrap items-center gap-2">
            <label htmlFor="location-filter" className="text-sm text-muted">Filter by {locationLabel}: </label>
            <select
              id="location-filter"
              value={locationFilter}
              onChange={(e) => setLocationFilter(e.target.value)}
              aria-label={`Filter by ${locationLabel}`}
              className="min-h-[44px] rounded-ctl border border-border bg-card px-3 py-2 text-sm text-text outline-none focus:border-accent focus:ring-1 focus:ring-accent"
            >
              <option value="all">All {locationLabel}s</option>
              {(headOffice.location_metrics ?? []).map((m) => (
                <option key={m.location_id} value={m.location_id}>{m.location_name}</option>
              ))}
            </select>
          </div>

          <h3 className="text-base font-semibold text-text">Per-{locationLabel} Performance Comparison</h3>

          {/* Simple bar chart for per-location revenue comparison */}
          <div data-testid="performance-chart" aria-label="Per-location performance chart" role="img" className="space-y-1 rounded-card border border-border bg-card p-4 shadow-card">
            {filteredMetrics.map((m) => {
              const pct = (parseFloat(m.revenue) / maxRevenue) * 100;
              return (
                <div key={m.location_id} data-testid={`chart-bar-${m.location_name}`} className="flex items-center gap-2">
                  <span className="w-32 truncate text-sm text-text">{m.location_name}</span>
                  <div
                    className="h-6 min-w-[4px] max-w-[60%] rounded-ctl bg-accent"
                    style={{ width: `${pct}%` }}
                    aria-label={`${m.location_name}: ${(parseFloat(m.revenue) || 0).toLocaleString()}`}
                  />
                  <span className="mono ml-2 text-sm text-text">${(parseFloat(m.revenue) || 0).toLocaleString()}</span>
                </div>
              );
            })}
            {filteredMetrics.length === 0 && <p className="text-sm text-muted">No location data available</p>}
          </div>

          <div className="overflow-x-auto overflow-hidden rounded-card border border-border bg-card shadow-card">
            <table role="grid" aria-label="Location comparison" className="w-full text-sm">
              <thead>
                <tr>
                  <th className={headerCell}>{locationLabel}</th>
                  <th className={headerCell}>{revenueLabel}</th>
                  <th className={headerCell}>Outstanding</th>
                  <th className={headerCell}>Invoices</th>
                </tr>
              </thead>
              <tbody>
                {filteredMetrics.map((m) => (
                  <tr key={m.location_id} data-testid={`loc-metric-${m.location_name}`} className="border-b border-border last:border-b-0 hover:bg-canvas">
                    <td className="px-4 py-3 text-text">{m.location_name}</td>
                    <td className="mono px-4 py-3 text-text">${(parseFloat(m.revenue) || 0).toLocaleString()}</td>
                    <td className="mono px-4 py-3 text-text">${(parseFloat(m.outstanding) || 0).toLocaleString()}</td>
                    <td className="mono px-4 py-3 text-text">{m.invoice_count}</td>
                  </tr>
                ))}
                {filteredMetrics.length === 0 && (
                  <tr><td colSpan={4} className="px-4 py-3 text-sm text-muted">No location data available</td></tr>
                )}
              </tbody>
            </table>
          </div>
        </div>
      )}

      {view === 'franchise' && franchise && (
        <div data-testid="franchise-view">
          <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-4" data-testid="franchise-metrics">
            <div data-testid="franchise-orgs" className={metricCard}>
              <h4 className="text-xs font-medium uppercase tracking-wide text-muted-2">Organisations</h4>
              <p className="mono mt-1 text-2xl font-semibold text-text">{franchise.total_organisations}</p>
            </div>
            <div data-testid="franchise-revenue" className={metricCard}>
              <h4 className="text-xs font-medium uppercase tracking-wide text-muted-2">{revenueLabel}</h4>
              <p className="mono mt-1 text-2xl font-semibold text-text">${(parseFloat(franchise.total_revenue) || 0).toLocaleString()}</p>
            </div>
            <div data-testid="franchise-outstanding" className={metricCard}>
              <h4 className="text-xs font-medium uppercase tracking-wide text-muted-2">Outstanding</h4>
              <p className="mono mt-1 text-2xl font-semibold text-text">${(parseFloat(franchise.total_outstanding) || 0).toLocaleString()}</p>
            </div>
            <div data-testid="franchise-locations" className={metricCard}>
              <h4 className="text-xs font-medium uppercase tracking-wide text-muted-2">Total {locationLabel}s</h4>
              <p className="mono mt-1 text-2xl font-semibold text-text">{franchise.total_locations}</p>
            </div>
          </div>
        </div>
      )}
    </section>
  );
}
