/**
 * TypeScript interfaces for the automotive dashboard widgets.
 *
 * Field names match the backend Pydantic schemas in
 * app/modules/organisations/schemas.py exactly.
 *
 * Ported verbatim from frontend/src/pages/dashboard/widgets/types.ts (Task 18,
 * FR-1). No field renamed, added or removed — the backend contract is unchanged.
 */

import type React from 'react';

// ---------------------------------------------------------------------------
// Data interfaces — one per widget data item
// ---------------------------------------------------------------------------

export interface RecentCustomer {
  customer_id: string;
  customer_name: string;
  invoice_date: string;
  vehicle_rego: string | null;
}

export interface TodayBooking {
  booking_id: string;
  scheduled_time: string;
  customer_name: string;
  vehicle_rego: string | null;
}

export interface PublicHoliday {
  name: string;
  holiday_date: string;
}

export interface InventoryCategory {
  category: string;
  total_count: number;
  low_stock_count: number;
}

export interface CashFlowMonth {
  month: string;
  month_label: string;
  revenue: number;
  expenses: number;
}

export interface RecentClaim {
  claim_id: string;
  reference: string;
  customer_name: string;
  claim_date: string;
  status: 'open' | 'investigating' | 'approved' | 'rejected' | 'resolved';
}

export interface ActiveStaffMember {
  staff_id: string;
  name: string;
  clock_in_time: string;
}

export interface ExpiryReminder {
  vehicle_id: string;
  vehicle_rego: string;
  vehicle_make: string | null;
  vehicle_model: string | null;
  expiry_type: 'wof' | 'service';
  expiry_date: string;
  customer_name: string;
  customer_id: string;
}

export interface ReminderConfig {
  wof_days: number;
  service_days: number;
}

export interface RecentInvoiceItem {
  id: string;
  invoice_number: string;
  customer_name: string;
  status: string;
  date: string;
  total: number;
  revenue: number;
  cost: number;
  profit: number;
  margin_pct: number | null;
}

// ---------------------------------------------------------------------------
// Container interfaces
// ---------------------------------------------------------------------------

export interface WidgetDataSection<T> {
  items: T[];
  total: number;
}

export interface DashboardWidgetData {
  recent_customers: WidgetDataSection<RecentCustomer>;
  todays_bookings: WidgetDataSection<TodayBooking>;
  public_holidays: WidgetDataSection<PublicHoliday>;
  inventory_overview: WidgetDataSection<InventoryCategory>;
  cash_flow: WidgetDataSection<CashFlowMonth>;
  recent_claims: WidgetDataSection<RecentClaim>;
  active_staff: WidgetDataSection<ActiveStaffMember>;
  expiry_reminders: WidgetDataSection<ExpiryReminder>;
  reminder_config: ReminderConfig;
}

// ---------------------------------------------------------------------------
// Component interfaces
// ---------------------------------------------------------------------------

export interface WidgetComponentProps {
  data: unknown;
  isLoading: boolean;
  error: string | null;
  branchId: string | null;
}

export interface WidgetDefinition {
  id: string;
  title: string;
  icon: React.ComponentType;
  module?: string;
  component: React.ComponentType<WidgetComponentProps>;
  defaultOrder: number;
}

export interface WidgetCardProps {
  title: string;
  icon: React.ComponentType<{ className?: string }>;
  actionLink?: { label: string; to: string };
  children: React.ReactNode;
  isLoading?: boolean;
  error?: string | null;
}

// ---------------------------------------------------------------------------
// Dashboard range filter (page-level 7D / 30D / QTR / YR control)
// ---------------------------------------------------------------------------
//
// The prototype Dashboard.html carries a `.seg` segmented control in the
// page-head (7D / 30D / QTR / YR) that drives every range-sensitive widget.
// In the prototype it is cosmetic; here the mapping below makes it functional —
// it picks the `/reports/revenue` preset AND the `/dashboard/widgets/cash-flow`
// period + window. The mapping mirrors MainDashboard.tsx's RANGE_CONFIG so the
// two dashboards behave identically.

export type DashboardRange = '7D' | '30D' | 'QTR' | 'YR';

export interface DashboardRangeConfig {
  preset: 'week' | 'month' | 'quarter' | 'year';
  period: 'daily' | 'weekly' | 'monthly';
  days: number;
}

export const DASHBOARD_RANGE_ORDER: DashboardRange[] = ['7D', '30D', 'QTR', 'YR'];

export const DASHBOARD_RANGE_CONFIG: Record<DashboardRange, DashboardRangeConfig> = {
  '7D': { preset: 'week', period: 'daily', days: 14 },
  '30D': { preset: 'month', period: 'weekly', days: 90 },
  QTR: { preset: 'quarter', period: 'monthly', days: 180 },
  YR: { preset: 'year', period: 'monthly', days: 365 },
};
