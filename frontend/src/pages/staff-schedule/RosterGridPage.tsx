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
      className="mx-auto mt-8 max-w-md rounded-lg border border-amber-200 bg-amber-50 p-6 text-center"
    >
      <h2 className="text-lg font-semibold text-amber-900">
        Roster Grid Editor is desktop-only
      </h2>
      <p className="mt-2 text-sm text-amber-800">
        The grid editor needs at least 1024px width. Use the day or
        week view on mobile.
      </p>
      <Link
        to="/schedule"
        className="mt-4 inline-block rounded-md bg-amber-600 px-4 py-2 text-sm font-medium text-white hover:bg-amber-700 focus:outline-none focus:ring-2 focus:ring-amber-500"
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

  /* ------------------------------------------------------------ */
  /*  Template palette + paint mode (B8, B9)                       */
  /* ------------------------------------------------------------ */

  const [selectedTemplate, setSelectedTemplate] =
    useState<ShiftTemplateResponse | null>(null)
  const paintMode = !!selectedTemplate

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
      if (cellEntries.length === 0) {
        openCreateModal(staffId, date)
      } else if (cellEntries.length === 1) {
        openEditModal(cellEntries[0])
      } else {
        setPopover({ entries: cellEntries, anchor, staffId, date })
      }
    },
    [openCreateModal, openEditModal, paintMode],
  )

  /* B6 — modal save / delete callbacks mutate the cache. */
  const handleModalSave = useCallback(() => {
    setModalOpen(false)
    setEditingEntry(null)
    setModalDefaults(null)
    // Modal does its own POST/PUT — we refetch via mutating the cache
    // by re-issuing a list call. Easiest path: trigger a window
    // bump. We do NOT refetch the whole window because the modal
    // returns the saved id; here we keep things simple and rely on
    // the modal's existing onSave→fetchEntries upstream (calendar).
    // For the grid, we just bump the visibleWindow which retriggers
    // useRosterGridData.
    setWindowStart((d) => new Date(d))
  }, [])

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
      // Filter out leave-shaded cells (R3.6, R6.8). Alt → confirmation.
      const leaveCount = cells.filter((c) =>
        leaveByStaffDate.get(c.staffId)?.has(toIsoDate(c.date)),
      ).length
      const nonLeave = cells.filter(
        (c) => !leaveByStaffDate.get(c.staffId)?.has(toIsoDate(c.date)),
      )
      const resolvedNonLeave: ResolvedCell[] = nonLeave.map((c) => ({
        staff_id: c.staffId,
        date: c.date,
      }))
      if (altKey && leaveCount > 0) {
        const allResolved: ResolvedCell[] = cells.map((c) => ({
          staff_id: c.staffId,
          date: c.date,
        }))
        setLeaveOverlap({ cells: allResolved, leaveCount })
        return
      }
      finalisePaint(resolvedNonLeave)
    },
    [bulkInFlight, finalisePaint, leaveByStaffDate, selectedTemplate],
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
    const matrix = computeApplyMatrix(
      [...selectedStaff],
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
        handleCellClick(s.id, d, cellEntries, { x: 0, y: 0 })
        return
      }

      if ((e.key === 'Delete' || e.key === 'Backspace') && focusedCell) {
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
        const d = (() => {
          const out = new Date(visibleWindow.start)
          out.setDate(out.getDate() + focusedCell.col)
          return out
        })()
        if (!s) return
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
    }
    document.addEventListener('keydown', onEsc)
    return () => document.removeEventListener('keydown', onEsc)
  }, [selectedTemplate])

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
        <h1 className="text-xl font-semibold text-gray-900">
          Roster Grid Editor
        </h1>
        <MobileFallback />
      </div>
    )
  }

  if (moduleDisabled) {
    return (
      <div className="mx-auto mt-12 max-w-md rounded-lg border border-amber-200 bg-amber-50 p-8 text-center">
        <h2 className="text-base font-semibold text-amber-900">
          Scheduling module is disabled
        </h2>
        <p className="mt-2 text-sm text-amber-800">
          Ask your org admin to enable it.
        </p>
        <Link
          to="/settings/modules"
          className="mt-4 inline-block rounded-md bg-amber-600 px-4 py-2 text-sm font-medium text-white hover:bg-amber-700 focus:outline-none focus:ring-2 focus:ring-amber-500"
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
          className="flex flex-wrap items-center justify-between gap-3 border-b border-gray-200 bg-white px-4 py-3"
          data-no-print
        >
          <div className="flex items-center gap-3">
            <h1 className="text-lg font-semibold text-gray-900">
              Roster Grid Editor
            </h1>
            <span
              className="text-sm text-gray-600"
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
              onClick={goToday}
              className="min-h-[36px] rounded border border-gray-300 bg-white px-3 py-1.5 text-sm font-medium text-gray-700 hover:bg-gray-50 focus:outline-none focus:ring-2 focus:ring-blue-500"
            >
              Today
            </button>
            <button
              type="button"
              onClick={goPrev}
              aria-label="Previous fortnight"
              className="min-h-[36px] rounded border border-gray-300 bg-white px-3 py-1.5 text-sm font-medium text-gray-700 hover:bg-gray-50 focus:outline-none focus:ring-2 focus:ring-blue-500"
            >
              ← Prev fortnight
            </button>
            <button
              type="button"
              onClick={goNext}
              aria-label="Next fortnight"
              className="min-h-[36px] rounded border border-gray-300 bg-white px-3 py-1.5 text-sm font-medium text-gray-700 hover:bg-gray-50 focus:outline-none focus:ring-2 focus:ring-blue-500"
            >
              Next fortnight →
            </button>
            <button
              type="button"
              onClick={() => setCopyWeekOpen(true)}
              disabled={bulkInFlight}
              className="min-h-[36px] rounded border border-gray-300 bg-white px-3 py-1.5 text-sm font-medium text-gray-700 hover:bg-gray-50 focus:outline-none focus:ring-2 focus:ring-blue-500 disabled:opacity-60"
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
                  className="min-h-[36px] rounded bg-blue-600 px-3 py-1.5 text-sm font-medium text-white hover:bg-blue-700 focus:outline-none focus:ring-2 focus:ring-blue-500 disabled:opacity-60"
                  data-testid="apply-template-button"
                >
                  Apply template ({selectedStaff.size} × {selectedDays.size})
                </button>
              )}
            <button
              type="button"
              onClick={handleExportCSV}
              className="min-h-[36px] rounded border border-gray-300 bg-white px-3 py-1.5 text-sm font-medium text-gray-700 hover:bg-gray-50 focus:outline-none focus:ring-2 focus:ring-blue-500"
            >
              Export CSV
            </button>
            <button
              type="button"
              onClick={handlePrint}
              className="min-h-[36px] rounded border border-gray-300 bg-white px-3 py-1.5 text-sm font-medium text-gray-700 hover:bg-gray-50 focus:outline-none focus:ring-2 focus:ring-blue-500"
            >
              Print
            </button>
          </div>
        </div>

        {/* Filters row */}
        <div
          className="flex items-center gap-4 border-b border-gray-200 bg-gray-50 px-4 py-2"
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
          <div className="border-b border-red-200 bg-red-50 px-4 py-2 text-sm text-red-700">
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
          <TemplatePalette
            selectedTemplate={selectedTemplate}
            onSelect={setSelectedTemplate}
            disabled={bulkInFlight}
          />
          <div className="flex-1 overflow-auto bg-gray-50 p-2">
            <RosterGrid
              staff={filteredStaff}
              entries={entries}
              leaveByStaffDate={leaveByStaffDate}
              visibleWindow={visibleWindow}
              isLoading={isLoading}
              onCellClick={handleCellClick}
              paintMode={paintMode}
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
