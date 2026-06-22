import { useCallback, useEffect, useState } from 'react'
import { useNavigate, useSearchParams } from 'react-router-dom'
import apiClient from '@/api/client'
import ClockedInTab from './ClockedInTab'
import AttendanceTab from './AttendanceTab'
import TimesheetsTab from './TimesheetsTab'
import PayRunsTab from './PayRunsTab'
import type { PeriodSummary } from './types'

const TABS = ['Attendance', 'Clocked In', 'Timesheets', 'Pay Runs'] as const

// URL <-> tab mapping so the active tab persists across reloads and can be
// deep-linked (e.g. /timesheets?tab=pay-runs from the Payroll console).
const TAB_TO_SLUG: Record<(typeof TABS)[number], string> = {
  Attendance: 'attendance',
  'Clocked In': 'clocked-in',
  Timesheets: 'timesheets',
  'Pay Runs': 'pay-runs',
}
const SLUG_TO_TAB: Record<string, (typeof TABS)[number]> = {
  attendance: 'Attendance',
  'clocked-in': 'Clocked In',
  timesheets: 'Timesheets',
  'pay-runs': 'Pay Runs',
}

export default function TimesheetsPage() {
  const [searchParams, setSearchParams] = useSearchParams()
  const activeTab: (typeof TABS)[number] = SLUG_TO_TAB[searchParams.get('tab') ?? ''] ?? 'Attendance'
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

  // Summary stats from API
  const [clockedInCount, setClockedInCount] = useState(0)
  const [pendingCount, setPendingCount] = useState(0)
  const [approvedCount, setApprovedCount] = useState(0)
  const [lockedCount, setLockedCount] = useState(0)
  const [totalHours, setTotalHours] = useState(0)

  useEffect(() => {
    const controller = new AbortController()
    // Use EXISTING time-clock endpoint that returns real data
    apiClient.get<{ items: any[]; total: number }>('/api/v2/time-clock/clocked-in', { signal: controller.signal })
      .then(res => setClockedInCount(res.data?.total ?? res.data?.items?.length ?? 0))
      .catch(() => {})

    return () => controller.abort()
  }, [])

  // Callback for TimesheetsTab to push period_summary up
  const handlePeriodSummary = useCallback((summary: PeriodSummary) => {
    setPendingCount(summary?.pending_count ?? 0)
    setApprovedCount(summary?.approved_count ?? 0)
    setLockedCount(summary?.locked_count ?? 0)
    const ordinary = Number(summary?.total_ordinary_hours) || 0
    const overtime = Number(summary?.total_overtime_hours) || 0
    const publicHoliday = Number(summary?.total_public_holiday_hours) || 0
    setTotalHours(ordinary + overtime + publicHoliday)
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
            Track work hours, manage approvals, and run payroll
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

      {/* Summary cards */}
      <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-5">
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
            <p className="text-xs font-medium uppercase tracking-wide text-muted">Pending Approval</p>
            <div className="rounded-full bg-warning/10 p-1.5">
              <svg className="h-3.5 w-3.5 text-warning" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={2}>
                <path strokeLinecap="round" strokeLinejoin="round" d="M12 9v3.75m9-.75a9 9 0 11-18 0 9 9 0 0118 0zm-9 3.75h.008v.008H12v-.008z" />
              </svg>
            </div>
          </div>
          <p className="mt-2 text-2xl font-bold text-warning">{pendingCount}</p>
          <p className="mt-0.5 text-xs text-muted">timesheets this period</p>
        </div>
        <div className="rounded-card border border-border bg-card p-4 shadow-card">
          <div className="flex items-center justify-between">
            <p className="text-xs font-medium uppercase tracking-wide text-muted">Approved</p>
            <div className="rounded-full bg-success/10 p-1.5">
              <svg className="h-3.5 w-3.5 text-success" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={2}>
                <path strokeLinecap="round" strokeLinejoin="round" d="M9 12.75L11.25 15 15 9.75M21 12a9 9 0 11-18 0 9 9 0 0118 0z" />
              </svg>
            </div>
          </div>
          <p className="mt-2 text-2xl font-bold text-success">{approvedCount}</p>
          <p className="mt-0.5 text-xs text-muted">ready to lock</p>
        </div>
        <div className="rounded-card border border-border bg-card p-4 shadow-card">
          <div className="flex items-center justify-between">
            <p className="text-xs font-medium uppercase tracking-wide text-muted">Locked</p>
            <div className="rounded-full bg-accent/10 p-1.5">
              <svg className="h-3.5 w-3.5 text-accent" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={2}>
                <path strokeLinecap="round" strokeLinejoin="round" d="M16.5 10.5V6.75a4.5 4.5 0 10-9 0v3.75m-.75 11.25h10.5a2.25 2.25 0 002.25-2.25v-6.75a2.25 2.25 0 00-2.25-2.25H6.75a2.25 2.25 0 00-2.25 2.25v6.75a2.25 2.25 0 002.25 2.25z" />
              </svg>
            </div>
          </div>
          <p className="mt-2 text-2xl font-bold text-text">{lockedCount}</p>
          <p className="mt-0.5 text-xs text-muted">approved &amp; ready for pay run</p>
        </div>
        <div className="rounded-card border border-border bg-card p-4 shadow-card">
          <div className="flex items-center justify-between">
            <p className="text-xs font-medium uppercase tracking-wide text-muted">Total Hours</p>
            <div className="rounded-full bg-muted/10 p-1.5">
              <svg className="h-3.5 w-3.5 text-muted" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={2}>
                <path strokeLinecap="round" strokeLinejoin="round" d="M3 13.125C3 12.504 3.504 12 4.125 12h2.25c.621 0 1.125.504 1.125 1.125v6.75C7.5 20.496 6.996 21 6.375 21h-2.25A1.125 1.125 0 013 19.875v-6.75zM9.75 8.625c0-.621.504-1.125 1.125-1.125h2.25c.621 0 1.125.504 1.125 1.125v11.25c0 .621-.504 1.125-1.125 1.125h-2.25a1.125 1.125 0 01-1.125-1.125V8.625zM16.5 4.125c0-.621.504-1.125 1.125-1.125h2.25C20.496 3 21 3.504 21 4.125v15.75c0 .621-.504 1.125-1.125 1.125h-2.25a1.125 1.125 0 01-1.125-1.125V4.125z" />
              </svg>
            </div>
          </div>
          <p className="mt-2 text-2xl font-bold text-text">{Number(totalHours || 0).toFixed(1)}</p>
          <p className="mt-0.5 text-xs text-muted">this period</p>
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
          {activeTab === 'Attendance' && <AttendanceTab />}
          {activeTab === 'Clocked In' && <ClockedInTab />}
          {activeTab === 'Timesheets' && <TimesheetsTab onPeriodSummary={handlePeriodSummary} />}
          {activeTab === 'Pay Runs' && <PayRunsTab />}
        </div>
      </div>
    </div>
    </div>
  )
}
