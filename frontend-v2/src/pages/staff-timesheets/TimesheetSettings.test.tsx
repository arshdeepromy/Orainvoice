/**
 * TimesheetSettings — Automatic Clock-Out settings form (Task 9.2).
 *
 * Covers the Configuration UI acceptance criteria for auto clock-out:
 *   • Req 8.1/8.2 — the form persists the three clock_in_policy keys
 *     (auto_clock_out_enabled, auto_clock_out_after_hours,
 *      auto_clock_out_grace_minutes) through PUT /api/v2/org/clock-in-policy.
 *   • Req 8.2 — range validation is enforced on the numeric inputs
 *     (after-hours clamped to 1..48, grace clamped to 0..240).
 *   • Req 8.3 — the auto clock-out controls are independent of the existing
 *     missed-clock-out / late alert toggles (changing one never clobbers the
 *     other in the persisted policy).
 *
 * `@/api/client` is mocked so the real component logic (load → edit → save)
 * runs end-to-end against deterministic shapes; `@/contexts/AuthContext` is
 * mocked to an org_admin so the form is editable (not read-only).
 */
import { describe, it, expect, beforeEach, vi } from 'vitest'
import { render, screen, fireEvent, waitFor, within } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'

vi.mock('@/api/client', () => ({
  default: { get: vi.fn(), put: vi.fn() },
}))

vi.mock('@/contexts/AuthContext', () => ({
  useAuth: () => ({
    user: { id: 'u1', email: 'admin@test.com', name: 'Admin', role: 'org_admin', org_id: 'org-1' },
  }),
}))

import apiClient from '@/api/client'
import TimesheetSettings from './TimesheetSettings'

const mockGet = apiClient.get as ReturnType<typeof vi.fn>
const mockPut = apiClient.put as ReturnType<typeof vi.fn>

const POLICY_ENDPOINT = '/api/v2/org/clock-in-policy'

/** Default policy returned by the clock-in-policy GET (auto OFF, alerts ON). */
function defaultPolicy(overrides: Record<string, unknown> = {}) {
  return {
    late_clock_in_alert_enabled: true,
    late_clock_in_alert_channels: ['sms'],
    missed_clock_out_alert_enabled: true,
    missed_clock_out_alert_channels: ['sms'],
    auto_clock_out_enabled: false,
    auto_clock_out_after_hours: 14,
    auto_clock_out_grace_minutes: 15,
    ...overrides,
  }
}

/** Wire the three GETs the screen fires in parallel on mount. */
function seedGets(policy: Record<string, unknown> = defaultPolicy()) {
  mockGet.mockImplementation((url: string) => {
    if (url === '/api/v2/timesheet-settings/') return Promise.resolve({ data: { org_default: {} } })
    if (url === '/api/v2/pay-cycles/') return Promise.resolve({ data: { items: [], total: 0 } })
    if (url === POLICY_ENDPOINT) return Promise.resolve({ data: { clock_in_policy: policy } })
    return Promise.resolve({ data: {} })
  })
}

function renderSettings() {
  return render(
    <MemoryRouter initialEntries={['/timesheets/settings']}>
      <TimesheetSettings />
    </MemoryRouter>,
  )
}

/** Resolve the most recent PUT body sent to the clock-in-policy endpoint. */
function lastPolicyPut(): Record<string, any> | undefined {
  const calls = mockPut.mock.calls.filter((c) => c[0] === POLICY_ENDPOINT)
  return calls.length ? calls[calls.length - 1][1]?.clock_in_policy : undefined
}

beforeEach(() => {
  vi.clearAllMocks()
  mockPut.mockResolvedValue({ data: {} })
})

describe('TimesheetSettings — auto clock-out persistence (Req 8.1, 8.2)', () => {
  it('persists the three auto clock-out keys through the clock-in-policy PUT', async () => {
    seedGets()
    renderSettings()

    // Wait for the form to finish loading.
    await screen.findByText('Automatic Clock-Out')

    // Enable the toggle (numeric inputs are disabled until it is on).
    fireEvent.click(screen.getByLabelText('Enable automatic clock-out'))

    const afterHours = screen.getByLabelText('Auto clock-out after (hours)')
    const grace = screen.getByLabelText('Grace after rostered end (minutes)')
    fireEvent.change(afterHours, { target: { value: '10' } })
    fireEvent.change(grace, { target: { value: '30' } })

    fireEvent.click(screen.getByRole('button', { name: 'Save Settings' }))

    await waitFor(() => expect(lastPolicyPut()).toBeDefined())
    expect(lastPolicyPut()).toMatchObject({
      auto_clock_out_enabled: true,
      auto_clock_out_after_hours: 10,
      auto_clock_out_grace_minutes: 30,
    })
  })
})

describe('TimesheetSettings — range validation (Req 8.2)', () => {
  it('clamps after-hours to 1..48 and grace to 0..240 on input and on save', async () => {
    seedGets()
    renderSettings()
    await screen.findByText('Automatic Clock-Out')

    fireEvent.click(screen.getByLabelText('Enable automatic clock-out'))
    const afterHours = screen.getByLabelText('Auto clock-out after (hours)') as HTMLInputElement
    const grace = screen.getByLabelText('Grace after rostered end (minutes)') as HTMLInputElement

    // Above the max clamps down.
    fireEvent.change(afterHours, { target: { value: '100' } })
    expect(afterHours.value).toBe('48')
    fireEvent.change(grace, { target: { value: '300' } })
    expect(grace.value).toBe('240')

    // Below the min clamps up.
    fireEvent.change(afterHours, { target: { value: '0' } })
    expect(afterHours.value).toBe('1')
    fireEvent.change(grace, { target: { value: '-5' } })
    expect(grace.value).toBe('0')

    fireEvent.click(screen.getByRole('button', { name: 'Save Settings' }))
    await waitFor(() => expect(lastPolicyPut()).toBeDefined())
    expect(lastPolicyPut()).toMatchObject({
      auto_clock_out_after_hours: 1,
      auto_clock_out_grace_minutes: 0,
    })
  })
})

describe('TimesheetSettings — auto clock-out independent of alert toggles (Req 8.3)', () => {
  it('lets the missed-clock-out alert be toggled while auto clock-out stays off', async () => {
    seedGets(defaultPolicy({ missed_clock_out_alert_enabled: true, auto_clock_out_enabled: false }))
    renderSettings()
    await screen.findByText('Automatic Clock-Out')

    // Toggle ONLY the missed-clock-out alert off — auto clock-out left untouched.
    const missedRow = screen.getByText('Forgotten clock-out reminder').closest('.flex-wrap') as HTMLElement
    fireEvent.click(within(missedRow).getByRole('button'))

    fireEvent.click(screen.getByRole('button', { name: 'Save Settings' }))
    await waitFor(() => expect(lastPolicyPut()).toBeDefined())

    const body = lastPolicyPut()!
    // The alert change persisted...
    expect(body.missed_clock_out_alert_enabled).toBe(false)
    // ...and the auto clock-out keys were not disturbed.
    expect(body.auto_clock_out_enabled).toBe(false)
    expect(body.auto_clock_out_after_hours).toBe(14)
    expect(body.auto_clock_out_grace_minutes).toBe(15)
  })

  it('changing auto clock-out does not clobber the alert settings', async () => {
    seedGets(defaultPolicy({ late_clock_in_alert_enabled: true, missed_clock_out_alert_enabled: true }))
    renderSettings()
    await screen.findByText('Automatic Clock-Out')

    // Flip auto clock-out on and edit its numeric controls only.
    fireEvent.click(screen.getByLabelText('Enable automatic clock-out'))
    fireEvent.change(screen.getByLabelText('Auto clock-out after (hours)'), { target: { value: '20' } })

    fireEvent.click(screen.getByRole('button', { name: 'Save Settings' }))
    await waitFor(() => expect(lastPolicyPut()).toBeDefined())

    const body = lastPolicyPut()!
    expect(body.auto_clock_out_enabled).toBe(true)
    expect(body.auto_clock_out_after_hours).toBe(20)
    // Alert toggles preserved at their loaded values.
    expect(body.late_clock_in_alert_enabled).toBe(true)
    expect(body.missed_clock_out_alert_enabled).toBe(true)
  })
})

describe('TimesheetSettings — edit pay cycle', () => {
  const CYCLE = {
    id: 'cycle-1',
    name: 'Fortnightly',
    frequency: 'fortnightly',
    anchor_date: '2026-06-01',
    pay_date_offset_days: 3,
    is_default: false,
  }

  /** Seed the mount GETs with one existing pay cycle. */
  function seedGetsWithCycle() {
    mockGet.mockImplementation((url: string) => {
      if (url === '/api/v2/timesheet-settings/') return Promise.resolve({ data: { org_default: {} } })
      if (url === '/api/v2/pay-cycles/')
        return Promise.resolve({ data: { items: [CYCLE], total: 1 } })
      if (url === POLICY_ENDPOINT)
        return Promise.resolve({ data: { clock_in_policy: defaultPolicy() } })
      return Promise.resolve({ data: {} })
    })
  }

  it('opens the modal pre-filled and PUTs the updated cycle (Edit is not a dead button)', async () => {
    seedGetsWithCycle()
    mockPut.mockResolvedValue({
      data: { ...CYCLE, name: 'Fortnightly — All Staff', pay_date_offset_days: 5 },
    })
    renderSettings()

    // The cycle row renders with its Edit control.
    const editBtn = await screen.findByRole('button', { name: 'Edit' })
    fireEvent.click(editBtn)

    // The modal opens in edit mode, pre-filled from the cycle.
    expect(screen.getByText('Edit Pay Cycle')).toBeInTheDocument()
    const nameInput = screen.getByDisplayValue('Fortnightly') as HTMLInputElement
    expect(nameInput).toBeInTheDocument()

    // Change a couple of fields and save.
    fireEvent.change(nameInput, { target: { value: 'Fortnightly — All Staff' } })

    fireEvent.click(screen.getByRole('button', { name: 'Save Changes' }))

    await waitFor(() => expect(mockPut).toHaveBeenCalled())
    const call = mockPut.mock.calls.find((c) => String(c[0]).startsWith('/api/v2/pay-cycles/'))
    expect(call).toBeDefined()
    expect(call![0]).toBe('/api/v2/pay-cycles/cycle-1')
    expect(call![1]).toMatchObject({
      name: 'Fortnightly — All Staff',
      frequency: 'fortnightly',
      anchor_date: '2026-06-01',
    })
  })
})
