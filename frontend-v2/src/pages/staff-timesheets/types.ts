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
