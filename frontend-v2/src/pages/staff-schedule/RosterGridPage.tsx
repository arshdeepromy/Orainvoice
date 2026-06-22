/**
 * RosterGridPage — desktop-first 14-day roster grid editor at
 * `/staff-schedule/grid` (Workstream B).
 *
 * Wires together: data fetch (B4), the grid (B5), click-to-create
 * modal (B6), drag-resize (B7), template palette (B8), paint mode
 * (B9), multi-select rows + columns + apply template (B10), copy
 * week (B11), Ctrl+C/Ctrl+V clipboard (B12), keyboard nav (B13),
 * conflict banner (B14), CSV export (B15), print stylesheet (B16),
 * branch + position filters (B17), mobile fallback (B18), loading
 * + error UX polish (B20).
 *
 * Validates: R1, R2, R3, R4, R5, R6, R7, R8, R9, R10, R12, R13, R15,
 *           R16, R17, R18, R21.
 *
 * Logic copied verbatim from frontend/src/pages/staff-schedule/RosterGridPage.tsx;
 * the toolbar / filter / banner chrome is remapped onto the design-system
 * tokens. The colour-coded roster grid (RosterGrid) preserves its entry
 * legend as-is.
 */

import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import apiClient from '@/api/client'
import { useToast, ToastContainer } from '@/components/ui/Toast'
import { bulkCreate, copyWeek } from '@/api/schedule'
import type {
  BulkConflictItem,
  ScheduleEntryCreate,
  ScheduleEntryResponse,
  ShiftTemplateResponse,
} from '@/types/schedule'
import RosterGrid from './components/RosterGrid'
import TemplatePalette from './components/TemplatePalette'
import LeaveTypePalette, { leaveSwatch } from './components/LeaveTypePalette'
import { Modal } from '@/components/ui/Modal'
import { markDayLeave, type LeaveType } from '@/api/leave'
import CopyWeekConfirmModal from './components/CopyWeekConfirmModal'
import ConflictBanner, {
  type ConflictBannerEntry,
} from './components/ConflictBanner'
import RosterGridFilters, {
  applyStaffFilters,
} from './components/RosterGridFilters'
import CellDisambiguationPopover from './components/CellDisambiguationPopover'
import LeaveOverlapConfirmationModal from './components/LeaveOverlapConfirmationModal'
import ScheduleEntryModal from '@/pages/schedule/ScheduleEntryModal'
import type { ScheduleEntry as LegacyScheduleEntry } from '@/pages/schedule/ScheduleCalendar'
import { useRosterGridData } from './hooks/useRosterGridData'
import {
  buildEntriesForTemplate,
  paintIdempotenceFilter,
  BULK_CELL_CAP,
  type ResolvedCell,
} from './utils/paint'
import { computeApplyMatrix } from './utils/apply'
import { combineDateAndTime, toDatetimeLocal, toIsoDate } from './utils/time'
import {
  gridKeyboardReducer,
  type GridKeyboardKey,
} from './utils/keyboard'
import {
  shiftClipboardToFocusCell,
  clipboardFromCell,
  type ClipboardItem,
} from './utils/clipboard'
import { generateRosterGridCSV, downloadRosterGridCSV } from './utils/csv'
import { genId } from './utils/genId'
import { isFixedArrangement, fixedHoursEditMessage } from './utils/fixedHours'
import type { StaffMember as RosterStaffMember } from './hooks/useRosterGridData'

/* ------------------------------------------------------------------ */
/*  Date helpers                                                       */
/* ------------------------------------------------------------------ */

export function startOfISOWeek(date: Date): Date {
  const d = new Date(date.getFullYear(), date.getMonth(), date.getDate())
  const day = d.getDay()
  const diff = day === 0 ? -6 : 1 - day
  d.setDate(d.getDate() + diff)
  d.setHours(0, 0, 0, 0)
  return d
}

export function addDays(date: Date, n: number): Date {
  const d = new Date(date)
  d.setDate(d.getDate() + n)
  return d
}

function formatShort(date: Date): string {
  return new Intl.DateTimeFormat('en-NZ', {
    weekday: 'short',
    day: 'numeric',
    month: 'short',
  }).format(date)
}

const DAY_KEYS = [
  'monday',
  'tuesday',
  'wednesday',
  'thursday',
  'friday',
  'saturday',
  'sunday',
]

function getDayKey(date: Date): string {
  return DAY_KEYS[date.getDay() === 0 ? 6 : date.getDay() - 1]
}

/* ------------------------------------------------------------------ */
/*  Mobile fallback                                                    */
/* ------------------------------------------------------------------ */

function MobileFallback() {
  return (
    <div
      data-testid="roster-grid-mobile-fallback"
      className="mx-auto mt-8 max-w-md rounded-card border border-warn/40 bg-warn-soft p-6 text-center"
    >
      <h2 className="text-lg font-semibold text-warn">
        Roster Grid Editor is desktop-only
      </h2>
      <p className="mt-2 text-sm text-warn">
        The grid editor needs at least 1024px width. Use the day or
        week view on mobile.
      </p>
      <Link
        to="/schedule"
        className="mt-4 inline-block rounded-ctl bg-warn px-4 py-2 text-sm font-medium text-white hover:brightness-95 focus:outline-none focus:ring-2 focus:ring-warn"
      >
        Open calendar view
      </Link>
    </div>
  )
}

/* ------------------------------------------------------------------ */
/*  Print stylesheet (B16)                                             */
/* ------------------------------------------------------------------ */

const PRINT_CSS = `
@media print {
  @page { size: A3 landscape; margin: 10mm; }
  [data-no-print] { display: none !important; }
  body { background: white !important; color: black !important; }
  [data-testid="roster-grid"] { font-size: 9px !important; }
}
`

/* ------------------------------------------------------------------ */
/*  Page                                                               */
/* ------------------------------------------------------------------ */

export default function RosterGridPage() {
  const navigate = useNavigate()
  const { toasts, addToast, dismissToast } = useToast()

  const [windowStart, setWindowStart] = useState<Date>(() =>
    startOfISOWeek(new Date()),
  )

  const visibleWindow = useMemo(
    () => ({ start: windowStart, end: addDays(windowStart, 13) }),
    [windowStart],
  )

  const [isDesktop, setIsDesktop] = useState<boolean>(() => {
    if (typeof window === 'undefined' || !window.matchMedia) return true
    return window.matchMedia('(min-width: 1024px)').matches
  })

  useEffect(() => {
    if (typeof window === 'undefined' || !window.matchMedia) return
    const mql = window.matchMedia('(min-width: 1024px)')
    const handler = (e: MediaQueryListEvent) => setIsDesktop(e.matches)
    mql.addEventListener('change', handler)
    return () => mql.removeEventListener('change', handler)
  }, [])

  const goToday = () => setWindowStart(startOfISOWeek(new Date()))
  const goPrev = () => setWindowStart((prev) => addDays(prev, -14))
  const goNext = () => setWindowStart((prev) => addDays(prev, 14))

  const rangeLabel = `${formatShort(visibleWindow.start)} – ${formatShort(visibleWindow.end)}`

  const {
    staff,
    entries,
    leaveByStaffDate,
    isLoading,
    error,
    refetch,
    setEntries,
  } = useRosterGridData(visibleWindow)

  /* ------------------------------------------------------------ */
  /*  403 / module-disabled handling (B20, R21)                    */
  /* ------------------------------------------------------------ */

  const [moduleDisabled, setModuleDisabled] = useState(false)
  useEffect(() => {
    if (!error) return
    // The hook stores a generic "Failed to load roster" string. We
    // can't distinguish the original status code here, but we can
    // re-check the page-level interceptor pattern: 403 + module key →
    // disabled state. We treat any error here as a soft warning.
  }, [error])

  /* ------------------------------------------------------------ */
  /*  Filters (B17)                                                */
  /* ------------------------------------------------------------ */

  const [branchFilter, setBranchFilter] = useState<string | null>(null)
  const [positionFilter, setPositionFilter] = useState<string | null>(null)

  const filteredStaff = useMemo(
    () => applyStaffFilters(staff, branchFilter, positionFilter),
    [staff, branchFilter, positionFilter],
  )

  /**
   * IDs of staff whose hours are fixed (read-only on the grid). Used to
   * exclude them from paint / apply-template bulk operations so a fixed
   * staff member's roster is never mutated from here.
   */
  const fixedStaffIds = useMemo(() => {
    const set = new Set<string>()
    for (const s of filteredStaff) {
      if (isFixedArrangement(s)) set.add(s.id)
    }
    return set
  }, [filteredStaff])

  /* ------------------------------------------------------------ */
  /*  Template palette + paint mode (B8, B9)                       */
  /* ------------------------------------------------------------ */

  const [selectedTemplate, setSelectedTemplate] =
    useState<ShiftTemplateResponse | null>(null)
  const paintMode = !!selectedTemplate

  /* ------------------------------------------------------------ */
  /*  Leave paint mode (mark leave by clicking a day)              */
  /* ------------------------------------------------------------ */

  const [selectedLeaveType, setSelectedLeaveType] = useState<LeaveType | null>(
    null,
  )
  const leaveMode = !!selectedLeaveType
  const [cursorPos, setCursorPos] = useState<{ x: number; y: number } | null>(
    null,
  )
  const [leaveConfirm, setLeaveConfirm] = useState<{
    staffId: string
    date: Date
  } | null>(null)
  const [leaveSubmitting, setLeaveSubmitting] = useState(false)

  // Leave paint and template paint are mutually exclusive.
  const handleSelectLeaveType = useCallback((lt: LeaveType | null) => {
    setSelectedLeaveType(lt)
    if (lt) setSelectedTemplate(null)
  }, [])
  const handleSelectTemplate = useCallback((t: ShiftTemplateResponse | null) => {
    setSelectedTemplate(t)
    if (t) setSelectedLeaveType(null)
  }, [])

  // While in leave mode, keep the selected leave type "stuck" to the cursor.
  useEffect(() => {
    if (!leaveMode) {
      setCursorPos(null)
      return
    }
    const onMove = (e: MouseEvent) => setCursorPos({ x: e.clientX, y: e.clientY })
    window.addEventListener('mousemove', onMove)
    return () => window.removeEventListener('mousemove', onMove)
  }, [leaveMode])

  /* ------------------------------------------------------------ */
  /*  Multi-select rows + columns (B10)                            */
  /* ------------------------------------------------------------ */

  const [selectedStaff, setSelectedStaff] = useState<Set<string>>(new Set())
  const [selectedDays, setSelectedDays] = useState<Set<string>>(new Set())

  /* ------------------------------------------------------------ */
  /*  Modal state (B6)                                             */
  /* ------------------------------------------------------------ */

  const [modalOpen, setModalOpen] = useState(false)
  const [editingEntry, setEditingEntry] = useState<LegacyScheduleEntry | null>(
    null,
  )
  const [modalDefaults, setModalDefaults] = useState<{
    staff_id?: string
    start_time?: string
    end_time?: string
    entry_type?: string
  } | null>(null)

  /* Cell disambiguation popover (B6) */
  const [popover, setPopover] = useState<{
    entries: ScheduleEntryResponse[]
    anchor: { x: number; y: number }
    staffId: string
    date: Date
  } | null>(null)

  /* ------------------------------------------------------------ */
  /*  Focused cell + selection rectangle (B13)                     */
  /* ------------------------------------------------------------ */

  const [focusedCell, setFocusedCell] = useState<{ row: number; col: number } | null>(
    { row: 0, col: 0 },
  )
  const [selectionAnchor, setSelectionAnchor] = useState<{
    row: number
    col: number
  } | null>({ row: 0, col: 0 })

  /* ------------------------------------------------------------ */
  /*  Conflict banner (B14)                                        */
  /* ------------------------------------------------------------ */

  const [conflictBanner, setConflictBanner] = useState<ConflictBannerEntry[]>(
    [],
  )

  const conflictCellSet = useMemo(() => {
    const out = new Set<string>()
    for (const c of conflictBanner) {
      const sid = c.conflict.attempted.staff_id ?? ''
      if (!sid) continue
      out.add(`${sid}|${c.date}`)
    }
    return out
  }, [conflictBanner])

  /* ------------------------------------------------------------ */
  /*  Optimistic placeholders / saving state (B12, B20)            */
  /* ------------------------------------------------------------ */

  const [savingEntryIds, setSavingEntryIds] = useState<Set<string>>(new Set())
  const [bulkInFlight, setBulkInFlight] = useState(false)

  /* ------------------------------------------------------------ */
  /*  Cell clipboard (B12)                                         */
  /* ------------------------------------------------------------ */

  const clipboardRef = useRef<ClipboardItem[]>([])

  /* ------------------------------------------------------------ */
  /*  Copy-week modal (B11)                                        */
  /* ------------------------------------------------------------ */

  const [copyWeekOpen, setCopyWeekOpen] = useState(false)

  /* ------------------------------------------------------------ */
  /*  Leave-overlap confirmation (B9 alt+leave)                    */
  /* ------------------------------------------------------------ */

  const [leaveOverlap, setLeaveOverlap] = useState<{
    cells: ResolvedCell[]
    leaveCount: number
  } | null>(null)

  /* ------------------------------------------------------------ */
  /*  Helpers                                                      */
  /* ------------------------------------------------------------ */

  /** Build pre-filled defaults for create-mode modal (B6). */
  const buildModalDefaultsForCell = useCallback(
    (staffId: string, date: Date) => {
      const staffMember = filteredStaff.find((s) => s.id === staffId)
      const dayKey = getDayKey(date)
      const avail = staffMember?.availability_schedule?.[dayKey]
      const startTimeStr = avail?.start ?? '09:00'
      const endTimeStr = avail?.end ?? '17:00'
      const startIso = combineDateAndTime(date, startTimeStr) ?? ''
      const endIso = combineDateAndTime(date, endTimeStr) ?? ''
      const start = startIso ? toDatetimeLocal(new Date(startIso)) : ''
      const end = endIso ? toDatetimeLocal(new Date(endIso)) : ''
      return {
        staff_id: staffId,
        start_time: start,
        end_time: end,
        entry_type: 'job',
      }
    },
    [filteredStaff],
  )

  /** Open modal in create mode with the given defaults. */
  const openCreateModal = useCallback(
    (staffId: string, date: Date) => {
      setEditingEntry(null)
      setModalDefaults(buildModalDefaultsForCell(staffId, date))
      setModalOpen(true)
    },
    [buildModalDefaultsForCell],
  )

  /** Open modal in edit mode for a specific entry. */
  const openEditModal = useCallback((entry: ScheduleEntryResponse) => {
    setEditingEntry({
      id: entry.id,
      staff_id: entry.staff_id ?? null,
      job_id: entry.job_id ?? null,
      booking_id: entry.booking_id ?? null,
      title: entry.title ?? null,
      description: entry.description ?? null,
      start_time: entry.start_time,
      end_time: entry.end_time,
      entry_type: entry.entry_type,
      status: entry.status,
      recurrence_group_id: entry.recurrence_group_id ?? null,
    })
    setModalDefaults(null)
    setModalOpen(true)
  }, [])

  /**
   * Fixed-hours staff are read-only on the grid. When the admin tries to
   * interact with such a row (click, keyboard create/delete, paint, apply),
   * surface a clear message directing them to change the working arrangement
   * under Staff — that's the only place fixed hours can be changed.
   */
  const notifyFixedLocked = useCallback(
    (staffMember: RosterStaffMember) => {
      addToast('info', fixedHoursEditMessage(staffMember), 7000)
    },
    [addToast],
  )

  /* B6 — single-cell click router. */
  const handleCellClick = useCallback(
    (
      staffId: string,
      date: Date,
      cellEntries: ScheduleEntryResponse[],
      anchor: { x: number; y: number },
    ) => {
      // In paint mode, clicks are part of paint capture — the grid
      // suppresses onClick already; this is a defensive guard.
      if (paintMode) return
      // In leave-paint mode, a click on any cell opens the mark-leave
      // confirmation for that staff member + day.
      if (leaveMode && selectedLeaveType) {
        setLeaveConfirm({ staffId, date })
        return
      }
      if (cellEntries.length === 0) {
        openCreateModal(staffId, date)
      } else if (cellEntries.length === 1) {
        openEditModal(cellEntries[0])
      } else {
        setPopover({ entries: cellEntries, anchor, staffId, date })
      }
    },
    [openCreateModal, openEditModal, paintMode, leaveMode, selectedLeaveType],
  )

  /* Leave confirmation → mark-day-leave API call. */
  const handleConfirmLeave = useCallback(async () => {
    if (!leaveConfirm || !selectedLeaveType) return
    setLeaveSubmitting(true)
    try {
      const res = await markDayLeave({
        staff_id: leaveConfirm.staffId,
        leave_type_id: selectedLeaveType.id,
        date: toIsoDate(leaveConfirm.date),
        publish_to_open_shifts: true,
      })
      const sm = filteredStaff.find((s) => s.id === leaveConfirm.staffId)
      const name =
        sm?.name ??
        `${sm?.first_name ?? ''} ${sm?.last_name ?? ''}`.trim() ??
        'Staff'
      addToast(
        'success',
        res.displaced_shift_count > 0
          ? `${name} marked ${selectedLeaveType.name} — ${res.displaced_shift_count} shift(s) sent to Open Shifts.`
          : `${name} marked ${selectedLeaveType.name}.`,
      )
      // Optimistic: drop the displaced shift(s) from that staff member's
      // day so the cell updates instantly, then refetch to pull in the
      // approved-leave overlay (server-derived).
      const dayKey = toIsoDate(leaveConfirm.date)
      setEntries((prev) =>
        prev.filter(
          (e) =>
            !(
              e.staff_id === leaveConfirm.staffId &&
              toIsoDate(new Date(e.start_time)) === dayKey
            ),
        ),
      )
      setLeaveConfirm(null)
      // Re-fetch in place so the leave overlay appears (no page reload).
      refetch()
    } catch (err: unknown) {
      const detail = (
        err as { response?: { data?: { detail?: unknown } } }
      )?.response?.data?.detail
      addToast(
        'error',
        typeof detail === 'string'
          ? detail
          : 'Failed to mark leave. Please try again.',
      )
    } finally {
      setLeaveSubmitting(false)
    }
  }, [leaveConfirm, selectedLeaveType, filteredStaff, addToast, refetch, setEntries])

  /* B6 — modal save / delete callbacks mutate the cache. */
  const handleModalSave = useCallback(() => {
    setModalOpen(false)
    setEditingEntry(null)
    setModalDefaults(null)
    // Re-fetch the window's data in place (create / edit / delete from the
    // modal). This updates the grid cells reactively without a full page
    // reload. NOTE: do NOT "bump" windowStart with a same-instant Date — the
    // data hook keys its effect on the ISO strings, so an identical value
    // would be a no-op and nothing would refresh.
    refetch()
  }, [refetch])

  /* ------------------------------------------------------------ */
  /*  Bulk create wrapper (B9, B10, B11, B12, B20)                 */
  /* ------------------------------------------------------------ */

  const submitBulk = useCallback(
    async (
      payload: ScheduleEntryCreate[],
      placeholderIds: string[],
    ): Promise<{ created: ScheduleEntryResponse[]; conflicts: BulkConflictItem[] } | null> => {
      if (payload.length === 0) return { created: [], conflicts: [] }
      setBulkInFlight(true)
      try {
        const res = await bulkCreate({ entries: payload })

        // Replace placeholders with created entries; remove the rest.
        setEntries((prev) => {
          const placeholderSet = new Set(placeholderIds)
          const withoutPlaceholders = prev.filter(
            (e) => !placeholderSet.has(e.id),
          )
          return [...withoutPlaceholders, ...(res.created ?? [])]
        })

        if ((res.conflicts ?? []).length > 0) {
          // Build banner rows.
          const staffNameById = new Map<string, string>()
          for (const s of filteredStaff) {
            staffNameById.set(
              s.id,
              s.name ?? `${s.first_name ?? ''} ${s.last_name ?? ''}`.trim(),
            )
          }
          const banner: ConflictBannerEntry[] = (res.conflicts ?? []).map(
            (c) => ({
              conflict: c,
              staff_name:
                staffNameById.get(c.attempted.staff_id ?? '') ?? 'Unknown',
              date: toIsoDate(new Date(c.attempted.start_time)),
            }),
          )
          setConflictBanner(banner)
        }
        return res
      } catch (err: unknown) {
        const e = err as
          | {
              code?: string
              name?: string
              response?: {
                status?: number
                data?: { detail?: unknown; module?: string }
              }
            }
          | undefined
        const isAbort =
          e?.code === 'ERR_CANCELED' ||
          e?.name === 'CanceledError' ||
          e?.name === 'AbortError'
        if (isAbort) {
          // Silent — drop placeholders.
          setEntries((prev) =>
            prev.filter((p) => !placeholderIds.includes(p.id)),
          )
          return null
        }
        const status = e?.response?.status
        if (status === 403) {
          if (e?.response?.data?.module === 'scheduling') {
            setModuleDisabled(true)
          } else {
            navigate('/dashboard')
          }
        } else if (status === 422) {
          const detail = e?.response?.data?.detail
          const msg =
            typeof detail === 'string'
              ? detail
              : Array.isArray(detail) && detail[0] && typeof detail[0] === 'object'
                ? (detail[0] as { msg?: string }).msg ?? 'Validation error'
                : 'Validation error'
          addToast('error', msg)
        } else {
          addToast('error', 'Failed to save shifts. Please try again.')
        }
        // Remove placeholders on failure (R12.4).
        setEntries((prev) =>
          prev.filter((p) => !placeholderIds.includes(p.id)),
        )
        return null
      } finally {
        setBulkInFlight(false)
        setSavingEntryIds(new Set())
      }
    },
    [addToast, filteredStaff, navigate, setEntries],
  )

  /* ------------------------------------------------------------ */
  /*  Paint commit (B9)                                            */
  /* ------------------------------------------------------------ */

  const finalisePaint = useCallback(
    (resolved: ResolvedCell[]) => {
      if (!selectedTemplate) return
      const filtered = paintIdempotenceFilter(
        resolved,
        entries,
        selectedTemplate,
      )
      if (filtered.length === 0) return
      if (filtered.length > BULK_CELL_CAP) {
        addToast(
          'warning',
          'Maximum 200 cells per paint action. Reduce the rectangle and try again.',
        )
        return
      }
      const payload = buildEntriesForTemplate(filtered, selectedTemplate)
      const placeholders: ScheduleEntryResponse[] = payload.map((p) => ({
        id: genId(),
        org_id: '',
        staff_id: p.staff_id ?? null,
        title: p.title ?? null,
        description: p.description ?? null,
        start_time: p.start_time,
        end_time: p.end_time,
        entry_type: p.entry_type,
        status: 'saving',
        notes: null,
        recurrence_group_id: null,
        created_at: new Date().toISOString(),
        updated_at: new Date().toISOString(),
      }))
      const placeholderIds = placeholders.map((p) => p.id)
      setEntries((prev) => [...prev, ...placeholders])
      setSavingEntryIds(new Set(placeholderIds))
      submitBulk(payload, placeholderIds)
    },
    [addToast, entries, selectedTemplate, setEntries, submitBulk],
  )

  const handlePaintCommit = useCallback(
    ({
      cells,
      altKey,
    }: {
      cells: Array<{ staffId: string; date: Date }>
      altKey: boolean
    }) => {
      if (!selectedTemplate || bulkInFlight) return
      // Exclude fixed-hours staff — their roster is read-only here (they
      // can only be changed via the staff working-arrangement edit).
      const hadFixed = cells.some((c) => fixedStaffIds.has(c.staffId))
      const editable = cells.filter((c) => !fixedStaffIds.has(c.staffId))
      if (hadFixed) {
        addToast(
          'info',
          "Fixed-hours staff were skipped — change their working arrangement under Staff to roster them here.",
        )
      }
      if (editable.length === 0) return
      // Filter out leave-shaded cells (R3.6, R6.8). Alt → confirmation.
      const leaveCount = editable.filter((c) =>
        leaveByStaffDate.get(c.staffId)?.has(toIsoDate(c.date)),
      ).length
      const nonLeave = editable.filter(
        (c) => !leaveByStaffDate.get(c.staffId)?.has(toIsoDate(c.date)),
      )
      const resolvedNonLeave: ResolvedCell[] = nonLeave.map((c) => ({
        staff_id: c.staffId,
        date: c.date,
      }))
      if (altKey && leaveCount > 0) {
        const allResolved: ResolvedCell[] = editable.map((c) => ({
          staff_id: c.staffId,
          date: c.date,
        }))
        setLeaveOverlap({ cells: allResolved, leaveCount })
        return
      }
      finalisePaint(resolvedNonLeave)
    },
    [addToast, bulkInFlight, fixedStaffIds, finalisePaint, leaveByStaffDate, selectedTemplate],
  )

  const handleLeaveOverlapConfirm = useCallback(() => {
    if (!leaveOverlap) return
    const cells = leaveOverlap.cells
    setLeaveOverlap(null)
    finalisePaint(cells)
  }, [finalisePaint, leaveOverlap])

  /* ------------------------------------------------------------ */
  /*  Apply template button (B10)                                  */
  /* ------------------------------------------------------------ */

  const handleApplyTemplate = useCallback(() => {
    if (!selectedTemplate || bulkInFlight) return
    const days: Date[] = []
    for (const dateKey of selectedDays) {
      const [y, m, d] = dateKey.split('-').map((p) => parseInt(p, 10))
      days.push(new Date(y, (m ?? 1) - 1, d ?? 1))
    }
    // Exclude fixed-hours staff from the multi-select apply — read-only here.
    const selectableStaff = [...selectedStaff].filter(
      (id) => !fixedStaffIds.has(id),
    )
    if (selectableStaff.length < selectedStaff.size) {
      addToast(
        'info',
        "Fixed-hours staff were skipped — change their working arrangement under Staff to roster them here.",
      )
    }
    if (selectableStaff.length === 0) {
      setSelectedStaff(new Set())
      setSelectedDays(new Set())
      return
    }
    const matrix = computeApplyMatrix(
      selectableStaff,
      days,
      selectedTemplate,
      entries,
    )
    if (matrix.exceedsCap) {
      addToast(
        'warning',
        'Maximum 200 cells per paint action. Reduce the rectangle and try again.',
      )
      return
    }
    finalisePaint(matrix.cells)
    setSelectedStaff(new Set())
    setSelectedDays(new Set())
  }, [
    addToast,
    bulkInFlight,
    entries,
    fixedStaffIds,
    finalisePaint,
    selectedDays,
    selectedStaff,
    selectedTemplate,
  ])

  /* ------------------------------------------------------------ */
  /*  Copy week (B11)                                              */
  /* ------------------------------------------------------------ */

  const week1Entries = useMemo(() => {
    const week1End = addDays(visibleWindow.start, 7)
    return entries.filter((e) => {
      const start = new Date(e.start_time)
      return start >= visibleWindow.start && start < week1End
    })
  }, [entries, visibleWindow.start])

  const week2Entries = useMemo(() => {
    const week2Start = addDays(visibleWindow.start, 7)
    const week2End = addDays(visibleWindow.start, 14)
    return entries.filter((e) => {
      const start = new Date(e.start_time)
      return start >= week2Start && start < week2End
    })
  }, [entries, visibleWindow.start])

  const handleCopyWeekConfirm = useCallback(
    async (overwrite: boolean) => {
      setCopyWeekOpen(false)
      if (bulkInFlight) return
      setBulkInFlight(true)
      try {
        const res = await copyWeek({
          source_week_start: toIsoDate(visibleWindow.start),
          target_week_start: toIsoDate(addDays(visibleWindow.start, 7)),
          overwrite_existing: overwrite,
        })
        setEntries((prev) => [...prev, ...(res.created ?? [])])
        addToast(
          'success',
          `Copied ${(res.created ?? []).length} entries, skipped ${(res.conflicts ?? []).length} due to conflicts.`,
        )
        if ((res.conflicts ?? []).length > 0) {
          const staffNameById = new Map<string, string>()
          for (const s of filteredStaff) {
            staffNameById.set(
              s.id,
              s.name ?? `${s.first_name ?? ''} ${s.last_name ?? ''}`.trim(),
            )
          }
          setConflictBanner(
            (res.conflicts ?? []).map((c) => ({
              conflict: c,
              staff_name:
                staffNameById.get(c.attempted.staff_id ?? '') ?? 'Unknown',
              date: toIsoDate(new Date(c.attempted.start_time)),
            })),
          )
        }
      } catch (err: unknown) {
        const e = err as
          | { response?: { status?: number; data?: { detail?: string } } }
          | undefined
        const status = e?.response?.status
        if (status === 422) {
          addToast('error', e?.response?.data?.detail ?? 'Validation error')
        } else {
          addToast('error', 'Failed to copy week. Please try again.')
        }
      } finally {
        setBulkInFlight(false)
      }
    },
    [addToast, bulkInFlight, filteredStaff, setEntries, visibleWindow.start],
  )

  /* ------------------------------------------------------------ */
  /*  Resize (B7)                                                  */
  /* ------------------------------------------------------------ */

  const handleResizeCommit = useCallback(
    async ({
      entry,
      newEndTime,
    }: {
      entry: ScheduleEntryResponse
      newEndTime: Date
    }) => {
      const originalEnd = entry.end_time
      const newEndIso = newEndTime.toISOString()
      if (newEndIso === originalEnd) return
      // Optimistic update.
      setEntries((prev) =>
        prev.map((e) =>
          e.id === entry.id ? { ...e, end_time: newEndIso } : e,
        ),
      )
      try {
        await apiClient.put(
          `/schedule/${entry.id}/reschedule`,
          { start_time: entry.start_time, end_time: newEndIso },
          { baseURL: '/api/v2' },
        )
      } catch (err: unknown) {
        // Revert.
        setEntries((prev) =>
          prev.map((e) =>
            e.id === entry.id ? { ...e, end_time: originalEnd } : e,
          ),
        )
        const e = err as
          | { response?: { status?: number; data?: { detail?: string; conflict_message?: string } } }
          | undefined
        const status = e?.response?.status
        if (status === 409) {
          const detail = e?.response?.data?.conflict_message ?? e?.response?.data?.detail ?? ''
          addToast(
            'warning',
            detail
              ? `Conflicts with "${detail}"`
              : `Conflicts with another entry`,
          )
        } else if (status === 422) {
          addToast('error', e?.response?.data?.detail ?? 'Validation error')
        } else {
          addToast('error', 'Failed to resize entry')
        }
      }
    },
    [addToast, setEntries],
  )

  /* ------------------------------------------------------------ */
  /*  Keyboard navigation (B13) + clipboard (B12)                  */
  /* ------------------------------------------------------------ */

  const rowsCount = filteredStaff.length
  const colsCount = 14

  const handleGridKeyDown = useCallback(
    async (e: KeyboardEvent) => {
      const grid = document.querySelector('[role="grid"]')
      if (!grid) return
      const activeIsInGrid = !!document.activeElement?.closest('[role="grid"]')
      if (!activeIsInGrid) return

      // Arrow navigation
      if (
        e.key === 'ArrowLeft' ||
        e.key === 'ArrowRight' ||
        e.key === 'ArrowUp' ||
        e.key === 'ArrowDown'
      ) {
        if (!focusedCell) return
        e.preventDefault()
        const next = gridKeyboardReducer(
          {
            rows: rowsCount,
            cols: colsCount,
            focused: focusedCell,
            selectionAnchor: selectionAnchor ?? focusedCell,
          },
          { key: e.key as GridKeyboardKey, shift: e.shiftKey },
        )
        setFocusedCell(next.focused)
        setSelectionAnchor(next.selectionAnchor)
        return
      }

      if (e.key === 'Enter' && focusedCell) {
        e.preventDefault()
        const s = filteredStaff[focusedCell.row]
        if (!s) return
        if (isFixedArrangement(s)) {
          notifyFixedLocked(s)
          return
        }
        const d = (() => {
          const out = new Date(visibleWindow.start)
          out.setDate(out.getDate() + focusedCell.col)
          return out
        })()
        const dateKey = toIsoDate(d)
        const cellEntries = entries.filter((entry) => {
          if (entry.staff_id !== s.id) return false
          const start = new Date(entry.start_time)
          return toIsoDate(start) === dateKey
        })
        handleCellClick(s.id, d, cellEntries, { x: 0, y: 0 })
        return
      }

      if ((e.key === 'Delete' || e.key === 'Backspace') && focusedCell) {
        const s = filteredStaff[focusedCell.row]
        if (!s) return
        if (isFixedArrangement(s)) {
          e.preventDefault()
          notifyFixedLocked(s)
          return
        }
        const d = (() => {
          const out = new Date(visibleWindow.start)
          out.setDate(out.getDate() + focusedCell.col)
          return out
        })()
        const dateKey = toIsoDate(d)
        const cellEntries = entries.filter((entry) => {
          if (entry.staff_id !== s.id) return false
          const start = new Date(entry.start_time)
          return toIsoDate(start) === dateKey
        })
        if (cellEntries.length === 1) {
          e.preventDefault()
          const target = cellEntries[0]
          if (
            typeof window !== 'undefined' &&
            !window.confirm(`Delete "${target.title ?? target.entry_type}"?`)
          )
            return
          try {
            await apiClient.delete(`/schedule/${target.id}`, {
              baseURL: '/api/v2',
            })
            setEntries((prev) => prev.filter((p) => p.id !== target.id))
          } catch {
            addToast('error', 'Failed to delete entry')
          }
        } else if (cellEntries.length > 1) {
          e.preventDefault()
          setPopover({
            entries: cellEntries,
            anchor: { x: 200, y: 200 },
            staffId: s.id,
            date: d,
          })
        }
        return
      }

      const isCopy = (e.ctrlKey || e.metaKey) && (e.key === 'c' || e.key === 'C')
      const isPaste =
        (e.ctrlKey || e.metaKey) && (e.key === 'v' || e.key === 'V')
      if (isCopy && focusedCell) {
        const s = filteredStaff[focusedCell.row]
        const d = (() => {
          const out = new Date(visibleWindow.start)
          out.setDate(out.getDate() + focusedCell.col)
          return out
        })()
        if (!s) return
        const dateKey = toIsoDate(d)
        const cellEntries = entries.filter((entry) => {
          if (entry.staff_id !== s.id) return false
          const start = new Date(entry.start_time)
          return toIsoDate(start) === dateKey
        })
        clipboardRef.current = clipboardFromCell(cellEntries)
        if (cellEntries.length > 0) {
          addToast('info', `Copied ${cellEntries.length} entr${cellEntries.length === 1 ? 'y' : 'ies'}`)
        }
        return
      }
      if (isPaste && focusedCell && !bulkInFlight) {
        const s = filteredStaff[focusedCell.row]
        if (!s) return
        if (isFixedArrangement(s)) {
          notifyFixedLocked(s)
          return
        }
        const d = (() => {
          const out = new Date(visibleWindow.start)
          out.setDate(out.getDate() + focusedCell.col)
          return out
        })()
        const items = clipboardRef.current
        if (items.length === 0) return
        const payload = shiftClipboardToFocusCell(
          items,
          { staffIndex: focusedCell.row, staff_id: s.id, date: d },
          (rowIndex) => filteredStaff[rowIndex]?.id ?? null,
        )
        if (payload.length === 0) return
        const placeholders: ScheduleEntryResponse[] = payload.map((p) => ({
          id: genId(),
          org_id: '',
          staff_id: p.staff_id ?? null,
          title: p.title ?? null,
          description: p.description ?? null,
          start_time: p.start_time,
          end_time: p.end_time,
          entry_type: p.entry_type,
          status: 'saving',
          notes: null,
          recurrence_group_id: null,
          created_at: new Date().toISOString(),
          updated_at: new Date().toISOString(),
        }))
        const placeholderIds = placeholders.map((p) => p.id)
        setEntries((prev) => [...prev, ...placeholders])
        setSavingEntryIds(new Set(placeholderIds))
        await submitBulk(payload, placeholderIds)
      }
    },
    [
      addToast,
      bulkInFlight,
      entries,
      filteredStaff,
      focusedCell,
      handleCellClick,
      notifyFixedLocked,
      rowsCount,
      selectionAnchor,
      setEntries,
      submitBulk,
      visibleWindow.start,
    ],
  )

  useEffect(() => {
    document.addEventListener('keydown', handleGridKeyDown)
    return () => document.removeEventListener('keydown', handleGridKeyDown)
  }, [handleGridKeyDown])

  /* Escape clears multi-select sets (R7.8). */
  useEffect(() => {
    const onEsc = (e: KeyboardEvent) => {
      if (e.key !== 'Escape') return
      setSelectedStaff(new Set())
      setSelectedDays(new Set())
      if (selectedTemplate) setSelectedTemplate(null)
      if (selectedLeaveType) setSelectedLeaveType(null)
    }
    document.addEventListener('keydown', onEsc)
    return () => document.removeEventListener('keydown', onEsc)
  }, [selectedTemplate, selectedLeaveType])

  /* When focused cell becomes out of bounds (e.g. filter shrank
   * the staff list), clamp it to a safe coord. */
  useEffect(() => {
    if (!focusedCell) return
    const row = Math.min(focusedCell.row, Math.max(0, rowsCount - 1))
    const col = Math.min(focusedCell.col, colsCount - 1)
    if (row !== focusedCell.row || col !== focusedCell.col) {
      setFocusedCell({ row, col })
      setSelectionAnchor({ row, col })
    }
  }, [focusedCell, rowsCount])

  /* When focused cell changes, move DOM focus to it. */
  useEffect(() => {
    if (!focusedCell) return
    const cell = document.querySelector(
      `[role="gridcell"][data-row="${focusedCell.row}"][data-col="${focusedCell.col}"]`,
    ) as HTMLElement | null
    cell?.focus({ preventScroll: true })
  }, [focusedCell])

  /* ------------------------------------------------------------ */
  /*  CSV export (B15)                                             */
  /* ------------------------------------------------------------ */

  const handleExportCSV = useCallback(() => {
    const csv = generateRosterGridCSV(
      visibleWindow,
      filteredStaff,
      entries,
      leaveByStaffDate,
    )
    downloadRosterGridCSV(
      `roster-${toIsoDate(visibleWindow.start)}.csv`,
      csv,
    )
  }, [entries, filteredStaff, leaveByStaffDate, visibleWindow])

  const handlePrint = useCallback(() => {
    if (typeof window !== 'undefined' && typeof window.print === 'function') {
      window.print()
    }
  }, [])

  /* ------------------------------------------------------------ */
  /*  Conflict banner scroll + dismiss (B14)                       */
  /* ------------------------------------------------------------ */

  const handleConflictScroll = useCallback(
    (staffId: string, date: string) => {
      const cell = document.querySelector(
        `[role="gridcell"][data-staff-id="${staffId}"][data-date="${date}"]`,
      ) as HTMLElement | null
      if (cell) {
        cell.scrollIntoView({ block: 'center', inline: 'center' })
        cell.focus({ preventScroll: true })
      }
    },
    [],
  )

  const handleConflictDismiss = useCallback(() => {
    setConflictBanner([])
  }, [])

  /* ------------------------------------------------------------ */
  /*  Render                                                       */
  /* ------------------------------------------------------------ */

  if (!isDesktop) {
    return (
      <div className="px-4 py-6">
        <h1 className="text-xl font-semibold text-text">
          Roster Grid Editor
        </h1>
        <MobileFallback />
      </div>
    )
  }

  if (moduleDisabled) {
    return (
      <div className="mx-auto mt-12 max-w-md rounded-card border border-warn/40 bg-warn-soft p-8 text-center">
        <h2 className="text-base font-semibold text-warn">
          Scheduling module is disabled
        </h2>
        <p className="mt-2 text-sm text-warn">
          Ask your org admin to enable it.
        </p>
        <Link
          to="/settings/modules"
          className="mt-4 inline-block rounded-ctl bg-warn px-4 py-2 text-sm font-medium text-white hover:brightness-95 focus:outline-none focus:ring-2 focus:ring-warn"
        >
          Settings → Modules
        </Link>
      </div>
    )
  }

  return (
    <>
      <style>{PRINT_CSS}</style>
      <ToastContainer toasts={toasts} onDismiss={dismissToast} />
      <div className="flex h-full flex-col">
        {/* Toolbar */}
        <div
          className="flex flex-wrap items-center justify-between gap-3 border-b border-border bg-card px-4 py-3"
          data-no-print
        >
          <div className="flex items-center gap-3">
            <h1 className="text-lg font-semibold text-text">
              Roster Grid Editor
            </h1>
            <span
              className="mono text-sm text-muted"
              data-testid="visible-window-label"
            >
              {rangeLabel}
            </span>
          </div>
          <div
            className="flex flex-wrap items-center gap-2"
            role="group"
            aria-label="Roster window navigator"
          >
            <button
              type="button"
              onClick={() => {
                setEditingEntry(null)
                setModalDefaults({ entry_type: 'job' })
                setModalOpen(true)
              }}
              className="min-h-[36px] rounded-ctl bg-accent px-3 py-1.5 text-sm font-medium text-white hover:bg-accent-press focus:outline-none focus:ring-2 focus:ring-accent"
            >
              + New Entry
            </button>
            <button
              type="button"
              onClick={() => {
                setEditingEntry(null)
                setModalDefaults({ entry_type: 'leave' })
                setModalOpen(true)
              }}
              className="min-h-[36px] rounded-ctl border border-border-strong bg-canvas px-3 py-1.5 text-sm font-medium text-text hover:bg-border focus:outline-none focus:ring-2 focus:ring-accent"
            >
              + Add Leave
            </button>
            <button
              type="button"
              onClick={goToday}
              className="min-h-[36px] rounded-ctl border border-border bg-card px-3 py-1.5 text-sm font-medium text-text hover:bg-canvas hover:border-border-strong focus:outline-none focus:ring-2 focus:ring-accent"
            >
              Today
            </button>
            <button
              type="button"
              onClick={goPrev}
              aria-label="Previous fortnight"
              className="min-h-[36px] rounded-ctl border border-border bg-card px-3 py-1.5 text-sm font-medium text-text hover:bg-canvas hover:border-border-strong focus:outline-none focus:ring-2 focus:ring-accent"
            >
              ← Prev fortnight
            </button>
            <button
              type="button"
              onClick={goNext}
              aria-label="Next fortnight"
              className="min-h-[36px] rounded-ctl border border-border bg-card px-3 py-1.5 text-sm font-medium text-text hover:bg-canvas hover:border-border-strong focus:outline-none focus:ring-2 focus:ring-accent"
            >
              Next fortnight →
            </button>
            <button
              type="button"
              onClick={() => setCopyWeekOpen(true)}
              disabled={bulkInFlight}
              className="min-h-[36px] rounded-ctl border border-border bg-card px-3 py-1.5 text-sm font-medium text-text hover:bg-canvas hover:border-border-strong focus:outline-none focus:ring-2 focus:ring-accent disabled:opacity-60"
            >
              Copy Week 1 → Week 2
            </button>
            {selectedStaff.size > 0 &&
              selectedDays.size > 0 &&
              selectedTemplate && (
                <button
                  type="button"
                  onClick={handleApplyTemplate}
                  disabled={bulkInFlight}
                  className="min-h-[36px] rounded-ctl bg-accent px-3 py-1.5 text-sm font-medium text-white hover:bg-accent-press focus:outline-none focus:ring-2 focus:ring-accent disabled:opacity-60"
                  data-testid="apply-template-button"
                >
                  Apply template ({selectedStaff.size} × {selectedDays.size})
                </button>
              )}
            <button
              type="button"
              onClick={handleExportCSV}
              className="min-h-[36px] rounded-ctl border border-border bg-card px-3 py-1.5 text-sm font-medium text-text hover:bg-canvas hover:border-border-strong focus:outline-none focus:ring-2 focus:ring-accent"
            >
              Export CSV
            </button>
            <button
              type="button"
              onClick={handlePrint}
              className="min-h-[36px] rounded-ctl border border-border bg-card px-3 py-1.5 text-sm font-medium text-text hover:bg-canvas hover:border-border-strong focus:outline-none focus:ring-2 focus:ring-accent"
            >
              Print
            </button>
          </div>
        </div>

        {/* Filters row */}
        <div
          className="flex items-center gap-4 border-b border-border bg-canvas px-4 py-2"
          data-no-print
        >
          <RosterGridFilters
            staff={staff}
            branchFilter={branchFilter}
            setBranchFilter={setBranchFilter}
            positionFilter={positionFilter}
            setPositionFilter={setPositionFilter}
          />
        </div>

        {error && (
          <div className="border-b border-danger/30 bg-danger-soft px-4 py-2 text-sm text-danger">
            {error}
          </div>
        )}

        <ConflictBanner
          conflicts={conflictBanner}
          onScrollToCell={handleConflictScroll}
          onDismiss={handleConflictDismiss}
        />

        {/* Body: palette + grid */}
        <div className="flex flex-1 overflow-hidden">
          <div
            className="flex w-60 shrink-0 flex-col gap-3 overflow-auto p-2"
            data-no-print
          >
            <TemplatePalette
              selectedTemplate={selectedTemplate}
              onSelect={handleSelectTemplate}
              disabled={bulkInFlight || leaveSubmitting}
            />
            <LeaveTypePalette
              selectedLeaveType={selectedLeaveType}
              onSelect={handleSelectLeaveType}
              disabled={bulkInFlight || leaveSubmitting}
            />
          </div>
          <div className="flex-1 overflow-auto bg-canvas p-2">
            <RosterGrid
              staff={filteredStaff}
              entries={entries}
              leaveByStaffDate={leaveByStaffDate}
              visibleWindow={visibleWindow}
              isLoading={isLoading}
              onCellClick={handleCellClick}
              onLockedInteraction={notifyFixedLocked}
              paintMode={paintMode}
              leaveMode={leaveMode}
              selectedTemplate={selectedTemplate}
              onPaintCommit={handlePaintCommit}
              onPaintCancel={() => setSelectedTemplate(null)}
              selectedStaff={selectedStaff}
              setSelectedStaff={setSelectedStaff}
              selectedDays={selectedDays}
              setSelectedDays={setSelectedDays}
              focusedCell={focusedCell}
              setFocusedCell={(c) => {
                setFocusedCell(c)
                setSelectionAnchor(c)
              }}
              selectionAnchor={selectionAnchor}
              onResizeCommit={handleResizeCommit}
              conflictCells={conflictCellSet}
              savingEntryIds={savingEntryIds}
              ariaBusy={bulkInFlight}
            />
          </div>
        </div>
      </div>

      {/* Leave type "stuck to cursor" indicator (leave paint mode) */}
      {leaveMode && selectedLeaveType && cursorPos && !leaveConfirm && (
        <div
          className="pointer-events-none fixed z-[60]"
          style={{ left: cursorPos.x + 14, top: cursorPos.y + 14 }}
        >
          <span className="inline-flex items-center gap-1.5 rounded-full border border-accent bg-card px-2 py-1 text-[11px] font-medium text-text shadow-pop">
            <span
              className={`h-2.5 w-2.5 rounded-full ${leaveSwatch(
                selectedLeaveType.code || selectedLeaveType.id,
              )}`}
            />
            {selectedLeaveType.name}
          </span>
        </div>
      )}

      {/* Mark-leave confirmation */}
      <Modal
        open={!!leaveConfirm}
        onClose={() => {
          if (!leaveSubmitting) setLeaveConfirm(null)
        }}
        title="Mark leave"
        className="max-w-md"
      >
        {leaveConfirm && selectedLeaveType && (
          <div className="space-y-4">
            <p className="text-sm text-text">
              Mark{' '}
              <span className="font-semibold">
                {(() => {
                  const sm = filteredStaff.find(
                    (s) => s.id === leaveConfirm.staffId,
                  )
                  return (
                    sm?.name ??
                    `${sm?.first_name ?? ''} ${sm?.last_name ?? ''}`.trim() ??
                    'this staff member'
                  )
                })()}
              </span>{' '}
              as{' '}
              <span className="font-semibold">{selectedLeaveType.name}</span> on{' '}
              <span className="font-semibold">
                {formatShort(leaveConfirm.date)}
              </span>
              ?
            </p>
            <p className="text-xs text-muted">
              Their shift that day will be published to Open Shifts so it can be
              covered.
            </p>
            <div className="flex items-center justify-end gap-3">
              <button
                type="button"
                onClick={() => setLeaveConfirm(null)}
                disabled={leaveSubmitting}
                className="rounded-ctl border border-border bg-card px-4 py-2 text-sm font-medium text-text hover:bg-canvas disabled:opacity-50 focus:outline-none focus-visible:ring-2 focus-visible:ring-accent"
              >
                Cancel
              </button>
              <button
                type="button"
                onClick={handleConfirmLeave}
                disabled={leaveSubmitting}
                className="rounded-ctl bg-accent px-4 py-2 text-sm font-medium text-white hover:bg-accent-press disabled:opacity-50 focus:outline-none focus-visible:ring-2 focus-visible:ring-accent"
              >
                {leaveSubmitting ? 'Marking…' : 'Confirm'}
              </button>
            </div>
          </div>
        )}
      </Modal>

      {popover && (
        <CellDisambiguationPopover
          entries={popover.entries}
          anchor={popover.anchor}
          onClose={() => setPopover(null)}
          onPick={(entry) => {
            setPopover(null)
            openEditModal(entry)
          }}
        />
      )}

      <ScheduleEntryModal
        open={modalOpen}
        onClose={() => {
          setModalOpen(false)
          setEditingEntry(null)
          setModalDefaults(null)
        }}
        onSave={handleModalSave}
        entry={editingEntry ?? undefined}
        defaultValues={modalDefaults ?? undefined}
      />

      <CopyWeekConfirmModal
        open={copyWeekOpen}
        sourceCount={week1Entries.length}
        targetCount={week2Entries.length}
        onConfirm={handleCopyWeekConfirm}
        onClose={() => setCopyWeekOpen(false)}
      />

      {leaveOverlap && (
        <LeaveOverlapConfirmationModal
          open={true}
          cellCount={leaveOverlap.leaveCount}
          onConfirm={handleLeaveOverlapConfirm}
          onClose={() => setLeaveOverlap(null)}
        />
      )}
    </>
  )
}
