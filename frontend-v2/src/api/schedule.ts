/**
 * Typed API client for the v2 scheduling endpoints used by the
 * Roster Grid Editor (`/staff-schedule/grid`).
 *
 * Every method takes an `AbortSignal` and threads it into the
 * underlying axios call so callers can cancel in-flight requests
 * from a `useEffect` cleanup. Every response accessor uses `?.` +
 * `?? []` / `?? 0` (per `.kiro/steering/safe-api-consumption.md`
 * Pattern 1/2). Generics on every `apiClient.{get,post}` call
 * preserve types end-to-end — no `as any` (Pattern 5).
 */

import apiClient from '@/api/client'
import type {
  BulkScheduleEntryResponse,
  CopyWeekRequest,
  ScheduleEntryCreate,
  ScheduleEntryListResponse,
  ShiftTemplateListResponse,
} from '@/types/schedule'

export async function listEntries(params: {
  start: string
  end: string
  staff_id?: string
  signal?: AbortSignal
}): Promise<ScheduleEntryListResponse> {
  const res = await apiClient.get<ScheduleEntryListResponse>('/schedule', {
    baseURL: '/api/v2',
    params: { start: params.start, end: params.end, staff_id: params.staff_id },
    signal: params.signal,
  })
  return {
    entries: res.data?.entries ?? [],
    total: res.data?.total ?? 0,
  }
}

export async function bulkCreate(payload: {
  entries: ScheduleEntryCreate[]
  signal?: AbortSignal
}): Promise<BulkScheduleEntryResponse> {
  const res = await apiClient.post<BulkScheduleEntryResponse>(
    '/schedule/bulk',
    { entries: payload.entries },
    { baseURL: '/api/v2', signal: payload.signal },
  )
  return {
    created: res.data?.created ?? [],
    conflicts: res.data?.conflicts ?? [],
  }
}

export async function copyWeek(payload: {
  source_week_start: string
  target_week_start: string
  overwrite_existing: boolean
  signal?: AbortSignal
}): Promise<BulkScheduleEntryResponse> {
  const body: CopyWeekRequest = {
    source_week_start: payload.source_week_start,
    target_week_start: payload.target_week_start,
    overwrite_existing: payload.overwrite_existing,
  }
  const res = await apiClient.post<BulkScheduleEntryResponse>(
    '/schedule/copy-week',
    body,
    { baseURL: '/api/v2', signal: payload.signal },
  )
  return {
    created: res.data?.created ?? [],
    conflicts: res.data?.conflicts ?? [],
  }
}

export async function listTemplates(opts: {
  signal?: AbortSignal
}): Promise<ShiftTemplateListResponse> {
  const res = await apiClient.get<ShiftTemplateListResponse>(
    '/schedule/templates',
    { baseURL: '/api/v2', signal: opts.signal },
  )
  return {
    templates: res.data?.templates ?? [],
    total: res.data?.total ?? 0,
  }
}

export async function deleteEntry(
  id: string,
  signal?: AbortSignal,
): Promise<void> {
  await apiClient.delete(`/schedule/${id}`, {
    baseURL: '/api/v2',
    signal,
  })
}
