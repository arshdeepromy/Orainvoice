/**
 * HoursTab — Staff Detail "Hours" tab (Phase 3, task D2 / G10).
 *
 * Layout per design.md §6.2:
 *   1. WeekNavigator — prev / this-week / next picker.
 *   2. ScheduledVsActualTable — per-day scheduled vs actual minutes + variance.
 *   3. FlaggedReviewBanner — surfaces when any week entry is flagged for review.
 *   4. ClockEntriesList — drill-down list with photo thumbnails (RBAC-gated)
 *      and per-row "Flag for follow-up" + "Compare with on-file" actions.
 *   5. BuddyPunchModal — side-by-side panel of on-file + clock-in / clock-out
 *      photos for visual buddy-punch verification by the manager.
 *   6. ApproveWeekBar — admin-only, posts to the timesheet approve endpoint.
 *      The Approve button surfaces a flagged-entry acknowledgement requirement
 *      when the week contains flagged rows.
 *
 * Backend endpoints consumed (all already implemented):
 *   - GET  /api/v2/staff/{id}/clock?week=YYYY-MM-DD       → { items, total }
 *   - GET  /api/v2/staff/{id}/timesheets                  → { items, total }
 *   - POST /api/v2/staff/{id}/clock-entries/{eid}/flag    → updated entry
 *   - POST /api/v2/staff/{id}/timesheets/{week}/approve   → approval row
 *   - GET  /api/v2/schedule?start=&end=&staff_id=         → { entries, total }
 *   - GET  /api/v2/staff/{id}                             → staff record (for photo)
 *
 * RBAC: photo URLs are RBAC-gated server-side (org_admin / branch_admin /
 * location_manager only). Lower roles receive `null` for both photo URLs and
 * the frontend renders the "[photo]" placeholder. The "Flag for follow-up"
 * action is also restricted to those same roles client-side (the backend
 * enforces the same restriction).
 *
 * Safe API consumption: every API response is consumed with `?.` chaining
 * and `?? null/0/[]` defaults; every useEffect uses an AbortController.
 *
 * Refs: Staff Management Phase 3 — R8, R9, G10.
 *
 * Logic copied verbatim; presentation remapped onto the design-system tokens.
 */

import {
  useCallback,
  useEffect,
  useMemo,
  useState,
  type ReactNode,
} from 'react'
import axios from 'axios'

import apiClient from '@/api/client'
import { useAuth } from '@/contexts/AuthContext'

/* ─────────────────────────────────────────────── Types ── */

interface ClockEntryFlags {
  flagged_for_review?: boolean
  review_reason?: string | null
  flagged_by?: string | null
  flagged_at?: string | null
}

interface ClockEntry {
  id: string
  org_id: string
  staff_id: string
  staff_name?: string | null
  clock_in_at: string
  clock_out_at: string | null
  source: string
  clock_in_photo_url: string | null
  clock_out_photo_url: string | null
  scheduled_entry_id: string | null
  break_minutes: number
  notes: string | null
  worked_minutes: number | null
  flags: ClockEntryFlags | null
  created_at: string
}

interface ClockEntriesPage {
  items: ClockEntry[]
  total: number
}

interface ScheduleEntry {
  id: string
  staff_id: string | null
  start_time: string
  end_time: string
  entry_type: string
  status: string
  title?: string | null
}

interface ScheduleEntriesPage {
  entries: ScheduleEntry[]
  total: number
}

interface TimesheetApproval {
  id: string
  org_id: string
  staff_id: string
  week_start: string
  week_end: string
  status:
    | 'pending'
    | 'approved'
    | 'rejected'
    | 'edited_after_approval'
  total_worked_minutes: number | null
  total_scheduled_minutes: number | null
  total_overtime_minutes: number
  total_break_minutes: number
  ordinary_minutes: number
  public_holiday_minutes: number
  toil_choice: string | null
  approved_by: string | null
  approved_by_email: string | null
  approved_at: string | null
  notes: string | null
}

interface TimesheetsPage {
  items: TimesheetApproval[]
  total: number
}

interface StaffMember {
  id: string
  first_name: string
  last_name: string | null
  on_file_photo_url: string | null
}

interface HoursTabProps {
  staffId: string
}

/* ──────────────────────────────────── Date / format helpers ── */

/** Monday-aligned ISO date (YYYY-MM-DD) for the given local Date. */
function mondayOf(d: Date): Date {
  const x = new Date(d.getFullYear(), d.getMonth(), d.getDate())
  const day = x.getDay()
  const diff = day === 0 ? -6 : 1 - day
  x.setDate(x.getDate() + diff)
  return x
}

function toIsoDate(d: Date): string {
  const y = d.getFullYear()
  const m = String(d.getMonth() + 1).padStart(2, '0')
  const dd = String(d.getDate()).padStart(2, '0')
  return `${y}-${m}-${dd}`
}

function addDays(d: Date, n: number): Date {
  const x = new Date(d.getFullYear(), d.getMonth(), d.getDate())
  x.setDate(x.getDate() + n)
  return x
}

function diffMinutes(startIso: string, endIso: string): number {
  const a = new Date(startIso).getTime()
  const b = new Date(endIso).getTime()
  if (!Number.isFinite(a) || !Number.isFinite(b)) return 0
  return Math.max(0, Math.round((b - a) / 60_000))
}

function fmtMinutes(mins: number | null | undefined): string {
  const safe = mins ?? 0
  const sign = safe < 0 ? '-' : ''
  const v = Math.abs(safe)
  const h = Math.floor(v / 60)
  const m = v % 60
  if (h > 0 && m > 0) return `${sign}${h}h ${m}m`
  if (h > 0) return `${sign}${h}h`
  return `${sign}${m}m`
}

function fmtVariance(mins: number): string {
  if (mins === 0) return '0m'
  return mins > 0 ? `+${fmtMinutes(mins)}` : `-${fmtMinutes(Math.abs(mins))}`
}

function fmtTime(iso: string | null | undefined): string {
  if (!iso) return '—'
  try {
    return new Date(iso).toLocaleTimeString([], {
      hour: '2-digit',
      minute: '2-digit',
    })
  } catch {
    return '—'
  }
}

function fmtDayLabel(d: Date): string {
  return d.toLocaleDateString('en-NZ', {
    weekday: 'short',
    day: 'numeric',
    month: 'short',
  })
}

const ADMIN_ROLES = new Set([
  'org_admin',
  'branch_admin',
  'location_manager',
])

/* ───────────────────────────────────── FlaggedReviewBanner ── */

interface FlaggedReviewBannerProps {
  count: number
}

function FlaggedReviewBanner({ count }: FlaggedReviewBannerProps) {
  if (count <= 0) return null
  return (
    <div
      role="status"
      data-testid="flagged-review-banner"
      className="mb-4 flex items-start gap-3 rounded-ctl border border-warn/40 bg-warn-soft px-4 py-3 text-sm text-warn"
    >
      <span aria-hidden="true" className="text-lg leading-none">
        🚩
      </span>
      <p className="flex-1">
        <span className="font-semibold">
          {count} {count === 1 ? 'entry' : 'entries'} flagged for review
        </span>
        . Review the highlighted rows below before approving the week.
      </p>
    </div>
  )
}

/* ────────────────────────────────────── BuddyPunchModal ── */

interface BuddyPunchModalProps {
  entry: ClockEntry
  onFilePhotoUrl: string | null
  staffName: string
  canViewPhotos: boolean
  onClose: () => void
  onFlag: (entry: ClockEntry) => void
}

function BuddyPunchModal({
  entry,
  onFilePhotoUrl,
  staffName,
  canViewPhotos,
  onClose,
  onFlag,
}: BuddyPunchModalProps) {
  const onFile = onFilePhotoUrl ?? null
  const inPhoto = entry?.clock_in_photo_url ?? null
  const outPhoto = entry?.clock_out_photo_url ?? null
  const isFlagged = !!entry?.flags?.flagged_for_review

  return (
    <div
      role="dialog"
      aria-modal="true"
      aria-labelledby="buddy-punch-title"
      data-testid="buddy-punch-modal"
      className="fixed inset-0 z-50 flex items-center justify-center bg-ink/50 p-4"
    >
      <div className="flex max-h-[90vh] w-full max-w-3xl flex-col overflow-hidden rounded-card bg-card shadow-pop">
        <header className="flex items-center justify-between border-b border-border px-6 py-4">
          <h2
            id="buddy-punch-title"
            className="text-[15px] font-semibold text-text"
          >
            Compare photos — {staffName}
          </h2>
          <button
            type="button"
            onClick={onClose}
            aria-label="Close dialog"
            className="min-h-[44px] min-w-[44px] rounded-ctl p-2 text-muted-2 hover:text-text focus:outline-none focus:ring-2 focus:ring-accent"
          >
            <span aria-hidden="true" className="text-xl leading-none">
              ×
            </span>
          </button>
        </header>

        <div className="overflow-y-auto px-6 py-4">
          <p className="mb-3 text-sm text-muted">
            {fmtDayLabel(new Date(entry?.clock_in_at ?? Date.now()))} ·{' '}
            {fmtTime(entry?.clock_in_at)} → {fmtTime(entry?.clock_out_at)}
          </p>

          <div className="grid grid-cols-1 gap-4 sm:grid-cols-3">
            <PhotoTile
              label="On file"
              url={onFile}
              canView={canViewPhotos}
              alt={`On-file photo of ${staffName}`}
            />
            <PhotoTile
              label="Clock-in"
              url={inPhoto}
              canView={canViewPhotos}
              alt="Clock-in photo"
            />
            <PhotoTile
              label="Clock-out"
              url={outPhoto}
              canView={canViewPhotos}
              alt="Clock-out photo"
            />
          </div>

          {!canViewPhotos && (
            <p className="mt-3 text-xs text-muted">
              Photo previews are visible to managers only.
            </p>
          )}
        </div>

        <footer className="flex flex-wrap items-center justify-end gap-2 border-t border-border px-6 py-3">
          <button
            type="button"
            onClick={onClose}
            className="min-h-[44px] rounded-ctl border border-border bg-card px-4 py-2 text-sm font-medium text-text hover:bg-canvas"
          >
            Looks correct
          </button>
          <button
            type="button"
            onClick={() => onFlag(entry)}
            disabled={isFlagged}
            className="min-h-[44px] rounded-ctl bg-warn px-4 py-2 text-sm font-medium text-white hover:brightness-95 disabled:cursor-not-allowed disabled:opacity-50"
            data-testid="buddy-punch-flag-button"
          >
            {isFlagged ? 'Already flagged' : 'Flag mismatch — investigate'}
          </button>
        </footer>
      </div>
    </div>
  )
}

interface PhotoTileProps {
  label: string
  url: string | null
  canView: boolean
  alt: string
}

function PhotoTile({ label, url, canView, alt }: PhotoTileProps) {
  return (
    <div className="space-y-2">
      <p className="mono text-xs font-semibold uppercase tracking-wide text-muted-2">
        {label}
      </p>
      <div className="aspect-square w-full overflow-hidden rounded-ctl border border-border bg-canvas">
        {!canView ? (
          <PhotoPlaceholder label="[photo]" />
        ) : url ? (
          <img
            src={url}
            alt={alt}
            className="h-full w-full object-cover"
          />
        ) : (
          <PhotoPlaceholder label="No photo" />
        )}
      </div>
    </div>
  )
}

function PhotoPlaceholder({ label }: { label: string }) {
  return (
    <div className="flex h-full w-full items-center justify-center text-xs font-medium text-muted-2">
      {label}
    </div>
  )
}

/* ─────────────────────────────────── ScheduledVsActualTable ── */

interface DayRow {
  date: Date
  iso: string
  scheduledMinutes: number
  actualMinutes: number
  breakMinutes: number
  varianceMinutes: number
}

interface ScheduledVsActualTableProps {
  rows: DayRow[]
}

function ScheduledVsActualTable({ rows }: ScheduledVsActualTableProps) {
  const totals = useMemo(() => {
    const scheduled = (rows ?? []).reduce(
      (acc, r) => acc + (r?.scheduledMinutes ?? 0),
      0,
    )
    const actual = (rows ?? []).reduce(
      (acc, r) => acc + (r?.actualMinutes ?? 0),
      0,
    )
    const breaks = (rows ?? []).reduce(
      (acc, r) => acc + (r?.breakMinutes ?? 0),
      0,
    )
    return {
      scheduled,
      actual,
      breaks,
      variance: actual - scheduled,
    }
  }, [rows])

  return (
    <div
      data-testid="scheduled-vs-actual"
      className="mb-4 overflow-hidden rounded-card border border-border"
    >
      <table className="min-w-full border-collapse text-sm">
        <thead className="bg-canvas">
          <tr>
            <th className="border-b border-border px-4 py-2 text-left font-medium text-muted">
              Day
            </th>
            <th className="border-b border-border px-4 py-2 text-right font-medium text-muted">
              Scheduled
            </th>
            <th className="border-b border-border px-4 py-2 text-right font-medium text-muted">
              Actual
            </th>
            <th className="border-b border-border px-4 py-2 text-right font-medium text-muted">
              Breaks
            </th>
            <th className="border-b border-border px-4 py-2 text-right font-medium text-muted">
              Variance
            </th>
          </tr>
        </thead>
        <tbody>
          {(rows ?? []).map((row) => (
            <tr key={row.iso} className="border-b border-border last:border-b-0">
              <td className="px-4 py-2 text-text">
                {fmtDayLabel(row.date)}
              </td>
              <td className="mono px-4 py-2 text-right text-muted">
                {fmtMinutes(row.scheduledMinutes)}
              </td>
              <td className="mono px-4 py-2 text-right text-muted">
                {fmtMinutes(row.actualMinutes)}
              </td>
              <td className="mono px-4 py-2 text-right text-muted">
                {fmtMinutes(row.breakMinutes)}
              </td>
              <td
                className={`mono px-4 py-2 text-right font-medium ${
                  row.varianceMinutes === 0
                    ? 'text-muted'
                    : row.varianceMinutes > 0
                      ? 'text-ok'
                      : 'text-danger'
                }`}
              >
                {fmtVariance(row.varianceMinutes)}
              </td>
            </tr>
          ))}
        </tbody>
        <tfoot className="bg-canvas">
          <tr>
            <td className="px-4 py-2 font-semibold text-text">
              Total
            </td>
            <td className="mono px-4 py-2 text-right font-semibold text-text">
              {fmtMinutes(totals.scheduled)}
            </td>
            <td className="mono px-4 py-2 text-right font-semibold text-text">
              {fmtMinutes(totals.actual)}
            </td>
            <td className="mono px-4 py-2 text-right font-semibold text-text">
              {fmtMinutes(totals.breaks)}
            </td>
            <td
              className={`mono px-4 py-2 text-right font-semibold ${
                totals.variance === 0
                  ? 'text-text'
                  : totals.variance > 0
                    ? 'text-ok'
                    : 'text-danger'
              }`}
            >
              {fmtVariance(totals.variance)}
            </td>
          </tr>
        </tfoot>
      </table>
    </div>
  )
}

/* ──────────────────────────────────────── ClockEntriesList ── */

interface ClockEntriesListProps {
  entries: ClockEntry[]
  canViewPhotos: boolean
  canFlag: boolean
  onCompare: (entry: ClockEntry) => void
  onFlag: (entry: ClockEntry) => void
  flaggingId: string | null
}

function ClockEntriesList({
  entries,
  canViewPhotos,
  canFlag,
  onCompare,
  onFlag,
  flaggingId,
}: ClockEntriesListProps) {
  const list = entries ?? []
  if (list.length === 0) {
    return (
      <div
        data-testid="clock-entries-empty"
        className="mb-4 rounded-card border border-dashed border-border px-4 py-8 text-center text-sm text-muted"
      >
        No clock entries recorded for this week yet.
      </div>
    )
  }
  return (
    <ul
      data-testid="clock-entries-list"
      className="mb-4 space-y-2"
      aria-label="Clock entries"
    >
      {list.map((entry) => (
        <ClockEntryRow
          key={entry?.id ?? Math.random().toString(36)}
          entry={entry}
          canViewPhotos={canViewPhotos}
          canFlag={canFlag}
          onCompare={onCompare}
          onFlag={onFlag}
          isFlagging={flaggingId === entry?.id}
        />
      ))}
    </ul>
  )
}

interface ClockEntryRowProps {
  entry: ClockEntry
  canViewPhotos: boolean
  canFlag: boolean
  onCompare: (entry: ClockEntry) => void
  onFlag: (entry: ClockEntry) => void
  isFlagging: boolean
}

function ClockEntryRow({
  entry,
  canViewPhotos,
  canFlag,
  onCompare,
  onFlag,
  isFlagging,
}: ClockEntryRowProps) {
  const flagged = !!entry?.flags?.flagged_for_review
  const inPhoto = entry?.clock_in_photo_url ?? null
  const outPhoto = entry?.clock_out_photo_url ?? null
  const dayLabel = fmtDayLabel(new Date(entry?.clock_in_at ?? Date.now()))
  const worked = entry?.worked_minutes ?? null
  const breakMin = entry?.break_minutes ?? 0

  return (
    <li
      data-testid={`clock-entry-${entry?.id ?? ''}`}
      data-flagged={flagged ? 'true' : 'false'}
      className={`rounded-card border px-4 py-3 ${
        flagged
          ? 'border-warn/40 bg-warn-soft'
          : 'border-border bg-card'
      }`}
    >
      <div className="flex flex-wrap items-start justify-between gap-2">
        <div className="min-w-0 flex-1">
          <div className="flex flex-wrap items-center gap-2">
            <span className="font-medium text-text">
              {dayLabel}
            </span>
            {flagged && (
              <span
                aria-label="Flagged for review"
                title={entry?.flags?.review_reason ?? 'Flagged for review'}
                className="inline-flex items-center gap-1 rounded-full bg-warn-soft px-2 py-0.5 text-xs font-medium text-warn"
                data-testid="row-flag-chip"
              >
                <span aria-hidden="true">🚩</span> Flagged
              </span>
            )}
            <span className="mono text-xs uppercase tracking-wide text-muted-2">
              {entry?.source ?? 'unknown'}
            </span>
          </div>
          <p className="mt-1 text-sm text-muted">
            <span className="mono">{fmtTime(entry?.clock_in_at)} → {fmtTime(entry?.clock_out_at)}</span>
            {' · '}
            <span>Worked {fmtMinutes(worked)}</span>
            {breakMin > 0 && <span> · Break {fmtMinutes(breakMin)}</span>}
          </p>
          {entry?.notes && (
            <p className="mt-1 text-xs text-muted-2">
              {entry.notes}
            </p>
          )}
        </div>

        {canViewPhotos && (
          <div
            className="flex items-center gap-2"
            data-testid="row-photo-thumbnails"
          >
            <PhotoThumb
              url={inPhoto}
              alt="Clock-in photo"
              testId="thumb-clock-in"
            />
            <PhotoThumb
              url={outPhoto}
              alt="Clock-out photo"
              testId="thumb-clock-out"
            />
          </div>
        )}
        {!canViewPhotos && (
          <div
            className="flex items-center gap-2"
            data-testid="row-photo-placeholders"
          >
            <span className="rounded bg-canvas px-2 py-1 text-xs text-muted">
              [photo]
            </span>
            <span className="rounded bg-canvas px-2 py-1 text-xs text-muted">
              [photo]
            </span>
          </div>
        )}
      </div>

      <div className="mt-3 flex flex-wrap items-center gap-2">
        {canViewPhotos && (
          <button
            type="button"
            onClick={() => onCompare(entry)}
            className="min-h-[36px] rounded-ctl border border-border bg-card px-3 py-1.5 text-xs font-medium text-text hover:bg-canvas"
            data-testid="row-compare-button"
          >
            Compare with on-file ▸
          </button>
        )}
        {canFlag && (
          <button
            type="button"
            onClick={() => onFlag(entry)}
            disabled={flagged || isFlagging}
            className="min-h-[36px] rounded-ctl border border-warn/40 bg-card px-3 py-1.5 text-xs font-medium text-warn hover:bg-warn-soft disabled:cursor-not-allowed disabled:opacity-50"
            data-testid="row-flag-button"
          >
            {flagged
              ? 'Flagged'
              : isFlagging
                ? 'Flagging…'
                : 'Flag for follow-up'}
          </button>
        )}
      </div>
    </li>
  )
}

interface PhotoThumbProps {
  url: string | null
  alt: string
  testId?: string
}

function PhotoThumb({ url, alt, testId }: PhotoThumbProps) {
  return (
    <div
      data-testid={testId}
      className="h-12 w-12 overflow-hidden rounded border border-border bg-canvas"
    >
      {url ? (
        <img src={url} alt={alt} className="h-full w-full object-cover" />
      ) : (
        <div className="flex h-full w-full items-center justify-center text-[10px] text-muted-2">
          —
        </div>
      )}
    </div>
  )
}

/* ─────────────────────────────────────────── ApproveWeekBar ── */

interface ApproveWeekBarProps {
  status: TimesheetApproval['status'] | 'no_approval'
  approval: TimesheetApproval | null
  totalActualMinutes: number
  totalScheduledMinutes: number
  flaggedCount: number
  approving: boolean
  approveError: string | null
  onApprove: (acknowledgeFlagged: boolean) => void
}

function ApproveWeekBar({
  status,
  approval,
  totalActualMinutes,
  totalScheduledMinutes,
  flaggedCount,
  approving,
  approveError,
  onApprove,
}: ApproveWeekBarProps) {
  const [acknowledged, setAcknowledged] = useState(false)
  const isApproved = status === 'approved'
  const needsAck = flaggedCount > 0
  const canSubmit = (!needsAck || acknowledged) && !approving && !isApproved

  return (
    <div
      data-testid="approve-week-bar"
      className="mt-4 rounded-card border border-border bg-canvas p-4"
    >
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <p className="text-sm font-semibold text-text">
            Week summary
          </p>
          <p className="text-xs text-muted">
            Scheduled <span className="mono">{fmtMinutes(totalScheduledMinutes)}</span> · Actual{' '}
            <span className="mono">{fmtMinutes(totalActualMinutes)}</span>
            {approval && (
              <>
                {' · Status: '}
                <span
                  className={`font-medium ${
                    isApproved
                      ? 'text-ok'
                      : approval.status === 'edited_after_approval'
                        ? 'text-warn'
                        : 'text-text'
                  }`}
                  data-testid="approval-status"
                >
                  {approval.status}
                </span>
              </>
            )}
          </p>
          {needsAck && !isApproved && (
            <label className="mt-2 flex items-start gap-2 text-xs text-warn">
              <input
                type="checkbox"
                checked={acknowledged}
                onChange={(e) => setAcknowledged(e.target.checked)}
                className="mt-0.5"
                data-testid="acknowledge-flagged-checkbox"
              />
              <span>
                {flaggedCount} {flaggedCount === 1 ? 'entry is' : 'entries are'}{' '}
                flagged for review. Approve anyway? You can also re-open the
                week later.
              </span>
            </label>
          )}
          {approveError && (
            <p
              role="alert"
              className="mt-2 text-xs text-danger"
              data-testid="approve-error"
            >
              {approveError}
            </p>
          )}
        </div>
        <div className="flex items-center gap-2">
          <button
            type="button"
            onClick={() => onApprove(acknowledged)}
            disabled={!canSubmit}
            className="min-h-[44px] rounded-ctl bg-accent px-4 py-2 text-sm font-medium text-white hover:bg-accent-press disabled:cursor-not-allowed disabled:opacity-50"
            data-testid="approve-week-button"
          >
            {approving
              ? 'Approving…'
              : isApproved
                ? 'Approved'
                : 'Approve hours'}
          </button>
        </div>
      </div>
    </div>
  )
}

/* ────────────────────────────────────────── WeekNavigator ── */

interface WeekNavigatorProps {
  weekStart: Date
  onPrev: () => void
  onNext: () => void
  onThis: () => void
}

function WeekNavigator({
  weekStart,
  onPrev,
  onNext,
  onThis,
}: WeekNavigatorProps) {
  const weekEnd = addDays(weekStart, 6)
  const label = `${weekStart.toLocaleDateString('en-NZ', {
    day: 'numeric',
    month: 'short',
  })} – ${weekEnd.toLocaleDateString('en-NZ', {
    day: 'numeric',
    month: 'short',
    year: 'numeric',
  })}`

  return (
    <div
      role="group"
      aria-label="Hours week navigator"
      className="mb-4 flex flex-wrap items-center gap-2"
    >
      <button
        type="button"
        onClick={onPrev}
        aria-label="Previous week"
        className="min-h-[44px] rounded-ctl border border-border px-3 py-2 text-sm font-medium text-text hover:bg-canvas focus:outline-none focus:ring-2 focus:ring-accent"
      >
        ←
      </button>
      <button
        type="button"
        onClick={onThis}
        className="min-h-[44px] rounded-ctl border border-border px-3 py-2 text-sm font-medium text-text hover:bg-canvas focus:outline-none focus:ring-2 focus:ring-accent"
      >
        This week
      </button>
      <button
        type="button"
        onClick={onNext}
        aria-label="Next week"
        className="min-h-[44px] rounded-ctl border border-border px-3 py-2 text-sm font-medium text-text hover:bg-canvas focus:outline-none focus:ring-2 focus:ring-accent"
      >
        →
      </button>
      <span
        className="mono ml-2 text-sm text-text"
        data-testid="hours-week-label"
      >
        {label}
      </span>
    </div>
  )
}

/* ─────────────────────────────────────────── Error helpers ── */

function readErrorMessage(err: unknown): string | null {
  if (axios.isCancel?.(err)) return null
  if (err instanceof DOMException && err.name === 'AbortError') return null
  const detail = (err as { response?: { data?: { detail?: unknown } } })
    ?.response?.data?.detail
  if (typeof detail === 'string') return detail
  if (
    detail &&
    typeof detail === 'object' &&
    'detail' in detail &&
    typeof (detail as { detail?: unknown }).detail === 'string'
  ) {
    return (detail as { detail: string }).detail
  }
  if (
    detail &&
    typeof detail === 'object' &&
    'reason' in detail &&
    typeof (detail as { reason?: unknown }).reason === 'string'
  ) {
    return (detail as { reason: string }).reason
  }
  return null
}

function isAbortError(err: unknown): boolean {
  if (axios.isCancel?.(err)) return true
  if (err instanceof DOMException && err.name === 'AbortError') return true
  if (
    typeof err === 'object' &&
    err !== null &&
    'code' in err &&
    (err as { code?: string }).code === 'ERR_CANCELED'
  ) {
    return true
  }
  return false
}


/* ──────────────────────────────────────────────── HoursTab ── */

export default function HoursTab({ staffId }: HoursTabProps) {
  const { user } = useAuth()
  const role = user?.role ?? null
  const isAdmin = !!role && ADMIN_ROLES.has(role)
  // Server-side RBAC redacts photos for non-admin roles. Client-side we
  // mirror the same gate for the placeholders shown in the row.
  const canViewPhotos = isAdmin

  const [weekStart, setWeekStart] = useState<Date>(() => mondayOf(new Date()))
  const weekIso = useMemo(() => toIsoDate(weekStart), [weekStart])

  const [staff, setStaff] = useState<StaffMember | null>(null)
  const [entries, setEntries] = useState<ClockEntry[]>([])
  const [scheduleEntries, setScheduleEntries] = useState<ScheduleEntry[]>([])
  const [approval, setApproval] = useState<TimesheetApproval | null>(null)

  const [loading, setLoading] = useState<boolean>(true)
  const [loadError, setLoadError] = useState<string | null>(null)

  const [compareEntry, setCompareEntry] = useState<ClockEntry | null>(null)
  const [flaggingId, setFlaggingId] = useState<string | null>(null)
  const [flagError, setFlagError] = useState<string | null>(null)

  const [approving, setApproving] = useState<boolean>(false)
  const [approveError, setApproveError] = useState<string | null>(null)

  /* ── Data load ────────────────────────────────────────── */

  const loadAll = useCallback(
    async (signal: AbortSignal) => {
      setLoading(true)
      setLoadError(null)
      try {
        const weekEndIso = toIsoDate(addDays(weekStart, 7))

        const [staffRes, entriesRes, scheduleRes, timesheetRes] =
          await Promise.all([
            apiClient.get<StaffMember>(`/api/v2/staff/${staffId}`, {
              signal,
            }),
            apiClient.get<ClockEntriesPage>(
              `/api/v2/staff/${staffId}/clock`,
              { params: { week: weekIso }, signal },
            ),
            apiClient.get<ScheduleEntriesPage>('/api/v2/schedule', {
              params: {
                start: `${weekIso}T00:00:00`,
                end: `${weekEndIso}T00:00:00`,
                staff_id: staffId,
              },
              signal,
            }),
            apiClient.get<TimesheetsPage>(
              `/api/v2/staff/${staffId}/timesheets`,
              { params: { limit: 50 }, signal },
            ),
          ])

        if (signal.aborted) return

        setStaff(staffRes.data ?? null)
        setEntries(entriesRes.data?.items ?? [])
        setScheduleEntries(scheduleRes.data?.entries ?? [])
        const approvals = timesheetRes.data?.items ?? []
        const matching =
          approvals.find((a) => a?.week_start === weekIso) ?? null
        setApproval(matching)
      } catch (err) {
        if (signal.aborted || isAbortError(err)) return
        setLoadError('Failed to load hours for this week.')
      } finally {
        if (!signal.aborted) setLoading(false)
      }
    },
    [staffId, weekIso, weekStart],
  )

  useEffect(() => {
    const controller = new AbortController()
    void loadAll(controller.signal)
    return () => controller.abort()
  }, [loadAll])

  /* ── Derived day rows ─────────────────────────────────── */

  const dayRows = useMemo<DayRow[]>(() => {
    const rows: DayRow[] = []
    for (let i = 0; i < 7; i += 1) {
      const day = addDays(weekStart, i)
      const dayStart = day.getTime()
      const dayEnd = addDays(day, 1).getTime()

      let scheduled = 0
      for (const se of scheduleEntries ?? []) {
        const startMs = new Date(se?.start_time ?? '').getTime()
        const endMs = new Date(se?.end_time ?? '').getTime()
        if (!Number.isFinite(startMs) || !Number.isFinite(endMs)) continue
        if (startMs >= dayStart && startMs < dayEnd) {
          scheduled += diffMinutes(se.start_time, se.end_time)
        }
      }

      let actual = 0
      let breaks = 0
      for (const ce of entries ?? []) {
        const inMs = new Date(ce?.clock_in_at ?? '').getTime()
        if (!Number.isFinite(inMs)) continue
        if (inMs >= dayStart && inMs < dayEnd) {
          actual += ce?.worked_minutes ?? 0
          breaks += ce?.break_minutes ?? 0
        }
      }

      rows.push({
        date: day,
        iso: toIsoDate(day),
        scheduledMinutes: scheduled,
        actualMinutes: actual,
        breakMinutes: breaks,
        varianceMinutes: actual - scheduled,
      })
    }
    return rows
  }, [scheduleEntries, entries, weekStart])

  const flaggedCount = useMemo(
    () =>
      (entries ?? []).filter(
        (e) => !!e?.flags?.flagged_for_review,
      ).length,
    [entries],
  )

  const totalActual = useMemo(
    () => (entries ?? []).reduce((acc, e) => acc + (e?.worked_minutes ?? 0), 0),
    [entries],
  )
  const totalScheduled = useMemo(
    () => dayRows.reduce((acc, r) => acc + (r?.scheduledMinutes ?? 0), 0),
    [dayRows],
  )

  const onFilePhotoUrl = staff?.on_file_photo_url ?? null
  const staffName = useMemo(() => {
    if (!staff) return ''
    const last = staff.last_name ?? ''
    const first = staff.first_name ?? ''
    const joined = [first, last].filter(Boolean).join(' ')
    return joined || 'this staff member'
  }, [staff])

  /* ── Actions ──────────────────────────────────────────── */

  const handleFlag = useCallback(
    async (entry: ClockEntry) => {
      if (!entry?.id || !isAdmin) return
      const entryId = entry.id
      setFlaggingId(entryId)
      setFlagError(null)
      try {
        const res = await apiClient.post<ClockEntry>(
          `/api/v2/staff/${staffId}/clock-entries/${entryId}/flag`,
          {},
        )
        const updated = res.data ?? null
        setEntries((prev) =>
          (prev ?? []).map((e) =>
            e?.id === entryId
              ? {
                  ...e,
                  flags: updated?.flags ?? {
                    ...(e.flags ?? {}),
                    flagged_for_review: true,
                  },
                }
              : e,
          ),
        )
        setCompareEntry((prev) =>
          prev?.id === entryId
            ? {
                ...prev,
                flags: updated?.flags ?? {
                  ...(prev.flags ?? {}),
                  flagged_for_review: true,
                },
              }
            : prev,
        )
      } catch (err) {
        if (isAbortError(err)) return
        setFlagError(
          readErrorMessage(err) ?? 'Failed to flag entry. Please try again.',
        )
      } finally {
        setFlaggingId(null)
      }
    },
    [isAdmin, staffId],
  )

  const handleApprove = useCallback(
    async (acknowledgeFlagged: boolean) => {
      setApproving(true)
      setApproveError(null)
      try {
        const res = await apiClient.post<TimesheetApproval>(
          `/api/v2/staff/${staffId}/timesheets/${weekIso}/approve`,
          { acknowledge_flagged: acknowledgeFlagged },
        )
        setApproval(res.data ?? null)
      } catch (err) {
        if (isAbortError(err)) return
        setApproveError(
          readErrorMessage(err) ??
            'Failed to approve the week. Please try again.',
        )
      } finally {
        setApproving(false)
      }
    },
    [staffId, weekIso],
  )

  /* ── Render ───────────────────────────────────────────── */

  const goPrev = useCallback(
    () => setWeekStart((prev) => addDays(prev, -7)),
    [],
  )
  const goNext = useCallback(
    () => setWeekStart((prev) => addDays(prev, 7)),
    [],
  )
  const goThis = useCallback(() => setWeekStart(mondayOf(new Date())), [])

  let content: ReactNode
  if (loading) {
    content = (
      <div
        data-testid="hours-tab-loading"
        className="rounded-card border border-border px-4 py-8 text-center text-sm text-muted"
      >
        Loading hours…
      </div>
    )
  } else if (loadError) {
    content = (
      <div
        role="alert"
        data-testid="hours-tab-error"
        className="rounded-card border border-danger/40 bg-danger-soft px-4 py-3 text-sm text-danger"
      >
        {loadError}
      </div>
    )
  } else {
    content = (
      <>
        <ScheduledVsActualTable rows={dayRows} />
        <FlaggedReviewBanner count={flaggedCount} />
        {flagError && (
          <p
            role="alert"
            data-testid="flag-error"
            className="mb-3 rounded-ctl bg-danger-soft px-3 py-2 text-sm text-danger"
          >
            {flagError}
          </p>
        )}
        <ClockEntriesList
          entries={entries ?? []}
          canViewPhotos={canViewPhotos}
          canFlag={isAdmin}
          onCompare={setCompareEntry}
          onFlag={handleFlag}
          flaggingId={flaggingId}
        />
        {isAdmin && (
          <ApproveWeekBar
            status={approval?.status ?? 'no_approval'}
            approval={approval}
            totalActualMinutes={totalActual}
            totalScheduledMinutes={totalScheduled}
            flaggedCount={flaggedCount}
            approving={approving}
            approveError={approveError}
            onApprove={handleApprove}
          />
        )}
      </>
    )
  }

  return (
    <div className="p-4 md:p-6" data-testid="hours-tab">
      <div className="mb-2 flex flex-wrap items-center justify-between gap-3">
        <h2 className="text-lg font-semibold text-text">
          Hours
        </h2>
      </div>
      <WeekNavigator
        weekStart={weekStart}
        onPrev={goPrev}
        onNext={goNext}
        onThis={goThis}
      />
      {content}
      {compareEntry && (
        <BuddyPunchModal
          entry={compareEntry}
          onFilePhotoUrl={onFilePhotoUrl}
          staffName={staffName}
          canViewPhotos={canViewPhotos}
          onClose={() => setCompareEntry(null)}
          onFlag={(e) => {
            void handleFlag(e)
          }}
        />
      )}
    </div>
  )
}
