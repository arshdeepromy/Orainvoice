/**
 * Mobile field-placement editor — example / integration tests (Task 24.5).
 *
 * Covers the EXAMPLE-classified acceptance criteria of the Mobile_Field_Placement_Editor
 * (R16) that the pure-core parity test (24.4) does not:
 *
 *   • More-menu gating (R16.1–R16.3) — the `esign-send` More-menu entry is gated
 *     by the `esignatures` module AND the org-sender roles, exercised through the
 *     real `isMoreMenuItemVisible` / `filterMoreMenuItems` helpers in
 *     `MoreMenuConfig.ts` (the same logic the menu screen renders from):
 *       - hidden when `esignatures` is not enabled (R16.1),
 *       - hidden for a non-sender role (technician / salesperson) (R16.2/R16.3),
 *       - visible for org_admin / branch_admin / location_manager with the module on.
 *
 *   • Touch_Place + 44 px controls (R16.4–R16.6) — tapping a page surface places a
 *     field of the armed type (R16.4); the selected-field nudge / resize / delete
 *     controls each meet the 44×44 px minimum, asserted across both ends of the
 *     320–430 px supported viewport range (R16.5/R16.6).
 *
 *   • Send contract + AbortController (R16.7/R16.8) — the editor-driven send calls
 *     `createEnvelope` with the identical multipart contract the web editor uses:
 *     a `fields[]` set mapped to `recipient_index`, bound to an AbortController
 *     signal that is aborted on unmount.
 *
 * The editor renders the PDF via `usePdfDocument`, which imports `pdfjs-dist`, so
 * we reuse the mock pattern established in the frontend-v2 field-placement tests:
 * mock `pdfjs-dist` + the `?url` worker asset and stub canvas `getContext`. jsdom
 * has no IntersectionObserver, so pages render eagerly.
 *
 * _Requirements: 16.1, 16.2, 16.3, 16.4, 16.5, 16.6, 16.7, 16.8_
 */

import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { render, screen, fireEvent, waitFor, within } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import type { ReactNode } from 'react'

import {
  MORE_MENU_ITEMS,
  isMoreMenuItemVisible,
  filterMoreMenuItems,
} from '@/navigation/MoreMenuConfig'
import type { PlacedField } from '@/lib/esign'
import TouchFieldOverlay from './TouchFieldOverlay'
import MobileFieldPlacementEditor, { type EditorRecipient } from './MobileFieldPlacementEditor'

/* ------------------------------------------------------------------ */
/*  Mock pdfjs-dist (module + worker ?url asset)                       */
/*  — a deterministic single-page happy-path document.                */
/* ------------------------------------------------------------------ */

const pdfMock = vi.hoisted(() => ({
  state: { numPages: 1, pageWidth: 600, pageHeight: 800 },
}))

vi.mock('pdfjs-dist', () => {
  const GlobalWorkerOptions = { workerSrc: '' as string }

  const makePage = () => ({
    getViewport: ({ scale }: { scale: number }) => ({
      width: pdfMock.state.pageWidth * scale,
      height: pdfMock.state.pageHeight * scale,
    }),
    render: () => ({ promise: Promise.resolve(), cancel: vi.fn() }),
  })

  const makeDoc = () => ({
    numPages: pdfMock.state.numPages,
    getPage: vi.fn(async () => makePage()),
    destroy: vi.fn(),
  })

  const getDocument = vi.fn(() => ({
    promise: Promise.resolve(makeDoc()),
    destroy: vi.fn(),
  }))

  return { GlobalWorkerOptions, getDocument }
})

vi.mock('pdfjs-dist/build/pdf.worker.min.mjs?url', () => ({ default: 'mock-worker-url' }))

/* ------------------------------------------------------------------ */
/*  Mock contexts + router for the EsignSendScreen send-contract test  */
/* ------------------------------------------------------------------ */

let mockEnabledModules: string[] = ['esignatures']
let mockUserRole = 'org_admin'

vi.mock('@/contexts/ModuleContext', () => ({
  useModules: () => ({
    modules: [],
    enabledModules: mockEnabledModules,
    isLoading: false,
    error: null,
    isModuleEnabled: (slug: string) => mockEnabledModules.includes(slug),
    tradeFamily: null,
    refetch: vi.fn(),
  }),
}))

vi.mock('@/contexts/AuthContext', () => ({
  useAuth: () => ({
    user: { id: '1', name: 'Test', email: 'test@test.com', role: mockUserRole, org_id: 'org1' },
    isAuthenticated: true,
    isLoading: false,
  }),
}))

const mockNavigate = vi.fn()
vi.mock('react-router-dom', async () => {
  const actual = await vi.importActual('react-router-dom')
  return { ...actual, useNavigate: () => mockNavigate }
})

// Partial mock of the API module: keep the real `placedFieldsToFieldIns`,
// `AGREEMENT_TYPES`, and types so the screen behaves normally, but spy on the
// network `createEnvelope` so we can assert the send contract + AbortController.
const mockCreateEnvelope = vi.hoisted(() => vi.fn())
vi.mock('@/api/esign', async (importOriginal) => {
  const actual = await importOriginal<typeof import('@/api/esign')>()
  return { ...actual, createEnvelope: mockCreateEnvelope }
})

/* ------------------------------------------------------------------ */
/*  Fixtures                                                           */
/* ------------------------------------------------------------------ */

function makePdfFile(): File {
  return new File([new Uint8Array([1, 2, 3, 4])], 'sample.pdf', { type: 'application/pdf' })
}

const EDITOR_RECIPIENTS: EditorRecipient[] = [
  { key: 1, name: 'Alex Tran', email: 'alex@example.com', signing_role: 'signer' },
]

function Wrapper({ children }: { children: ReactNode }) {
  return <MemoryRouter>{children}</MemoryRouter>
}

beforeEach(() => {
  vi.clearAllMocks()
  mockEnabledModules = ['esignatures']
  mockUserRole = 'org_admin'
  pdfMock.state.numPages = 1
  pdfMock.state.pageWidth = 600
  pdfMock.state.pageHeight = 800

  // jsdom has no canvas 2d context; a truthy stub lets the page rasterise past
  // its `getContext` guard so the render resolves to `rendered`.
  HTMLCanvasElement.prototype.getContext = vi.fn(
    () => ({}) as unknown as CanvasRenderingContext2D,
  ) as unknown as typeof HTMLCanvasElement.prototype.getContext
})

afterEach(() => {
  vi.restoreAllMocks()
})

/* ================================================================== */
/*  R16.1–R16.3 — More-menu gating                                    */
/* ================================================================== */

describe('Mobile More-menu gating for the e-signature send entry (R16.1–R16.3)', () => {
  const esignItem = MORE_MENU_ITEMS.find((i) => i.id === 'esign-send')!

  it('the esign-send entry exists and is gated by the esignatures module + org-sender roles', () => {
    expect(esignItem).toBeDefined()
    expect(esignItem.moduleSlug).toBe('esignatures')
    expect(esignItem.tradeFamily).toBeNull() // no trade-family gate (design decision)
    expect(esignItem.allowedRoles).toEqual(['org_admin', 'branch_admin', 'location_manager'])
  })

  // R16.1 — hidden when the esignatures module is not enabled.
  it('is hidden when the esignatures module is not enabled', () => {
    expect(isMoreMenuItemVisible(esignItem, [], null, 'org_admin')).toBe(false)
    expect(isMoreMenuItemVisible(esignItem, ['inventory', 'staff'], null, 'org_admin')).toBe(false)
  })

  // R16.2 / R16.3 — hidden for a non-sender role even with the module enabled.
  it('is hidden for non-sender roles even when the module is enabled', () => {
    expect(isMoreMenuItemVisible(esignItem, ['esignatures'], null, 'technician')).toBe(false)
    expect(isMoreMenuItemVisible(esignItem, ['esignatures'], null, 'salesperson')).toBe(false)
    expect(isMoreMenuItemVisible(esignItem, ['esignatures'], null, 'kiosk')).toBe(false)
  })

  // R16.2 — visible for every org-sender role with the module enabled.
  it('is visible for org_admin / branch_admin / location_manager with the module enabled', () => {
    for (const role of ['org_admin', 'branch_admin', 'location_manager'] as const) {
      expect(isMoreMenuItemVisible(esignItem, ['esignatures'], null, role)).toBe(true)
    }
  })

  it('filterMoreMenuItems includes the entry only when both gates pass', () => {
    // Module off → excluded.
    expect(
      filterMoreMenuItems(MORE_MENU_ITEMS, [], null, 'org_admin').some((i) => i.id === 'esign-send'),
    ).toBe(false)
    // Module on but non-sender role → excluded.
    expect(
      filterMoreMenuItems(MORE_MENU_ITEMS, ['esignatures'], null, 'technician').some(
        (i) => i.id === 'esign-send',
      ),
    ).toBe(false)
    // Module on + sender role → included.
    expect(
      filterMoreMenuItems(MORE_MENU_ITEMS, ['esignatures'], null, 'branch_admin').some(
        (i) => i.id === 'esign-send',
      ),
    ).toBe(true)
  })
})

/* ================================================================== */
/*  R16.5 / R16.6 — 44×44 px nudge / resize controls                  */
/* ================================================================== */

describe('TouchFieldOverlay adjustment controls meet the 44×44 px minimum (R16.5/R16.6)', () => {
  const field: PlacedField = {
    clientId: 'f1',
    type: 'signature',
    page: 1,
    rect: { positionX: 10, positionY: 20, width: 30, height: 8 },
    recipientKey: 1,
    required: true,
  }
  const recipients = [{ key: 1, name: 'Alex Tran' }]

  // Exercise both ends of the supported viewport width range (R16.6).
  for (const cssWidth of [320, 430]) {
    it(`renders ≥44×44 px controls and an accessible field name at ${cssWidth}px wide`, () => {
      const dims = { cssWidth, cssHeight: Math.round(cssWidth * (800 / 600)) }
      render(
        <TouchFieldOverlay
          fields={[field]}
          recipients={recipients}
          dims={dims}
          selectedClientId="f1"
          onSelect={vi.fn()}
          onNudge={vi.fn()}
          onResize={vi.fn()}
          onDelete={vi.fn()}
        />,
      )

      // R10.4 / R5.5 — the field box conveys its type, recipient, and required state.
      const box = screen.getByTestId('field-box-f1')
      expect(box).toHaveAttribute('aria-label', 'Signature field for Alex Tran (required)')

      // The selected field shows its adjustment cluster (nudge / resize / delete).
      const controls = screen.getByTestId('field-controls-f1')
      const buttons = within(controls).getAllByRole('button')
      // 4 nudge + 4 resize + 1 delete = 9 controls.
      expect(buttons).toHaveLength(9)
      for (const btn of buttons) {
        expect(btn.className).toContain('min-h-[44px]')
        expect(btn.className).toContain('min-w-[44px]')
      }
    })
  }

  it('wires the nudge / resize / delete controls to their callbacks', () => {
    const onNudge = vi.fn()
    const onResize = vi.fn()
    const onDelete = vi.fn()
    render(
      <TouchFieldOverlay
        fields={[field]}
        recipients={recipients}
        dims={{ cssWidth: 360, cssHeight: 480 }}
        selectedClientId="f1"
        onSelect={vi.fn()}
        onNudge={onNudge}
        onResize={onResize}
        onDelete={onDelete}
        nudgeStepPx={8}
        resizeStepPx={8}
      />,
    )

    fireEvent.click(screen.getByLabelText('Move right'))
    expect(onNudge).toHaveBeenCalledWith('f1', 8, 0)

    fireEvent.click(screen.getByLabelText('Taller'))
    expect(onResize).toHaveBeenCalledWith('f1', 0, 8)

    fireEvent.click(screen.getByLabelText('Delete field'))
    expect(onDelete).toHaveBeenCalledWith('f1')
  })
})

/* ================================================================== */
/*  R16.4 — Touch_Place places a field on tap                         */
/* ================================================================== */

describe('Touch_Place places a field of the armed type on tap (R16.4)', () => {
  it('placing on the page surface adds a field, then the send control enables', async () => {
    render(
      <MobileFieldPlacementEditor
        file={makePdfFile()}
        recipients={EDITOR_RECIPIENTS}
        onSend={vi.fn()}
        onBack={vi.fn()}
        isSending={false}
        sendError={null}
      />,
    )

    // Wait for the page (and its tap-to-place surface) to mount.
    const placeSurface = await screen.findByTestId('pdf-page-place-1')

    // Default armed type is `signature`; tap the surface to place a field.
    fireEvent.pointerUp(placeSurface, { clientX: 120, clientY: 140 })

    // A field box appears for the placed (signature) field.
    const box = await screen.findByTestId(/^field-box-/)
    expect(box).toHaveAttribute('aria-label', expect.stringContaining('Signature field for Alex Tran'))

    // With a signature field placed for the lone signer, the send control enables (R6.5).
    await waitFor(() => {
      expect(screen.getByRole('button', { name: 'Send for signature' })).toBeEnabled()
    })
  })

  it('keeps the send control disabled while the Field_Set is empty', async () => {
    render(
      <MobileFieldPlacementEditor
        file={makePdfFile()}
        recipients={EDITOR_RECIPIENTS}
        onSend={vi.fn()}
        onBack={vi.fn()}
        isSending={false}
        sendError={null}
      />,
    )
    await screen.findByTestId('pdf-page-place-1')
    expect(screen.getByRole('button', { name: 'Send for signature' })).toBeDisabled()
  })
})

/* ================================================================== */
/*  R16.7 / R16.8 — send contract + AbortController                   */
/* ================================================================== */

describe('EsignSendScreen send uses the shared contract + AbortController (R16.7/R16.8)', () => {
  /** Drive the step-1 composer through to a placed signature field in step 2. */
  async function fillComposerAndPlaceField(container: HTMLElement) {
    // Select the PDF (the file input is hidden inside its label).
    const fileInput = container.querySelector('input[type="file"]') as HTMLInputElement
    const file = makePdfFile()
    Object.defineProperty(fileInput, 'files', { value: [file], configurable: true })
    fireEvent.change(fileInput)

    // Record reference + recipient name/email.
    fireEvent.change(screen.getByLabelText('Record reference'), { target: { value: 'INV-1001' } })
    fireEvent.change(screen.getByLabelText('Name'), { target: { value: 'Alex Tran' } })
    fireEvent.change(screen.getByLabelText('Email'), { target: { value: 'alex@example.com' } })

    // Step 1 → step 2.
    fireEvent.click(screen.getByRole('button', { name: 'Next: place fields' }))

    // Place a signature field by tapping the rendered page surface.
    const placeSurface = await screen.findByTestId('pdf-page-place-1')
    fireEvent.pointerUp(placeSurface, { clientX: 120, clientY: 140 })
    await screen.findByTestId(/^field-box-/)

    return file
  }

  it('calls createEnvelope with the mapped fields[] and an AbortSignal', async () => {
    mockCreateEnvelope.mockResolvedValue({
      id: 'env-1',
      agreement_type: 'sales_agreement',
      originating_entity_type: 'invoice',
      originating_entity_id: 'INV-1001',
      status: 'sent',
      recipients: [],
      signed_document_url: null,
      created_at: '',
      updated_at: '',
    })

    const { default: EsignSendScreen } = await import('./EsignSendScreen')
    const { container } = render(<EsignSendScreen />, { wrapper: Wrapper })

    const file = await fillComposerAndPlaceField(container)

    const sendBtn = await screen.findByRole('button', { name: 'Send for signature' })
    await waitFor(() => expect(sendBtn).toBeEnabled())
    fireEvent.click(sendBtn)

    await waitFor(() => expect(mockCreateEnvelope).toHaveBeenCalledTimes(1))

    const [sentFile, payload, signal] = mockCreateEnvelope.mock.calls[0]
    expect(sentFile).toBe(file)

    // Same contract as the web editor: recipients + a fields[] set mapped to
    // recipient_index (R16.7).
    expect(payload.agreement_type).toBe('sales_agreement')
    expect(payload.recipients).toHaveLength(1)
    expect(payload.fields).toHaveLength(1)
    expect(payload.fields[0]).toMatchObject({ type: 'signature', page: 1, recipient_index: 0 })

    // The in-flight request is bound to an AbortController signal (R16.8).
    expect(signal).toBeInstanceOf(AbortSignal)
    expect(signal.aborted).toBe(false)
  })

  it('aborts the in-flight send when the screen unmounts (R16.8)', async () => {
    let capturedSignal: AbortSignal | undefined
    // Never resolves — the request stays in flight until unmount aborts it.
    mockCreateEnvelope.mockImplementation((_file: File, _payload: unknown, signal: AbortSignal) => {
      capturedSignal = signal
      return new Promise<never>(() => {})
    })

    const { default: EsignSendScreen } = await import('./EsignSendScreen')
    const { container, unmount } = render(<EsignSendScreen />, { wrapper: Wrapper })

    await fillComposerAndPlaceField(container)

    const sendBtn = await screen.findByRole('button', { name: 'Send for signature' })
    await waitFor(() => expect(sendBtn).toBeEnabled())
    fireEvent.click(sendBtn)

    await waitFor(() => expect(mockCreateEnvelope).toHaveBeenCalledTimes(1))
    expect(capturedSignal).toBeInstanceOf(AbortSignal)
    expect(capturedSignal?.aborted).toBe(false)

    unmount()
    expect(capturedSignal?.aborted).toBe(true)
  })
})
