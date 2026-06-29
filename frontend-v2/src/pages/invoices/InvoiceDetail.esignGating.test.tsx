import { render, screen } from '@testing-library/react'
import { describe, it, expect, beforeEach, vi } from 'vitest'
import { MemoryRouter, Routes, Route } from 'react-router-dom'

/* ============================================================
   Contextual "Send for signature" gating — Invoice detail page
   (feature: esignature-integration, Task 18.2).
   ------------------------------------------------------------
   The invoice page exposes a "Send for signature" action that is shown
   only while the `esignatures` module is enabled and hidden when it is
   disabled. Visibility is driven purely by
   useModules().isEnabled('esignatures') (R10.1 / R10.5).

   We mirror the established module-gating test convention (see
   src/components/shell/Sidebar.test.tsx): mock @/contexts/ModuleContext
   and toggle a single module flag between the two cases. The invoice
   fetch is mocked so the page leaves its loading state and renders its
   action toolbar; the heavy preview/modal children are stubbed so the
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

vi.mock('@/contexts/AuthContext', () => ({
  useAuth: () => ({ user: { id: 'u1', role: 'org_admin', org_id: 'org-1' } }),
}))

// Minimal issued invoice so the page renders its toolbar (which hosts the
// gated action) without reaching its loading / not-found branches.
const INVOICE = {
  id: 'inv-1',
  invoice_number: 'INV-1',
  status: 'issued',
  total: 100,
  amount_paid: 0,
  balance_due: 100,
  subtotal: 100,
  gst_amount: 0,
  line_items: [],
  payments: [],
  credit_notes: [],
  customer: null,
}

vi.mock('@/api/client', () => ({
  default: {
    get: vi.fn(async (url: string) => {
      if (typeof url === 'string' && url.includes('/payments/online-payments/status')) {
        return { data: { is_connected: false } }
      }
      // GET /invoices/:id
      return { data: INVOICE }
    }),
    post: vi.fn(async () => ({ data: {} })),
    put: vi.fn(async () => ({ data: {} })),
  },
}))

// Stub heavy children so the test isolates the toolbar gating.
vi.mock('@/components/pos/POSReceiptPreview', () => ({ default: () => null }))
vi.mock('@/components/pos/PrinterErrorModal', () => ({ default: () => null }))
vi.mock('@/pages/compliance/LinkedComplianceDocs', () => ({ default: () => null }))
vi.mock('./QrPaymentWaitingPopup', () => ({ QrPaymentWaitingPopup: () => null }))
vi.mock('./QrPaymentAmountModal', () => ({ QrPaymentAmountModal: () => null }))
vi.mock('@/components/invoices/CreditNoteModal', () => ({ CreditNoteModal: () => null }))
vi.mock('@/components/invoices/RefundModal', () => ({ RefundModal: () => null }))

import InvoiceDetail from './InvoiceDetail'

async function renderPage() {
  const utils = render(
    <MemoryRouter initialEntries={['/invoices/inv-1']}>
      <Routes>
        <Route path="/invoices/:id" element={<InvoiceDetail />} />
      </Routes>
    </MemoryRouter>,
  )
  // Wait out the initial invoice fetch — the "Duplicate" toolbar button is
  // always present once the invoice has loaded.
  await screen.findByRole('button', { name: 'Duplicate' })
  return utils
}

describe('InvoiceDetail — "Send for signature" module gating', () => {
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
