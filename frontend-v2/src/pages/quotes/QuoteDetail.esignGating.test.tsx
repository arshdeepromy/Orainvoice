import { render, screen } from '@testing-library/react'
import { describe, it, expect, beforeEach, vi } from 'vitest'
import { MemoryRouter } from 'react-router-dom'

/* ============================================================
   Contextual "Send for signature" gating — Quote detail page
   (feature: esignature-integration, Task 18.2).
   ------------------------------------------------------------
   The quote page exposes a "Send for signature" action that is shown
   only while the `esignatures` module is enabled and hidden when it is
   disabled. Visibility is driven purely by
   useModules().isEnabled('esignatures') (R10.1 / R10.5).

   We mirror the established module-gating test convention (see
   src/components/shell/Sidebar.test.tsx): mock @/contexts/ModuleContext
   and toggle a single module flag between the two cases. The quote fetch
   is mocked so the page leaves its loading state and renders its action
   toolbar; the heavy composer/attachment children are stubbed so the
   test isolates the gated action.

   Validates: Requirements 10.1, 10.5
   ============================================================ */

// Controls isEnabled('esignatures'). Other modules stay disabled so the test
// isolates the e-signature gate.
let esignEnabled = false
vi.mock('@/contexts/ModuleContext', () => ({
  useModules: () => ({ isEnabled: (slug: string) => slug === 'esignatures' && esignEnabled }),
}))

vi.mock('@/contexts/TenantContext', () => ({
  useTenant: () => ({ tradeFamily: null }),
}))

// Minimal draft quote so the page renders its toolbar (which hosts the gated
// action) without reaching its loading / not-found branches.
const QUOTE = {
  id: 'q-1',
  quote_number: 'Q-1001',
  subject: 'Test quote',
  status: 'draft',
  line_items: [],
  additional_vehicles: [],
  fluid_usage: [],
  subtotal: 0,
  gst_amount: 0,
  total: 0,
  discount_value: 0,
  customer: null,
  acceptance_token: null,
  attachment_count: 0,
}

vi.mock('@/api/client', () => ({
  default: {
    get: vi.fn(async () => ({ data: QUOTE })),
    put: vi.fn(async () => ({ data: {} })),
    post: vi.fn(async () => ({ data: {} })),
    delete: vi.fn(async () => ({ data: {} })),
  },
}))

// Stub heavy children so the test isolates the toolbar gating.
vi.mock('@/components/quotes/QuoteAttachmentList', () => ({
  default: () => <div data-testid="quote-attachment-list" />,
}))
vi.mock('@/components/quotes/CancelQuoteModal', () => ({
  default: () => null,
}))
vi.mock('@/components/email/SendEmailModal', () => ({
  SendEmailModal: () => null,
}))

import QuoteDetail from './QuoteDetail'

async function renderPage() {
  const utils = render(
    <MemoryRouter initialEntries={['/quotes/q-1']}>
      <QuoteDetail quoteId="q-1" />
    </MemoryRouter>,
  )
  // Wait out the initial quote fetch — the "Print" toolbar button is always
  // present once the quote has loaded.
  await screen.findByRole('button', { name: 'Print' })
  return utils
}

describe('QuoteDetail — "Send for signature" module gating', () => {
  beforeEach(() => {
    esignEnabled = false
  })

  it('shows the "Send for signature" action when the esignatures module is enabled (R10.1)', async () => {
    esignEnabled = true
    await renderPage()

    expect(
      screen.getByRole('button', { name: /send for signature/i }),
    ).toBeInTheDocument()
  })

  it('hides the "Send for signature" action when the esignatures module is disabled (R10.5)', async () => {
    esignEnabled = false
    await renderPage()

    expect(
      screen.queryByRole('button', { name: /send for signature/i }),
    ).not.toBeInTheDocument()
  })
})
