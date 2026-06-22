import { useCallback, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { Capacitor } from '@capacitor/core'
import { Page, Block } from 'konsta/react'
import { usePortalSelection } from '@/contexts/PortalSelectionContext'
import type { PortalType } from '@/contexts/PortalSelectionContext'

/**
 * PortalTypeSelector — mobile first-run screen.
 *
 * Shown when no portal selection is persisted AND no authenticated session
 * exists. Presents exactly three selectable choices (R10.1) with ≥44×44px
 * touch targets (R10.8):
 *
 *  1. Employee / Staff → route to the org lookup screen (carries portal_type)
 *  2. Fleet           → route to the org lookup screen (carries portal_type)
 *  3. Organisation    → route to the existing org-user login and persist
 *                       `{portal_type:'org'}` so the selector is not shown
 *                       again on subsequent app starts (R10.2)
 *
 * The decision of *whether* to show this screen lives in the app shell
 * (App.tsx) which reads the persisted PortalSelection + auth session; this
 * component only renders the choices and routes/persists on selection.
 *
 * Requirements: 10.1, 10.2, 10.8
 */

/** Route the employee/fleet lookup flow lives at. */
export const ORG_LOOKUP_PATH = '/portal-select/lookup'
/** Route the existing org-user login lives at. */
export const ORG_LOGIN_PATH = '/login'

/**
 * Resolve the API base/origin for the org-user portal, mirroring the base
 * resolution in `api/client.ts`: native targets the production backend,
 * web uses the nginx reverse-proxy relative path.
 */
export function resolveOrgApiBase(): string {
  return Capacitor.isNativePlatform()
    ? 'https://devin.oraflow.co.nz/api/v1'
    : '/api/v1'
}

interface PortalChoice {
  type: PortalType
  title: string
  description: string
  icon: React.ReactNode
}

const CHOICES: PortalChoice[] = [
  {
    type: 'employee',
    title: 'Employee / Staff',
    description: 'Log in to your organisation’s staff portal',
    icon: <StaffIcon />,
  },
  {
    type: 'fleet',
    title: 'Fleet',
    description: 'Log in to your fleet management portal',
    icon: <FleetIcon />,
  },
  {
    type: 'org',
    title: 'Organisation',
    description: 'Log in as an organisation user (owner, admin, staff app)',
    icon: <OrgIcon />,
  },
]

export default function PortalTypeSelector() {
  const navigate = useNavigate()
  const { save } = usePortalSelection()
  const [busyType, setBusyType] = useState<PortalType | null>(null)

  const handleSelect = useCallback(
    async (type: PortalType) => {
      if (busyType) return

      if (type === 'org') {
        // Persist the org selection so the selector is not shown again on
        // subsequent app starts while the selection remains persisted (R10.2),
        // then route to the existing org-user login flow.
        setBusyType('org')
        try {
          await save({ portal_type: 'org', api_base: resolveOrgApiBase() })
        } finally {
          setBusyType(null)
        }
        navigate(ORG_LOGIN_PATH)
        return
      }

      // Employee/Staff or Fleet → org lookup, carrying the chosen portal_type.
      // Selection is persisted only after a successful branded login (R11.1),
      // so nothing is saved here.
      navigate(ORG_LOOKUP_PATH, { state: { portal_type: type } })
    },
    [busyType, navigate, save],
  )

  return (
    <Page className="bg-white dark:bg-gray-900">
      {/* Hero header */}
      <div
        className="bg-gradient-to-b from-slate-900 to-indigo-900 px-6 pb-10 text-center"
        style={{ paddingTop: 'calc(env(safe-area-inset-top, 0px) + 4rem)' }}
      >
        <div className="mx-auto mb-3 flex h-16 w-16 items-center justify-center rounded-2xl bg-white/10 backdrop-blur-sm">
          <OraInvoiceLogo />
        </div>
        <h1 className="text-2xl font-bold text-white">Welcome</h1>
        <p className="mt-1 text-sm text-indigo-200">
          How would you like to sign in?
        </p>
      </div>

      <Block className="-mt-4 rounded-t-2xl bg-white pt-6 dark:bg-gray-900">
        <div
          className="flex flex-col gap-3"
          style={{ paddingBottom: 'env(safe-area-inset-bottom, 0px)' }}
          role="group"
          aria-label="Choose a portal type"
        >
          {CHOICES.map((choice) => (
            <button
              key={choice.type}
              type="button"
              onClick={() => void handleSelect(choice.type)}
              disabled={busyType !== null}
              aria-label={choice.title}
              className="flex min-h-[44px] w-full items-center gap-4 rounded-xl border border-gray-200 bg-white px-4 py-3 text-left transition-colors active:bg-gray-50 disabled:opacity-60 dark:border-gray-700 dark:bg-gray-800 dark:active:bg-gray-700"
            >
              <span className="flex h-11 w-11 flex-shrink-0 items-center justify-center rounded-xl bg-indigo-50 dark:bg-indigo-900/30">
                {choice.icon}
              </span>
              <span className="flex-1">
                <span className="block text-base font-semibold text-gray-900 dark:text-white">
                  {choice.title}
                </span>
                <span className="mt-0.5 block text-sm text-gray-500 dark:text-gray-400">
                  {choice.description}
                </span>
              </span>
              <ChevronRightIcon />
            </button>
          ))}
        </div>
      </Block>
    </Page>
  )
}

// ---------------------------------------------------------------------------
// Icons
// ---------------------------------------------------------------------------

function OraInvoiceLogo() {
  return (
    <svg
      className="h-8 w-8 text-white"
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="2"
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
    >
      <path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z" />
      <polyline points="14 2 14 8 20 8" />
      <line x1="16" y1="13" x2="8" y2="13" />
      <line x1="16" y1="17" x2="8" y2="17" />
    </svg>
  )
}

function StaffIcon() {
  return (
    <svg
      className="h-6 w-6 text-indigo-600 dark:text-indigo-400"
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="2"
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
    >
      <path d="M16 21v-2a4 4 0 0 0-4-4H6a4 4 0 0 0-4 4v2" />
      <circle cx="9" cy="7" r="4" />
      <path d="M22 21v-2a4 4 0 0 0-3-3.87" />
      <path d="M16 3.13a4 4 0 0 1 0 7.75" />
    </svg>
  )
}

function FleetIcon() {
  return (
    <svg
      className="h-6 w-6 text-indigo-600 dark:text-indigo-400"
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="2"
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
    >
      <path d="M10 17h4V5H2v12h3" />
      <path d="M20 17h2v-3.34a4 4 0 0 0-1.17-2.83L19 9h-5v8h1" />
      <circle cx="7.5" cy="17.5" r="2.5" />
      <circle cx="17.5" cy="17.5" r="2.5" />
    </svg>
  )
}

function OrgIcon() {
  return (
    <svg
      className="h-6 w-6 text-indigo-600 dark:text-indigo-400"
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="2"
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
    >
      <path d="M3 21h18" />
      <path d="M5 21V7l8-4v18" />
      <path d="M19 21V11l-6-4" />
      <line x1="9" y1="9" x2="9" y2="9" />
      <line x1="9" y1="13" x2="9" y2="13" />
      <line x1="9" y1="17" x2="9" y2="17" />
    </svg>
  )
}

function ChevronRightIcon() {
  return (
    <svg
      className="h-5 w-5 flex-shrink-0 text-gray-400 dark:text-gray-500"
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="2"
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
    >
      <polyline points="9 18 15 12 9 6" />
    </svg>
  )
}
