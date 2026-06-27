import { useCallback, useEffect, useState } from 'react'
import { useNavigate, useSearchParams } from 'react-router-dom'
import apiClient from '@/api/client'
import ClockedInTab from './ClockedInTab'
import AttendanceTab from './AttendanceTab'
import PayRunsTab from './PayRunsTab'
import type { AttendanceResponse } from './types'

const TABS = ['Review Hours', 'Clocked In', 'Pay Runs'] as const

// URL <-> tab mapping so the active tab persists across reloads and can be
// deep-linked (e.g. /timesheets?tab=pay-runs from the Payroll console).
const TAB_TO_SLUG: Record<(typeof TABS)[number], string> = {
  'Review Hours': 'review',
  'Clocked In': 'clocked-in',
  'Pay Runs': 'pay-runs',
}
// Backward-compatible: old deep-links (?tab=attendance / ?tab=timesheets) still
// resolve sensibly now that review lives on one tab and pay on another.
const SLUG_TO_TAB: Record<string, (typeof TABS)[number]> = {
  review: 'Review Hours',
  attendance: 'Review Hours',
  'clocked-in': 'Clocked In',
  timesheets: 'Pay Runs',
  'pay-runs': 'Pay Runs',
}

/** Local date as YYYY-MM-DD. */
function localISO(d: Date): string {
  const tz = d.getTimezoneOffset() * 60000
  return new Date(d.getTime() - tz).toISOString().split('T')[0]
}

/** Monday (start) and Sunday (end) of the week containing `d`. */
function weekBounds(d: Date): { start: string; end: string } {
  const day = d.getDay()
  const mondayOffset = day === 0 ? -6 : 1 - day
  const monday = new Date(d)
  monday.setDate(d.getDate() + mondayOffset)
  const sunday = new Date(monday)
  sunday.setDate(monday.getDate() + 6)
  return { start: localISO(monday), end: localISO(sunday) }
}

function fmtHours(hours: number): string {
  const totalMin = Math.round((hours || 0) * 60)
  const h = Math.floor(totalMin / 60)
  const m = totalMin % 60
  if (h === 0 && m === 0) return '0h'
  return `${h}h${m ? ` ${m}m` : ''}`
}

export default function TimesheetsPage() {
  const [searchParams, setSearchParams] = useSearchParams()
  const activeTab: (typeof TABS)[number] = SLUG_TO_TAB[searchParams.get('tab') ?? ''] ?? 'Review Hours'
  const setActiveTab = useCallback(
    (tab: (typeof TABS)[number]) => {
      setSearchParams(
        (prev) => {
          const next = new URLSearchParams(prev)
          next.set('tab', TAB_TO_SLUG[tab])
          return next
        },
        { replace: true },
      )
    },
    [setSearchParams],
  )
  const navigate = useNavigate()

  // Header summary — sourced from the live clocked-in endpoint + this week's
  // attendance summary (the weekly review is the source of truth now).
  const [clockedInCount, setClockedInCount] = useState(0)
  const [pendingReview, setPendingReview] = useState(0)
  const [hoursThisWeek, setHoursThisWeek] = useState(0)
  const [staffThisWeek, setStaffThisWeek] = useState(0)

  useEffect(() => {
    const controller = new AbortController()
    apiClient
      .get<{ items: unknown[]; total: number }>('/api/v2/time-clock/clocked-in', { signal: controller.signal })
      .then((res) => setClockedInCount(res.data?.total ?? res.data?.items?.length ?? 0))
      .catch(() => {})

    const { start, end } = weekBounds(new Date())
    apiClient
      .get<AttendanceResponse>('/api/v2/timesheets/attendance', {
        params: { start, end },
        signal: controller.signal,
      })
      .then((res) => {
        const s = res.data?.summary
        setPendingReview(s?.pending_review_count ?? 0)
        setHoursThisWeek(Number(s?.total_worked_hours) || 0)
        setStaffThisWeek(s?.total_staff ?? 0)
      })
      .catch(() => {})

    return () => controller.abort()
  }, [])

  return (
    <div className="page page-wide">
    <div className="space-y-6">
      {/* Page header */}
      <div className="page-head">
        <div>
          <div className="eyebrow">Staff</div>
          <h1>Staff Timesheets</h1>
          <p className="sub">
            Review hours weekly, then run payroll on each staff member's cycle
          </p>
        </div>
        <div className="flex items-center gap-2">
          <button
            onClick={() => navigate('/timesheets/settings')}
            className="inline-flex h-10 items-center gap-2 rounded-ctl border border-border bg-card px-3.5 text-[13.5px] font-medium text-text hover:bg-canvas dark:hover:bg-canvas"
          >
            <svg className="h-4 w-4 text-muted-2" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={2}>
              <path strokeLinecap="round" strokeLinejoin="round" d="M10.325 4.317c.426-1.756 2.924-1.756 3.35 0a1.724 1.724 0 002.573 1.066c1.543-.94 3.31.826 2.37 2.37a1.724 1.724 0 001.066 2.573c1.756.426 1.756 2.924 0 3.35a1.724 1.724 0 00-1.066 2.573c.94 1.543-.826 3.31-2.37 2.37a1.724 1.724 0 00-2.573 1.066c-.426 1.756-2.924 1.756-3.35 0a1.724 1.724 0 00-2.573-1.066c-1.543.94-3.31-.826-2.37-2.37a1.724 1.724 0 00-1.066-2.573c-1.756-.426-1.756-2.924 0-3.35a1.724 1.724 0 001.066-2.573c-.94-1.543.826-3.31 2.37-2.37.996.608 2.296.07 2.572-1.065z" />
              <path strokeLinecap="round" strokeLinejoin="round" d="M15 12a3 3 0 11-6 0 3 3 0 016 0z" />
            </svg>
            Settings
          </button>
        </div>
      </div>

      {/* Summary cards — this week */}
      <div className="grid grid-cols-2 gap-4 lg:grid-cols-4">
        <div className="rounded-card border border-border bg-card p-4 shadow-card">
          <div className="flex items-center justify-between">
            <p className="text-xs font-medium uppercase tracking-wide text-muted">Clocked In</p>
            <div className="rounded-full bg-accent/10 p-1.5">
              <svg className="h-3.5 w-3.5 text-accent" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={2}>
                <path strokeLinecap="round" strokeLinejoin="round" d="M12 6v6h4.5m4.5 0a9 9 0 11-18 0 9 9 0 0118 0z" />
              </svg>
            </div>
          </div>
          <p className="mt-2 text-2xl font-bold text-text">{clockedInCount}</p>
          <p className="mt-0.5 text-xs text-muted">staff right now</p>
        </div>
        <div className="rounded-card border border-border bg-card p-4 shadow-card">
          <div className="flex items-center justify-between">
            <p className="text-xs font-medium uppercase tracking-wide text-muted">Pending Review</p>
            <div className="rounded-full bg-warning/10 p-1.5">
              <svg className="h-3.5 w-3.5 text-warning" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={2}>
                <path strokeLinecap="round" strokeLinejoin="round" d="M12 9v3.75m9-.75a9 9 0 11-18 0 9 9 0 0118 0zm-9 3.75h.008v.008H12v-.008z" />
              </svg>
            </div>
          </div>
          <p className={`mt-2 text-2xl font-bold ${pendingReview > 0 ? 'text-warning' : 'text-success'}`}>{pendingReview}</p>
          <p className="mt-0.5 text-xs text-muted">shifts to approve this week</p>
        </div>
        <div className="rounded-card border border-border bg-card p-4 shadow-card">
          <div className="flex items-center justify-between">
            <p className="text-xs font-medium uppercase tracking-wide text-muted">Hours Worked</p>
            <div className="rounded-full bg-muted/10 p-1.5">
              <svg className="h-3.5 w-3.5 text-muted" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={2}>
                <path strokeLinecap="round" strokeLinejoin="round" d="M12 6v6l4 2" />
                <circle cx="12" cy="12" r="9" />
              </svg>
            </div>
          </div>
          <p className="mt-2 text-2xl font-bold text-text">{fmtHours(hoursThisWeek)}</p>
          <p className="mt-0.5 text-xs text-muted">this week</p>
        </div>
        <div className="rounded-card border border-border bg-card p-4 shadow-card">
          <div className="flex items-center justify-between">
            <p className="text-xs font-medium uppercase tracking-wide text-muted">Staff</p>
            <div className="rounded-full bg-accent/10 p-1.5">
              <svg className="h-3.5 w-3.5 text-accent" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={2}>
                <path strokeLinecap="round" strokeLinejoin="round" d="M15 19.128a9.38 9.38 0 002.625.372 9.337 9.337 0 004.121-.952 4.125 4.125 0 00-7.533-2.493M15 19.128v-.003c0-1.113-.285-2.16-.786-3.07M15 19.128v.106A12.318 12.318 0 018.624 21c-2.331 0-4.512-.645-6.374-1.766l-.001-.109a6.375 6.375 0 0111.964-3.07M12 6.375a3.375 3.375 0 11-6.75 0 3.375 3.375 0 016.75 0zm8.25 2.25a2.625 2.625 0 11-5.25 0 2.625 2.625 0 015.25 0z" />
              </svg>
            </div>
          </div>
          <p className="mt-2 text-2xl font-bold text-text">{staffThisWeek}</p>
          <p className="mt-0.5 text-xs text-muted">worked this week</p>
        </div>
      </div>

      {/* Tab switcher */}
      <div className="rounded-card border border-border bg-card shadow-card">
        <div className="border-b border-border px-4">
          <nav className="flex gap-6">
            {TABS.map((tab) => (
              <button
                key={tab}
                onClick={() => setActiveTab(tab)}
                className={`relative py-3 text-sm font-medium transition-colors ${
                  activeTab === tab
                    ? 'text-accent after:absolute after:bottom-0 after:left-0 after:right-0 after:h-0.5 after:bg-accent'
                    : 'text-muted hover:text-text'
                }`}
              >
                {tab}
                {tab === 'Clocked In' && clockedInCount > 0 && (
                  <span className="ml-1.5 inline-flex h-5 min-w-[20px] items-center justify-center rounded-full bg-accent/10 px-1.5 text-[10px] font-bold text-accent">
                    {clockedInCount}
                  </span>
                )}
              </button>
            ))}
          </nav>
        </div>

        {/* Tab content */}
        <div className="p-4">
          {activeTab === 'Review Hours' && <AttendanceTab />}
          {activeTab === 'Clocked In' && <ClockedInTab />}
          {activeTab === 'Pay Runs' && <PayRunsTab />}
        </div>
      </div>
    </div>
    </div>
  )
}
