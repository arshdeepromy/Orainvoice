/**
 * TypeScript types mirroring the Pydantic schemas in
 * `app/modules/scheduling_v2/schemas.py`.
 *
 * Manual sync — there is no auto-generated OpenAPI client at the time
 * of writing. Keep this file in lock-step with the backend schemas.
 *
 * Datetime fields are serialised as ISO-8601 strings on the wire.
 * Date fields (date-only) are `YYYY-MM-DD` strings.
 * UUIDs are stringified.
 */

export interface ScheduleEntryCreate {
  staff_id?: string | null
  job_id?: string | null
  booking_id?: string | null
  location_id?: string | null
  title?: string | null
  description?: string | null
  /** ISO-8601 datetime */
  start_time: string
  /** ISO-8601 datetime */
  end_time: string
  /** "job" | "booking" | "break" | "other" | "leave" */
  entry_type: string
  notes?: string | null
  /** "none" | "daily" | "weekly" | "fortnightly" */
  recurrence: string
}

export interface ScheduleEntryResponse {
  id: string
  org_id: string
  staff_id?: string | null
  job_id?: string | null
  booking_id?: string | null
  location_id?: string | null
  title?: string | null
  description?: string | null
  /** ISO-8601 datetime */
  start_time: string
  /** ISO-8601 datetime */
  end_time: string
  entry_type: string
  status: string
  notes?: string | null
  recurrence_group_id?: string | null
  /** ISO-8601 datetime */
  created_at: string
  /** ISO-8601 datetime */
  updated_at: string
}

export interface ScheduleEntryListResponse {
  entries: ScheduleEntryResponse[]
  total: number
}

export interface BulkConflictItem {
  index: number
  attempted: ScheduleEntryCreate
  conflicts_with: ScheduleEntryResponse[]
}

export interface BulkScheduleEntryResponse {
  created: ScheduleEntryResponse[]
  conflicts: BulkConflictItem[]
}

export interface BulkScheduleEntryCreateRequest {
  entries: ScheduleEntryCreate[]
}

export interface CopyWeekRequest {
  /** YYYY-MM-DD */
  source_week_start: string
  /** YYYY-MM-DD */
  target_week_start: string
  overwrite_existing: boolean
}

export interface ShiftTemplateResponse {
  id: string
  org_id: string
  name: string
  /** "HH:MM:SS" or "HH:MM" — backend serialises a SQL `time` */
  start_time: string
  /** "HH:MM:SS" or "HH:MM" */
  end_time: string
  entry_type: string
  /** ISO-8601 datetime */
  created_at: string
}

export interface ShiftTemplateListResponse {
  templates: ShiftTemplateResponse[]
  total: number
}
