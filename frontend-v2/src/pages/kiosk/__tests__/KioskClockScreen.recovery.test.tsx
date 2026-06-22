/**
 * Kiosk 409-recovery tests (auto-clock-out spec, task 7.2).
 *
 * Drives the real KioskClockScreen multi-step flow
 * (choice → entry → confirm-identity → camera → capture → action) so the
 * recovery logic in `handleCapture` is exercised end-to-end. The camera
 * (getUserMedia) and canvas capture are stubbed so the flow can reach the
 * clock action POST; apiClient is mocked to drive the `already_clocked_in` /
 * `not_clocked_in` conflicts.
 *
 * Covers:
 *   - Property 12: Kiosk idempotent retry — a self-caused double-submit
 *     `already_clocked_in` resolves to a success confirmation.
 *   - Property 13: Genuine stale entry routes to manager — a pre-existing open
 *     entry routes to the `needs-manager` sub-screen and never fabricates a
 *     clock-in.
 *   - REQ 7.4: `not_clocked_in` on a clock-OUT surfaces a recoverable message.
 *
 * Validates: Requirements 7.1, 7.2, 7.3, 7.4, 9.5
 */

import { render, screen, fireEvent, waitFor } from '@testing-library/react'
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'

/* ─────────────────────────────────────────────────────────── Mocks ── */

const post = vi.fn()
const get = vi.fn()

vi.mock('@/api/client', () => ({
  default: {
    post: (...a: unknown[]) => post(...a),
    get: (...a: unknown[]) => get(...a),
  },
}))

// AuthorizedAvatar fetches the on-file photo through an authenticated axios
// call (useAuthorizedImage). Stub it to a plain element so the flow doesn't
// touch the network and the rendered tree stays deterministic.
vi.mock('@/components/AuthorizedAvatar', () => ({
  default: ({ alt }: { alt?: string }) => <div data-testid="avatar" aria-label={alt} />,
}))

import { KioskClockScreen } from '../KioskClockScreen'

/* ─────────────────────────────────────────────────── Test helpers ── */

interface LookupResult {
  staff_id: string
  first_name: string
  on_file_photo_url: string | null
  currently_clocked_in: boolean
}

const LOOKUP_URL = '/kiosk/clock/lookup'
const UPLOAD_URL = '/api/v2/uploads/clock-photos'
const ACTION_URL = '/kiosk/clock/action'

/** Build an axios-like error the component's helpers understand. */
function axiosError(status: number, detail: string, url: string) {
  return {
    isAxiosError: true,
    response: { status, data: { detail } },
    config: { url },
  }
}

/**
 * Wire the apiClient.post mock.
 *
 * @param lookupQueue   one LookupResult per lookup call (initial + re-lookups);
 *                      the last entry is reused if more calls arrive.
 * @param actionResult  resolver/rejecter for the `/kiosk/clock/action` POST.
 */
function wirePost(
  lookupQueue: LookupResult[],
  actionResult: () => Promise<unknown>,
) {
  let lookupCalls = 0
  post.mockImplementation((url: string) => {
    if (url === LOOKUP_URL) {
      const idx = Math.min(lookupCalls, lookupQueue.length - 1)
      lookupCalls += 1
      return Promise.resolve({ data: lookupQueue[idx] })
    }
    if (url === UPLOAD_URL) {
      return Promise.resolve({ data: { file_key: 'fk-1', file_name: 'x.jpg', file_size: 1 } })
    }
    if (url === ACTION_URL) {
      return actionResult()
    }
    return Promise.reject(new Error(`unexpected POST ${url}`))
  })
}

/** Drive the flow from the choice screen up to a ready camera, then capture. */
async function runToCapture(action: 'in' | 'out') {
  render(<KioskClockScreen />)

  // 1. Choice → pick intent (animated; onChoose fires after a short timeout).
  fireEvent.click(screen.getByRole('button', { name: action === 'in' ? 'Clock in' : 'Clock out' }))

  // 2. Entry → type a code and continue.
  const continueBtn = await screen.findByRole('button', { name: /continue/i })
  fireEvent.click(screen.getByRole('button', { name: '1' }))
  fireEvent.click(continueBtn)

  // 3. Confirm-identity → take photo.
  const takePhoto = await screen.findByRole('button', { name: /take photo/i })
  fireEvent.click(takePhoto)

  // 4. Camera → wait for getUserMedia + loadedmetadata to mark it ready.
  const video = await screen.findByLabelText('Camera preview')
  await waitFor(() => {
    fireEvent(video, new Event('loadedmetadata'))
    expect(screen.getByRole('button', { name: /capture/i })).not.toBeDisabled()
  })

  // 5. Capture → triggers upload + clock action (and any recovery).
  fireEvent.click(screen.getByRole('button', { name: /capture/i }))
}

/* ──────────────────────────────────────────── Camera / canvas stubs ── */

let originalGetContext: typeof HTMLCanvasElement.prototype.getContext
let originalToDataURL: typeof HTMLCanvasElement.prototype.toDataURL
let originalToBlob: typeof HTMLCanvasElement.prototype.toBlob
let originalPlay: typeof HTMLMediaElement.prototype.play

beforeEach(() => {
  post.mockReset()
  get.mockReset()

  // Fake camera stream.
  const fakeStream = { getTracks: () => [{ stop: () => {} }] } as unknown as MediaStream
  Object.defineProperty(navigator, 'mediaDevices', {
    configurable: true,
    value: { getUserMedia: vi.fn().mockResolvedValue(fakeStream) },
  })

  // jsdom has no media playback / canvas raster — stub the bits handleCapture
  // and the camera preview touch.
  originalPlay = HTMLMediaElement.prototype.play
  HTMLMediaElement.prototype.play = vi.fn().mockResolvedValue(undefined) as unknown as typeof HTMLMediaElement.prototype.play

  originalGetContext = HTMLCanvasElement.prototype.getContext
  HTMLCanvasElement.prototype.getContext = vi.fn(() => ({
    save: vi.fn(),
    translate: vi.fn(),
    scale: vi.fn(),
    drawImage: vi.fn(),
    restore: vi.fn(),
  })) as unknown as typeof HTMLCanvasElement.prototype.getContext

  originalToDataURL = HTMLCanvasElement.prototype.toDataURL
  HTMLCanvasElement.prototype.toDataURL = vi.fn(() => 'data:image/jpeg;base64,abc')

  originalToBlob = HTMLCanvasElement.prototype.toBlob
  HTMLCanvasElement.prototype.toBlob = vi.fn(function (cb: BlobCallback) {
    cb(new Blob(['x'], { type: 'image/jpeg' }))
  }) as unknown as typeof HTMLCanvasElement.prototype.toBlob
})

afterEach(() => {
  HTMLMediaElement.prototype.play = originalPlay
  HTMLCanvasElement.prototype.getContext = originalGetContext
  HTMLCanvasElement.prototype.toDataURL = originalToDataURL
  HTMLCanvasElement.prototype.toBlob = originalToBlob
})

/* ───────────────────────────────────────────────────────── Tests ── */

describe('KioskClockScreen — 409 recovery', () => {
  it('Property 12: a self-caused double-submit already_clocked_in shows a success confirmation', async () => {
    // Not clocked in when the session started → the open entry must be our own
    // just-now write → idempotent success.
    wirePost(
      [
        { staff_id: 's1', first_name: 'Sam', on_file_photo_url: null, currently_clocked_in: false },
        { staff_id: 's1', first_name: 'Sam', on_file_photo_url: null, currently_clocked_in: true },
      ],
      () => Promise.reject(axiosError(409, 'already_clocked_in', ACTION_URL)),
    )

    await runToCapture('in')

    // Resolves to the success confirmation, not a dead end.
    expect(await screen.findByText(/clocked in at/i)).toBeInTheDocument()
    // The re-lookup happened (initial lookup + re-lookup = 2 lookup POSTs).
    const lookupPosts = post.mock.calls.filter((c) => c[0] === LOOKUP_URL)
    expect(lookupPosts.length).toBe(2)
    // Never routed to the manager recovery screen.
    expect(screen.queryByText(/you still have an open shift/i)).not.toBeInTheDocument()
  })

  it('Property 13: a genuine pre-existing open entry routes to needs-manager and never fabricates a clock-in', async () => {
    // Already clocked in when the session started → the open entry pre-dates
    // this capture → must route to a manager, never a synthesised clock-in.
    wirePost(
      [
        { staff_id: 's2', first_name: 'Pat', on_file_photo_url: null, currently_clocked_in: true },
        { staff_id: 's2', first_name: 'Pat', on_file_photo_url: null, currently_clocked_in: true },
      ],
      () => Promise.reject(axiosError(409, 'already_clocked_in', ACTION_URL)),
    )

    await runToCapture('in')

    // Routed to the manager recovery sub-screen.
    expect(await screen.findByText(/you still have an open shift/i)).toBeInTheDocument()
    // No fabricated clock-in confirmation.
    expect(screen.queryByText(/clocked in at/i)).not.toBeInTheDocument()
    // No clock-out was silently performed either.
    expect(screen.queryByText(/clocked out at/i)).not.toBeInTheDocument()
  })

  it('REQ 7.4: not_clocked_in on a clock-OUT surfaces a recoverable inline message', async () => {
    wirePost(
      [{ staff_id: 's3', first_name: 'Lee', on_file_photo_url: null, currently_clocked_in: true }],
      () => Promise.reject(axiosError(409, 'not_clocked_in', ACTION_URL)),
    )

    await runToCapture('out')

    // The clock-OUT path does not enter the in-only recovery branch; it shows
    // the refined, recoverable `not_clocked_in` message.
    expect(
      await screen.findByText(/you don't appear to be clocked in\. tap clock in to start a shift\./i),
    ).toBeInTheDocument()
    // No re-lookup for the out path (recovery is in-only).
    const lookupPosts = post.mock.calls.filter((c) => c[0] === LOOKUP_URL)
    expect(lookupPosts.length).toBe(1)
  })
})
