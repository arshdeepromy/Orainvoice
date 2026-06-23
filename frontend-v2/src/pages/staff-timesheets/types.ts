export interface TimesheetSummary {
  id: string
  staff_id: string
  staff_name: string
  branch_name: string | null
  status: string
  rostered_hours: number
  actual_hours: number
  adjusted_hours: number | null
  variance_hours: number
  exception_count: number
  approved_by_name: string | null
  approved_at: string | null
}

export interface PeriodSummary {
  total_staff: number
  approved_count: number
  pending_count: number
  locked_count: number
  total_ordinary_hours: number
  total_overtime_hours: number
  total_public_holiday_hours: number
}

export interface TimesheetListResponse {
  items: TimesheetSummary[]
  total: number
  period_summary: PeriodSummary
}

export interface TimesheetDetailEntry {
  id: string
  clock_in_at: string
  clock_out_at: string | null
  worked_minutes: number | null
  matched_minutes: number | null
  match_type: string | null
  schedule_entry_id: string | null
  schedule_start: string | null
  schedule_end: string | null
  branch_name: string | null
  source: string | null
  breaks: Record<string, unknown>[]
}

export interface TimesheetDetail {
  id: string
  staff_id: string
  staff_name: string
  pay_period_id: string
  period_start: string
  period_end: string
  branch_name: string | null
  status: string
  rostered_minutes: number
  actual_minutes: number
  adjusted_minutes: number | null
  ordinary_minutes: number
  overtime_minutes: number
  public_holiday_minutes: number
  exception_flags: Record<string, unknown>[]
  notes: string | null
  approved_by_name: string | null
  approved_at: string | null
  locked_at: string | null
  locked_by_name: string | null
  entries: TimesheetDetailEntry[]
}

export interface ClockedInEntry {
  id: string
  staff_id: string
  staff_name: string
  position: string | null
  clock_in_at: string
  elapsed_minutes: number
  on_break: boolean
  break_started_at: string | null
  clock_in_branch_name: string
  clock_out_branch_name: string | null
  source: string
  clock_in_ip: string | null
  rostered_start: string | null
  punctuality: string | null
}

export interface ClockedInResponse {
  items: ClockedInEntry[]
  total: number
}

export interface TimesheetSettingsData {
  id: string
  org_id: string
  branch_id: string | null
  branch_name: string | null
  clock_rounding_minutes: number
  clock_rounding_direction: string
  early_grace_minutes: number
  late_grace_minutes: number
  match_policy: string
  auto_approve_threshold_minutes: number
  require_approval_before_lock: boolean
}

export interface TimesheetSettingsResponse {
  org_default: TimesheetSettingsData | null
  branch_overrides: TimesheetSettingsData[]
}

// --- Weekly breakdown ("weekly lens" review aid) ---

export interface WeeklyBreakdownStaffEntry {
  staff_id: string
  staff_name: string
  minutes: number
}

export interface WeeklyBreakdownWeek {
  week_index: number
  iso_week: number
  start_date: string
  end_date: string
  total_minutes: number
  staff: WeeklyBreakdownStaffEntry[]
}

export interface WeeklyBreakdownResponse {
  pay_period_id: string
  multi_week: boolean
  weeks: WeeklyBreakdownWeek[]
}


// --- Attendance report (date-range "who worked + hours vs expected") ---

export interface AttendanceRow {
  staff_id: string
  staff_name: string
  position: string | null
  branch_name: string | null
  worked_hours: number
  expected_hours: number | null
  expected_source: 'scheduled' | 'fixed' | 'roster' | 'none'
  variance_hours: number | null
  shift_count: number
  is_clocked_in: boolean
  last_clock_out_at: string | null
  pending_review_count: number
  reviewed_count: number
}

export interface AttendanceSummary {
  total_staff: number
  total_worked_hours: number
  total_expected_hours: number
  clocked_in_count: number
  pending_review_count: number
}

export interface AttendanceResponse {
  items: AttendanceRow[]
  total: number
  summary: AttendanceSummary
  date_from: string
  date_to: string
}

// --- Attendance drill-in (per-staff shift list + review/approve) ---

export interface AttendanceShift {
  id: string
  work_date: string
  clock_in_at: string
  clock_out_at: string | null
  worked_hours: number | null
  branch_name: string | null
  source: string
  scheduled_start: string | null
  scheduled_end: string | null
  pattern_start: string | null
  pattern_end: string | null
  is_open: boolean
  reviewed: boolean
  reviewed_by_name: string | null
  reviewed_at: string | null
  flagged_for_review: boolean
  review_reason: string | null
}

export interface AttendanceDetailResponse {
  staff_id: string
  staff_name: string
  position: string | null
  date_from: string
  date_to: string
  worked_hours: number
  expected_hours: number | null
  expected_source: string
  variance_hours: number | null
  shifts: AttendanceShift[]
  pending_review_count: number
  reviewed_count: number
}

export interface ShiftReviewResponse {
  id: string
  reviewed: boolean
  reviewed_by_name: string | null
  reviewed_at: string | null
}

export interface AttendanceReviewAllResponse {
  affected_count: number
  pending_review_count: number
}
