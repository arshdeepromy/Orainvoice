import { render, screen } from '@testing-library/react'
import { describe, it, expect, beforeEach, vi } from 'vitest'

/* ============================================================
   Contextual "Send for signature" gating — Staff → Documents tab
   (feature: esignature-integration, Task 18.2).
   ------------------------------------------------------------
   The Staff → Documents tab exposes a "Send for signature" action that
   is shown only while the `esignatures` module is enabled and hidden
   when it is disabled. Visibility is driven purely by
   useModules().isEnabled('esignatures') (R10.2 / R10.5).

   We mirror the established module-gating test convention (see
   src/components/shell/Sidebar.test.tsx): mock @/contexts/ModuleContext
   and toggle a single module flag between the two cases. The staff/docs
   fetches are mocked so the tab finishes loading and renders its toolbar.

   Validates: Requirements 10.2, 10.5
   ============================================================ */

// Controls isEnabled('esignatures'). Other modules stay disabled so the test
// isolates the e-signature gate.
let esignEnabled = false
vi.mock('@/contexts/ModuleContext', () => ({
  useModules: () => ({ isEnabled: (slug: string) => slug === 'esignatures' && esignEnabled }),
}))

// Deterministic backend shapes so the tab leaves its loading state and renders
// the "Submitted documents" toolbar that hosts the gated action.
vi.mock('@/api/client', () => ({
  default: {
    get: vi.fn(async (url: string) => {
      if (typeof url === 'string' && url.endsWith('/documents')) {
        return { data: { items: [], total: 0 } }
      }
      // GET /api/v2/staff/:id — staff summary
      return { data: { id: 'staff-1', employment_agreement_upload_id: null } }
    }),
  },
}))

import DocumentsTab from './DocumentsTab'

async function renderTab() {
  const utils = render(<DocumentsTab staffId="staff-1" />)
  // Wait out the initial staff fetch so the toolbar (not the "Loading…"
  // placeholder) is on screen.
  await screen.findByTestId('documents-tab')
  return utils
}

describe('DocumentsTab — "Send for signature" module gating', () => {
  beforeEach(() => {
    esignEnabled = false
  })

  it('shows the "Send for signature" action when the esignatures module is enabled (R10.2)', async () => {
    esignEnabled = true
    await renderTab()

    expect(
      screen.getByRole('button', { name: /send for signature/i }),
    ).toBeInTheDocument()
  })

  it('hides the "Send for signature" action when the esignatures module is disabled (R10.5)', async () => {
    esignEnabled = false
    await renderTab()

    expect(
      screen.queryByRole('button', { name: /send for signature/i }),
    ).not.toBeInTheDocument()
  })
})
