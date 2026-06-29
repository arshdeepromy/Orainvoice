import { render, screen } from '@testing-library/react'
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { MemoryRouter } from 'react-router-dom'

/* ============================================================
   Sidebar gating tests — Agreements (e-signature) entry (Task 16.3).
   ------------------------------------------------------------
   The "Agreements" nav item is module-gated on `esignatures` only
   (no flagKey / tradeFamily / adminOnly), so its visibility is driven
   purely by useModules().isEnabled('esignatures') via the Sidebar's
   `isVisible` filter.

   Assertions:
     - R2.3: WHILE `esignatures` is enabled → "Agreements" entry shown.
     - R2.4: WHILE `esignatures` is disabled → "Agreements" entry hidden.

   The four gating contexts (Module / FeatureFlag / Auth / Tenant) plus
   OrgSwitcher and the compliance badge hook are mocked so the rail
   renders deterministically and we can toggle just the esignatures
   module flag between the two cases.
   ============================================================ */

// Controls isEnabled('esignatures'). Other modules stay disabled so the
// test isolates the Agreements gate.
let esignEnabled = false
vi.mock('@/contexts/ModuleContext', () => ({
  useModules: () => ({ isEnabled: (slug: string) => slug === 'esignatures' && esignEnabled }),
}))

vi.mock('@/contexts/FeatureFlagContext', () => ({
  useFeatureFlags: () => ({ flags: {} }),
}))

vi.mock('@/contexts/AuthContext', () => ({
  useAuth: () => ({ user: { id: 'u1', role: 'org_admin', org_id: 'org-1' }, isLoading: false }),
}))

vi.mock('@/contexts/TenantContext', () => ({
  useTenant: () => ({ tradeFamily: null }),
}))

// OrgSwitcher pulls in its own contexts/api; stub it to a plain box.
vi.mock('@/components/shell/OrgSwitcher', () => ({
  default: () => <div data-testid="org-switcher" />,
}))

// Compliance badge hook hits the API; force it to a static 0.
vi.mock('@/hooks/useComplianceBadgeCount', () => ({
  useComplianceBadgeCount: () => 0,
}))

import Sidebar from './Sidebar'

function renderSidebar() {
  return render(
    <MemoryRouter>
      <Sidebar open={false} onClose={() => {}} />
    </MemoryRouter>,
  )
}

describe('Sidebar — Agreements module gating', () => {
  beforeEach(() => {
    esignEnabled = false
  })

  it('shows the "Agreements" entry when the esignatures module is enabled (R2.3)', () => {
    esignEnabled = true
    renderSidebar()

    const link = screen.getByRole('link', { name: 'Agreements' })
    expect(link).toBeInTheDocument()
    expect(link).toHaveAttribute('href', '/agreements')
  })

  it('hides the "Agreements" entry when the esignatures module is disabled (R2.4)', () => {
    esignEnabled = false
    renderSidebar()

    expect(screen.queryByRole('link', { name: 'Agreements' })).not.toBeInTheDocument()
  })
})
