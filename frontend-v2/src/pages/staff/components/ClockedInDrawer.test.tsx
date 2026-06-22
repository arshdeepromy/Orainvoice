/**
 * ClockedInDrawer — admin clock-out UI tests (auto-clock-out spec, task 8.2).
 *
 * Drives the real drawer (load list → open the reason modal → confirm) so the
 * admin clock-out wiring from task 8.1 is exercised end-to-end against the
 * existing `POST /api/v2/time-clock/admin-clock-out/{entry_id}` endpoint.
 *
 * Covers:
 *   • Reason-modal happy path closes the entry (REQ 6.1, 6.2): a valid reason
 *     note POSTs to the admin clock-out endpoint and the closed row drops off
 *     the list.
 *   • Already-closed 409 (REQ 6.3): a `409 already_clocked_out` surfaces the
 *     "already clocked out" inline message and leaves the row in place.
 *   • Out-of-scope rejection (REQ 6.5): a `403 forbidden_scope` surfaces the
 *     "outside your branch scope" inline message and leaves the row in place.
 *
 * `@/api/client` is mocked so the component logic runs against deterministic
 * shapes; AuthorizedAvatar is stubbed so the flow never touches the network.
 *
 * Validates: Requirements 6.1, 6.2, 6.3, 6.5
 */

import { render, screen, fireEvent, waitFor, within } from '@testing-library/react'
import { describe, it, expect, vi, beforeEach } from 'vitest'

/* ─────────────────────────────────────────────────────────── Mocks ── */

const get = vi.fn()
const post = vi.fn()

vi.mock('@/api/client', () => ({
  default: {
    get: (...a: unknown[]) => get(...a),
    post: (...a: unknown[]) => post(...a),
  },
}))

// AuthorizedAvatar fetches the on-file photo through an authenticated axios
// call. Stub it to a plain element so the flow stays off the network.
vi.mock('@/components/AuthorizedAvatar', () => ({
  default: ({ alt }: { alt?: string }) => <div data-testid="avatar" aria-label={alt} />,
}))

import ClockedInDrawer from './ClockedInDrawer'

/* ─────────────────────────────────────────────────── Test helpers ── */

const CLOCKED_IN_URL = '/time-clock/clocked-in'
const ADMIN_CLOCK_OUT_PREFIX = '/time-clock/admin-clock-out/'

interface ClockedInEntry {
  time_clock_entry_id: string
  staff_id: string
  staff_name: string
  employee_id: string | null
  position: string | null
  on_file_photo_url: string | null
  clock_in_at: string
  source: string
  break_minutes: number
}

function sampleEntry(overrides: Partial<ClockedInEntry> = {}): ClockedInEntry {
  return {
    time_clock_entry_id: 'tce-1',
    staff_id: 's1',
    staff_name: 'Sam Smith',
    employee_id: 'E001',
    position: 'Technician',
    on_file_photo_url: null,
    clock_in_at: new Date(Date.now() - 3 * 60 * 60 * 1000).toISOString(),
    source: 'kiosk',
    break_minutes: 0,
    ...overrides,
  }
}

/** Build an axios-like error the component's error mapping understands. */
function axiosError(status: number, detail: string) {
  return {
    isAxiosError: true,
    response: { status, data: { detail } },
  }
}

/** Seed the clocked-in list GET with a single row. */
function seedList(entries: ClockedInEntry[] = [sampleEntry()]) {
  get.mockImplementation((url: string) => {
    if (url === CLOCKED_IN_URL) {
      return Promise.resolve({ data: { items: entries, total: entries.length } })
    }
    return Promise.reject(new Error(`unexpected GET ${url}`))
  })
}

/** Open the reason modal for the first row and enter a valid reason note. */
async function openModalWithReason(reason = 'Forgot to tap out at end of shift') {
  // Row appears once the list resolves.
  await screen.findByText('Sam Smith')
  // The row "Clock out" action opens the confirmation modal.
  fireEvent.click(screen.getByRole('button', { name: 'Clock out' }))
  // Modal renders its own dialog (titled "Clock out Sam Smith?").
  const dialog = await screen.findByRole('dialog', { name: /clock out sam smith\?/i })
  fireEvent.change(within(dialog).getByLabelText(/reason note/i), {
    target: { value: reason },
  })
  return dialog
}

beforeEach(() => {
  get.mockReset()
  post.mockReset()
})

/* ───────────────────────────────────────────────────────── Tests ── */

describe('ClockedInDrawer — admin clock-out', () => {
  it('REQ 6.1/6.2: reason-modal happy path POSTs the reason and closes the entry', async () => {
    // The row is present until it is clocked out; the post-success refresh GET
    // then returns an empty list (the backend has closed the entry).
    let closed = false
    get.mockImplementation((url: string) => {
      if (url === CLOCKED_IN_URL) {
        const items = closed ? [] : [sampleEntry()]
        return Promise.resolve({ data: { items, total: items.length } })
      }
      return Promise.reject(new Error(`unexpected GET ${url}`))
    })
    post.mockImplementation(() => {
      closed = true
      return Promise.resolve({ data: {} })
    })

    render(<ClockedInDrawer open onClose={() => {}} />)

    const dialog = await openModalWithReason()
    fireEvent.click(within(dialog).getByRole('button', { name: /^clock out$/i }))

    // POSTed to the admin clock-out endpoint with the required reason note.
    await waitFor(() => {
      const call = post.mock.calls.find((c) =>
        String(c[0]).startsWith(ADMIN_CLOCK_OUT_PREFIX),
      )
      expect(call).toBeDefined()
    })
    const call = post.mock.calls.find((c) =>
      String(c[0]).startsWith(ADMIN_CLOCK_OUT_PREFIX),
    )!
    expect(call[0]).toBe(`${ADMIN_CLOCK_OUT_PREFIX}tce-1`)
    expect(call[1]).toMatchObject({ reason_note: 'Forgot to tap out at end of shift' })

    // The closed row drops off the list optimistically.
    await waitFor(() => {
      expect(screen.queryByText('Sam Smith')).not.toBeInTheDocument()
    })
  })

  it('REQ 6.3: an already-closed 409 shows the "already clocked out" inline message and keeps the row', async () => {
    seedList()
    post.mockRejectedValue(axiosError(409, 'already_clocked_out'))

    render(<ClockedInDrawer open onClose={() => {}} />)

    const dialog = await openModalWithReason()
    fireEvent.click(within(dialog).getByRole('button', { name: /^clock out$/i }))

    expect(
      await within(dialog).findByText(/already clocked out by someone else/i),
    ).toBeInTheDocument()
    // Row is not removed when the close failed.
    expect(screen.getByText('Sam Smith')).toBeInTheDocument()
  })

  it('REQ 6.5: an out-of-scope 403 shows the "outside your branch scope" inline message and keeps the row', async () => {
    seedList()
    post.mockRejectedValue(axiosError(403, 'forbidden_scope'))

    render(<ClockedInDrawer open onClose={() => {}} />)

    const dialog = await openModalWithReason()
    fireEvent.click(within(dialog).getByRole('button', { name: /^clock out$/i }))

    expect(
      await within(dialog).findByText(/outside your branch scope/i),
    ).toBeInTheDocument()
    // The out-of-scope entry is left unchanged in the list.
    expect(screen.getByText('Sam Smith')).toBeInTheDocument()
  })
})
